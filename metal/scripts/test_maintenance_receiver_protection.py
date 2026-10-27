"""Exact recovery receivers, native identities and stale-source rejection."""
import ast
import unittest
from unittest import mock
import maintenance_receiver_protection as recovery


class ReceiverTests(unittest.TestCase):
    def test_reviewed_source_receiver_pairs_and_native_guards(self):
        pairs = {'pikachu': ('10.0.20.14','10.0.20.17'), 'growlithe': ('10.0.20.18','10.0.20.11'),
                 'pikachu-security-20261027': ('10.0.20.14','10.0.20.16')}
        for node, addresses in pairs.items():
            with self.subTest(node=node):
                profile, inventory, readback = recovery.programs(node)
                self.assertEqual((profile['source_address'],profile['receiver_address']),addresses)
                self.assertIn(repr(profile['source_machine']),inventory)
                self.assertIn(repr(profile['source_root']),inventory)
                self.assertIn(repr(profile['receiver_machine']),readback)
                self.assertIn(repr(profile['receiver_root']),readback)
                self.assertIn(repr(profile['destination']),readback)
                self.assertNotIn('10.0.40.3',inventory+readback)
                ast.parse(inventory);ast.parse(readback)

    def test_verification_reads_fixed_receiver_then_unchanged_source(self):
        for node in recovery.PROFILES:
            profile, _, _ = recovery.programs(node)
            saved = {'source_inventory': {'files':7,'bytes':1024,'metadata_sha256':'a'*64}}
            with mock.patch.object(recovery,'remote',side_effect=[saved,saved['source_inventory']]) as remote:
                self.assertEqual(recovery.verify(object(),node),saved)
                self.assertEqual([call.args[2]for call in remote.call_args_list], [profile['receiver_address'],profile['source_address']])
            with mock.patch.object(recovery,'remote',side_effect=[saved,{'files':8}]):
                with self.assertRaisesRegex(RuntimeError,'source changed'):recovery.verify(object(),node)

    def test_unknown_profile_cannot_start_a_remote_operation(self):
        with mock.patch.object(recovery,'remote') as remote:
            with self.assertRaisesRegex(RuntimeError,'unreviewed'):recovery.protect(object(),'nas')
            remote.assert_not_called()


if __name__ == '__main__':unittest.main()
