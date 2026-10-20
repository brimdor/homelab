#!/usr/bin/env python3
"""Reject incomplete SABnzbd recovery evidence and unsafe native copies."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import sabnzbd_recovery as sab


class SABRecovery(unittest.TestCase):
    def manifest(self):
        tree = {'directories': ['config', 'config/admin', 'intermediate'],
                'files': {n: {'bytes': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}
                          for n in ('config/sabnzbd.ini', sab.HISTORY, 'intermediate/synthetic-part')}}
        tasks = {pid: exe for c in sab.PROFILE['containers'].values() for pid, exe in c['tasks'].items()}
        return {'format': 1, 'cluster_uid': sab.common.CLUSTER_UID,
                'scope': 'both-ceph-stores-only', 'two_stores_same_pause': True, 'original_processes_resumed': True,
                'source': {'namespace': 'sabnzbd', 'profile': sab.PROFILE, 'image': sab.IMAGE,
                           'processes': [{'pid': int(pid), 'exe': exe, 'start_ticks': '123',
                                          'cgroup': sab.POD.replace('-', '_')} for pid, exe in tasks.items()]},
                'pause': {'process_count': 12, 'stopped_seconds': 0.25}, 'tree': tree, 'bytes': 3}

    def test_manifest_requires_both_containers_all_twelve_processes_and_both_stores(self):
        value = json.loads(json.dumps(self.manifest()))
        sab.validate_manifest(value, 'sabnzbd')
        for mutate in (lambda v: v['source']['processes'].pop(),
                       lambda v: v['source']['processes'][0].update(start_ticks='changed'),
                       lambda v: v['source']['profile']['containers']['fix-host'].update(id='changed'),
                       lambda v: v['pause'].update(process_count=10),
                       lambda v: v['pause'].update(stopped_seconds=12),
                       lambda v: v.update(original_processes_resumed=False),
                       lambda v: v.update(two_stores_same_pause=False),
                       lambda v: v['tree']['directories'].remove('intermediate'),
                       lambda v: v['tree']['files'].pop(sab.HISTORY)):
            bad = copy.deepcopy(value)
            mutate(bad)
            with self.assertRaises(RuntimeError):
                sab.validate_manifest(bad, 'sabnzbd')

    def test_manifest_refuses_nas_paths_new_database_or_wrong_namespace(self):
        for name in ('backups/real-data', 'config/../escape', '/absolute', 'config/unreviewed.db'):
            bad = copy.deepcopy(self.manifest())
            bad['tree']['files'][name] = {'bytes': 1, 'sha256': 'a' * 64}
            bad['bytes'] += 1
            with self.assertRaises(RuntimeError):
                sab.validate_manifest(bad, 'sabnzbd')
        with self.assertRaises(RuntimeError):
            sab.validate_manifest(self.manifest(), 'other')

    def test_committed_history_wal_rows_and_typed_duplicates_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            (source / 'config/admin').mkdir(parents=True)
            db = sqlite3.connect(source / sab.HISTORY)
            try:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE history(value)')
                db.executemany('INSERT INTO history VALUES(?)', [(None,), (1,), (1,), ('text',), (b'blob',)])
                db.commit()
                copied = root / 'copy'
                sab.files.copy_tree(source, copied)
                result = sab.history(copied, root / 'canonical.sqlite')
                self.assertEqual((result['tables'], result['rows']), (1, 5))
                self.assertTrue((source / (sab.HISTORY + '-wal')).is_file())
            finally:
                db.close()

    def test_transfer_requires_complete_committed_frame_and_no_trailer(self):
        value = self.manifest()
        header = sab.common.canonical(value)
        checksum = hashlib.sha256(header).hexdigest()
        wire = header + b'\nxxx' + sab.common.canonical({'commit': checksum}) + b'\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = sab.transfer.receive(io.BytesIO(wire), root / 'good', 'sabnzbd', validator=sab.validate_manifest, verifier=sab.verify)
            self.assertEqual(result['manifest_sha256'], checksum)
            for index, bad in enumerate((wire[:-1], wire + b'trailer', wire.replace(b'\nxxx', b'\nyxx', 1))):
                with self.assertRaises(RuntimeError):
                    sab.transfer.receive(io.BytesIO(bad), root / str(index), 'sabnzbd', validator=sab.validate_manifest, verifier=sab.verify)

    def container(self, scratch):
        return {'Config': {'Image': sab.IMAGE, 'User': '99:100', 'Entrypoint': ['/lsiopy/bin/python3'], 'Cmd': sab.ARGS,
                           'Labels': {sab.LABEL: 'fixture'}},
                'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                               'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '',
                               'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 2147483648,
                               'NanoCpus': 1000000000, 'GroupAdd': ['1000'], 'Tmpfs': sab.TMPFS,
                               'RestartPolicy': {'Name': 'no'}},
                'Mounts': [{'Type': 'bind', 'Source': str(scratch / 'native' / name), 'RW': True, 'Destination': target}
                           for name, target in (('config', '/config'), ('intermediate', '/incomplete-downloads'))]}

    def test_native_copy_refuses_network_privilege_original_or_extra_storage(self):
        scratch = Path('/synthetic/owned')
        value = self.container(scratch)
        sab.require_container(value, scratch, 'fixture')
        for mutate in (lambda v: v['HostConfig'].update(NetworkMode='host'),
                       lambda v: v['HostConfig'].update(CapAdd=['SYS_ADMIN']),
                       lambda v: v['Config'].update(User='0:0'),
                       lambda v: v['Mounts'][0].update(Source='/original'),
                       lambda v: v['Mounts'].append({'Destination': '/backups', 'Type': 'volume'})):
            bad = copy.deepcopy(value)
            mutate(bad)
            with self.assertRaises(RuntimeError):
                sab.require_container(bad, scratch, 'fixture')
        arguments = sab.native_arguments(scratch, 'fixture')
        self.assertEqual(sum(a.startswith('--mount=') for a in arguments), 2)
        self.assertIn('--network=none', arguments)
        self.assertNotIn('--privileged', arguments)
        self.assertFalse(any('apikey' in a.lower() for a in arguments))


if __name__ == '__main__':
    unittest.main()
