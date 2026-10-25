"""Actual API response-loss injection and clearly bounded synthetic safety."""

import copy
import gzip
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import maintenance_release_qualification as qualification


PATCH = ('patch', 'daemonset', 'kured', '-n', 'kured', '--type=json', '--patch', '[]', '-o', 'json')


class ReleaseQualificationTests(unittest.TestCase):
    def test_global_response_loss_follows_one_actual_successful_patch(self):
        fixture = SimpleNamespace(identity=Mock(), kubectl=Mock(return_value=b'{"kind":"DaemonSet"}'))
        api = qualification.API(fixture);api.lose_global_response = True
        with self.assertRaisesRegex(RuntimeError, 'after actual global release'):api.call(*PATCH)
        fixture.identity.assert_called_once_with()
        fixture.kubectl.assert_called_once_with(*PATCH, data=None, json_output=False)
        self.assertFalse(api.lose_global_response)
        self.assertEqual(api.global_patches, [{'argv': list(PATCH), 'operations': []}])
        self.assertFalse(api.posts);self.assertFalse(api.node_patches)

    def test_reads_do_not_consume_release_response_loss(self):
        fixture = SimpleNamespace(identity=Mock(), kubectl=Mock(return_value=b'{"kind":"DaemonSet"}'))
        api = qualification.API(fixture);api.lose_global_response = True
        self.assertEqual(api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json'),
                         {'kind': 'DaemonSet'})
        self.assertTrue(api.lose_global_response);self.assertFalse(api.global_patches)
        fixture.identity.assert_not_called()

    def test_actual_api_refusal_preserved_without_replay_or_injected_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'1.log.gz').write_bytes(gzip.compress(b'Forbidden\n'))
            fixture = SimpleNamespace(identity=Mock(), kubectl=Mock(side_effect=RuntimeError('actual access refusal')),
                                      work=root, count=1)
            api = qualification.API(fixture);api.lose_global_response = True
            with self.assertRaisesRegex(RuntimeError, 'actual access refusal'):api.call(*PATCH)
            self.assertTrue(api.lose_global_response);self.assertEqual(fixture.kubectl.call_count, 1)

    def test_synthetic_safety_is_explicit_and_copies_application(self):
        application = {'canary_uid': 'fixture'};saved = copy.deepcopy(application)
        evidence = qualification.synthetic_safety(application);application['canary_uid'] = 'changed'
        self.assertEqual(evidence, {'application': saved,
                                   'native_host_package_reboot_recovery_six_layers_synthetic': True,
                                   'production_release_unqualified': True})

    def test_inherited_finally_cleanup_covers_creation_and_profile_failure(self):
        for fail_create in (False, True):
            fixture = object.__new__(qualification.Qualification)
            fixture.create = Mock(side_effect=RuntimeError('create failure') if fail_create else None)
            fixture.profile = Mock(side_effect=RuntimeError('profile failure'));fixture.cleanup = Mock()
            with self.subTest(fail_create=fail_create), self.assertRaises(RuntimeError):fixture.run()
            fixture.cleanup.assert_called_once_with()
            if fail_create:fixture.profile.assert_not_called()


if __name__ == '__main__':
    unittest.main()
