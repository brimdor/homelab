"""Journal the first control-plane serial-image-pull mitigation without changing data."""

import hashlib
import json
import os
from pathlib import Path
import stat

import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_hop_journal as hops
from maintenance_node_drain import Drain, EXCLUDED_NAMESPACES, hashed, private_json
from maintenance_node_scheduling import Scheduling


VERSION = 'v1.36.5+k3s1'
POLICY = Path('/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-serial-image-pulls.conf')
REQUIRED = {'apiVersion': 'kubelet.config.k8s.io/v1beta1',
            'kind': 'KubeletConfiguration', 'serializeImagePulls': True}


def policy_bytes(text):
    value = json.loads(text)
    actors.require(value == REQUIRED and type(value.get('serializeImagePulls')) is bool,
                   'image-pull candidate must contain only the reviewed serial policy')
    return text.encode()


def runtime(native):
    from maintenance_k3s_production import runtime as k3s_runtime
    value = k3s_runtime(native, VERSION)
    directory = POLICY.parent
    actors.safe(directory)
    info = directory.stat()
    actors.require(info.st_uid == 0 and not info.st_mode & 0o022,
                   'unsafe kubelet configuration directory')
    files = {}
    for path in sorted(directory.glob('*.conf')):
        actors.safe(path)
        info = path.stat()
        actors.require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                       info.st_nlink == 1 and not info.st_mode & 0o022,
                       'unsafe kubelet configuration file')
        files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    value['kubelet_configs'] = files
    return value


def installed(before, after, content):
    actors.require(all(before[k] == after[k] for k in
                   ('version', 'binary_sha256', 'runtime_sha256', 'boot', 'configs',
                    'unit_sha256', 'selinux', 'stargz')),
                   'image-pull activation changed unrelated host state')
    actors.require(before['pid'] != after['pid'], 'K3s activation was not observed')
    actors.require(str(POLICY) not in before['kubelet_configs'] and
                   after['kubelet_configs'] == dict(before['kubelet_configs'],
                       **{str(POLICY): hashlib.sha256(content).hexdigest()}),
                   'kubelet configuration changed beyond the reviewed serial policy')


def storage_boundary(pods):
    """This first intervention has no application volume or NAS consumer to evict."""
    actors.require(not any(p['metadata']['namespace'] == 'zot' or
        any(set(v) & {'nfs', 'persistentVolumeClaim', 'csi'} for v in p['spec'].get('volumes', []))
        for p in pods if p['metadata']['namespace'] not in EXCLUDED_NAMESPACES),
        'target has a protected or unreviewed storage consumer')


def preserve_registry_observation(pod, original):
    """Preserve a remote observation without replacing the older accepted process guard."""
    statuses = pod['status'].get('containerStatuses', [])
    actors.require(original['node'] != 'squirtle' and
                   pod['metadata']['uid'] == original['uid'] and
                   pod['metadata']['name'] == original['name'] and
                   pod['spec']['nodeName'] == original['node'] and
                   not pod['metadata'].get('deletionTimestamp') and
                   len(statuses) == 1 and statuses[0].get('ready') is True and
                   {k: statuses[0].get(k) for k in ('containerID', 'imageID', 'restartCount')} ==
                   original['container'], 'observed protected Zot runtime changed')


def native_operation(context):
    from maintenance_k3s_production import verified_completed_drain
    from maintenance_safe_release import Release, KINDS
    api, controller, hold, owner, native, identity, rpc = (context[k] for k in
        ('api', 'controller', 'hold', 'owner', 'native', 'identity', 'rpc'))
    actors.require(owner.get('component') == 'kubelet-image-pulls' and
                   coordination.reviewed_hop(owner['node'], owner['source'], owner['target'],
                                             owner['component']), 'unreviewed image-pull transition')
    content = policy_bytes(context['recovery_manifest']['policy'])
    operation, root = context['operation'], hold.state
    journal = hops.Journal(controller, hold, owner['owner'])
    before_path = root / ('image-pulls-before-' + owner['owner'] + '.json')

    def evidence(kind='prerequisites'):
        return rpc(kind)

    def verifier(value):
        return lambda step, digest: digest == hashed(value) and evidence() == value

    def accepted_runtime():
        before, after = private_json(before_path), runtime(native)
        installed(before, after, content)
        config = api.call('get', '--raw=/api/v1/nodes/' + owner['node'] + '/proxy/configz')
        actors.require(config['kubeletconfig'].get('serializeImagePulls') is True and
                       'maxParallelImagePulls' not in config['kubeletconfig'],
                       'effective kubelet policy does not serialize image pulls')
        return after

    if operation == 'initialize':
        if hold.marker.exists():
            hold.resume(owner['owner'])
        else:
            hold.acquire(owner['owner'], context['expected_identity'], owner['revision'])
        before = runtime(native)
        actors.require(str(POLICY) not in before['kubelet_configs'],
                       'existing image-pull policy requires observation, not replacement')
        if not before_path.exists():
            actors.exclusive_file(before_path, hops.canonical(before), 0o600)
        actors.require(private_json(before_path) == before, 'initial runtime changed')
        if not journal.path.exists():
            journal.initialize()
        result = {'owner': owner, 'journal': journal.inspect(), 'before': before}
    elif operation == 'release':
        release = Release(journal)
        value = evidence('applications'); digest = hashed(value)

        def safe(header, observed):
            accepted_runtime()
            return (observed == digest and identity() == header['owners']['host']['identity'] and
                    evidence('applications') == value)

        if not release.path.exists():
            release.prepare(digest, safe)
        result = release.observe(digest, safe)
        if result['state']['kinds'] == ['header']:
            result = release.release_host(digest, safe)
        if result['state']['kinds'] == list(KINDS[:3]):
            result = release.release_global(digest, safe)
    else:
        state = journal.inspect()
        if operation == 'inspect':
            result = {'owner': owner, 'journal': state}
        elif operation in ('cordon', 'restore-scheduling'):
            step = operation.replace('-', '_')
            if step == 'restore_scheduling':
                accepted_runtime()
            worker = Scheduling(journal, api)
            value = evidence(); digest = hashed(value)
            path = root / (step + '-' + owner['owner'] + '.json')
            original = private_json(root / ('cordon-' + owner['owner'] + '.json')) if step != 'cordon' else None
            if not path.exists():
                actors.exclusive_file(path, hops.canonical(worker.plan(step, original)), 0o600)
            plan = private_json(path)
            result = (worker.dispatch(plan, hashed(plan), digest, verifier(value)) if not state['pending']
                      else worker.observe(plan, digest, verifier(value)))
        elif operation == 'drain':
            worker = Drain(journal, api); value = evidence(); digest = hashed(value)
            path = root / ('drain-' + owner['owner'] + '.json')
            if not path.exists():
                plan = worker.inventory()
                actors.require(not any(ref['namespace'] == 'zot' for ref in plan['pods']),
                               'image-pull mitigation must not touch Zot')
                actors.exclusive_file(path, hops.canonical(plan), 0o600)
            plan = private_json(path)
            if not state['pending']:
                worker.start(plan, hashed(plan), digest, verifier(value))
            elif not worker.path.exists():
                worker.attach(plan)
            result = worker.advance(digest, verifier(value))
            if result.get('complete'):
                accepted = dict(result)
                journal.accept(result['parent_intent']['sha256'], hashed(accepted),
                    lambda step, observed: step == 'drain' and observed == hashed(accepted) and
                    evidence() == value and verified_completed_drain(worker, accepted))
        elif operation == 'apply-policy':
            before = private_json(before_path)
            actors.require(runtime(native) == before and not POLICY.exists(),
                           'source runtime or absent-policy rollback boundary changed')
            value = evidence(); digest = hashed(value)
            pending = journal.begin('apply_policy', hashlib.sha256(content).hexdigest(), digest, verifier(value))
            with hold.serialized():
                journal.owners(idle=True)
                actors.require(journal.read() == pending and runtime(native) == before,
                               'runtime changed before policy installation')
                node = api.call('get', 'node', owner['node'], '-o', 'json')
                actors.require(node['metadata']['uid'] == owner['node_uid'] and
                               node['spec'].get('unschedulable') is True and
                               native('systemctl', 'show', 'k3s', '-p', 'KillMode', '--value') == 'process',
                               'cordon or container-preserving service mode differs')
                actors.exclusive_file(POLICY, content, 0o644)
                native('restorecon', str(POLICY))
                native('systemctl', 'restart', 'k3s')
            result = {'dispatched': True, 'pending': pending['pending'], 'restart_replay_allowed': False}
        elif operation == 'observe-policy':
            actors.require(state['pending'] and state['pending']['step'] == 'apply_policy',
                           'no exact pending policy activation')
            after = accepted_runtime(); value = evidence(); digest = hashed(value)
            receipt = {'runtime': after, 'health': value, 'effective_serial_pulls': True}
            result = {'receipt': receipt, 'journal': journal.accept(state['pending']['sha256'], hashed(receipt),
                lambda step, observed: step == 'apply_policy' and observed == hashed(receipt) and
                accepted_runtime() == after and verifier(value)(step, digest))}
        elif operation == 'accept-applications':
            after = accepted_runtime(); value = evidence('applications')
            receipt = {'runtime': after, 'health': value}; digest = hashed(receipt)

            def verified(step, observed):
                return (step == 'accept_applications' and observed == digest and
                        accepted_runtime() == after and evidence('applications') == value)

            if not state['pending']:
                state = journal.begin('accept_applications', digest, digest, verified)
            result = {'receipt': receipt, 'journal': journal.accept(state['pending']['sha256'], digest, verified)}
        else:
            raise RuntimeError('unreviewed image-pull operation')
    print(json.dumps({'result': result}), flush=True)


def observe(args, api, baseline, kind):
    """Allow only the selected cordoned node's proven Rook monitor downtime."""
    import maintenance_production_node as production
    from rook_monitor_qualification import monitor_view
    nodes = api.call('get', 'nodes', '-o', 'json')['items']
    actors.require({n['metadata']['name']: n['metadata']['uid'] for n in nodes} == baseline['nodes'],
                   'image-pull inventory identities changed')
    target = next(n for n in nodes if n['metadata']['name'] == args.node)
    cordoned = target['spec'].get('unschedulable', False)
    target_pods = api.call('get', 'pods', '-A', '--field-selector',
                          'spec.nodeName=' + args.node, '-o', 'json')['items']
    storage_boundary(target_pods)
    from maintenance_control_plane import observe as etcd_observe
    etcd = etcd_observe(args, {name: VERSION for name in ('charmander', 'squirtle', 'bulbasaur')})
    for node in nodes:
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        actors.require(node['status']['nodeInfo']['kubeletVersion'] == VERSION and
                       conditions.get('Ready') == 'True' and all(conditions.get(k) == 'False' for k in
                       ('MemoryPressure', 'DiskPressure', 'PIDPressure')), 'node health differs')
    ceph = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'ceph', 'status', '-f', 'json')
    monmap = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'ceph', 'mon', 'dump', '-f', 'json')
    view = monitor_view(ceph, monmap, baseline['monitors'], baseline['target_monitor'], baseline['fsid'])
    actors.require(not view['checks'] or cordoned, 'monitor outage outside the cordoned intervention')
    groups = ceph['pgmap']['pgs_by_state']
    actors.require(groups and all({'active', 'clean'} <= set(g['state_name'].split('+')) and
                   set(g['state_name'].split('+')) <= {'active', 'clean', 'scrubbing', 'deep'} for g in groups),
                   'Ceph PGs are not active and clean')
    expected_outages = []
    for resource in ('deployments', 'statefulsets'):
        for item in production.maintenance_items(api.call('get', resource, '-A', '-o', 'json')['items']):
            desired = item['spec'].get('replicas', 1); status = item.get('status', {})
            if (status.get('observedGeneration') == item['metadata']['generation'] and
                    status.get('readyReplicas', 0) == desired and status.get('updatedReplicas', 0) == desired):
                continue
            if (cordoned and item['metadata']['uid'] in baseline['target_observers'] and
                    production.pending_on_maintained_node(api, item, args.node)):
                expected_outages.append(item['metadata']['uid']); continue
            raise RuntimeError('controller unready: ' + item['metadata']['namespace'] + '/' + item['metadata']['name'])
    pod = api.call('get', 'pod', baseline['zot']['name'], '-n', 'zot', '-o', 'json')
    preserve_registry_observation(pod, baseline['zot'])
    result = {'node_uids': baseline['nodes'], 'ceph_fsid': baseline['fsid'],
              'etcd_cluster_id': etcd['status'][0]['Status']['header']['cluster_id'],
              'monitor_members': view['members'], 'monitor_quorum': view['quorum'],
              'checks': view['checks'], 'expected_outages': sorted(expected_outages),
              'zot_observation_preserved': baseline['zot']}
    if kind == 'applications':
        actors.require(not cordoned and not view['checks'] and not expected_outages,
                       'target is not fully restored')
        applications = production.maintenance_items(api.call('get', 'applications', '-n', 'argocd', '-o', 'json')['items'],
                                                    applications=True)
        actors.require(applications, 'application inventory absent')
        for app in applications:
            actors.require(app['status']['sync']['status'] == 'Synced' and
                           app['status']['health']['status'] == 'Healthy' and
                           app['status']['sync']['revision'] == baseline['revision'] and
                           not app['status'].get('conditions'), 'application comparison is not current and green')
        for item in production.maintenance_items(target_pods):
            if item['status']['phase'] == 'Succeeded':
                production.completed_job_pod(api, item); continue
            actors.require(not item['metadata'].get('deletionTimestamp') and
                           any(c['type'] == 'Ready' and c['status'] == 'True' for c in
                               item['status'].get('conditions', [])) and
                           len(item['status'].get('containerStatuses', [])) == len(item['spec']['containers']) and
                           all(c.get('ready') for c in item['status']['containerStatuses']),
                           'target workload is not ready')
        result['applications'] = sorted(app['metadata']['name'] for app in applications)
    return result


def main():
    import argparse
    import subprocess
    import maintenance_production_node as production
    from maintenance_api_reader import Reader
    from maintenance_k3s_production import published_revision
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('initialize', 'inspect', 'cordon', 'drain', 'apply-policy',
        'observe-policy', 'restore-scheduling', 'accept-applications', 'release'))
    parser.add_argument('--node', choices=('squirtle',), required=True)
    for name in ('kubectl', 'identity', 'known-hosts', 'baseline'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(); production.select_node(args.node)
    revision = published_revision()
    baseline = json.loads(Path(args.baseline).read_bytes())
    actors.require(baseline['revision'] == revision and baseline['target'] == args.node,
                   'rollout baseline is not bound to the published candidate')
    policy_path = 'metal/roles/k3s/files/kubelet-serial-image-pulls.conf'
    policy = Path(policy_path).read_text(); policy_bytes(policy)
    actors.require(policy.encode() == subprocess.check_output(['git', 'show', revision + ':' + policy_path]),
                   'unpublished image-pull configuration')
    names = (*production.MODULES, 'maintenance_k3s_contract', 'maintenance_k3s_binary',
             'maintenance_k3s_production', 'maintenance_kubelet_image_pulls')
    bundle = {}
    for name in names:
        path = 'metal/scripts/' + name + '.py'
        source = subprocess.check_output(['git', 'show', revision + ':' + path])
        actors.require(Path(path).read_bytes() == source, 'unpublished image-pull dependency: ' + path)
        bundle[name] = source.decode()
    api = Reader(args.kubectl, 'https://10.0.20.11:6443')
    try:
        controller = coordination.Ownership(api, production.DS_UID, baseline['nodes'])
        ds = controller.observed()
        raw = ds['metadata'].get('annotations', {}).get(coordination.JOURNAL)
        if raw:
            owner = controller.resume(json.loads(raw)['owner'])
            actors.require(owner.get('component') == 'kubelet-image-pulls' and owner['node'] == args.node and
                           owner['revision'] == revision, 'another transition owns maintenance')
        else:
            actors.require(args.operation == 'initialize', 'initialize ownership before an image-pull action')
            observe(args, api, baseline, 'prerequisites')
            owner = controller.acquire(args.node, 'parallel', 'serial', revision, component='kubelet-image-pulls')
        result = production.run_worker(args, api, owner, {}, {'policy': policy}, bundle,
            component_observer=lambda request: observe(args, api, baseline, request['rpc']))
        print(json.dumps(result))
    finally:
        api.close()


if __name__ == '__main__':
    main()
