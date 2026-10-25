#!/usr/bin/env python3
"""Actual Node scheduling and eviction; native package/host phases stay synthetic."""

import argparse
import copy
import json
from pathlib import Path
import signal

import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_drain_qualification as drain_fixture
import maintenance_hop_journal as hops
import maintenance_node_drain as drain
import maintenance_node_scheduling as scheduling
from test_maintenance_actor_hold import Systemd


class API(drain_fixture.API):
    def __init__(self, fixture):
        super().__init__(fixture)
        self.node_patches, self.lose_node_response = [], False

    def call(self, *args, data=None):
        node_patch = args[:2] == ('patch', 'node')
        if node_patch:
            actors.require(args[3:5] == ('--type=json', '--patch') and args[6:] == ('-o', 'json'),
                           'foreign qualification Node patch')
            self.node_patches.append({'argv': list(args), 'operations': json.loads(args[5])})
        result = super().call(*args, data=data)
        if node_patch and self.lose_node_response:
            self.lose_node_response = False
            raise RuntimeError('qualification lost response after actual Node patch')
        return result


def synthetic_checkpoint(step):
    actors.require(step in hops.STEPS[2:7], 'foreign synthetic checkpoint')
    return {'step': step, 'synthetic_not_executed': True,
            'native_package_reboot_recovery_and_infrastructure_unqualified': True}


class Qualification(drain_fixture.Qualification):
    def transition(self, journal, api, plan, available):
        digest = drain.hashed(available)
        api.lose_node_response = True
        count = len(api.node_patches)
        try:
            scheduling.Scheduling(journal, api).dispatch(
                plan, drain.hashed(plan), digest, lambda *_: self.availability() == available)
        except RuntimeError as error:
            actors.require(str(error) == 'qualification lost response after actual Node patch',
                           'unexpected actual scheduling refusal')
        else:raise RuntimeError('expected lost Node patch response missing')
        pending = journal.inspect()
        actors.require(pending['pending']['step'] == plan['step'] and len(api.node_patches) == count + 1,
                       'durable scheduling intent or single patch missing')
        accepted = scheduling.Scheduling(journal, api).observe(
            plan, digest, lambda *_: self.availability() == available)
        actors.require(accepted['accepted'] and len(api.node_patches) == count + 1,
                       'scheduling observation replayed or incomplete')
        return {'plan': plan, 'pending_after_response_loss': pending, 'acceptance': accepted}

    def canary(self, target):
        workload = copy.deepcopy(next(obj for obj in drain_fixture.fixtures(2) if obj['kind'] == 'Deployment'))
        workload['metadata']['name'] = 'scheduling-canary'
        spec = workload['spec'];spec['replicas'] = 1
        labels = {'app': 'scheduling-canary'}
        spec['selector']['matchLabels'] = labels;spec['template']['metadata']['labels'] = labels
        pod_spec = spec['template']['spec'];pod_spec.pop('affinity')
        hostname = target['metadata']['labels']['kubernetes.io/hostname']
        pod_spec['nodeSelector'] = {'kubernetes.io/hostname': hostname}
        self.kubectl('apply', '-f', '-', data=hops.canonical(workload), json_output=False)
        self.kubectl('rollout', 'status', 'deployment/scheduling-canary', '-n', drain_fixture.NAMESPACE,
                     '--timeout=600s', json_output=False)
        pods = self.kubectl('get', 'pods', '-n', drain_fixture.NAMESPACE, '-l', 'app=scheduling-canary')['items']
        actors.require(len(pods) == 1, 'restored scheduling canary coverage differs')
        pod = pods[0]
        actors.require(not pod['metadata'].get('deletionTimestamp') and
                       pod['spec']['nodeName'] == target['metadata']['name'] and
                       len(pod['status'].get('containerStatuses', [])) == 1 and
                       pod['status']['containerStatuses'][0].get('ready') is True,
                       'canary did not become Ready on exact restored Node')
        response = self.kubectl('get', '--raw=/api/v1/namespaces/' + drain_fixture.NAMESPACE +
                                '/pods/' + pod['metadata']['name'] + ':8080/proxy/', json_output=False)
        actors.require(response == drain_fixture.PAYLOAD, 'restored Node canary HTTP differs')
        return {'pod': pod, 'target_node_uid': target['metadata']['uid'],
                'http_sha256': hops.digest(response), 'origin': 'API-server Pod proxy'}

    def profile(self):
        objects = drain_fixture.fixtures(2)
        self.kubectl('apply', '-f', '-', data=hops.canonical({'apiVersion': 'v1', 'kind': 'List',
                                                           'items': objects}), json_output=False)
        for resource, namespace in (('daemonset/kured', 'kured'), ('deployment/workload', drain_fixture.NAMESPACE)):
            self.kubectl('rollout', 'status', resource, '-n', namespace, '--timeout=600s', json_output=False)
        initial = self.availability();api = API(self)
        ds, _, nodes = api.snapshot();node_uids = {n['metadata']['name']: n['metadata']['uid'] for n in nodes}
        actors.require({node for _,node in initial['ready_pods']} == set(node_uids), 'initial replicas not spread')
        target_name = 'k3d-' + self.args.name + '-agent-0'
        target = api.call('get', 'node', target_name, '-o', 'json')
        ownership = coordination.Ownership(api, ds['metadata']['uid'], node_uids)
        owner = ownership.acquire(target_name, 39, 41, self.args.revision)
        local = self.work / 'scheduling';local.mkdir(mode=0o700);(local / 'units').mkdir(mode=0o700)
        identity = {'machine': 'synthetic-host-' + owner['node_uid'], 'root_uuid': 'synthetic-root'}
        hold = actors.Hold(Systemd(), lambda: identity, lambda token: ownership.resume(token) == owner,
                           local / 'state', local / 'units')
        hold.acquire(owner['owner'], identity, self.args.revision)
        journal = hops.Journal(ownership, hold, owner['owner']);journal.initialize()
        cordon_plan = scheduling.Scheduling(journal, api).plan('cordon')
        cordon = self.transition(journal, api, cordon_plan, initial)
        worker = drain.Drain(journal, api);plan = worker.inventory()
        selected = [pod for pod in plan['pods'] if not pod['keep']]
        actors.require(len(selected) == 1 and selected[0]['namespace'] == drain_fixture.NAMESPACE,
                       'unexpected actual eviction target')
        self.kubectl('wait', 'pdb/workload', '-n', drain_fixture.NAMESPACE,
                     '--for=jsonpath={.status.disruptionsAllowed}=1', '--timeout=180s', json_output=False)
        digest = drain.hashed(initial)
        worker.start(plan, drain.hashed(plan), digest, lambda *_: self.availability() == initial)
        queued = worker.advance(digest, lambda *_: self.availability() == initial)
        actors.require(queued['mutation_performed'] and len(api.posts) == 1, 'actual eviction not queued once')
        self.kubectl('wait', 'pod/' + selected[0]['name'], '-n', drain_fixture.NAMESPACE,
                     '--for=delete', '--timeout=180s', json_output=False)
        self.kubectl('rollout', 'status', 'deployment/workload', '-n', drain_fixture.NAMESPACE,
                     '--timeout=600s', json_output=False)
        current = self.availability();digest = drain.hashed(current)
        actors.require(selected[0]['uid'] not in current['endpoint_uids'] and
                       all(node != target_name for _,node in current['ready_pods']), 'drain replacement differs')
        fresh = drain.Drain(journal, api)
        actors.require('observed' in fresh.advance(digest, lambda *_: self.availability() == current),
                       'drained UID observation missing')
        outcome = fresh.advance(digest, lambda *_: self.availability() == current)
        actors.require(outcome['complete'], 'actual drain receipt incomplete')
        pending = journal.inspect()['pending']
        journal.accept(pending['sha256'], drain.hashed(outcome), lambda step, value:
                       step == 'drain' and value == drain.hashed(outcome) and
                       fresh.read()['records_sha256'] == outcome['records_sha256'] and
                       drain.hashed(fresh.inventory()) == outcome['inventory_sha256'] and
                       self.availability() == current)
        synthetic = []
        for step in hops.STEPS[2:7]:
            receipt = synthetic_checkpoint(step);synthetic.append(receipt);digest = drain.hashed(receipt)
            pending = journal.begin(step, digest, digest, lambda *_: True)
            journal.accept(pending['pending']['sha256'], digest,
                           lambda observed, value: observed == step and value == digest)
        restore_plan = scheduling.Scheduling(journal, api).plan('restore_scheduling', cordon_plan)
        restored = self.transition(journal, api, restore_plan, current)
        canary = self.canary(api.call('get', 'node', target_name, '-o', 'json'))
        after = api.call('get', 'node', target_name, '-o', 'json')
        for key in ('labels', 'annotations'):
            actors.require(after['metadata'].get(key) == target['metadata'].get(key), 'unrelated Node metadata changed')
        actors.require({k:v for k,v in target['spec'].items() if k != 'unschedulable'} ==
                       {k:v for k,v in after['spec'].items() if k != 'unschedulable'}, 'unrelated Node spec changed')
        final = journal.inspect()
        actors.require(final['completed'] == list(hops.STEPS[:-1]) and final['pending'] is None and
                       after['spec']['unschedulable'] is False and len(api.node_patches) == 2 and
                       len(api.posts) == 1 and hold.marker.exists() and ownership.resume(owner['owner']) == owner,
                       'actual scheduling outcome, ownership or mutation count differs')
        return {'cluster_uid': self.cluster_uid, 'node_uids': node_uids, 'initial_availability': initial,
                'post_drain_availability': current, 'cordon': cordon, 'drain_plan': plan,
                'drain_receipt': outcome, 'synthetic_not_executed': synthetic, 'restore': restored,
                'canary': canary, 'final_node': after, 'node_patches': api.node_patches,
                'evictions': api.posts, 'parent': final, 'host_systemd_and_recovery_synthetic': True,
                'native_packages_ceph_cilium_nas_and_safe_release_unqualified': True, 'production_changes': False}

    def run(self):
        try:self.create();return self.profile()
        finally:self.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('name', 'docker-host', 'docker-server', 'k3d', 'kubectl', 'guest-resolver-file', 'revision'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    fixture = Qualification(parser.parse_args())
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):signal.signal(number, drain_fixture.cluster.interrupted)
    try:fixture.save('result', fixture.run())
    finally:fixture.cleanup()


if __name__ == '__main__':
    main()
