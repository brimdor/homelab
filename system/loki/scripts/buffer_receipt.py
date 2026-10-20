#!/usr/bin/env python3
"""Verify the persisted read-only continuation receipt without mounting originals."""

import argparse
import hashlib
import json
from pathlib import Path

import buffer_transfer
import cold_recovery


RECEIPT = Path('/recovery/cutover-transfer/continuation-30.json')


def verify(target_uid, expected_sha256):
    raw = RECEIPT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RuntimeError('persisted continuation receipt hash differs')
    value = json.loads(raw)
    windows = value['windows']
    if not (value['phase'] == 'continuation' and value['attempt'] == 30 and
            value['applied'] is False and value['all_tail_records_visible'] is True and
            value['missing_before'] == 0 and value['tail_enumeration_complete'] is True and
            value['complete_source_quiescence'] is True and value['target_uid'] == target_uid and
            value['source_uid'] == cold_recovery.BUFFER_POD_UID and
            value['prefix_receipt_sha256'] == buffer_transfer.SECOND_CONTINUATION_RECEIPT_SHA256 and
            value['prefix_distinct_records'] == 7090404 and value['tail_distinct_records'] == 277756 and
            value['source_query_count'] == value['source_accounting']['accepted_records'] == 7368160 and
            len(windows) == 834 and sum(w['source_distinct_records'] for w in windows) == 277756 and
            all(w['missing_before'] == 0 for w in windows)):
        raise RuntimeError('persisted continuation receipt lacks the exact accepted coverage')
    buffer_transfer.require_stage(target_uid, 'continuation')
    if (buffer_transfer.source_accounting() != value['source_accounting'] or
            cold_recovery.metrics(buffer_transfer.SOURCE) != (0, 7373410) or RECEIPT.read_bytes() != raw):
        raise RuntimeError('source accounting or protected receipt changed during verification')
    return {'receipt_sha256': expected_sha256, 'attempt': 30, 'missing_originals': 0,
            'tail_originals': 277756, 'full_source_originals': 7368160,
            'target_uid': target_uid, 'source_uid': value['source_uid'], 'persisted_readback': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-uid', required=True)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.target_uid, args.expected_sha256)), flush=True)
