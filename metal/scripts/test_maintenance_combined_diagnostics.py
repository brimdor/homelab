#!/usr/bin/env python3
"""A failed combined transaction must remain failed and must never replay."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_combined_diagnostics as subject


class DiagnosticsTests(unittest.TestCase):
    def test_failure_observes_once_without_replaying_or_changing_original_error(self):
        qualification = object.__new__(subject.Qualification)
        original = RuntimeError('original ownership refusal')
        with tempfile.TemporaryDirectory() as directory:
            qualification.root = Path(directory)
            with patch.object(subject.combined.Qualification, 'guest',
                              side_effect=[original, {'daemonset': {'status': {'numberReady': 0}}}]) as guest:
                with self.assertRaises(RuntimeError) as error:
                    qualification.guest('original operation', 73)
            self.assertIs(error.exception, original)
            self.assertEqual([call.args for call in guest.call_args_list],
                             [('original operation', 73), (subject.DIAGNOSTIC,)])
            evidence = json.loads((qualification.root / 'readiness-failure.json').read_bytes())
            self.assertEqual(evidence['daemonset']['status']['numberReady'], 0)

    def test_diagnostic_failure_is_recorded_without_replacing_original_refusal(self):
        qualification = object.__new__(subject.Qualification)
        original = RuntimeError('original refusal')
        with tempfile.TemporaryDirectory() as directory:
            qualification.root = Path(directory)
            with patch.object(subject.combined.Qualification, 'guest',
                              side_effect=[original, ValueError('PRIVATE_SENTINEL')]):
                with self.assertRaises(RuntimeError) as error:
                    qualification.guest('original operation')
            self.assertIs(error.exception, original)
            value = (qualification.root / 'readiness-failure.json').read_text()
            self.assertEqual(json.loads(value), {'diagnostic_failed': 'ValueError'})
            self.assertNotIn('PRIVATE_SENTINEL', value)

    def test_success_passes_through_without_diagnostic_or_new_file(self):
        qualification = object.__new__(subject.Qualification)
        with patch.object(subject.combined.Qualification, 'guest', return_value={'accepted': True}) as guest:
            self.assertEqual(qualification.guest('original operation'), {'accepted': True})
        guest.assert_called_once_with('original operation', 0)
        compile(subject.DIAGNOSTIC, '<actual-native-readiness-diagnostic>', 'exec')


if __name__ == '__main__':
    unittest.main()
