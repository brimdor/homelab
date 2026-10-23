#!/usr/bin/env python3
"""Exercise real GPU controllers against an owned agentless synthetic API."""

import copy
import hashlib
import json
import re
import subprocess
import threading
import time

import etcd_recovery as common
import gpu_admission_qualification as admission


BUNDLE_SHA256 = 'b3ce3c334be09c1c46c31f0b17cccc50fce7ba80adb587000b977bf73648a88d'
IMAGES = dict(zip(admission.VERSIONS, (
    'fd432b106a44ce10935bd48c90c72687a62bda162429a8527858b1a8afe2ead0',
    '46dbfc6fd6df39dc3356ab536c8bd222c42db98f9505f508a8d17b6830a23842',
    '687b3ca93ec7bcbac9e62e86217e41219c1a45e57127c4428ad7cb636cea63ba',
    'ca6cbd45e11779164aa89fa9d20517bce4717b9a772f168a3c492075aad0abfe',
    'e118f631813f93a43fa17332fb2060d3d1f3f150359dd6744f3a9b2f7b7c5707',
)))


def validate_bundle(bundle):
    if hashlib.sha256(common.canonical(bundle)).hexdigest() != BUNDLE_SHA256:
        raise RuntimeError('reviewed GPU controller bundle changed')
    subset = {'values_sha256': bundle['values_sha256'], 'stages': [
        {key: stage[key] for key in ('version', 'archive_sha256', 'crds', 'policy')}
        for stage in bundle['stages']]}
    admission.validate_resources(subset)
    for stage in bundle['stages']:
        operator = stage['operator']
        if (operator['command'] != ['gpu-operator'] or
                operator['image'] != 'nvcr.io/nvidia/gpu-operator:v' + stage['version'] or
                operator['resources']['limits'] != {'cpu': '500m', 'memory': '350Mi'}):
            raise RuntimeError('reviewed GPU operator process changed')
    return BUNDLE_SHA256


def require_operator(value, api_id, scratch, run_id, stage):
    host = value['HostConfig']
    expected = {'NetworkMode': 'container:' + api_id, 'ReadonlyRootfs': True,
                'Privileged': False, 'CapDrop': ['ALL'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 256, 'NanoCpus': 500000000,
                'Memory': 350 * 1024 * 1024, 'Tmpfs': {'/tmp': 'rw,nosuid,nodev'}}
    labels = value['Config'].get('Labels', {})
    if (any(host.get(k) != v for k, v in expected.items()) or
            any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings', 'Links', 'VolumesFrom')) or
            host.get('SecurityOpt') != ['no-new-privileges:true'] or
            host.get('LogConfig', {}).get('Type') != 'none' or
            labels.get('io.eaglepass.maintenance') != '103' or
            labels.get('io.eaglepass.recovery-run') != run_id or
            labels.get('io.eaglepass.gpu-version') != stage['version'] or
            value['Config']['Image'] != 'nvcr.io/nvidia/gpu-operator@sha256:' + IMAGES[stage['version']] or
            value['Config'].get('User') != '0' or
            value['Config'].get('Entrypoint') != ['gpu-operator'] or
            value['Config'].get('Cmd') != stage['operator']['args']):
        raise RuntimeError('GPU controller isolation or process identity changed')
    mounts = {(str(scratch / 'kubeconfig'), '/qualification/kubeconfig', False)}
    if stage['version'] in admission.VERSIONS[:3]:
        mounts.add((str(scratch / 'gpu-os-release'), '/host-etc/os-release', False))
    actual = value.get('Mounts', [])
    if (len(actual) != len(mounts) or any(m.get('Type') != 'bind' for m in actual) or
            {(m.get('Source'), m.get('Destination'), m.get('RW')) for m in actual} != mounts):
        raise RuntimeError('GPU controller has an unexpected mount')


def ready_policy(value, uid):
    metadata = value['metadata']
    if metadata.get('uid') != uid or metadata.get('deletionTimestamp'):
        raise RuntimeError('owned GPU policy identity changed')
    status = value.get('status', {})
    return (status.get('state') == 'ready' and any(
        condition.get('type') == 'Ready' and condition.get('status') == 'True' and
        condition.get('reason') == 'NFDLabelsMissing' for condition in status.get('conditions', [])))


def ready_endpoint(api_id):
    pid = str(common.inspect(api_id)['State']['Pid'])
    program = ('import urllib.request; '
               'r=urllib.request.urlopen("http://127.0.0.1:8081/readyz",timeout=5); '
               'assert r.status==200; print(r.read().decode())')
    result = common.command(['nsenter', '-t', pid, '-n', 'python3', '-c', program], check=False)
    return result.returncode == 0 and result.stdout.strip() == b'ok'


def workload_inventory(workloads, policy_uid):
    objects = {value['metadata']['uid']: value for value in workloads}
    if len(objects) != len(workloads):
        raise RuntimeError('duplicate GPU workload UID')
    inventory = []
    for workload in workloads:
        current = workload
        seen = set()
        while True:
            uid = current['metadata']['uid']
            if uid in seen:
                raise RuntimeError('cyclic GPU workload ownership')
            seen.add(uid)
            owners = [owner for owner in current['metadata'].get('ownerReferences', [])
                      if owner.get('controller') is True]
            if len(owners) != 1:
                raise RuntimeError('GPU workload has ambiguous controller ownership')
            owner = owners[0]
            if owner.get('uid') == policy_uid and owner.get('kind') == 'ClusterPolicy':
                break
            parent = objects.get(owner.get('uid'))
            if parent is None or parent['kind'] != owner.get('kind'):
                raise RuntimeError('GPU workload has an unexpected owner')
            current = parent
        meta = workload['metadata']
        spec = workload.get('spec', {}).get('template', workload).get('spec', {})
        inventory.append({'kind': workload['kind'], 'name': meta['name'], 'uid': meta['uid'],
                          'owner_uid': policy_uid, 'images': [c['image'] for c in
                          spec.get('initContainers', []) + spec.get('containers', [])]})
    return inventory


def qualify(bundle, run_id):
    digest = validate_bundle(bundle)

    def reconcile(api_id, scratch, client, identity):
        evidence = {'accepted': False, 'bundle_sha256': digest, 'stages': [], 'gpu_devices_used': 0}
        schemas = {}
        policy_uid = None

        def api(*args):
            result = common.docker(*client, *args, check=False)
            if result.returncode:
                evidence['api_failure'] = {'exit': result.returncode,
                                           'stderr_sha256': hashlib.sha256(result.stderr).hexdigest()}
                raise RuntimeError('synthetic GPU API operation failed')
            return json.loads(result.stdout)

        def submit(value, operation, *extra):
            (scratch / 'gpu-resource.json').write_bytes(common.canonical(value))
            return api(operation, '--validate=strict', '-f=/work/gpu-resource.json', '-o=json', *extra)

        def no_nodes():
            if api('get', 'nodes', '-o=json')['items']:
                raise RuntimeError('GPU controller fixture acquired a node')
            state = common.inspect(api_id)
            common.require_isolation(state, scratch, identity, None)
            pid = str(state['State']['Pid'])
            links = json.loads(common.command(['nsenter', '-t', pid, '-n', 'ip', '-j', 'link']).stdout)
            routes = []
            for family in ('-4', '-6'):
                routes += json.loads(common.command([
                    'nsenter', '-t', pid, '-n', 'ip', family, '-j', 'route', 'show', 'table', 'all']).stdout)
            common.require_network(links, routes)

        try:
            no_nodes()
            submit({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'gpu-operator'}}, 'create')
            (scratch / 'gpu-os-release').write_text('NAME=Fedora\nID=fedora\nVERSION_ID=44\n')
            for stage in bundle['stages']:
                record = {'version': stage['version'], 'accepted': False}
                evidence['stages'].append(record)
                for crd in stage['crds']:
                    desired = copy.deepcopy(crd)
                    name = crd['metadata']['name']
                    operation = 'create'
                    if name in schemas:
                        meta = api('get', 'crd', name, '-o=json')['metadata']
                        if meta['uid'] != schemas[name] or meta.get('deletionTimestamp'):
                            raise RuntimeError('owned GPU schema identity changed')
                        desired['metadata'].update(uid=meta['uid'], resourceVersion=meta['resourceVersion'])
                        operation = 'replace'
                    written = submit(desired, operation)
                    uid = written['metadata']['uid']
                    if name in schemas and uid != schemas[name]:
                        raise RuntimeError('GPU schema replacement changed UID')
                    schemas[name] = uid
                common.docker(*client, 'wait', '--for=condition=Established', '--timeout=180s',
                              *['crd/' + name for name in sorted(schemas)])
                desired = copy.deepcopy(stage['policy'])
                operation = 'create'
                if policy_uid:
                    meta = api('get', 'clusterpolicy', 'cluster-policy', '-o=json')['metadata']
                    if meta['uid'] != policy_uid or meta.get('deletionTimestamp'):
                        raise RuntimeError('owned GPU policy changed before upgrade')
                    desired['metadata'].update(uid=meta['uid'], resourceVersion=meta['resourceVersion'])
                    operation = 'replace'
                policy = submit(desired, operation)
                policy_uid = policy['metadata']['uid']
                api('patch', 'clusterpolicy', 'cluster-policy', '--subresource=status', '--type=merge',
                    '-p={"status":null}', '-o=json')
                image = 'nvcr.io/nvidia/gpu-operator@sha256:' + IMAGES[stage['version']]
                before = set(common.docker('image', 'ls', '--no-trunc', '-q').stdout.decode().split())
                operator_id = image_id = attach = reader = None
                output = bytearray()
                output_lock = threading.Lock()
                try:
                    common.docker('pull', image)
                    image_info = json.loads(common.docker('image', 'inspect', image).stdout)[0]
                    image_id = image_info['Id']
                    if (image_info['Os'] != 'linux' or image_info['Architecture'] != 'amd64' or
                            image_info['Config'].get('Volumes')):
                        raise RuntimeError('GPU operator image platform or volume contract changed')
                    args = ['create', '--network=container:' + api_id, '--read-only', '--cap-drop=ALL',
                            '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=256',
                            '--cpus=0.5', '--memory=350m', '--user=0', '--tmpfs=/tmp:rw,nosuid,nodev',
                            '--label=io.eaglepass.maintenance=103', '--label=io.eaglepass.recovery-run=' + identity,
                            '--label=io.eaglepass.gpu-version=' + stage['version'],
                            '--mount=type=bind,source=' + str(scratch / 'kubeconfig') + ',target=/qualification/kubeconfig,readonly',
                            '--env=KUBECONFIG=/qualification/kubeconfig', '--entrypoint=gpu-operator']
                    for env in stage['operator']['env']:
                        value = env.get('value')
                        if env['name'] == 'OPERATOR_NAMESPACE':
                            if env.get('valueFrom') != {'fieldRef': {'fieldPath': 'metadata.namespace'}}:
                                raise RuntimeError('GPU namespace environment changed')
                            value = 'gpu-operator'
                        if not isinstance(value, str):
                            raise RuntimeError('unexpected GPU controller environment source')
                        args.append('--env=' + env['name'] + '=' + value)
                    if stage['version'] in admission.VERSIONS[:3]:
                        args.append('--mount=type=bind,source=' + str(scratch / 'gpu-os-release') +
                                    ',target=/host-etc/os-release,readonly')
                    operator_id = common.docker(*args, image, *stage['operator']['args']).stdout.decode().strip()
                    if not re.fullmatch('[a-f0-9]{64}', operator_id):
                        raise RuntimeError('invalid owned GPU operator identity')
                    require_operator(common.inspect(operator_id), api_id, scratch, identity, stage)
                    common.require_no_logging(operator_id)
                    attach = subprocess.Popen(['docker', 'start', '--attach', operator_id],
                                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

                    def drain():
                        while chunk := attach.stdout.read(4096):
                            with output_lock:
                                output.extend(chunk)
                                del output[:-262144]
                    reader = threading.Thread(target=drain)
                    reader.start()
                    for iteration in range(2):
                        deadline = time.monotonic() + 180
                        while True:
                            if attach.poll() is not None:
                                raise RuntimeError('native GPU operator exited before reconciliation')
                            no_nodes()
                            require_operator(common.inspect(operator_id), api_id, scratch, identity, stage)
                            current = api('get', 'clusterpolicy', 'cluster-policy', '-o=json')
                            record['latest_status'] = current.get('status', {})
                            if ready_policy(current, policy_uid) and ready_endpoint(api_id):
                                break
                            if time.monotonic() >= deadline:
                                raise RuntimeError('native GPU no-node reconciliation did not become ready in180seconds')
                            time.sleep(2)
                        record.setdefault('reconciliations', []).append({
                            'policy_uid': policy_uid, 'resource_version': current['metadata']['resourceVersion'],
                            'status': current['status']})
                        if iteration == 0:
                            api('patch', 'clusterpolicy', 'cluster-policy', '--subresource=status', '--type=merge',
                                '-p={"status":null}', '-o=json')
                    no_nodes()
                    workloads = api('get', 'daemonsets,deployments,replicasets,jobs,pods',
                                    '-n=gpu-operator', '-o=json')['items']
                    inventory = workload_inventory(workloads, policy_uid)
                    record.update(accepted=True, image=image, schema_uids=dict(schemas), nodes=0,
                                  controller_only_no_device_acceptance=True, workloads=inventory)
                finally:
                    if operator_id:
                        require_operator(common.inspect(operator_id), api_id, scratch, identity, stage)
                        common.docker('rm', '--force', '--volumes', operator_id)
                        if common.docker('inspect', operator_id, check=False).returncode == 0:
                            raise RuntimeError('owned GPU operator container remains')
                    if attach:
                        try:
                            attach.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            attach.terminate()
                            attach.wait(timeout=15)
                    if reader:
                        reader.join(timeout=15)
                        if reader.is_alive():
                            raise RuntimeError('GPU output reader remains')
                    with output_lock:
                        record['attached_output_sha256'] = hashlib.sha256(output).hexdigest()
                        record['attached_output_retained_bytes'] = len(output)
                        record['public_error_categories'] = [term.decode() for term in (
                            b'permission denied', b'no such file', b'connection refused', b'failed to')
                            if term in output.lower()]
                    if image_id and image_id not in before:
                        if common.docker('ps', '--all', '--quiet', '--filter=ancestor=' + image_id).stdout.strip():
                            raise RuntimeError('new GPU image acquired another consumer; retained')
                        common.docker('image', 'rm', image)
                        if common.docker('image', 'inspect', image, check=False).returncode == 0:
                            raise RuntimeError('new unused GPU operator image remains')
                    record['operator_container_absent'] = True
                    record['attach_reaped'] = attach is None or attach.poll() is not None
            evidence['accepted'] = True
        except RuntimeError as error:
            evidence['error'] = str(error)
        return evidence

    return common.qualify(common.run_identifier(run_id), synthetic_check=reconcile)
