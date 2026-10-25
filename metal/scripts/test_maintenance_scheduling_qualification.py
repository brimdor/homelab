"""Guard actual-response injection, explicit synthetic limits and finally cleanup."""

import gzip
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import maintenance_hop_journal as hops
import maintenance_scheduling_qualification as qualification


PATCH = ('patch', 'node', 'owned-node', '--type=json', '--patch', '[]', '-o', 'json')


class SchedulingQualificationTests(unittest.TestCase):
    def test_loss_occurs_after_one_successful_actual_node_patch_only(self):
        fixture = SimpleNamespace(identity=Mock(), kubectl=Mock(return_value=b'{"kind":"Node"}'))
        api = qualification.API(fixture);api.lose_node_response = True
        with self.assertRaisesRegex(RuntimeError, 'after actual Node patch'):api.call(*PATCH)
        fixture.identity.assert_called_once_with()
        fixture.kubectl.assert_called_once_with(*PATCH, data=None, json_output=False)
        self.assertFalse(api.lose_node_response)
        self.assertEqual(api.node_patches, [{'argv': list(PATCH), 'operations': []}])
        self.assertFalse(api.posts)

    def test_reads_and_global_owner_patches_do_not_trigger_node_response_loss(self):
        fixture = SimpleNamespace(identity=Mock(), kubectl=Mock(return_value=b'{"kind":"Node"}'))
        api = qualification.API(fixture);api.lose_node_response = True
        self.assertEqual(api.call('get', 'node', 'owned-node', '-o', 'json'), {'kind': 'Node'})
        api.call('patch', 'daemonset', 'kured', '-n', 'kured', '--type=json', '--patch', '[]', '-o', 'json')
        self.assertTrue(api.lose_node_response)
        self.assertFalse(api.node_patches)
        self.assertEqual(fixture.kubectl.call_count, 2)

    def test_actual_access_failure_remains_original_failure_without_retry_or_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'1.log.gz').write_bytes(gzip.compress(b'Forbidden\n'))
            fixture = SimpleNamespace(identity=Mock(), work=root, count=1,
                                      kubectl=Mock(side_effect=RuntimeError('actual access refusal')))
            api = qualification.API(fixture);api.lose_node_response = True
            with self.assertRaisesRegex(RuntimeError, 'actual access refusal'):api.call(*PATCH)
            self.assertTrue(api.lose_node_response)
            self.assertEqual(fixture.kubectl.call_count, 1)

    def test_package_reconnect_and_infrastructure_steps_are_explicitly_unexecuted(self):
        for step in hops.STEPS[2:7]:
            receipt = qualification.synthetic_checkpoint(step)
            self.assertEqual(receipt, {'step': step, 'synthetic_not_executed': True,
                                      'native_package_reboot_recovery_and_infrastructure_unqualified': True})
        for step in ('cordon', 'drain', 'restore_scheduling', 'accept_applications', 'foreign'):
            with self.subTest(step=step), self.assertRaisesRegex(RuntimeError, 'foreign synthetic checkpoint'):
                qualification.synthetic_checkpoint(step)

    def test_owned_cluster_cleanup_runs_on_creation_and_profile_failure(self):
        for creation_failure in (False, True):
            fixture = object.__new__(qualification.Qualification)
            fixture.create = Mock(side_effect=RuntimeError('create failure') if creation_failure else None)
            fixture.profile = Mock(side_effect=RuntimeError('profile failure'))
            fixture.cleanup = Mock()
            with self.subTest(creation_failure=creation_failure), self.assertRaises(RuntimeError):fixture.run()
            fixture.cleanup.assert_called_once_with()
            if creation_failure:fixture.profile.assert_not_called()


if __name__ == '__main__':
    unittest.main()
