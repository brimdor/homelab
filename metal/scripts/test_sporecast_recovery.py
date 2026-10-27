#!/usr/bin/env python3
"""Prove WAL-only rows survive framing and isolated-copy recovery guards."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import tarfile
import unittest
from unittest.mock import patch

import sporecast_recovery as recovery


class RecoveryGuards(unittest.TestCase):
    def setUp(self):
        recovery.select_profile('historical')
        self.addCleanup(recovery.select_profile, 'historical')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def manifest(self):
        records = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                   for name, data in self.payloads().items()}
        return {'format': 1, 'cluster_uid': recovery.common.CLUSTER_UID,
                'source': {**recovery.SOURCES['sporecast'], 'namespace': 'sporecast', 'image': recovery.IMAGE,
                           'process': {'pid': recovery.SOURCES['sporecast']['pid'], 'exe': '/sporecast-backend',
                                       **({'start_ticks': recovery.SOURCES['sporecast']['start_ticks']}
                                          if 'start_ticks' in recovery.SOURCES['sporecast'] else {})}},
                'tree': {'directories': ['empty'], 'files': records}, 'bytes': sum(r['bytes'] for r in records.values()),
                'pause': {'stopped_seconds': 0.1}, 'original_process_resumed': True}

    def payloads(self):
        return {'sporecast.db': b'synthetic database', 'sporecast.db-wal': b'synthetic WAL',
                'sporecast.db-shm': b'synthetic SHM', 'empty-file': b''}

    def stream(self, manifest=None):
        raw = recovery.common.canonical(manifest or self.manifest())
        checksum = hashlib.sha256(raw).hexdigest()
        return raw + b'\n' + b''.join(v for _, v in sorted(self.payloads().items())) + recovery.common.canonical({'commit': checksum}) + b'\n'

    def test_committed_wal_only_rows_types_duplicates_and_metadata_survive_copy(self):
        live = self.root / 'live'; live.mkdir(); path = live / 'sporecast.db'
        database = sqlite3.connect(path); self.addCleanup(database.close)
        self.assertEqual(database.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
        database.execute('PRAGMA wal_autocheckpoint=0')
        database.execute('CREATE TABLE records (value, blob_value)')
        database.execute('PRAGMA user_version=9'); database.commit()
        database.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        base = path.read_bytes()
        row = ('synthetic\x00日本語', b'\x00\xff')
        database.executemany('INSERT INTO records VALUES (?,?)', [row, row]); database.commit()
        self.assertEqual(path.read_bytes(), base)
        self.assertGreater((live / 'sporecast.db-wal').stat().st_size, 0)
        before = recovery.files.tree(live)
        recovery.files.copy_tree(live, self.root / 'reader')
        actual = recovery.wal_fingerprint(self.root / 'reader', self.root / 'canonical.db')
        self.assertEqual(actual['rows'], 2)
        self.assertEqual(recovery.files.tree(live), before)
        expected_path = self.root / 'expected.db'
        with sqlite3.connect(expected_path) as destination: database.backup(destination)
        with sqlite3.connect(expected_path) as destination: destination.execute('PRAGMA journal_mode=DELETE')
        self.assertEqual(actual, recovery.files.fingerprint(expected_path))

    def test_framed_receiver_preserves_complete_tree_and_refuses_transport_damage(self):
        point = self.root / 'accepted'
        result = recovery.receive(io.BytesIO(self.stream()), point, 'sporecast')
        recovery.verify(point, result['manifest_sha256'], 'sporecast')
        for name, value in self.payloads().items(): self.assertEqual((point / 'data' / name).read_bytes(), value)
        self.assertTrue((point / 'data/empty').is_dir())
        bad = [self.stream()[:-1], self.stream() + b'extra', self.stream().replace(b'synthetic WAL', b'synthetic BAD'),
               self.stream().split(b'\n')[0] + b'\n', self.stream().replace(b'"commit"', b'"wrong!"')]
        for index, value in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                recovery.receive(io.BytesIO(value), self.root / str(index), 'sporecast')
        (point / 'data/empty').chmod(0o755)
        with self.assertRaises(RuntimeError): recovery.verify(point, result['manifest_sha256'], 'sporecast')

    def test_manifest_refuses_identity_pause_wal_types_and_path_changes(self):
        original = self.manifest(); recovery.validate_manifest(original, 'sporecast')
        changes = [('source', 'pod_uid', 'different'), ('source', 'image', 'mutable'),
                   ('source', 'pv_uid', 'different'), ('pause', 'stopped_seconds', 10),
                   ('pause', 'stopped_seconds', '0.1'), ('tree', 'directories', ['.']),
                   ('tree', 'directories', ['empty', 'empty'])]
        for section, key, value in changes:
            changed = copy.deepcopy(original); changed[section][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'sporecast')
        for name in ('.', '..', '/absolute', '../escape', 'a/../escape', 'a//b', 'a/', 'a\\b', ''):
            with self.subTest(name=name), self.assertRaises(RuntimeError): recovery.safe_name(name)
        for changed in (None, [], {'source': []}):
            with self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'sporecast')
        changed = copy.deepcopy(original); del changed['tree']['files']['sporecast.db-wal']
        with self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'sporecast')
        changed = copy.deepcopy(original); changed['tree']['files']['sporecast.db']['bytes'] = True
        with self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'sporecast')

    def test_sqlite_reader_refuses_links_and_missing_database_without_creation(self):
        source = self.root / 'source'; source.mkdir()
        with self.assertRaises(RuntimeError): recovery.wal_fingerprint(source, self.root / 'missing.db')
        self.assertFalse((self.root / 'missing.db').exists())
        (source / 'sporecast.db').symlink_to(self.root / 'elsewhere')
        with self.assertRaises(RuntimeError): recovery.wal_fingerprint(source, self.root / 'linked.db')
        self.assertFalse((self.root / 'linked.db').exists())

    def test_memory_snapshot_hashes_all_files_and_refuses_links(self):
        source = self.root / 'source'; source.mkdir(); (source / 'empty').mkdir()
        (source / 'file').write_bytes(b'synthetic')
        original = Path.read_text
        def read_text(path, *args, **kwargs):
            return 'MemAvailable: 1048576 kB\n' if str(path) == '/proc/meminfo' else original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read_text):
            tree, payloads = recovery.memory_snapshot(source)
            self.assertEqual(tree, recovery.files.tree(source)); self.assertEqual(payloads, {'file': b'synthetic'})
            (source / 'link').symlink_to(source / 'file')
            with self.assertRaises(RuntimeError): recovery.memory_snapshot(source)

    def test_native_isolation_refuses_privilege_network_mount_and_command_drift(self):
        scratch = self.root / 'scratch'
        host = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 536870912, 'NanoCpus': 1000000000, 'Tmpfs': {'/tmp': 'rw,nosuid,nodev'},
                'RestartPolicy': {'Name': 'no'}, 'Binds': [str(scratch / 'data') + ':/data:Z']}
        original = {'HostConfig': host, 'Config': {'Image': recovery.IMAGE, 'User': '65532:65532',
                    'Entrypoint': ['/sporecast-backend'], 'Cmd': None, 'Labels': {recovery.LABEL: 'fixture'},
                    'Env': [k + '=' + v for k, v in recovery.ENVIRONMENT.items()]},
                    'Mounts': [{'Type': 'bind', 'Source': str(scratch / 'data'), 'Destination': '/data', 'RW': True, 'Mode': 'Z'}]}
        recovery.require_container(original, scratch, 'fixture')
        for section, key, value in [('HostConfig', 'NetworkMode', 'host'), ('HostConfig', 'Privileged', True),
                                    ('HostConfig', 'PidMode', 'host'), ('HostConfig', 'CapAdd', ['SYS_ADMIN']),
                                    ('HostConfig', 'ReadonlyRootfs', False), ('HostConfig', 'Devices', ['/dev/sda']),
                                    ('Config', 'Image', 'mutable'), ('Config', 'User', '0'),
                                    ('Config', 'Entrypoint', ['/bin/sh']), ('Config', 'Env', [])]:
            changed = copy.deepcopy(original); changed[section][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, 'fixture')
        changed = copy.deepcopy(original); changed['Mounts'][0]['Source'] = '/production'
        with self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, 'fixture')
        for mode in ('', 'z', 'ro', 'rw'):
            changed = copy.deepcopy(original); changed['HostConfig']['Binds'] = [str(scratch / 'data') + ':/data:' + mode]
            changed['Mounts'][0]['Mode'] = mode
            with self.subTest(mode=mode), self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, 'fixture')

    def test_current_profile_cannot_reinterpret_historical_point_or_reused_process(self):
        historical = self.manifest()
        recovery.select_profile('pikachu-20261027')
        current = self.manifest(); recovery.validate_manifest(current, 'sporecast')
        self.assertEqual(set(recovery.SOURCES), {'sporecast'})
        with self.assertRaises(RuntimeError): recovery.validate_manifest(historical, 'sporecast')
        for key in ('boot', 'machine', 'root_uuid', 'pv_uid', 'start_ticks'):
            changed = copy.deepcopy(current); changed['source'][key] = 'changed'
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'sporecast')
        changed = copy.deepcopy(current); changed['source']['process']['start_ticks'] = 'reused'
        with self.assertRaises(RuntimeError): recovery.validate_manifest(changed, 'sporecast')
        with self.assertRaises(RuntimeError): recovery.select_profile('unreviewed')
        recovery.select_profile('historical'); recovery.validate_manifest(historical, 'sporecast')
        with self.assertRaises(RuntimeError): recovery.validate_manifest(current, 'sporecast')

    def test_cached_archive_binds_all_blobs_and_refuses_load_mapping_drift(self):
        def blob(data): return 'sha256:' + hashlib.sha256(data).hexdigest()
        config = json.dumps({'architecture': 'amd64', 'os': 'linux', 'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + 'a' * 64]}}).encode()
        layer = b'synthetic layer'; config_digest = blob(config); layer_digest = blob(layer)
        manifest = json.dumps({'schemaVersion': 2, 'config': {'digest': config_digest, 'size': len(config)},
                               'layers': [{'digest': layer_digest, 'size': len(layer)}]}).encode()
        digest = blob(manifest); reference = '10.0.20.11:32309/sporecast-backend@' + digest
        path_for = lambda value: 'blobs/sha256/' + value.split(':')[1]
        records = {path_for(config_digest): config, path_for(layer_digest): layer, path_for(digest): manifest,
                   'index.json': json.dumps({'manifests': [{'digest': digest, 'size': len(manifest)}]}).encode(),
                   'oci-layout': b'{"imageLayoutVersion":"1.0.0"}',
                   'manifest.json': json.dumps([{'Config': path_for(config_digest), 'RepoTags': [reference],
                                                'Layers': [path_for(layer_digest)]}]).encode()}
        def write(values, extra=None):
            path = self.root / 'image.tar'
            with tarfile.open(path, 'w') as archive:
                for name, data in values.items():
                    entry = tarfile.TarInfo(name); entry.size = len(data); archive.addfile(entry, io.BytesIO(data))
                if extra: archive.addfile(extra)
            return path
        with patch.object(recovery, 'IMAGE', 'registry.eaglepass.io/sporecast-backend@' + digest), \
                patch.object(recovery, 'CACHED_IMAGE', reference), patch.object(recovery, 'CACHED_CONFIG', config_digest):
            accepted = recovery.cached_archive(write(records))
            self.assertEqual(accepted['blobs'], 3); self.assertEqual(accepted['config'], config_digest)
            load_archive = self.root / 'docker-image.tar'
            self.assertEqual(recovery.docker_load_archive(write(records), load_archive), accepted)
            with tarfile.open(load_archive) as archive:
                self.assertNotIn('oci-layout', archive.getnames()); self.assertNotIn('index.json', archive.getnames())
                self.assertIsNone(json.load(archive.extractfile('manifest.json'))[0]['RepoTags'])
                for name in (path_for(config_digest), path_for(layer_digest), path_for(digest)):
                    self.assertEqual(archive.extractfile(name).read(), records[name])
            with self.assertRaises(FileExistsError): recovery.docker_load_archive(write(records), load_archive)
            for name, data in [(path_for(layer_digest), b'damaged'), ('../escape', b'bad'),
                               ('manifest.json', b'[{"Config":"wrong","Layers":[],"RepoTags":null}]'),
                               ('index.json', b'{"manifests":[]}')]:
                changed = dict(records); changed[name] = data
                with self.subTest(name=name), self.assertRaises((RuntimeError, KeyError)):
                    recovery.cached_archive(write(changed))
            changed = dict(records); mapping = json.loads(changed['manifest.json']); mapping[0]['RepoTags'] = ['unrelated:latest']
            changed['manifest.json'] = json.dumps(mapping).encode()
            with self.assertRaises(RuntimeError): recovery.cached_archive(write(changed))
            for entry in (tarfile.TarInfo('index.json'), tarfile.TarInfo('link')):
                if entry.name == 'link': entry.type = tarfile.SYMTYPE; entry.linkname = '/production'
                with self.assertRaises(RuntimeError): recovery.cached_archive(write(records, entry))

    def test_current_restore_container_requires_verified_config_not_tag(self):
        recovery.select_profile('pikachu-20261027')
        # The existing isolation test exercises every other field with its historical profile.
        with self.assertRaises(RuntimeError):
            recovery.require_container({'HostConfig': {}, 'Config': {'Image': recovery.IMAGE}}, self.root, 'fixture')


if __name__ == '__main__': unittest.main()
