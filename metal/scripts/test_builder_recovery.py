#!/usr/bin/env python3
"""Exercise joint-store WAL recovery, framing, identity and isolation refusals."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import builder_recovery as recovery


class RecoveryGuards(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def paths(self):
        result = {}
        for name in recovery.DATABASES:
            path = self.root / name; path.mkdir(); result[name] = path
        return result

    def memory(self):
        original = Path.read_text
        def read_text(path, *args, **kwargs):
            return 'MemAvailable: 1048576 kB\n' if str(path) == '/proc/meminfo' else original(path, *args, **kwargs)
        return patch.object(Path, 'read_text', read_text)

    def manifest(self, tree):
        return {'format': 1, 'cluster_uid': recovery.common.CLUSTER_UID,
                'source': {'namespace': 'builder', 'profile': recovery.SOURCES['builder'], 'image': recovery.image('builder'),
                           'process': {'pid': recovery.SOURCES['builder']['pid'], 'exe': '/usr/local/bin/node'}},
                'tree': tree, 'bytes': sum(r['bytes'] for r in tree['files'].values()), 'pause': {'stopped_seconds': 0.1},
                'original_process_resumed': True, 'two_stores_same_pause': True}

    def fixture(self):
        paths = self.paths()
        for name, database in recovery.DATABASES.items():
            path = paths[name] / database; path.parent.mkdir()
            for suffix in ('', '-wal', '-shm'): Path(str(path) + suffix).write_bytes(('synthetic-' + name + suffix).encode())
        with self.memory(): tree, payloads = recovery.snapshot(paths)
        return self.manifest(tree), payloads

    def stream(self, manifest, payloads):
        header = recovery.common.canonical(manifest)
        return header + b'\n' + b''.join(v for _, v in sorted(payloads.items())) + recovery.common.canonical({'commit': hashlib.sha256(header).hexdigest()}) + b'\n'

    def test_both_complete_stores_transfer_and_protected_checks_reject_damage(self):
        manifest, payloads = self.fixture(); recovery.validate_manifest(manifest, 'builder')
        raw = self.stream(manifest, payloads); point = self.root / 'protected'
        result = recovery.transfer.receive(io.BytesIO(raw), point, 'builder', recovery.validate_manifest, recovery.verify)
        recovery.verify(point, result['manifest_sha256'], 'builder')
        self.assertEqual(recovery.files.tree(point / 'data'), manifest['tree'])
        for index, broken in enumerate((raw[:-1], raw + b'extra', raw.replace(b'synthetic-data-wal', b'corrupted-data-wal'))):
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                recovery.transfer.receive(io.BytesIO(broken), self.root / str(index), 'builder', recovery.validate_manifest, recovery.verify)
        (point / 'data/data').chmod(0o755)
        with self.assertRaises(RuntimeError): recovery.verify(point, result['manifest_sha256'], 'builder')

    def test_manifest_refuses_one_store_wrong_profile_pause_and_extra_root(self):
        manifest, _ = self.fixture()
        for key, value in [('two_stores_same_pause', False), ('bytes', True), ('pause', {'stopped_seconds': 10})]:
            changed = copy.deepcopy(manifest); changed[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'builder')
        changed = copy.deepcopy(manifest); changed['source']['profile']['stores']['data']['pvc_uid'] = 'different'
        with self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'builder')
        changed = copy.deepcopy(manifest); del changed['tree']['files']['recovery/control/control.sqlite-wal']
        changed['bytes'] = sum(r['bytes'] for r in changed['tree']['files'].values())
        with self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'builder')
        changed = copy.deepcopy(manifest); changed['tree']['directories'].append('nas')
        with self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'builder')

    def test_snapshot_refuses_a_cross_store_change_or_symlink(self):
        paths = self.paths()
        for root in paths.values(): (root / 'file').write_bytes(b'synthetic')
        original = recovery.transfer.memory_snapshot
        def mutate(root):
            value = original(root)
            if root == paths['data']: (paths['recovery'] / 'file').write_bytes(b'changed')
            return value
        with self.memory(), patch.object(recovery.transfer, 'memory_snapshot', mutate), self.assertRaises(RuntimeError):
            recovery.snapshot(paths)
        (paths['data'] / 'link').symlink_to(paths['recovery'] / 'file')
        with self.memory(), self.assertRaises(RuntimeError): recovery.snapshot(paths)

    def test_native_probe_recovers_committed_wal_for_both_matching_instances(self):
        paths = self.paths(); instance = '00000000-0000-4000-8000-000000000001'; before = {}
        for name, relative in recovery.DATABASES.items():
            path = paths[name] / relative; path.parent.mkdir(); db = sqlite3.connect(path); self.addCleanup(db.close)
            db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('CREATE TABLE builder_instance(id INTEGER PRIMARY KEY,origin TEXT,instance_id TEXT)')
            db.execute('INSERT INTO builder_instance VALUES(1,?,?)', ('https://builder.eaglepass.io', instance))
            db.execute('CREATE TABLE records (value, blob_value)'); db.commit(); db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.executemany('INSERT INTO records VALUES(?,?)', [('synthetic\x00日本語', b'\x00\xff')] * 2); db.commit()
            before[name] = recovery.files.tree(paths[name])
        with self.memory(): tree, payloads = recovery.snapshot(paths)
        point = self.root / 'protected'; manifest = self.manifest(tree)
        recovery.transfer.receive(io.BytesIO(self.stream(manifest, payloads)), point, 'builder', recovery.validate_manifest, recovery.verify)
        recovery.files.copy_tree(point / 'data', self.root / 'reader')
        program = recovery.probe_program().replace('/tool/sqlite_recovery.cjs', str(Path(__file__).with_name('sqlite_recovery.cjs').resolve()))
        for name, relative in recovery.DATABASES.items(): program = program.replace('/' + name + '/' + relative, str(self.root / 'reader' / name / relative))
        env = os.environ.copy(); env['BUILDER_ORIGIN'] = 'https://builder.eaglepass.io'
        result = subprocess.run([os.environ.get('NODE', 'node'), '--disable-warning=ExperimentalWarning', '-e', program], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        actual = json.loads(result.stdout)
        for name in recovery.DATABASES:
            self.assertEqual(actual[name]['rows'], 3); self.assertEqual(actual[name]['tables'], 2)
            self.assertEqual(recovery.files.tree(paths[name]), before[name])
        self.assertEqual(actual['instance_sha256'], hashlib.sha256(instance.encode()).hexdigest())

    def test_native_isolation_refuses_mounts_command_credentials_and_privileges(self):
        scratch = self.root / 'scratch'; phase = 'native'; ns = 'builder'
        host = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 2147483648, 'NanoCpus': 1000000000, 'Tmpfs': recovery.TMPFS,
                'RestartPolicy': {'Name': 'no'}}
        mounts = [{'Type': 'bind', 'Source': str(scratch / phase / name), 'Destination': '/' + name, 'RW': True} for name in recovery.DATABASES]
        mounts.append({'Type': 'bind', 'Source': str(scratch / 'tools'), 'Destination': '/tool', 'RW': False})
        config = {'Image': recovery.image(ns), 'User': '1000:1000', 'WorkingDir': '/app', 'Labels': {recovery.LABEL: 'fixture'},
                  'Entrypoint': ['/usr/local/bin/node'], 'Cmd': ['dist/server/index.js'],
                  'Env': [k + '=' + v for k, v in recovery.environment(ns).items()]}
        original = {'HostConfig': host, 'Config': config, 'Mounts': mounts}; recovery.require_container(original, scratch, ns, 'fixture', phase)
        for section, key, value in [('HostConfig', 'NetworkMode', 'host'), ('HostConfig', 'Privileged', True),
                                    ('HostConfig', 'CapAdd', ['SYS_ADMIN']), ('HostConfig', 'PidMode', 'host'),
                                    ('HostConfig', 'Tmpfs', {}), ('Config', 'User', '0'), ('Config', 'Cmd', ['operator.js']),
                                    ('Config', 'Env', config['Env'] + ['CLOUDFLARE_ANALYTICS_TOKEN=unexpected'])]:
            changed = copy.deepcopy(original); changed[section][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, ns, 'fixture', phase)
        changed = copy.deepcopy(original); changed['Mounts'][0]['Source'] = '/original'
        with self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, ns, 'fixture', phase)
        probe = copy.deepcopy(original); probe['Config']['Cmd'] = ['--disable-warning=ExperimentalWarning', '/tool/probe.cjs']
        for mount in probe['Mounts'][:2]: mount['Source'] = mount['Source'].replace('/native/', '/before/')
        recovery.require_container(probe, scratch, ns, 'fixture', 'before')


if __name__ == '__main__': unittest.main()
