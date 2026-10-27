"""The boot repair grants one metadata permission and retains every audit finding."""

from contextlib import nullcontext
import hashlib
import unittest
from unittest.mock import Mock, patch

import maintenance_init_socket as socket_policy


class InitSocketTests(unittest.TestCase):
    def test_only_exact_metadata_permission(self):
        self.assertEqual(socket_policy.POLICY,
            b'(allow init_t kernel_t (netlink_kobject_uevent_socket (getattr)))\n')
        self.assertNotIn(b'dontaudit', socket_policy.POLICY)
        self.assertNotIn(b'permissive', socket_policy.POLICY)

    def test_foreign_owner_refused_before_native_or_file_mutation(self):
        journal = Mock()
        journal.hold.serialized.return_value = nullcontext()
        journal.owners.return_value = {'global': {'owner': 'foreign', 'node': 'pikachu'}}
        native = Mock()
        with self.assertRaises(AssertionError): socket_policy.execute(journal, native, Mock(), {})
        native.assert_not_called()

    def test_only_two_exact_terminated_probe_records_are_accounted(self):
        records = [{'record_sha256': value} for value in socket_policy.PROBE_HASHES]
        with patch.object(socket_policy, 'Path') as path:
            path.return_value.__truediv__.return_value.exists.return_value = False
            self.assertTrue(socket_policy.diagnostic_audits_resolved(records, socket_policy.BOOT))
            self.assertFalse(socket_policy.diagnostic_audits_resolved(records, 'another-boot'))
            self.assertFalse(socket_policy.diagnostic_audits_resolved(records[:1], socket_policy.BOOT))
            self.assertFalse(socket_policy.diagnostic_audits_resolved(records + records[:1], socket_policy.BOOT))
            self.assertFalse(socket_policy.diagnostic_audits_resolved([records[0], {'record_sha256': 'changed'}], socket_policy.BOOT))
            path.return_value.__truediv__.return_value.exists.return_value = True
            self.assertFalse(socket_policy.diagnostic_audits_resolved(records, socket_policy.BOOT))

    def test_new_kernel_denial_or_missing_permission_stays_blocked(self):
        record = {'owner': socket_policy.OWNER, 'boot': socket_policy.BOOT,
                  'policy_sha256': hashlib.sha256(socket_policy.POLICY).hexdigest()}
        native = Mock(return_value='Enforcing')
        with patch.object(socket_policy, 'allowed', return_value=False):
            with self.assertRaises(AssertionError): socket_policy.verify(native, record)
        with patch.object(socket_policy, 'allowed', return_value=True), patch.object(
                socket_policy, 'kernel_records', return_value=[socket_policy.HISTORICAL, 'another AVC']):
            with self.assertRaisesRegex(AssertionError, 'new kernel AVC'):
                socket_policy.verify(native, record)

    def test_pending_stage_refused_without_nested_lock_or_mutation(self):
        journal = Mock()
        journal.hold.serialized.return_value = nullcontext()
        journal.owners.return_value = {'global': {'owner': socket_policy.OWNER,
            'node': 'pikachu', 'source': 44, 'target': 44}}
        journal.read.return_value = {'pending': {'step': 'drain'}, 'completed': []}
        native = Mock()
        identity = lambda: {'machine': '0a7daf8b33244d9d85f46223c3582da9',
                            'root_uuid': '76e53a95-725a-4430-9d7b-a8db413f3997'}
        with patch.object(socket_policy, 'Path') as path:
            path.return_value.read_text.return_value = socket_policy.BOOT
            with self.assertRaises(AssertionError): socket_policy.execute(journal, native, identity, {})
        journal.read.assert_called_once()
        journal.inspect.assert_not_called()
        native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
