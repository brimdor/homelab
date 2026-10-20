#!/usr/bin/env python3
"""Persisted byte identity and complete coverage must precede live evidence reads."""

import hashlib
import json
import unittest
from unittest.mock import patch

import buffer_receipt as subject


class ReceiptTests(unittest.TestCase):
    def fixture(self):
        return {'phase': 'continuation', 'attempt': 30, 'applied': False,
                'all_tail_records_visible': True, 'missing_before': 0, 'tail_enumeration_complete': True,
                'complete_source_quiescence': True, 'target_uid': 'target',
                'source_uid': subject.cold_recovery.BUFFER_POD_UID,
                'prefix_receipt_sha256': subject.buffer_transfer.SECOND_CONTINUATION_RECEIPT_SHA256,
                'prefix_distinct_records': 7090404, 'tail_distinct_records': 277756,
                'source_query_count': 7368160, 'source_accounting': {'accepted_records': 7368160},
                'windows': [{'source_distinct_records': 277756, 'missing_before': 0}] +
                           [{'source_distinct_records': 0, 'missing_before': 0} for _ in range(833)]}

    def test_matching_receipt_and_unchanged_live_evidence(self):
        value = self.fixture();raw = json.dumps(value).encode();sha = hashlib.sha256(raw).hexdigest()
        with patch.object(subject.Path, 'read_bytes', return_value=raw), \
                patch.object(subject.buffer_transfer, 'require_stage') as stage, \
                patch.object(subject.buffer_transfer, 'source_accounting', return_value=value['source_accounting']), \
                patch.object(subject.cold_recovery, 'metrics', return_value=(0, 7373410)):
            self.assertTrue(subject.verify('target', sha)['persisted_readback'])
            stage.assert_called_once_with('target', 'continuation')
            with patch.object(subject.cold_recovery, 'metrics', return_value=(1, 7373410)):
                with self.assertRaises(RuntimeError):
                    subject.verify('target', sha)
            with patch.object(subject.Path, 'read_bytes', side_effect=[raw, raw + b' ']):
                with self.assertRaises(RuntimeError):
                    subject.verify('target', sha)

    def test_changed_bytes_target_write_or_missing_coverage_refuse_before_api(self):
        with patch.object(subject.buffer_transfer, 'require_stage') as stage:
            for changed in ({}, {'applied': True}, {'missing_before': 1}, {'target_uid': 'foreign'},
                            {'tail_distinct_records': 1}):
                value = {**self.fixture(), **changed};raw = json.dumps(value).encode()
                sha = '0' * 64 if not changed else hashlib.sha256(raw).hexdigest()
                with patch.object(subject.Path, 'read_bytes', return_value=raw), self.assertRaises(RuntimeError):
                    subject.verify('target', sha)
            stage.assert_not_called()


if __name__ == '__main__':
    unittest.main()
