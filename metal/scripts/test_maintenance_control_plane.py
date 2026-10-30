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

    def observe(self, values, versions=None, active_endpoints=None):
        def run(argv, **kwargs):
            self.assertIn('--cacert=/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt', argv)
            self.assertIn('--cert=/var/lib/rancher/k3s/server/tls/etcd/client.crt', argv)
            self.assertNotIn('--insecure-skip-tls-verify', argv)
            endpoints = active_endpoints or self.urls
            self.assertIn('--endpoints=' + ','.join(endpoints), argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps(values[tuple(argv[-2:])]).encode(), b'')
        with patch('os.geteuid', return_value=0), patch('socket.gethostname', return_value='squirtle'), \
                patch.object(Path, 'read_text', return_value=CP.IDENTITY), patch('subprocess.run', side_effect=run), \
                patch.object(Path, 'read_bytes', return_value=b'client'), \
                patch('hashlib.sha256') as digest, \
                contextlib.redirect_stdout(io.StringIO()):
            digest.return_value.hexdigest.return_value = CP.BINARY_SHA256
            exec(compile(CP.program(CP.OBSERVE, versions, active_endpoints), 'native-etcd-observation', 'exec'), {})

    def test_exact_three_voting_members_are_accepted(self):
        self.observe(self.values)

    def test_mixed_etcd_versions_are_bound_to_the_exact_serial_server(self):
        versions = {'charmander': 'v1.33.10+k3s1', 'squirtle': 'v1.33.6+k3s1', 'bulbasaur': 'v1.33.6+k3s1'}
        values = copy.deepcopy(self.values)
        values[('endpoint', 'status')][0]['Status']['version'] = '3.5.26'
        self.observe(values, versions)
        with self.assertRaises(AssertionError):
            self.observe(self.values, versions)
        for changed in (dict(versions, squirtle='v1.36.5+k3s1'),
                        dict(versions, bulbasaur='v1.33.10+k3s1'),
                        dict(versions, charmander='v1.33.13+k3s2')):
            with self.subTest(versions=changed), self.assertRaises(RuntimeError):
                CP.expected_versions(changed)

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

    def test_exact_two_survivors_keep_all_three_original_members(self):
        versions = dict.fromkeys(('charmander', 'squirtle', 'bulbasaur'), 'v1.33.10+k3s1')
        for stopped in range(3):
            for index, name in enumerate(('charmander', 'squirtle', 'bulbasaur')):
                versions[name] = 'v1.33.13+k3s2' if index < stopped else 'v1.33.10+k3s1'
            values = copy.deepcopy(self.values)
            active = [url for i, url in enumerate(self.urls) if i != stopped]
            for key in (('endpoint', 'status'), ('endpoint', 'health')):
                values[key].pop(stopped)
            for entry in values[('endpoint', 'status')]:
                entry['Status']['version'] = CP.expected_versions(versions)[entry['Endpoint']]
                entry['Status']['leader'] = next(n for i, n in enumerate(self.ids) if i != stopped)
            with self.subTest(stopped=stopped):
                self.observe(values, versions, active)
                with self.assertRaises(AssertionError):
                    self.observe(values, versions)
            for fault in ('membership', 'swapped', 'leader', 'health', 'duplicate', 'version', 'alarm', 'cluster'):
                changed = copy.deepcopy(values)
                if fault == 'membership': changed[('member', 'list')]['members'].pop(stopped)
                if fault == 'swapped':
                    rows = changed[('endpoint', 'status')]
                    rows[0]['Status']['header']['member_id'], rows[1]['Status']['header']['member_id'] = (
                        rows[1]['Status']['header']['member_id'], rows[0]['Status']['header']['member_id'])
                if fault == 'leader':
                    for entry in changed[('endpoint', 'status')]: entry['Status']['leader'] = self.ids[stopped]
                if fault == 'health': changed[('endpoint', 'health')][0]['endpoint'] = self.urls[stopped]
                if fault == 'duplicate': changed[('endpoint', 'status')][1] = changed[('endpoint', 'status')][0]
                if fault == 'version': changed[('endpoint', 'status')][0]['Status']['version'] = '0.0.0'
                if fault == 'alarm': changed[('alarm', 'list')]['alarms'] = [{'alarm': 1}]
                if fault == 'cluster': changed[('endpoint', 'status')][0]['Status']['header']['cluster_id'] = 1
                with self.subTest(stopped=stopped, fault=fault), self.assertRaises((AssertionError, KeyError)):
                    self.observe(changed, versions, active)

    def test_stopped_observer_requires_reviewed_stage_and_two_parent_proofs(self):
        from unittest.mock import Mock
        versions = dict.fromkeys(('charmander', 'squirtle', 'bulbasaur'), 'v1.33.10+k3s1')
        proof = Mock(side_effect=[True, True])
        with patch.object(PRODUCTION, 'remote', return_value={'verified': True}) as remote:
            self.assertEqual(CP.observe_stopped(None, versions, 'squirtle', proof), {'verified': True})
            self.assertEqual(proof.call_count, 2)
            self.assertEqual(remote.call_args.args[2], '10.0.20.12')
            self.assertIn("ACTIVE_ENDPOINTS=('https://10.0.20.11:2379', 'https://10.0.20.13:2379')", remote.call_args.args[1])
        for proof in (None, Mock(return_value=False), Mock(return_value=1)):
            with patch.object(PRODUCTION, 'remote') as remote, self.assertRaises(RuntimeError):
                CP.observe_stopped(None, versions, 'squirtle', proof)
            remote.assert_not_called()
        with patch.object(PRODUCTION, 'remote', return_value={}) as remote, self.assertRaisesRegex(RuntimeError, 'changed'):
            CP.observe_stopped(None, versions, 'squirtle', Mock(side_effect=[True, False]))
        self.assertEqual(remote.call_count, 1)
        for node, changed in (('growlithe', versions), ('squirtle', dict(versions, squirtle='v1.33.6+k3s1')),
                              ('squirtle', dict(versions, charmander='v1.34.12+k3s1'))):
            with self.subTest(node=node, versions=changed), patch.object(PRODUCTION, 'remote') as remote, self.assertRaises(RuntimeError):
                CP.observe_stopped(None, changed, node, Mock(return_value=True))
            remote.assert_not_called()


class NativeVoterTests(unittest.TestCase):
    def test_original_host_profiles_preserve_pinned_client_and_compile(self):
        for host, identity in CP.IDENTITIES.items():
            source = CP.program(CP.OBSERVE, host=host)
            self.assertIn('HOST=' + repr(host), source)
            self.assertIn('IDENTITY=' + repr(identity), source)
            self.assertIn('BINARY_SHA256=' + repr(CP.BINARY_SHA256), source)
            compile(source, 'native-voter-observation', 'exec')
            compile(CP.program(CP.INSTALL, host=host), 'native-voter-installation', 'exec')
        with self.assertRaisesRegex(RuntimeError, 'unreviewed native'):
            CP.program(CP.OBSERVE, host='foreign')

    def test_native_result_captures_only_structured_output_and_install_is_explicit(self):
        self.assertEqual(CP.native_result("print('{\"verified\":true}')", 'squirtle'), {'verified': True})
        with patch.object(CP, 'native_result', return_value={'installed': True}) as result:
            self.assertEqual(CP.native_install('charmander'), {'installed': True})
            result.assert_called_once_with(CP.INSTALL, 'charmander')

    def test_native_stopped_mode_requires_exact_stage_and_pre_post_source_proof(self):
        from unittest.mock import Mock
        versions = dict.fromkeys(CP.IDENTITIES, 'v1.33.10+k3s1')
        for host in CP.IDENTITIES:
            proof = Mock(side_effect=[True, True])
            with patch.object(CP, 'native_result', return_value={'verified': True}) as result:
                self.assertEqual(CP.native_observe(host, versions, confirm_stopped=proof), {'verified': True})
                active = tuple('https://10.0.20.' + str(n) + ':2379' for n, name in
                               zip((11, 12, 13), CP.IDENTITIES) if name != host)
                result.assert_called_once_with(CP.OBSERVE, host, versions, active)
                self.assertEqual(proof.call_count, 2)
        for proof in (Mock(return_value=False), Mock(return_value=1)):
            with patch.object(CP, 'native_result') as result, self.assertRaises(RuntimeError):
                CP.native_observe('charmander', versions, confirm_stopped=proof)
            result.assert_not_called()
        with patch.object(CP, 'native_result', return_value={}), self.assertRaisesRegex(RuntimeError, 'changed'):
            CP.native_observe('squirtle', versions, confirm_stopped=Mock(side_effect=[True, False]))
        with patch.object(CP, 'native_result') as result, self.assertRaisesRegex(RuntimeError, 'transition'):
            CP.native_observe('bulbasaur', dict(versions, bulbasaur='v1.33.6+k3s1'), confirm_stopped=Mock(return_value=True))
        result.assert_not_called()
        with patch.object(CP, 'native_result', return_value={}) as result:
            CP.native_observe('squirtle', versions)
            result.assert_called_once_with(CP.OBSERVE, 'squirtle', versions, None)


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
