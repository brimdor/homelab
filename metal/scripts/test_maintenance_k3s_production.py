"""Production bridge trust boundaries; no live cluster or host mutations."""

import copy
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

import maintenance_k3s_contract as contract
import maintenance_k3s_production as production


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.before = {'boot': 'original', 'configs': {'/config': 'digest'}, 'unit_sha256': 'unit',
                       'selinux': 'Enforcing', 'stargz': True, 'pid': 10, 'version': production.SOURCE}
        self.after = dict(self.before, pid=11, version=production.TARGET)

    def test_retains_host_state_and_requires_one_observed_restart(self):
        production.unchanged_runtime(self.before, self.after)
        with self.assertRaisesRegex(RuntimeError, 'restart not observed'):
            production.unchanged_runtime(self.before, dict(self.after, pid=10))
        for field in ('boot', 'configs', 'unit_sha256', 'selinux', 'stargz'):
            changed = copy.deepcopy(self.after); changed[field] = 'different'
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'protected host state'):
                production.unchanged_runtime(self.before, changed)

    def test_production_cannot_cross_etcd_36_gate_or_touch_an_osd_host(self):
        class Hold:
            state = None
        for node, source, target in (('charmander', contract.VERSIONS[1], contract.VERSIONS[2]),
                                     ('cyndaquil', production.SOURCE, production.TARGET)):
            context = dict.fromkeys(('api', 'controller', 'native', 'identity', 'rpc'))
            context.update(hold=Hold(), operation='activate-binary', owner={
                'component': 'k3s', 'node': node, 'source': source, 'target': target})
            with self.subTest(node=node), self.assertRaisesRegex(RuntimeError, 'unreviewed production bridge'):
                production.native_operation(context)

    def test_all_embedded_remote_programs_compile_after_string_decoding(self):
        tree = ast.parse(Path(production.__file__).read_text())
        count = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                    ('sender_program', 'receiver_program', 'program') for t in node.targets)):
                value = node.value.right if isinstance(node.value, ast.BinOp) else node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and '\n' in value.value:
                    compile(value.value, 'decoded-remote-program', 'exec'); count += 1
        self.assertGreaterEqual(count, 5)


class BehaviorTests(unittest.TestCase):
    def test_missing_mesh_member_stops_before_dns_or_http(self):
        class API:
            def call(self, *args):
                return {'nodes': []}
        pod = {'metadata': {'name': 'cilium-fixture', 'labels': {'k8s-app': 'cilium'}}}
        with patch.object(production.subprocess, 'run') as command:
            with self.assertRaisesRegex(RuntimeError, 'mesh membership differs'):
                production.behavior(None, API(), [pod])
        command.assert_not_called()

    def test_registry_ref_requires_exact_existing_pod_and_spec(self):
        import maintenance_production_node as shared
        pod = {'metadata': {'name': 'zot', 'uid': 'different'}, 'spec': {}}
        class API:
            def call(self, *args):
                return {'items': [pod]}
        with patch.object(shared, 'protected_registry'), patch.object(shared, 'remote') as remote:
            with self.assertRaisesRegex(RuntimeError, 'registry drain reference differs'):
                production.registry(None, API(), {'namespace': 'zot', 'name': 'zot', 'uid': 'different'})
        remote.assert_not_called()


if __name__ == '__main__':
    unittest.main()
