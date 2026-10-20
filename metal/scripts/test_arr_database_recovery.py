#!/usr/bin/env python3
"""Selected Arr database and multi-process pause safety regressions."""

from contextlib import contextmanager
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import arr_database_recovery as arr


class ArrRecovery(unittest.TestCase):
    def fixture(self, root):
        handles = []
        for name in ('radarr.db', 'logs.db'):
            connection = sqlite3.connect(root / name)
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('CREATE TABLE records(value)')
            connection.executemany('INSERT INTO records VALUES(?)', [(None,), (3,), (3,), ('text',), (b'blob',)])
            connection.commit()
            handles.append(connection)
        (root / 'config.xml').write_text('<Config><ApiKey>synthetic-only</ApiKey></Config>')
        return handles

    def manifest(self, tree):
        p = arr.SOURCES['radarr']
        return {'format': 1, 'cluster_uid': arr.common.CLUSTER_UID,
                'source': {'namespace': 'radarr', 'profile': p, 'image': arr.image('radarr'),
                           'processes': [{'pid': int(pid), 'exe': exe, 'start_ticks': '123',
                                          'cgroup': p['pod_uid'].replace('-', '_')} for pid, exe in p['tasks'].items()]},
                'pause': {'process_count': len(p['tasks']), 'stopped_seconds': 0.25},
                'original_process_resumed': True, 'scope': 'selected-databases-and-config-only',
                'tree': tree, 'bytes': sum(r['bytes'] for r in tree['files'].values())}

    def test_selection_never_traverses_backups_or_unrelated_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            handles = self.fixture(root)
            try:
                (root / 'Backups').symlink_to('/unavailable-nas')
                (root / 'MediaCover').mkdir()
                (root / 'MediaCover/unrelated').write_bytes(b'not-a-database')
                selected = arr.selected(root, 'radarr')
                self.assertEqual(set(selected), {'config.xml', 'radarr.db', 'logs.db', 'radarr.db-wal', 'radarr.db-shm', 'logs.db-wal', 'logs.db-shm'})
                (root / 'config.xml').unlink()
                (root / 'config.xml').symlink_to(root / 'radarr.db')
                with self.assertRaises(RuntimeError):
                    arr.selected(root, 'radarr')
            finally:
                for handle in handles:
                    handle.close()

    def test_copied_committed_wal_rows_and_typed_duplicates_survive_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            handles = self.fixture(source)
            try:
                with patch.object(arr, 'available_memory', return_value=1), self.assertRaises(RuntimeError):
                    arr.snapshot(source, 'radarr')
                with patch.object(arr, 'available_memory', return_value=1048576):
                    tree, payloads = arr.snapshot(source, 'radarr')
                point = root / 'copy'
                point.mkdir()
                for name, data in payloads.items():
                    (point / name).write_bytes(data)
                    self.assertEqual(hashlib.sha256(data).hexdigest(), tree['files'][name]['sha256'])
                fingerprints = arr.fingerprints(point, root / 'canonical', 'radarr')
                for name in ('radarr.db', 'logs.db'):
                    self.assertEqual(fingerprints[name]['rows'], 5)
                    connection = sqlite3.connect(root / 'canonical' / name)
                    self.assertEqual(connection.execute('SELECT value FROM records').fetchall(), [(None,), (3,), (3,), ('text',), (b'blob',)])
                    connection.close()
            finally:
                for handle in handles:
                    handle.close()

    def test_manifest_requires_every_reviewed_process_and_complete_journals(self):
        tree = {'directories': [], 'files': {n: {'bytes': 1, 'sha256': 'a' * 64} for n in ('config.xml', 'radarr.db', 'logs.db')}}
        manifest = self.manifest(tree)
        arr.validate_manifest(manifest, 'radarr')
        changes = []
        for path, value in [('source', None), ('pause', []), ('original_process_resumed', False), ('bytes', True),
                            ('scope', 'whole-pvc')]:
            bad = copy.deepcopy(manifest)
            bad[path] = value
            changes.append(bad)
        for identities in ([], None, manifest['source']['processes'][:-1], [None] * 10):
            bad = copy.deepcopy(manifest)
            bad['source']['processes'] = identities
            changes.append(bad)
        for extra in ('radarr.db-wal', 'Backups/not-owned', '../escape'):
            bad = copy.deepcopy(manifest)
            bad['tree']['files'][extra] = {'bytes': 1, 'sha256': 'a' * 64}
            bad['bytes'] += 1
            changes.append(bad)
        for bad in changes:
            with self.assertRaises(RuntimeError):
                arr.validate_manifest(bad, 'radarr')

    def test_application_only_preserves_committed_rows_without_accepting_malformed_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            handles = self.fixture(source)
            try:
                copy = root / 'copy'
                arr.files.copy_tree(source, copy)
                for suffix in ('', '-wal', '-shm'):
                    path = copy / ('logs.db' + suffix)
                    if path.exists():
                        path.unlink()
                (copy / 'logs.db').write_bytes(b'malformed synthetic log database')
                narrow = arr.fingerprints(copy, root / 'narrow', 'radarr', application_only=True)
                self.assertEqual(set(narrow), {'radarr.db'})
                self.assertEqual(narrow['radarr.db']['rows'], 5)
                with self.assertRaises(sqlite3.DatabaseError):
                    arr.fingerprints(copy, root / 'full', 'radarr')
                with self.assertRaises(RuntimeError):
                    arr.fingerprints(copy, root / 'unsupported', 'sonarr', application_only=True)
                self.assertEqual((copy / 'logs.db').read_bytes(), b'malformed synthetic log database')
            finally:
                for handle in handles:
                    handle.close()

    def test_transport_requires_commit_complete_bytes_and_no_trailer(self):
        tree = {'directories': [], 'files': {n: {'bytes': 1, 'sha256': hashlib.sha256(b'x').hexdigest()} for n in ('config.xml', 'radarr.db', 'logs.db')}}
        manifest = self.manifest(tree)
        encoded = arr.common.canonical(manifest)
        checksum = hashlib.sha256(encoded).hexdigest()
        stream = encoded + b'\nxxx' + arr.common.canonical({'commit': checksum}) + b'\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = arr.transfer.receive(io.BytesIO(stream), root / 'good', 'radarr', validator=arr.validate_manifest, verifier=arr.verify)
            self.assertEqual(result['manifest_sha256'], checksum)
            for index, data in enumerate((stream[:-1], stream + b'trailer', stream.replace(b'\nxxx', b'\nyxx', 1))):
                with self.assertRaises(RuntimeError):
                    arr.transfer.receive(io.BytesIO(data), root / str(index), 'radarr', validator=arr.validate_manifest, verifier=arr.verify)

    def test_coordinated_pause_unwinds_every_process_on_exception_and_partial_enter(self):
        identities = [{'pid': 101}, {'pid': 102}, {'pid': 103}]
        states = {i['pid']: 'S' for i in identities}
        exited = []

        @contextmanager
        def frozen(identity, _marker):
            states[identity['pid']] = 'T'
            try:
                yield {'stopped_seconds': 0.01}
            finally:
                states[identity['pid']] = 'S'
                exited.append(identity['pid'])

        with tempfile.TemporaryDirectory() as temporary, patch.object(arr.process, 'process_identity', side_effect=lambda pid: {'pid': pid}), patch.object(arr.process, 'thread_states', side_effect=lambda pid: {pid: states[pid]}), patch.object(arr.process, 'frozen', side_effect=frozen):
            with self.assertRaisesRegex(RuntimeError, 'body failure'):
                with arr.stopped(identities, Path(temporary) / 'one'):
                    self.assertEqual(set(states.values()), {'T'})
                    raise RuntimeError('body failure')
            self.assertEqual(exited, [103, 102, 101])
            self.assertEqual(set(states.values()), {'S'})

            @contextmanager
            def partial(identity, marker):
                if identity['pid'] == 103:
                    raise RuntimeError('enter failure')
                with frozen(identity, marker) as result:
                    yield result

            with patch.object(arr.process, 'frozen', side_effect=partial), self.assertRaisesRegex(RuntimeError, 'enter failure'):
                with arr.stopped(identities, Path(temporary) / 'two'):
                    self.fail('partial entry reached capture')
            self.assertEqual(set(states.values()), {'S'})
            self.assertEqual(exited[-2:], [102, 101])

    def test_manifest_wire_profile_survives_json_without_key_coercion(self):
        tree = {'directories': [], 'files': {n: {'bytes': 1, 'sha256': 'b' * 64} for n in ('config.xml', 'radarr.db', 'logs.db')}}
        manifest = json.loads(json.dumps(self.manifest(tree)))
        arr.validate_manifest(manifest, 'radarr')
        manifest['source']['processes'][0]['start_ticks'] = 'changed'
        with self.assertRaises(RuntimeError):
            arr.validate_manifest(manifest, 'radarr')

    def test_native_isolation_rejects_original_data_network_or_extra_capabilities(self):
        scratch = Path('/synthetic/owned')
        value = {'Config': {'Image': arr.image('radarr'), 'User': '99:100',
                            'Entrypoint': ['/app/radarr/bin/Radarr'], 'Cmd': ['-nobrowser', '-data=/config'],
                            'Labels': {arr.LABEL: 'fixture'}},
                 'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                                'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private',
                                'PidMode': '', 'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128,
                                'Memory': 4294967296, 'NanoCpus': 1000000000, 'GroupAdd': ['1000'],
                                'Tmpfs': {'/tmp': 'rw,nosuid,nodev,uid=99,gid=100,mode=1777'},
                                'RestartPolicy': {'Name': 'no'}},
                 'Mounts': [{'Type': 'bind', 'RW': True, 'Source': str(scratch / 'native'), 'Destination': '/config'}]}
        arr.require_container(value, scratch, 'radarr', 'fixture')
        for mutate in [lambda v: v['HostConfig'].update(NetworkMode='host'),
                       lambda v: v['HostConfig'].update(CapAdd=['SYS_ADMIN']),
                       lambda v: v['Config'].update(User='0:0'),
                       lambda v: v['Mounts'][0].update(Source='/var/lib/kubelet/original'),
                       lambda v: v['Mounts'].append({'Type': 'volume', 'Source': 'NFS', 'Destination': '/backups'})]:
            bad = copy.deepcopy(value)
            mutate(bad)
            with self.assertRaises(RuntimeError):
                arr.require_container(bad, scratch, 'radarr', 'fixture')
        image = {'Architecture': 'amd64', 'Os': 'linux', 'Config': {'Volumes': {'/config': {}}},
                 'RepoDigests': [arr.image('radarr')]}
        arr.require_image(image, 'radarr')
        image['Config']['Volumes']['/other'] = {}
        with self.assertRaises(RuntimeError):
            arr.require_image(image, 'radarr')
        arguments = arr.native_arguments(scratch, 'radarr', 'fixture')
        self.assertEqual(sum(a.startswith('--mount=') for a in arguments), 1)
        self.assertIn('--network=none', arguments)
        self.assertIn('--user=99:100', arguments)


if __name__ == '__main__':
    unittest.main()
