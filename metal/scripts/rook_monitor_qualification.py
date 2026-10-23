#!/usr/bin/env python3
"""Qualify owning monitor replacement in the exact disposable Rook fixture."""

from datetime import datetime, timezone
import hashlib
import json
import re
import time

import rook_runtime_qualification as runtime


def scale_patch(deployment, monitor, cluster_uid):
    metadata = deployment['metadata']
    owners = metadata.get('ownerReferences', [])
    if (not re.fullmatch(r'[a-z]+', monitor) or not cluster_uid or
            metadata.get('name') != 'rook-ceph-mon-' + monitor or
            metadata.get('namespace') != runtime.candidate.NAMESPACE or
            metadata.get('labels', {}).get('mon') != monitor or
            len(owners) != 1 or owners[0].get('kind') != 'CephCluster' or
            owners[0].get('apiVersion') != 'ceph.rook.io/v1' or
            owners[0].get('name') != runtime.candidate.NAMESPACE or owners[0].get('uid') != cluster_uid or
            not metadata.get('uid') or not metadata.get('resourceVersion') or
            deployment['spec'].get('replicas') != 1 or deployment.get('status', {}).get('readyReplicas') != 1):
        raise RuntimeError('synthetic monitor Deployment ownership or readiness differs')
    return [{'op': 'test', 'path': '/metadata/' + key, 'value': metadata[key]}
            for key in ('uid', 'resourceVersion')] + [
                {'op': 'test', 'path': '/spec/replicas', 'value': 1},
                {'op': 'replace', 'path': '/spec/replicas', 'value': 0}]


def monitor_view(status, monmap, original, target, fsid):
    names = [row['name'] for row in monmap['mons']]
    quorum = status.get('quorum_names', [])
    checks = sorted(status['health'].get('checks', {}))
    survivors = set(original) - {target}
    if (len(original) != 3 or target not in original or len(survivors) != 2 or
            status.get('fsid') != fsid or monmap.get('fsid') != fsid or
            len(names) not in (3, 4) or len(set(names)) != len(names) or
            any(not re.fullmatch(r'[a-z]+', name) for name in names) or
            len(quorum) != len(set(quorum)) or not 2 <= len(quorum) <= 3 or
            not survivors <= set(quorum) <= set(names) or len(set(names) - set(original)) > 1 or
            set(checks) - {'MON_DOWN'} or
            status['health']['status'] != ('HEALTH_WARN' if checks else 'HEALTH_OK')):
        raise RuntimeError('native monitor quorum, identity or health differs')
    complete = (target not in names and len(names) == len(quorum) == 3 and not checks and
                len(set(names) - set(original)) == 1)
    return {'members': sorted(names), 'quorum': sorted(quorum), 'checks': checks, 'complete': complete}


class Qualification(runtime.Qualification):
    def run(self, fixture, inventory, identities):
        runtime.disks.require_config(runtime.yaml.safe_load((fixture.root / 'l/colima-q/lima.yaml').read_text()),
                                     'qemu', 'storage')
        self.create_storage_cluster(fixture, inventory)
        requested = runtime.resources(self.args.name, fixture.names[0][:-2], inventory)
        self.apply(requested[:2])
        self.operator('1.20.9')
        self.apply(requested[2:])
        self.wait('cephcluster/' + runtime.candidate.NAMESPACE, '-n', runtime.candidate.NAMESPACE,
                  '--for=jsonpath={.status.phase}=Ready')
        self.clients()
        self.snapshot(fixture, identities, requested, 1, 'initial')
        self.objects(write=True)
        original = sorted(self.ceph('status')['quorum_names'])
        target = original[0]
        deployment = self.kubectl('get', 'deployment', 'rook-ceph-mon-' + target,
                                  '-n', runtime.candidate.NAMESPACE)
        patch = scale_patch(deployment, target, self.resource_uids[0])
        before = monitor_view(self.ceph('status'), self.ceph('mon', 'dump'), original, target, self.fsid)
        if before['members'] != original or before['quorum'] != original or before['checks']:
            raise RuntimeError('initial monitor quorum is not fully healthy')
        self.stage = 'native-monitor-failover'
        self.kubectl('patch', 'deployment', deployment['metadata']['name'], '-n', runtime.candidate.NAMESPACE,
                     '--type=json', '-p', json.dumps(patch))
        observations = []
        lost_member = False
        started = time.monotonic()
        payload = hashlib.sha256(b'0').digest() * 512
        while True:
            self.identity()
            view = monitor_view(self.ceph('status'), self.ceph('mon', 'dump'), original, target, self.fsid)
            lost_member |= len(view['quorum']) == 2 and target not in view['quorum']
            self.tools('rados', '-p', 'qualification', 'get', 'replica-000', '/work/readback')
            if self.tools('cat', '/work/readback') != payload:
                raise RuntimeError('complete monitor-failover object bytes differ')
            observations.append({'elapsed_seconds': round(time.monotonic() - started), **view})
            self.evidence['monitor_failover'] = {'original': original, 'target': target,
                'deployment_uid': deployment['metadata']['uid'], 'observations': observations,
                'two_member_quorum_observed': lost_member}
            (self.work / 'monitor-progress.json').write_text(json.dumps(self.evidence['monitor_failover']))
            if view['complete']:
                if not lost_member:
                    raise RuntimeError('failed monitor absence was not observed')
                remaining = self.kubectl('get', 'deployments', '-n', runtime.candidate.NAMESPACE)['items']
                if any(row['metadata']['uid'] == deployment['metadata']['uid'] or
                       row['metadata']['name'] == deployment['metadata']['name'] for row in remaining):
                    raise RuntimeError('original monitor Deployment remains after replacement')
                break
            time.sleep(30)
        self.snapshot(fixture, identities, requested, 1, 'monitor-replaced')
        self.objects()
        self.evidence.update(accepted=True, scope='owning-rook-monitor-failover',
                             production_writes=0, physical_relocation_qualified=False,
                             kubernetes_warning_observations_preserved=True, whole_vm_cleanup_required=True)
        self.evidence['result_sha256'] = hashlib.sha256(json.dumps(self.evidence, sort_keys=True).encode()).hexdigest()
        return self.evidence
