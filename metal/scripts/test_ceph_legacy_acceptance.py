#!/usr/bin/env python3
"""Match exact vendor service-family scope without hiding authentication failures."""

import copy
import unittest

import ceph_legacy_acceptance as subject


class LegacyAcceptance(unittest.TestCase):
    def types(self):
        return {'entities': {**{entity: 'aes256k' for entity in subject.legacy.CORE},
                             'client.ordinary': 'aes'},
                'rotating': {**{entity: ['aes256k'] * 3 for entity in subject.SERVICES},
                             'auth.*': ['aes'] * 3}}

    def test_auth_family_remains_visible_but_only_actual_services_gate_warning(self):
        value = self.types()
        self.assertTrue(subject.service_keys_ready(value, ['AUTH_INSECURE_CLIENT_KEY_TYPE', 'POOL_NO_REDUNDANCY']))
        for entity in subject.SERVICES:
            pending = copy.deepcopy(value)
            pending['rotating'][entity][0] = 'aes'
            self.assertFalse(subject.service_keys_ready(pending, [subject.WARNING]))
            with self.assertRaisesRegex(RuntimeError, 'contradicts'):
                subject.service_keys_ready(pending, [])
        with self.assertRaisesRegex(RuntimeError, 'contradicts'):
            subject.service_keys_ready(value, [subject.WARNING])

    def test_missing_foreign_or_changed_core_client_health_never_passes(self):
        for mutate in (lambda v: v['rotating'].pop('mds.*'),
                       lambda v: v['rotating'].update(foreign=['aes256k'] * 3),
                       lambda v: v['rotating']['mon.*'].pop(),
                       lambda v: v['entities'].update({'mon.': 'aes'}),
                       lambda v: v['entities'].update({'client.ordinary': 'aes256k'})):
            value = self.types()
            mutate(value)
            with self.assertRaises(RuntimeError):
                subject.service_keys_ready(value, [])
        for check in subject.ERRORS | {'MON_DOWN', 'OSD_DOWN'}:
            with self.assertRaises(RuntimeError):
                subject.service_keys_ready(self.types(), [check])

    def test_exact_original_process_identity_required_before_signal(self):
        arguments = subject.transition_arguments('legacy103-owned')
        owned = (42, '1234', arguments)
        self.assertEqual(subject.select_runtime([owned, (43, '4567', [b'unrelated'])], 'legacy103-owned'), (42, '1234'))
        for rows in ([], [owned, owned], [(1, '1234', arguments)], [(42, '', arguments)],
                     [(42, '1234', arguments + [b'foreign'])], [(42, '1234', subject.transition_arguments('other'))]):
            with self.assertRaisesRegex(RuntimeError, 'one exact owned'):
                subject.select_runtime(rows, 'legacy103-owned')


if __name__ == '__main__':
    unittest.main()
