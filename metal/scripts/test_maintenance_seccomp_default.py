"""Scoped default-seccomp configuration must preserve existing node arguments."""
import unittest
import maintenance_host_security as security


class SeccompDefaultTests(unittest.TestCase):
    def test_first_node_enables_supported_kubelet_flag(self):
        before = 'server: https://10.0.20.50:6443\nsnapshotter: stargz\n'
        after = security.k3s_security_config(before, 'charmander')
        self.assertEqual(after, before + 'selinux: true\nkubelet-arg:\n  - seccomp-default=true\n')

    def test_next_serial_node_uses_the_accepted_default(self):
        self.assertEqual(security.k3s_security_config('snapshotter: stargz\n', 'cyndaquil'),
                         'snapshotter: stargz\nselinux: true\nkubelet-arg:\n  - seccomp-default=true\n')

    def test_other_nodes_keep_existing_behavior(self):
        for node in ('totodile', 'pikachu', 'squirtle'):
            with self.subTest(node=node):
                self.assertEqual(security.k3s_security_config('snapshotter: stargz\n', node),
                                 'snapshotter: stargz\nselinux: true\n')

    def test_conflicting_kubelet_arguments_are_never_overwritten(self):
        with self.assertRaisesRegex(AssertionError, 'review existing kubelet arguments'):
            security.k3s_security_config('kubelet-arg:\n  - rotate-certificates=true\n', 'charmander')

    def test_runtime_requires_filtered_process_and_blocks_every_io_uring_exception(self):
        import copy
        profile = {'defaultAction': 'SCMP_ACT_ERRNO', 'syscalls': [{'names': ['read'], 'action': 'SCMP_ACT_ALLOW'}]}
        self.assertTrue(security.seccomp_profile(profile, 'Seccomp: 2\n')['io_uring_blocked'])
        for action in ('SCMP_ACT_ALLOW', 'SCMP_ACT_LOG', 'SCMP_ACT_TRACE', 'SCMP_ACT_NOTIFY'):
            value = copy.deepcopy(profile);value['syscalls'].append({'names': ['io_uring_setup'], 'action': action})
            with self.subTest(action=action), self.assertRaises(AssertionError):security.seccomp_profile(value, 'Seccomp: 2\n')
        with self.assertRaises(AssertionError):security.seccomp_profile({}, 'Seccomp: 2\n')
        with self.assertRaises(AssertionError):security.seccomp_profile(profile, 'Seccomp: 0\n')

    def test_before_offline_record_reuses_only_identical_proven_predispatch_state(self):
        import maintenance_production_node as production
        import tempfile
        import types
        from pathlib import Path
        start = production.NATIVE.index("   before_path=root/('before-offline-" )
        end = production.NATIVE.index('\n  value=evidence();pending=journal.begin', start)
        import textwrap
        snippet = textwrap.dedent(production.NATIVE[start:end])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);writes=[]
            def write(path, value, mode):writes.append(path);path.write_bytes(value);path.chmod(mode)
            import os
            scope = {'os':os,'root':root,'owner':{'owner':'owned'},'before':{'boot':'same'},
                     'actors':types.SimpleNamespace(safe=lambda path:None,exclusive_file=write),
                     'hops':types.SimpleNamespace(canonical=lambda value:repr(value).encode())}
            exec(snippet, scope);exec(snippet, scope);self.assertEqual(len(writes),1)
            scope['before']={'boot':'different'}
            with self.assertRaisesRegex(AssertionError,'never replay'):exec(snippet,scope)


if __name__ == '__main__':
    unittest.main()
