#!/usr/bin/env python3
"""Actual Kubernetes release and private files; native host/package safety synthetic."""

import argparse
import copy
import json
from pathlib import Path
import signal

import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_hop_journal as hops
import maintenance_node_drain as drain
import maintenance_safe_release as release
import maintenance_scheduling_qualification as scheduling_fixture


class SyntheticIdle:
    """No native actor proof; queries deliberately allow an absent released marker."""
    def idle(self, _marker):
        pass


class API(scheduling_fixture.API):
    def __init__(self, fixture):
        super().__init__(fixture)
        self.global_patches, self.lose_global_response = [], False

    def call(self, *args, data=None):
        global_patch = args[:4] == ('patch', 'daemonset', 'kured', '-n')
        if global_patch:
            actors.require(args[4:7] == ('kured', '--type=json', '--patch') and args[8:] == ('-o', 'json'),
                           'foreign qualification global patch')
            self.global_patches.append({'argv': list(args), 'operations': json.loads(args[7])})
        result = super().call(*args, data=data)
        if global_patch and self.lose_global_response:
            self.lose_global_response = False
            raise RuntimeError('qualification lost response after actual global release')
        return result


def synthetic_safety(application):
    return {'application': copy.deepcopy(application), 'native_host_package_reboot_recovery_six_layers_synthetic': True,
            'production_release_unqualified': True}


class Qualification(scheduling_fixture.Qualification):
    def application(self, prior):
        fixture = scheduling_fixture.drain_fixture
        deployment = self.kubectl('get', 'deployment', 'workload', '-n', fixture.NAMESPACE)
        actors.require(deployment['metadata']['uid'] == prior['post_drain_availability']['deployment_uid'] and
                       deployment['status']['observedGeneration'] == deployment['metadata']['generation'] and
                       all(deployment['status'].get(k) == 3 for k in
                           ('replicas', 'readyReplicas', 'availableReplicas', 'updatedReplicas')),
                       'original qualification workload changed or is unready')
        pods = self.kubectl('get', 'pods', '-n', fixture.NAMESPACE, '-l', 'app=qualification-drain')['items']
        actors.require(len(pods) == 3 and all(not p['metadata'].get('deletionTimestamp') and
                       len(p['status'].get('containerStatuses', [])) == 1 and
                       p['status']['containerStatuses'][0].get('ready') is True for p in pods),
                       'qualification application replicas are unready')
        original = prior['canary']['pod']
        canary = self.kubectl('get', 'pod', original['metadata']['name'], '-n', fixture.NAMESPACE)
        actors.require(canary['metadata']['uid'] == original['metadata']['uid'] and
                       canary['spec']['nodeName'] == original['spec']['nodeName'] and
                       not canary['metadata'].get('deletionTimestamp') and
                       len(canary['status'].get('containerStatuses', [])) == 1 and
                       canary['status']['containerStatuses'][0].get('ready') is True,
                       'original restored-node canary changed or is unready')
        response = self.kubectl('get', '--raw=/api/v1/namespaces/' + fixture.NAMESPACE + '/pods/' +
                                canary['metadata']['name'] + ':8080/proxy/', json_output=False)
        actors.require(response == fixture.PAYLOAD, 'release application HTTP differs')
        return {'deployment_uid': deployment['metadata']['uid'], 'ready_pod_uids': sorted(
            p['metadata']['uid'] for p in pods), 'canary_uid': canary['metadata']['uid'],
                'target_node_uid': prior['canary']['target_node_uid'], 'http_sha256': hops.digest(response)}

    def profile(self):
        prior = super().profile()
        api = API(self)
        original = prior['parent']['owners']
        daemonset_uid = next(p['controller']['uid'] for p in prior['drain_plan']['pods']
                             if p['keep'] and p['controller']['kind'] == 'DaemonSet')
        ownership = coordination.Ownership(api, daemonset_uid, prior['node_uids'])
        token = original['global']['owner'];local = self.work / 'scheduling'
        def fresh():
            hold = actors.Hold(SyntheticIdle(), lambda: copy.deepcopy(original['host']['identity']),
                               lambda value: ownership.resume(value) == original['global'],
                               local / 'state', local / 'units')
            return release.Release(hops.Journal(ownership, hold, token))
        worker = fresh()
        actors.require(worker.journal.inspect() == prior['parent'], 'original scheduling journal changed')
        application = self.application(prior);evidence = synthetic_safety(application);digest = drain.hashed(evidence)
        pending = worker.journal.begin('accept_applications', drain.hashed(application), digest,
                                       lambda *_: self.application(prior) == application)
        worker.journal.accept(pending['pending']['sha256'], drain.hashed(application),
                              lambda *_: self.application(prior) == application)
        def verify(_header, value):
            return value == digest and self.application(prior) == application
        prepared = worker.prepare(digest, verify)
        hop_files = {p.name: p.read_bytes() for p in worker.journal.path.iterdir()}
        guard_files = {str(p): p.read_bytes() for p in worker.hold.units.rglob('*.conf')}
        original_annotations = api.snapshot()[0]['metadata']['annotations']
        actual_host_release = worker.hold.release;host_calls = []
        def lose_host(*args):
            host_calls.append(True);actual_host_release(*args)
            raise RuntimeError('qualification lost response after actual host marker release')
        worker.hold.release = lose_host
        try:worker.release_host(digest, verify)
        except RuntimeError as error:
            actors.require(str(error) == 'qualification lost response after actual host marker release',
                           'unexpected host release refusal')
        else:raise RuntimeError('expected lost host release response missing')
        host_pending = fresh().read()
        actors.require(host_pending['kinds'] == list(release.KINDS[:2]) and len(host_calls) == 1 and
                       not worker.hold.marker.exists() and not api.global_patches, 'host release intent differs')
        host_accepted = fresh().observe(digest, verify)
        actors.require(host_accepted['state']['kinds'] == list(release.KINDS[:3]) and not api.global_patches,
                       'host observer replayed a release')
        api.lose_global_response = True
        try:fresh().release_global(digest, verify)
        except RuntimeError as error:
            actors.require(str(error) == 'qualification lost response after actual global release',
                           'unexpected global release refusal')
        else:raise RuntimeError('expected lost global release response missing')
        global_pending = fresh().read()
        actors.require(global_pending['kinds'] == list(release.KINDS[:4]) and len(api.global_patches) == 1,
                       'global release intent or mutation count differs')
        final = fresh().observe(digest, verify)
        repeated = fresh().observe(digest, verify)
        actors.require(final == repeated and final['complete'] is True and len(api.global_patches) == 1 and
                       len(host_calls) == 1 and not worker.hold.marker.exists(), 'release acceptance or replay differs')
        annotations = api.snapshot()[0]['metadata'].get('annotations', {})
        actors.require(annotations == {k:v for k,v in original_annotations.items() if k not in
                       (coordination.LOCK, coordination.JOURNAL)}, 'unrelated Kured annotations changed')
        actors.require(hop_files == {p.name:p.read_bytes() for p in worker.journal.path.iterdir()} and
                       guard_files == {str(p):p.read_bytes() for p in worker.hold.units.rglob('*.conf')},
                       'original hop records or guards changed')
        return {'scheduling': prior, 'application': application, 'synthetic_safety': evidence,
                'prepared': prepared, 'host_pending': host_pending, 'host_accepted': host_accepted,
                'global_pending': global_pending, 'final': final, 'host_release_calls': len(host_calls),
                'actual_global_patches': api.global_patches, 'unrelated_annotations_preserved': True,
                'original_hop_and_guard_bytes_preserved': True, 'production_changes': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('name', 'docker-host', 'docker-server', 'k3d', 'kubectl', 'guest-resolver-file', 'revision'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    fixture = Qualification(parser.parse_args())
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, scheduling_fixture.drain_fixture.cluster.interrupted)
    try:fixture.save('result', fixture.run())
    finally:fixture.cleanup()


if __name__ == '__main__':
    main()
