#!/usr/bin/env python3
"""Reject changed SearxNG store scope, source identities and native isolation."""
import copy
import hashlib
from pathlib import Path
import unittest

import searxng_recovery as s


class SearxRecovery(unittest.TestCase):
    def manifest(self):
        tree = {'directories': ['cache', 'cache/lost+found', 'etc', 'etc/lost+found', 'overlays'],
                'files': {'overlays/' + n: dict(v) for n, v in s.OVERLAYS.items()}}
        tree['files']['etc/settings.yml'] = {'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest()}
        return {'format': 1, 'cluster_uid': s.common.CLUSTER_UID,
                'source': {'pod_uid': s.POD, 'container_id': s.CONTAINER, 'image': s.IMAGE, 'stores': s.PROFILE,
                           'processes': [{'pid': int(pid), 'exe': exe, 'start_ticks': '123', 'cgroup': s.POD.replace('-', '_')}
                                         for pid, exe in s.TASKS.items()]},
                'pause': {'process_count': 3, 'stopped_seconds': .25}, 'original_processes_resumed': True,
                'scope': 'empty-ceph-stores-and-git-overlays', 'tree': tree,
                'bytes': sum(v['bytes'] for v in tree['files'].values())}

    def test_requires_exact_three_processes_and_safe_shared_pause(self):
        good = self.manifest()
        s.validate_manifest(good, 'searxng')
        for mutate in (lambda v: v['source']['processes'].pop(),
                       lambda v: v['source'].update(container_id='changed'),
                       lambda v: v['source'].update(image='changed'),
                       lambda v: v['source'].update(stores={}),
                       lambda v: v['pause'].update(stopped_seconds=12),
                       lambda v: v.update(original_processes_resumed=False)):
            bad = copy.deepcopy(good)
            mutate(bad)
            with self.assertRaises(RuntimeError):
                s.validate_manifest(bad, 'searxng')
        for bad in (None, [], {'source': None}, {'pause': None}):
            with self.assertRaises(RuntimeError):
                s.validate_manifest(bad, 'searxng')

    def test_requires_both_empty_stores_and_complete_effective_overlays(self):
        for mutate in (lambda v: v['tree']['directories'].remove('cache'),
                       lambda v: v['tree']['files'].pop('overlays/settings.yml'),
                       lambda v: v['tree']['files']['overlays/limiter.toml'].update(sha256='f' * 64),
                       lambda v: v['tree']['files']['etc/settings.yml'].update(bytes=1),
                       lambda v: v['tree']['files'].update({'nas/file': {'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest()}}),
                       lambda v: v['tree']['directories'].append('etc/../escape')):
            bad = copy.deepcopy(self.manifest())
            mutate(bad)
            with self.assertRaises(RuntimeError):
                s.validate_manifest(bad, 'searxng')

    def container(self, scratch):
        return {'Config': {'Image': s.IMAGE, 'User': '0:0', 'Entrypoint': [s.ENTRYPOINT], 'Cmd': ['searx.webapp:app'],
                           'Env': [k + '=' + v for k, v in s.ENVIRONMENT.items()], 'Labels': {s.LABEL: 'fixture'}},
                'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                               'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '',
                               'UsernsMode': '', 'PidsLimit': 128, 'Memory': 2147483648, 'NanoCpus': 1000000000,
                               'Tmpfs': s.TMPFS, 'RestartPolicy': {'Name': 'no'}},
                'Mounts': [{'Type': 'bind', 'Source': str(scratch / 'native' / n), 'RW': True, 'Destination': d}
                           for n, d in s.DESTINATIONS.items()]}

    def test_native_fixture_refuses_privilege_network_mount_and_secret_changes(self):
        scratch = Path('/synthetic/owned')
        good = self.container(scratch)
        s.require_container(good, scratch, 'fixture')
        for mutate in (lambda v: v['HostConfig'].update(NetworkMode='host'),
                       lambda v: v['HostConfig'].update(CapAdd=['NET_ADMIN']),
                       lambda v: v['HostConfig'].update(Privileged=True),
                       lambda v: v['Mounts'][0].update(Source='/original'),
                       lambda v: v['Mounts'].append({'Destination': '/foreign'}),
                       lambda v: v['Config'].update(Env=[])):
            bad = copy.deepcopy(good)
            mutate(bad)
            with self.assertRaises(RuntimeError):
                s.require_container(bad, scratch, 'fixture')
        arguments = s.native_arguments(scratch, 'fixture')
        self.assertEqual(sum(a.startswith('--mount=') for a in arguments), 2)
        self.assertIn('--network=none', arguments)
        self.assertNotIn('--privileged', arguments)


if __name__ == '__main__':
    unittest.main()
