"""Preserve complete native backup data and refuse unsafe recovery containers."""

import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import kanidm_recovery as recovery


class KanidmRecoveryContract(unittest.TestCase):
    def backup(self):
        return {'version': '1.10', 'db_s_uuid': 'source', 'db_d_uuid': 'domain', 'db_ts_max': [1, 2],
                'keyhandles': {'a': 'synthetic'}, 'repl_meta': {'ruv': []},
                'entries': [{'id': 'a', 'values': [None, 'escaped\nvalue']}, {'id': 'b'}, {'id': 'b'}]}

    def test_complete_entries_duplicates_and_metadata(self):
        value = self.backup()
        original = recovery.fingerprint(value)
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
            'Cmd': ['--config=/data/offline.toml', 'database', *args],
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
