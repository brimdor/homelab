#!/usr/bin/env python3
"""Exercise typed SQLite preservation, protected trees and native isolation refusals."""
import copy
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

import grafana_recovery as recovery


class RecoveryGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def database(self):
        path = self.root / 'grafana.db'
        with sqlite3.connect(path) as database:
            database.execute('CREATE TABLE values_test (nullable, integer_value, real_value, text_value, blob_value)')
            record = (None, 9223372036854775807, 1.23456789012345, 'synthetic\x00日本語', b'\x00\xff')
            database.executemany('INSERT INTO values_test VALUES (?,?,?,?,?)', [record, record])
            database.execute('CREATE TABLE keyed (key TEXT PRIMARY KEY, value) WITHOUT ROWID')
            database.execute("INSERT INTO keyed VALUES ('synthetic', 'value')")
            database.execute('PRAGMA user_version=7')
        return path

    def test_fingerprint_preserves_types_duplicates_rowids_schema_and_metadata(self):
        path = self.database(); before = path.read_bytes(); expected = recovery.fingerprint(path)
        self.assertEqual(expected['tables'], 2); self.assertEqual(expected['rows'], 3)
        self.assertEqual(path.read_bytes(), before)
        cases = [('UPDATE values_test SET rowid=rowid+20', 'data_sha256'),
                 ('DELETE FROM values_test WHERE rowid=(SELECT MAX(rowid) FROM values_test)', 'data_sha256'),
                 ('UPDATE values_test SET real_value=1.23456789012346', 'data_sha256'),
                 ('UPDATE values_test SET blob_value=NULL', 'data_sha256'),
                 ('ALTER TABLE keyed ADD COLUMN extra', 'schema_sha256'),
                 ('PRAGMA user_version=8', 'metadata_sha256')]
        for sql, field in cases:
            with self.subTest(sql=sql):
                path.write_bytes(before)
                with sqlite3.connect(path) as database: database.execute(sql)
                self.assertNotEqual(recovery.fingerprint(path)[field], expected[field])
        self.assertEqual(len({recovery.digest(recovery.typed(v)) for v in (None, 1, 1.0, '1', b'1')}), 5)

    def test_database_refuses_missing_symlink_journal_and_hidden_rowid(self):
        missing = self.root / 'missing.db'
        with self.assertRaises(RuntimeError): recovery.fingerprint(missing)
        self.assertFalse(missing.exists())
        path = self.database(); link = self.root / 'link.db'; link.symlink_to(path)
        with self.assertRaises(RuntimeError): recovery.fingerprint(link)
        for suffix in ('-journal', '-wal', '-shm'):
            sidecar = Path(str(path) + suffix); sidecar.touch()
            with self.subTest(suffix=suffix), self.assertRaises(RuntimeError): recovery.fingerprint(path)
            sidecar.unlink()
        with sqlite3.connect(path) as database: database.execute('CREATE TABLE hidden (rowid, oid, _rowid_)')
        with self.assertRaises(RuntimeError): recovery.fingerprint(path)

    def test_complete_tree_copy_preserves_empty_directories_and_rejects_symlinks(self):
        source = self.root / 'source'; source.mkdir(); (source / 'empty').mkdir()
        (source / 'file').write_bytes(b'synthetic')
        target = self.root / 'target'; recovery.copy_tree(source, target)
        self.assertEqual(recovery.tree(source), recovery.tree(target))
        self.assertEqual((target / 'file').stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError): recovery.copy_tree(source, target)
        link = self.root / 'link'; link.symlink_to(source, target_is_directory=True)
        with self.assertRaises(RuntimeError): recovery.copy_tree(link, self.root / 'refused')
        self.assertFalse((self.root / 'refused').exists())
        (source / 'unsafe').symlink_to(source / 'file')
        with self.assertRaises(RuntimeError): recovery.tree(source)

    def protected_point(self):
        point = self.root / 'point'; point.mkdir(mode=0o700)
        for name in [*recovery.VOLUMES, 'config']: (point / name).mkdir(mode=0o700)
        source = self.database(); source.rename(point / 'data/grafana.db'); (point / 'data/grafana.db').chmod(0o600)
        manifest = {'format': 1, 'cluster_uid': recovery.common.CLUSTER_UID,
                    'source': {'pod_uid': recovery.POD, 'image': recovery.IMAGE},
                    'trees': {name: recovery.tree(point / name) for name in recovery.VOLUMES},
                    'config': recovery.tree(point / 'config'), 'default_image_encryption': True,
                    'snapshot': recovery.fingerprint(point / 'data/grafana.db')}
        recovery.write_json(point / 'verified.json', manifest)
        return point, hashlib.sha256((point / 'verified.json').read_bytes()).hexdigest()

    def test_protected_point_refuses_corruption_extra_files_permissions_and_manifest(self):
        point, checksum = self.protected_point(); recovery.verify(point, checksum)
        with self.assertRaises(RuntimeError): recovery.verify(point, '0' * 64)
        extra = point / 'extra'; extra.touch()
        with self.assertRaises(RuntimeError): recovery.verify(point, checksum)
        extra.unlink(); database = point / 'data/grafana.db'; database.chmod(0o644)
        with self.assertRaises(RuntimeError): recovery.verify(point, checksum)
        database.chmod(0o600); (point / 'search').chmod(0o755)
        with self.assertRaises(RuntimeError): recovery.verify(point, checksum)
        (point / 'search').chmod(0o700); database.write_bytes(b'corruption')
        with self.assertRaises(RuntimeError): recovery.verify(point, checksum)

    def container(self):
        scratch = self.root / 'scratch'
        host = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '',
                'UsernsMode': '', 'PidsLimit': 256, 'Memory': 1073741824, 'NanoCpus': 1000000000,
                'Tmpfs': {'/tmp': 'rw,nosuid,nodev'}, 'RestartPolicy': {'Name': 'no'}}
        mounts = [{'Type': 'bind', 'Source': str(scratch / name), 'Destination': target, 'RW': True}
                  for name, (_, target) in recovery.VOLUMES.items()]
        mounts += [{'Type': 'bind', 'Source': str(scratch / 'config' / name), 'Destination': target, 'RW': False}
                   for name, target in recovery.CONFIG.items()]
        config = {'Image': recovery.IMAGE, 'User': '472:472', 'Labels': {recovery.LABEL: scratch.name},
                  'Entrypoint': recovery.ENTRYPOINT, 'Cmd': recovery.SERVER_ARGS,
                  'Env': [k + '=' + v for k, v in recovery.ENVIRONMENT.items()] + ['PATH=/usr/bin']}
        return scratch, {'HostConfig': host, 'Config': config, 'Mounts': mounts}

    def test_native_isolation_refuses_each_privilege_network_mount_command_and_env_change(self):
        scratch, original = self.container(); recovery.require_container(original, scratch)
        with_tmpfs = copy.deepcopy(original)
        with_tmpfs['Mounts'].append({'Type': 'tmpfs', 'Source': '', 'Destination': '/tmp', 'RW': True})
        recovery.require_container(with_tmpfs, scratch)
        with_tmpfs['Mounts'][-1]['Destination'] = '/production'
        with self.assertRaises(RuntimeError): recovery.require_container(with_tmpfs, scratch)
        mutations = [('HostConfig', 'NetworkMode', 'host'), ('HostConfig', 'ReadonlyRootfs', False),
                     ('HostConfig', 'Privileged', True), ('HostConfig', 'CapAdd', ['SYS_ADMIN']),
                     ('HostConfig', 'PidMode', 'host'), ('HostConfig', 'Tmpfs', {}),
                     ('HostConfig', 'PortBindings', {'3000/tcp': [{'HostPort': '3000'}]}),
                     ('Config', 'Image', 'grafana:latest'), ('Config', 'User', '0'),
                     ('Config', 'Entrypoint', ['/bin/sh']), ('Config', 'Cmd', ['server']),
                     ('Config', 'Env', original['Config']['Env'] + ['GF_SECURITY_SECRET_KEY=synthetic'])]
        for section, key, value in mutations:
            changed = copy.deepcopy(original); changed[section][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.require_container(changed, scratch)
        changed = copy.deepcopy(original); changed['Mounts'][0]['Source'] = '/production'
        with self.assertRaises(RuntimeError): recovery.require_container(changed, scratch)
        changed = copy.deepcopy(original); changed['Mounts'][-1]['RW'] = True
        with self.assertRaises(RuntimeError): recovery.require_container(changed, scratch)


if __name__ == '__main__': unittest.main()
