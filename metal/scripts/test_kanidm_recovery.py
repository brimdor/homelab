"""Preserve complete native backup data and refuse unsafe recovery containers."""

import copy
import gzip
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import kanidm_recovery as recovery


class KanidmRecoveryContract(unittest.TestCase):
    def test_native_startup_transformation_preserves_all_data_and_prior_history(self):
        original = self.backup()
        old = {'s': 'source', 't': {'secs': 1, 'nanos': 0}}
        new = {'s': 'source', 't': {'secs': 3, 'nanos': 0}}
        original['db_ts_max'] = old['t']
        original['repl_meta'] = {'V1': {'ruv': [old]}}
        original['entries'] = [{'ent': {'V3': {
            'attrs': {'uuid': ['entry'], 'credential': {'opaque': 'private'}, 'last_modified_cid': {'CI': [old]}},
            'changestate': {'V1Live': {'at': old, 'changes': {'credential': old}}}}}}]
        restored = copy.deepcopy(original)
        restored['db_ts_max'] = {'secs': 4, 'nanos': 0}
        restored['repl_meta']['V1']['ruv'].append(new)
        item = restored['entries'][0]['ent']['V3']
        item['attrs']['last_modified_cid'] = {'CI': [new]}
        item['changestate']['V1Live']['changes']['credential'] = new
        result = recovery.validate_native_restore(original, restored, 2 * 10**9, 5 * 10**9, 1)
        self.assertTrue(result['data_equal'])
        self.assertEqual(result['normalized_fingerprint'], recovery.fingerprint(original))
        self.assertEqual(result['validated_new_replication_points'], 1)
        self.assertNotIn('private', json.dumps(result))
        mutations = [
            lambda v: v['entries'][0]['ent']['V3']['attrs'].update(credential={'opaque': 'altered'}),
            lambda v: v['entries'][0]['ent']['V3']['attrs'].pop('credential'),
            lambda v: v['entries'].clear(),
            lambda v: v['entries'].append(copy.deepcopy(v['entries'][0])),
            lambda v: v['entries'][0]['ent']['V3']['changestate']['V1Live'].update(at=new),
            lambda v: v['entries'][0]['ent']['V3']['changestate']['V1Live']['changes'].clear(),
            lambda v: v['repl_meta']['V1']['ruv'].pop(0),
            lambda v: v.update(db_ts_max={'secs': 9, 'nanos': 0}),
            lambda v: v['repl_meta']['V1']['ruv'].append({'s': 'foreign', 't': new['t']}),
            lambda v: v['repl_meta']['V1']['ruv'].append({'s': 'source', 't': {'secs': 1, 'nanos': 1}}),
            lambda v: v['repl_meta']['V1']['ruv'].append({'s': 'source', 't': {'secs': 8, 'nanos': 0}}),
            lambda v: v.update(keyhandles={'changed': 'secret'}),
        ]
        for mutation in mutations:
            value = copy.deepcopy(restored)
            mutation(value)
            with self.assertRaises(RuntimeError):
                recovery.validate_native_restore(original, value, 2 * 10**9, 5 * 10**9, 1)
        with self.assertRaisesRegex(RuntimeError, 'count differs'):
            recovery.validate_native_restore(original, restored, 2 * 10**9, 5 * 10**9, 2)

    def test_difference_diagnostic_contains_only_schema_names_and_counts(self):
        original = {'entries': [{'ent': {'V3': {'attrs': {'uuid': ['synthetic-id'],
                                'secret': ['synthetic-secret']}, 'changestate': [1]}}}]}
        restored = copy.deepcopy(original)
        restored['entries'][0]['ent']['V3']['attrs']['secret'] = ['other-private-value']
        restored['entries'][0]['ent']['V3']['changestate'] = [2]
        result = recovery.backup_differences(original, restored)
        self.assertEqual(result, {'removed_entries': 0, 'added_entries': 0,
                                 'changed_entry_states': 1, 'changed_attribute_counts': {'secret': 1}})
        self.assertNotIn('synthetic', json.dumps(result))
        original['entries'].append(copy.deepcopy(original['entries'][0]))
        with self.assertRaisesRegex(RuntimeError, 'identity/schema'):
            recovery.backup_differences(original, restored)

    def test_offline_configuration_has_inert_tls_paths_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(recovery.os, 'chown') as owner:
                recovery.config(root, 'restored.db')
            path = root / 'offline.toml'
            self.assertIn('db_path = "/data/restored.db"', path.read_text())
            self.assertIn('db_arc_size = 2048', path.read_text())
            self.assertIn('tls_chain = "/data/offline-unused.crt"', path.read_text())
            self.assertIn('tls_key = "/data/offline-unused.key"', path.read_text())
            self.assertEqual(list(root.iterdir()), [path])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            owner.assert_called_once_with(path, 1000, 1000)

    def test_failure_output_stays_in_exclusive_private_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def docker(*args, **_kwargs):
                if args[0] == 'create':
                    return SimpleNamespace(stdout=('a' * 64).encode())
                if args[0] == 'start':
                    return SimpleNamespace(stdout=b'synthetic-private-record', stderr=b'', returncode=2)
                return SimpleNamespace(returncode=1 if args[0] == 'inspect' else 0)
            state = {'State': {'Running': False, 'ExitCode': 2, 'OOMKilled': False}}
            with patch.object(recovery, 'POINT', root), patch.object(recovery.common, 'docker', side_effect=docker), \
                    patch.object(recovery.common, 'inspect', return_value=state), \
                    patch.object(recovery, 'require_container'):
                for _ in range(2):
                    with self.assertRaises(RuntimeError) as caught:
                        recovery.operation(root, 'fixture', ['verify'], b'Verification passed!', 'owned')
                    self.assertNotIn('synthetic-private-record', str(caught.exception))
            logs = list(root.glob('native-failure-fixture-*.log'))
            self.assertEqual(len(logs), 2)
            for path in logs:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.read_bytes(), b'synthetic-private-record')

    def backup(self):
        return {'version': '1.10', 'db_s_uuid': 'source', 'db_d_uuid': 'domain', 'db_ts_max': [1, 2],
                'keyhandles': {'a': 'synthetic'}, 'repl_meta': {'ruv': []},
                'entries': [{'id': 'a', 'values': [None, 'escaped\nvalue']}, {'id': 'b'}, {'id': 'b'}]}

    def test_complete_entries_duplicates_and_metadata(self):
        value = self.backup()
        original = recovery.fingerprint(value)
        self.assertEqual(set(original['metadata_fields']), set(value) - {'entries'})
        changed = copy.deepcopy(value)
        changed['entries'].reverse()
        self.assertEqual(recovery.fingerprint(changed), original)
        for key in value:
            changed = copy.deepcopy(value)
            if key == 'entries':
                changed[key].pop()
            elif key == 'version':
                changed[key] = '1.9'
                with self.assertRaises(RuntimeError):
                    recovery.fingerprint(changed)
                continue
            else:
                changed[key] = {'changed': True}
            self.assertNotEqual(recovery.fingerprint(changed), original)
        for bad in ({}, {**value, 'unknown': True}, {**value, 'entries': []}):
            with self.assertRaises(RuntimeError):
                recovery.fingerprint(bad)

    def test_plain_gzip_and_actual_ram_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'backup'
            raw = json.dumps(self.backup()).encode()
            with patch.object(recovery.retained, 'available_memory', return_value=4 * 1024 * 1024):
                for data in (raw, gzip.compress(raw)):
                    path.write_bytes(data)
                    self.assertEqual(recovery.backup_fingerprint(path), recovery.fingerprint(self.backup()))
            with patch.object(recovery.retained, 'available_memory', return_value=16):
                with self.assertRaisesRegex(RuntimeError, 'available RAM'):
                    recovery.backup_fingerprint(path)

    def test_exact_isolation_refuses_changed_image_mount_or_privilege(self):
        root = Path('/synthetic/owned')
        args = ['verify']
        value = {'Image': 'sha256:owned', 'Config': {
            'Image': recovery.IMAGE, 'User': '1000:1000', 'Entrypoint': ['/sbin/kanidmd'],
            'Cmd': ['--config-path=/data/offline.toml', 'database', *args],
            'Labels': {recovery.LABEL: 'fixture'}}, 'HostConfig': {
                'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 1073741824,
                'NanoCpus': 1000000000, 'Tmpfs': {'/tmp': 'rw,nosuid,nodev,uid=1000,gid=1000,mode=1777'},
                'RestartPolicy': {'Name': 'no'}},
            'Mounts': [{'Type': 'bind', 'RW': True, 'Source': str(root), 'Destination': '/data'}]}
        recovery.require_container(value, root, 'fixture', args, 'sha256:owned')
        for section, key, new in [('HostConfig', 'NetworkMode', 'host'), ('HostConfig', 'Privileged', True),
                                  ('HostConfig', 'Devices', ['unowned']), ('Config', 'User', '0:0'),
                                  ('Config', 'Image', 'mutable:latest')]:
            changed = copy.deepcopy(value)
            changed[section][key] = new
            with self.assertRaises(RuntimeError):
                recovery.require_container(changed, root, 'fixture', args, 'sha256:owned')
        changed = copy.deepcopy(value)
        changed['Mounts'][0]['Source'] = '/production'
        with self.assertRaises(RuntimeError):
            recovery.require_container(changed, root, 'fixture', args, 'sha256:owned')


if __name__ == '__main__':
    unittest.main()
