"""Exact quorum and transport checks before Squirtle's serial host work."""

import contextlib
import copy
import io
import json
import importlib
from pathlib import Path
import shlex
import subprocess
import unittest
from unittest.mock import patch

import maintenance_control_plane as CP
import maintenance_production_node as PRODUCTION


class QuorumTests(unittest.TestCase):
    def setUp(self):
        self.urls = ['https://10.0.20.' + str(n) + ':2379' for n in (11, 12, 13)]
        self.ids = [11787375536453005064, 16426130908996892198, 480346530818056711]
        self.values = {
            ('member', 'list'): {'members': [
                {'ID': n, 'clientURLs': [url], 'peerURLs': [url.replace('2379', '2380')]}
                for n, url in zip(self.ids, self.urls)]},
            ('endpoint', 'status'): [{'Endpoint': url, 'Status': {
                'header': {'cluster_id': 10496245635645811339, 'member_id': n}, 'leader': self.ids[0], 'version': '3.5.21'}}
                for n, url in zip(self.ids, self.urls)],
            ('endpoint', 'health'): [{'endpoint': url, 'health': True} for url in self.urls],
            ('alarm', 'list'): {},
        }

    def observe(self, values):
        def run(argv, **kwargs):
            self.assertIn('--cacert=/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt', argv)
            self.assertIn('--cert=/var/lib/rancher/k3s/server/tls/etcd/client.crt', argv)
            self.assertNotIn('--insecure-skip-tls-verify', argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps(values[tuple(argv[-2:])]).encode(), b'')
        with patch('os.geteuid', return_value=0), patch('socket.gethostname', return_value='squirtle'), \
                patch.object(Path, 'read_text', return_value=CP.IDENTITY), patch('subprocess.run', side_effect=run), \
                patch.object(Path, 'read_bytes', return_value=b'client'), \
                patch('hashlib.sha256') as digest, \
                contextlib.redirect_stdout(io.StringIO()):
            digest.return_value.hexdigest.return_value = CP.BINARY_SHA256
            exec(compile(CP.program(CP.OBSERVE), 'native-etcd-observation', 'exec'), {})

    def test_exact_three_voting_members_are_accepted(self):
        self.observe(self.values)

    def test_learner_failed_member_changed_cluster_leader_and_alarm_are_refused(self):
        for fault in ('learner', 'health', 'cluster', 'leader', 'alarm'):
            values = copy.deepcopy(self.values)
            if fault == 'learner': values[('member', 'list')]['members'][0]['isLearner'] = True
            if fault == 'health': values[('endpoint', 'health')][0]['health'] = False
            if fault == 'cluster': values[('endpoint', 'status')][0]['Status']['header']['cluster_id'] = 43
            if fault == 'leader': values[('endpoint', 'status')][0]['Status']['leader'] = 2
            if fault == 'alarm': values[('alarm', 'list')]['alarms'] = [{'alarm': 1}]
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                self.observe(values)


class ProductionProfileTests(unittest.TestCase):
    def setUp(self):
        importlib.reload(PRODUCTION)
        self.addCleanup(importlib.reload, PRODUCTION)

    def test_configuration_recovery_uses_reviewed_receiver_for_each_source(self):
        for node in ('totodile', 'pikachu', 'squirtle', 'charmander'):
            for release in (39, 41, 43, 44):
                with self.subTest(node=node, release=release):
                    importlib.reload(PRODUCTION)
                    PRODUCTION.select_node(node)
                    growlithe = (node == 'pikachu' and release in (43, 44) or
                                 node == 'squirtle' and release in (41, 43, 44) or node == 'charmander')
                    receiver = '10.0.20.18' if growlithe else (
                        '10.0.20.17' if node == 'pikachu' else '10.0.20.14')
                    point = {'manifest_sha256': 'a' * 64}
                    manifest = {'identity': PRODUCTION.IDENTITY, 'node_uid': PRODUCTION.UID,
                                'source_release': release}
                    if node in ('squirtle', 'charmander'):
                        manifest['control_plane_recovery'] = point
                    with patch.object(CP, 'recovery', return_value=point), \
                            patch.object(PRODUCTION, 'remote', return_value=manifest) as readback:
                        self.assertEqual(PRODUCTION.recovery(None, release), manifest)
                    self.assertEqual(readback.call_args.args[2], receiver)
                    if growlithe:
                        self.assertIn('a26cbcc990c044dea41fbf4f957f453d', readback.call_args.args[1])
                        self.assertIn('710e2dca-691e-4123-a867-4994b9c6e612', readback.call_args.args[1])

    def test_squirtle_security_recovery_is_fresh_and_never_writes_growlithe(self):
        PRODUCTION.select_node('squirtle')
        PRODUCTION.BACKUPS[44] = PRODUCTION.SECURITY_BACKUPS['squirtle']
        point = {'manifest_sha256': 'a' * 64}
        manifest = {'identity': PRODUCTION.IDENTITY, 'node_uid': PRODUCTION.UID,
                    'source_release': 44, 'control_plane_recovery': point}
        with patch.object(CP, 'recovery', return_value=point) as snapshot, \
                patch.object(PRODUCTION, 'remote', return_value=manifest) as readback:
            self.assertEqual(PRODUCTION.recovery(None, 44), manifest)
        snapshot.assert_called_once_with(None, 44, False, node='squirtle', security_followup=True)
        self.assertEqual(readback.call_args.args[2], '10.0.20.16')
        self.assertIn('squirtle-fedora44-seccomp-config-20261028-a', readback.call_args.args[1])
        self.assertIn('fc02c8c4-35c6-4efe-a88a-b03d7673c0c8', readback.call_args.args[1])
        with patch.object(PRODUCTION, 'remote', side_effect=RuntimeError('stop before native read')) as readback:
            with self.assertRaisesRegex(RuntimeError, 'stop before native'):
                CP.recovery(None, 44, node='squirtle', security_followup=True)
        self.assertIn('squirtle-fedora44-seccomp-20261028-a', readback.call_args.args[1])
        for node, release in [('charmander', 44), ('squirtle', 43), ('bulbasaur', 44)]:
            with self.subTest(node=node, release=release), patch.object(PRODUCTION, 'remote') as remote:
                with self.assertRaisesRegex(AssertionError, 'unreviewed'):
                    CP.recovery(None, release, node=node, security_followup=True)
                remote.assert_not_called()

    def test_master_archive_excludes_live_etcd_and_binds_protected_snapshot(self):
        PRODUCTION.select_node('squirtle')
        point = {'manifest_sha256': 'a' * 64}
        manifest = {'identity': PRODUCTION.IDENTITY, 'node_uid': PRODUCTION.UID,
                    'source_release': 39, 'control_plane_recovery': point}
        with patch.object(CP, 'recovery', return_value=point), \
                patch.object(PRODUCTION, 'remote', return_value=manifest):
            self.assertEqual(PRODUCTION.recovery(None, 39), manifest)
        changed = dict(manifest, control_plane_recovery={'manifest_sha256': 'b' * 64})
        with patch.object(CP, 'recovery', return_value=point), \
                patch.object(PRODUCTION, 'remote', return_value=changed), self.assertRaises(RuntimeError):
            PRODUCTION.recovery(None, 39)

    def test_generated_master_archive_program_has_no_live_etcd_database(self):
        PRODUCTION.select_node('squirtle')
        point = {'manifest_sha256': 'a' * 64}
        class Child:
            returncode = 0
            stdout = io.BytesIO()
            stderr = io.BytesIO()
            def communicate(self): return (b'{"sha256":"abc","bytes":1024}', b'')
            def wait(self): return 0
            def poll(self): return 0
        from types import SimpleNamespace
        args = SimpleNamespace(identity='/secure/identity', known_hosts='/secure/known_hosts')
        with patch.object(CP, 'recovery', return_value=point), \
                patch.object(PRODUCTION, 'remote', side_effect=[None, {}, {'accepted': True}]), \
                patch.object(PRODUCTION.subprocess, 'Popen', side_effect=[Child(), Child()]) as popen:
            PRODUCTION.recovery(args, 39, capture=True)
        source = shlex.split(popen.call_args_list[0].args[0][-1])[3]
        compile(source, 'native-master-archive', 'exec')
        self.assertIn("if True:", source)
        self.assertIn("command.insert(1,'--exclude=var/lib/rancher/k3s/server/db')", source)
        self.assertIn("command.append('var/lib/homelab-recovery/maintenance-103')", source)
        compile(PRODUCTION.NATIVE, 'native-production', 'exec')


if __name__ == '__main__':
    unittest.main()
