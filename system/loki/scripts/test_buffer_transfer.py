#!/usr/bin/env python3
"""Exercise complete pagination, exact labels and idempotent recovery boundaries."""

import copy
import hashlib
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from unittest.mock import Mock
from unittest.mock import MagicMock

import buffer_transfer as TRANSFER
import test_cold_recovery as cold_fixture


class BufferTransferTests(unittest.TestCase):
    def test_only_exact_attributed_owned_receipt_rejection_is_qualified(self):
        data = json.dumps({"synthetic": "receipt"}, sort_keys=True).encode()
        size = len(data)
        with patch.object(TRANSFER, "QUALIFIED_OWNED_LOG_BYTES", size), \
                patch.object(TRANSFER, "SECOND_CONTINUATION_RECEIPT_SHA256", hashlib.sha256(data).hexdigest()), \
                patch.object(TRANSFER.Path, "read_bytes", return_value=data):
            self.assertEqual(TRANSFER.qualified_owned_log_rejection(1, size)["records"], 1)
            for count, changed_size in ((2, size), (1, size + 1), (0, size)):
                with self.assertRaisesRegex(RuntimeError, "unqualified oversized"):
                    TRANSFER.qualified_owned_log_rejection(count, changed_size)
            with patch.object(TRANSFER.Path, "read_bytes", return_value=b"{}"):
                with self.assertRaisesRegex(RuntimeError, "protected native evidence"):
                    TRANSFER.qualified_owned_log_rejection(1, size)

    def test_owned_rejection_does_not_change_rate_limit_accounting(self):
        metrics = (b'loki_distributor_lines_received_total 10\n'
                   b'loki_discarded_samples_total{reason="rate_limited"} 2\n'
                   b'loki_discarded_samples_total{reason="line_too_long"} 1\n'
                   b'loki_discarded_bytes_total{reason="line_too_long"} 402891\n')
        with patch.object(TRANSFER.urllib.request, "urlopen", return_value=io.BytesIO(metrics)), \
                patch.object(TRANSFER, "qualified_owned_log_rejection", return_value={"records": 1}) as qualify:
            result = TRANSFER.source_accounting()
            self.assertEqual(result["accepted_records"], 7)
            self.assertEqual(result["rate_limited_attempts"], 2)
            self.assertEqual(result["qualified_owned_log_rejection"], {"records": 1})
            qualify.assert_called_once_with(1, 402891)

    def test_default_pages_are_bounded_without_changing_originals(self):
        rows = self.rows()
        with patch.object(TRANSFER, "query", return_value=rows) as query:
            result = list(TRANSFER.windows("synthetic", 0, 7))
        self.assertEqual(result, [(0, 7, rows)])
        self.assertEqual(query.call_args_list[0].args, ("synthetic", 0, 7, 500))
        self.assertEqual(query.call_args_list[1].kwargs, {"direction": "backward"})

    def test_checkpoint_count_requires_two_exact_reads_and_refuses_persistent_or_denied_reads(self):
        with patch.object(TRANSFER, "source_query_count", side_effect=[3, 5, 5]) as query, \
                patch.object(TRANSFER.time, "sleep"):
            self.assertEqual(TRANSFER.settled_source_count(1, 9, 5), 5)
            self.assertEqual(query.call_count, 3)
        with patch.object(TRANSFER, "source_query_count", return_value=3) as query, \
                patch.object(TRANSFER.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "did not converge"):
                TRANSFER.settled_source_count(1, 9, 5)
            self.assertEqual(query.call_count, 5)
        denied = urllib.error.HTTPError("https://synthetic.invalid", 403, "denied", {}, None)
        with patch.object(TRANSFER, "source_query_count", side_effect=denied) as query:
            with self.assertRaises(urllib.error.HTTPError):
                TRANSFER.settled_source_count(1, 9, 5)
            query.assert_called_once()

    def test_read_disconnect_subdivides_without_masking_persistent_or_security_failures(self):
        rows = self.rows()[:3]

        def read(_base, start, end, *_args, **_kwargs):
            if (start, end) == (0, 3):
                raise TRANSFER.http.client.RemoteDisconnected("synthetic closed response")
            return [row for row in rows if start <= row[1] <= end]

        with patch.object(TRANSFER, "query", side_effect=read):
            found = list(TRANSFER.windows(TRANSFER.SOURCE, 0, 3))
            self.assertEqual([row for _, _, page in found for row in page], rows)
            self.assertEqual([(a, b) for a, b, _ in found], [(0, 1), (2, 3)])
        with patch.object(TRANSFER, "query", side_effect=TRANSFER.http.client.RemoteDisconnected()) as query:
            with self.assertRaisesRegex(RuntimeError, "bounded interval subdivision"):
                list(TRANSFER.windows(TRANSFER.SOURCE, 0, 31))
            self.assertEqual(query.call_count, 4)
        denied = urllib.error.HTTPError("https://synthetic.invalid", 401, "denied", {}, None)
        with patch.object(TRANSFER, "query", side_effect=denied) as query:
            with self.assertRaises(urllib.error.HTTPError):
                list(TRANSFER.windows(TRANSFER.SOURCE, 0, 3))
            query.assert_called_once()

    def test_continuation_uses_the_accepted_second_checkpoint_hash(self):
        account = {"received_attempts": 8, "rate_limited_attempts": 1, "accepted_records": 7}
        prefix = {"start": 1, "end": 9, "source_accepted_records": 5}
        result = {"source_distinct_records": 2, "all_source_records_visible": False, "end": 12}
        with patch.object(TRANSFER, "SECOND_CONTINUATION_RECEIPT_SHA256", "b" * 64), \
                patch.object(TRANSFER.cold_recovery, "flush_old", return_value=8), \
                patch.object(TRANSFER, "source_accounting", return_value=account), \
                patch.object(TRANSFER, "continuation_prefix", return_value=prefix) as checkpoint, \
                patch.object(TRANSFER, "query", return_value=[({"job": "synthetic"}, 12, "original")]), \
                patch.object(TRANSFER, "source_query_count", side_effect=[7, 5, 7]), \
                patch.object(TRANSFER, "transfer", return_value=result), \
                patch.object(TRANSFER, "require_stage"), \
                patch.object(TRANSFER.cold_recovery, "metrics", return_value=(0, 8)), \
                patch.object(TRANSFER.cold_recovery, "write_verified") as write:
            root = MagicMock()
            TRANSFER.run_tail(root, "synthetic", 25, False, "continuation")
            checkpoint.assert_called_once_with(root, account, "synthetic", TRANSFER.SECOND_CONTINUATION_ATTEMPT)
            self.assertEqual(write.call_args.args[1]["prefix_receipt_sha256"], "b" * 64)

    def test_continuation_audit_ends_at_latest_actual_original(self):
        account = {"received_attempts": 8, "rate_limited_attempts": 1, "accepted_records": 7}
        prefix = {"start": 1, "end": 9, "source_accepted_records": 5}
        result = {"source_distinct_records": 2, "all_source_records_visible": False, "end": 12}
        with patch.object(TRANSFER.cold_recovery, "flush_old", return_value=8), \
                patch.object(TRANSFER, "source_accounting", return_value=account), \
                patch.object(TRANSFER, "continuation_prefix", return_value=prefix), \
                patch.object(TRANSFER, "query", return_value=[({"job": "synthetic"}, 12, "original")]) as query, \
                patch.object(TRANSFER.time, "time_ns", return_value=100), \
                patch.object(TRANSFER, "source_query_count", side_effect=[7, 5, 7]), \
                patch.object(TRANSFER, "transfer", return_value=result) as transfer, \
                patch.object(TRANSFER, "require_stage"), \
                patch.object(TRANSFER.cold_recovery, "metrics", return_value=(0, 8)), \
                patch.object(TRANSFER.cold_recovery, "write_verified") as write:
            TRANSFER.run_tail(MagicMock(), "synthetic", 16, False, "continuation")
            query.assert_called_once_with(TRANSFER.SOURCE, 10, 100 + 600 * 10**9,
                                          limit=1, direction="backward")
            transfer.assert_called_once_with(10, 12, False, None, max_record_age_ns=45 * 60 * 10**9)
            self.assertEqual(write.call_args.args[1]["end"], 12)

    def test_continuation_refuses_old_original_before_any_push(self):
        rows = self.rows()[:2]
        for now, accepted in ((100, True), (101, False)):
            with patch.object(TRANSFER, "windows", return_value=[(0, 4, rows)]), \
                    patch.object(TRANSFER, "observed", return_value=set()), \
                    patch.object(TRANSFER, "prove_missing", side_effect=lambda pending, *_: (pending, {})), \
                    patch.object(TRANSFER.time, "time_ns", return_value=now), \
                    patch.object(TRANSFER, "confirm_visible"), patch.object(TRANSFER, "push") as push:
                if accepted:
                    TRANSFER.transfer(0, 4, apply=True, max_record_age_ns=99)
                    push.assert_called_once_with(rows)
                else:
                    with self.assertRaisesRegex(RuntimeError, "qualified normal receiver age"):
                        TRANSFER.transfer(0, 4, apply=True, max_record_age_ns=99)
                    push.assert_not_called()

    def test_continuation_requires_hash_bound_complete_buffered_coverage(self):
        old = {"received_attempts": 6, "rate_limited_attempts": 1, "accepted_records": 5}
        new = {"received_attempts": 8, "rate_limited_attempts": 1, "accepted_records": 7}
        prefix = {"start": 1, "end": 4, "source_accepted_records": 3}
        windows = [{"start": 5, "end": 9, "source_distinct_records": 2, "source_sha256": "a" * 64}]
        audit = {"start": 5, "end": 9, "tail_distinct_records": 2, "windows": windows}
        covered = {"phase": "buffered-tail", "attempt": 15, "applied": True, "all_source_records_visible": True,
                   "frozen_tail_enumeration_complete": True, "target_uid": "synthetic",
                   "source_uid": TRANSFER.cold_recovery.BUFFER_POD_UID, "source_accounting": old,
                   "prefix_receipt_sha256": TRANSFER.PREFIX_RECEIPT_SHA256,
                   "start": 5, "end": 9, "source_distinct_records": 2, "prefix_distinct_records": 3,
                   "windows": windows, "missing_before": 2,
                   "target_counters_before": {"loki_distributor_lines_received_total": 100, "loki_discarded_samples_total": 2},
                   "target_counters_after": {"loki_distributor_lines_received_total": 102, "loki_discarded_samples_total": 2}}
        root = MagicMock()
        def check(value, account=new):
            data = json.dumps(value).encode(); root.__truediv__.return_value.read_bytes.return_value = data
            with patch.object(TRANSFER, "CONTINUATION_RECEIPT_SHA256", hashlib.sha256(data).hexdigest()), \
                    patch.object(TRANSFER, "tail_prefix", return_value=prefix), \
                    patch.object(TRANSFER, "tail_audit", return_value=audit), \
                    patch.object(TRANSFER, "settled_source_count", return_value=5):
                return TRANSFER.continuation_prefix(root, account, "synthetic")
        self.assertEqual(check(covered), {"start": 1, "end": 9, "source_accepted_records": 5})
        second = {**covered, "phase": "buffered-continuation", "attempt": 24,
                  "prefix_receipt_sha256": "c" * 64}
        data = json.dumps(second).encode()
        root.__truediv__.return_value.read_bytes.return_value = data
        original = TRANSFER.continuation_prefix
        with patch.object(TRANSFER, "CONTINUATION_RECEIPT_SHA256", "c" * 64), \
                patch.object(TRANSFER, "SECOND_CONTINUATION_RECEIPT_SHA256", hashlib.sha256(data).hexdigest()), \
                patch.object(TRANSFER, "continuation_prefix", return_value=prefix) as previous, \
                patch.object(TRANSFER, "tail_audit", return_value=audit) as read, \
                patch.object(TRANSFER, "settled_source_count", return_value=5):
            self.assertEqual(original(root, new, "synthetic", 24),
                             {"start": 1, "end": 9, "source_accepted_records": 5})
            previous.assert_called_once_with(root, old, "synthetic")
            read.assert_called_once_with(root, 24, "synthetic", old, prefix, "continuation", "c" * 64)
        with self.assertRaisesRegex(RuntimeError, "unqualified continuation checkpoint"):
            original(root, new, "synthetic", 19)
        for key, value in (("applied", False), ("all_source_records_visible", False), ("target_uid", "different"),
                           ("prefix_receipt_sha256", "wrong"), ("source_distinct_records", 1), ("end", 8)):
            changed = copy.deepcopy(covered); changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "coverage"):
                check(changed)
        changed = copy.deepcopy(covered); changed["target_counters_after"]["loki_discarded_samples_total"] = 3
        with self.assertRaisesRegex(RuntimeError, "coverage"):
            check(changed)
        with self.assertRaisesRegex(RuntimeError, "coverage"):
            check(covered, old)
        with patch.object(TRANSFER, "CONTINUATION_RECEIPT_SHA256", "wrong"), self.assertRaisesRegex(RuntimeError, "receipt changed"):
            TRANSFER.continuation_prefix(root, new, "synthetic")

    def test_continuation_apply_accepts_only_its_own_audit_and_checkpoint(self):
        account = {"received_attempts": 8, "rate_limited_attempts": 1, "accepted_records": 7}
        prefix = {"end": 9, "source_accepted_records": 5}
        audit = {"phase": "continuation", "applied": False, "tail_enumeration_complete": True,
                 "target_uid": "synthetic", "source_uid": TRANSFER.cold_recovery.BUFFER_POD_UID,
                 "source_accounting": account, "prefix_receipt_sha256": "b" * 64,
                 "start": 10, "end": 12, "tail_distinct_records": 2,
                 "windows": [{"start": 10, "end": 12, "source_distinct_records": 2, "source_sha256": "a" * 64}]}
        root = MagicMock(); root.__truediv__.return_value.read_bytes.return_value = json.dumps(audit).encode()
        self.assertEqual(TRANSFER.tail_audit(root, 17, "synthetic", account, prefix, "continuation", "b" * 64), audit)
        with self.assertRaisesRegex(RuntimeError, "fresh complete"):
            TRANSFER.tail_audit(root, 17, "synthetic", account, prefix, "tail", "b" * 64)
        with self.assertRaisesRegex(RuntimeError, "fresh complete"):
            TRANSFER.tail_audit(root, 17, "synthetic", account, prefix, "continuation", "c" * 64)

    def test_buffered_flush_only_follows_proven_missing_writes(self):
        rows = self.rows()[:2]
        existing = {TRANSFER.fingerprint(rows[0])}
        response = MagicMock()
        response.__enter__.return_value.status = 204
        events = []
        with patch.object(TRANSFER, "windows", return_value=[(0, 4, rows)]), \
                patch.object(TRANSFER, "observed", return_value=existing), \
                patch.object(TRANSFER, "prove_missing", side_effect=lambda pending, *_: (pending, {})), \
                patch.object(TRANSFER, "push", side_effect=lambda pending: events.append(("push", pending))), \
                patch.object(TRANSFER.urllib.request, "urlopen", side_effect=lambda *_args, **_kw: (events.append(("flush",)), response)[1]) as post, \
                patch.object(TRANSFER, "confirm_visible", side_effect=lambda *_args: events.append(("verify",))):
            TRANSFER.transfer(0, 4, apply=True, flush_after_push=True)
            self.assertEqual(events, [("push", rows[1:]), ("flush",), ("verify",)])
            self.assertEqual(post.call_args.args[0].full_url, TRANSFER.TARGET + "/flush")
            self.assertEqual(post.call_args.args[0].method, "POST")
        with patch.object(TRANSFER.urllib.request, "urlopen") as post, self.assertRaisesRegex(RuntimeError, "restricted"):
            TRANSFER.transfer(0, 4, flush_after_push=True)
        post.assert_not_called()

    def test_target_metric_contract_handles_tenant_labels_and_refuses_bad_counters(self):
        data = ("loki_distributor_lines_received_total{tenant=\"fake\"} 42\n"
                "loki_discarded_samples_total{reason=\"too_far_behind\",tenant=\"fake\"} 2\n"
                "loki_ingester_memory_chunks 0\nloki_ingester_memory_streams{tenant=\"fake\"} 0\n")
        with patch.object(TRANSFER.urllib.request, "urlopen", return_value=io.BytesIO(data.encode())):
            counters = TRANSFER.target_counters()
        self.assertEqual(counters["loki_distributor_lines_received_total"], 42)
        self.assertEqual(counters["loki_discarded_samples_total"], 2)
        self.assertEqual(counters["loki_ingester_memory_streams"], 0)
        for changed in (data.replace(" 42", " NaN"), data.replace(" 42", " 42.5"),
                        data.replace("loki_ingester_memory_streams", "unrelated_metric")):
            with self.subTest(data=changed), patch.object(TRANSFER.urllib.request, "urlopen", return_value=io.BytesIO(changed.encode())), self.assertRaises(RuntimeError):
                TRANSFER.target_counters()

    def test_buffered_tail_requires_removed_streams_and_exact_write_accounting(self):
        frozen = {"source_accounting": {"accepted_records": 5}}
        root = Mock()
        root.__truediv__ = Mock(return_value=Mock(read_bytes=Mock(return_value=json.dumps(frozen).encode())))
        prefix = {"start": 0, "source_accepted_records": 3}
        audit = {"start": 10, "end": 20, "tail_distinct_records": 2}
        before = {"loki_distributor_lines_received_total": 100, "loki_discarded_samples_total": 2,
                  "loki_ingester_memory_chunks": 0, "loki_ingester_memory_streams": 0}
        after = {**before, "loki_distributor_lines_received_total": 102}
        for changed, expected_error in ((after, None),
                ({**after, "loki_discarded_samples_total": 3}, "rejected"),
                ({**after, "loki_distributor_lines_received_total": 103}, "another writer"),
                ({**before, "loki_ingester_memory_streams": 1}, "removed every")):
            initial = changed if expected_error == "removed every" else before
            with patch.object(TRANSFER, "tail_prefix", return_value=prefix), \
                    patch.object(TRANSFER, "tail_audit", return_value=audit), \
                    patch.object(TRANSFER, "source_query_count", return_value=5), \
                    patch.object(TRANSFER.cold_recovery, "flush_old", return_value=100), \
                    patch.object(TRANSFER, "target_counters", side_effect=[initial, changed]), \
                    patch.object(TRANSFER, "transfer", return_value={"missing_before": 2, "source_distinct_records": 2}) as transfer, \
                    patch.object(TRANSFER, "require_stage") as stage, \
                    patch.object(TRANSFER.cold_recovery, "write_verified") as write:
                if expected_error:
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        TRANSFER.run_buffered_tail(root, "target", 15, True)
                    write.assert_not_called()
                    if expected_error == "removed every":
                        transfer.assert_not_called()
                else:
                    TRANSFER.run_buffered_tail(root, "target", 15, True)
                    transfer.assert_called_once_with(10, 20, True, audit, flush_after_push=True)
                    stage.assert_called_once_with("target", "buffered-tail")
                    self.assertFalse(write.call_args.args[1]["complete_source_quiescence"])
        with self.assertRaisesRegex(RuntimeError, "preceding complete"):
            TRANSFER.run_buffered_tail(root, "target", 15, False)
        with self.assertRaisesRegex(RuntimeError, "qualified checkpoint sequence"):
            TRANSFER.run_buffered_tail(root, "target", 19, True, "buffered-continuation")

    def test_read_only_presence_verification_resolves_underfill_without_any_push(self):
        rows = self.rows()[:3]
        with patch.object(TRANSFER, "windows", return_value=[(0, 4, rows)]), \
                patch.object(TRANSFER, "observed", return_value={TRANSFER.fingerprint(rows[0])}), \
                patch.object(TRANSFER, "prove_missing", return_value=([], {"strict": True})) as strict, \
                patch.object(TRANSFER, "push") as push:
            result = TRANSFER.transfer(0, 4, verify_presence=True)
            self.assertTrue(result["all_source_records_visible"])
            self.assertEqual(result["source_distinct_records"], 3)
            self.assertFalse(result["applied"])
            strict.assert_called_once_with(rows[1:], 0, 4)
            push.assert_not_called()
        with patch.object(TRANSFER, "push") as push:
            with self.assertRaisesRegex(RuntimeError, "cannot write"):
                TRANSFER.transfer(0, 4, apply=True, verify_presence=True)
            with self.assertRaisesRegex(RuntimeError, "read-only"):
                TRANSFER.run("synthetic", "prefix", 13, True)
            push.assert_not_called()

    def test_prefix_changed_accounting_cannot_write_a_receipt(self):
        accounting = {"received_attempts": 6, "rate_limited_attempts": 1, "accepted_records": 5}
        prefix = {"start": 1, "end": 4, "source_accepted_records": 3,
                  "source_received_counter": 4, "source_rate_limited_attempts": 1}
        with patch.object(TRANSFER, "source_accounting", side_effect=[accounting, {**accounting, "accepted_records": 6}]), \
                patch.object(TRANSFER, "tail_prefix", return_value=prefix), \
                patch.object(TRANSFER, "preserved_source_audit"), patch.object(TRANSFER, "frozen_source_audit"), \
                patch.object(TRANSFER, "transfer", return_value={"source_distinct_records": 3}) as compare, \
                patch.object(TRANSFER, "require_stage"), patch.object(TRANSFER.cold_recovery, "write_verified") as write:
            with self.assertRaisesRegex(RuntimeError, "prefix changed"):
                TRANSFER.run_prefix(Mock(), "synthetic", 13)
            self.assertTrue(compare.call_args.kwargs["verify_presence"])
            self.assertNotIn("apply", compare.call_args.kwargs)
            write.assert_not_called()

    def rows(self):
        return [({"job": "synthetic", "stream": "stdout"}, n, "original-" + str(n)) for n in range(1, 7)]

    def test_tail_prefix_requires_exact_receipt_and_unchanged_independent_prefix_count(self):
        prefix = {"applied": True, "all_source_records_visible": True, "enumeration_complete": True,
                  "complete_source_quiescence": True, "source_uid": TRANSFER.cold_recovery.BUFFER_POD_UID,
                  "frozen_source_sha256": TRANSFER.FROZEN_SOURCE_SHA256,
                  "source_received_counter": 4, "source_rate_limited_attempts": 1,
                  "source_accepted_records": 3, "start": 1, "end": 4}
        data = json.dumps(prefix).encode()
        root = Mock()
        root.__truediv__ = Mock(return_value=Mock(read_bytes=Mock(return_value=data)))
        accounting = {"received_attempts": 6, "rate_limited_attempts": 1, "accepted_records": 5}
        with patch.object(TRANSFER, "PREFIX_RECEIPT_SHA256", hashlib.sha256(data).hexdigest()), \
                patch.object(TRANSFER, "preserved_source_audit"), patch.object(TRANSFER, "frozen_source_audit"), \
                patch.object(TRANSFER, "source_query_count", return_value=3) as count:
            self.assertEqual(TRANSFER.tail_prefix(root, accounting), prefix)
            count.return_value = 4
            with self.assertRaisesRegex(RuntimeError, "independent count"):
                TRANSFER.tail_prefix(root, accounting)
            root.__truediv__.return_value.read_bytes.return_value = data + b" "
            with self.assertRaisesRegex(RuntimeError, "receipt changed"):
                TRANSFER.tail_prefix(root, accounting)

    def test_tail_apply_requires_fresh_audit_identity_counters_and_nonoverlapping_windows(self):
        accounting = {"received_attempts": 6, "rate_limited_attempts": 1, "accepted_records": 5}
        prefix = {"end": 4, "source_accepted_records": 3}
        audit = {"phase": "tail", "applied": False, "tail_enumeration_complete": True,
                 "target_uid": "synthetic", "source_uid": TRANSFER.cold_recovery.BUFFER_POD_UID,
                 "source_accounting": accounting, "prefix_receipt_sha256": TRANSFER.PREFIX_RECEIPT_SHA256,
                 "start": 5, "end": 9, "tail_distinct_records": 2,
                 "windows": [{"start": 5, "end": 9, "source_distinct_records": 2,
                              "source_sha256": "a" * 64}]}
        root = Mock()
        root.__truediv__ = Mock(return_value=Mock())
        def check(value):
            root.__truediv__.return_value.read_bytes.return_value = json.dumps(value).encode()
            return TRANSFER.tail_audit(root, 12, "synthetic", accounting, prefix)
        self.assertEqual(check(audit), audit)
        for key, value in (("applied", True), ("target_uid", "changed"), ("source_uid", "changed"),
                           ("source_accounting", {}), ("tail_distinct_records", 1),
                           ("tail_enumeration_complete", False), ("start", 4)):
            changed = copy.deepcopy(audit); changed[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                check(changed)
        changed = copy.deepcopy(audit)
        changed["windows"] *= 2; changed["windows"][0]["source_distinct_records"] = 1
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            check(changed)

    def test_tail_incomplete_enumeration_cannot_write_acceptance_receipt(self):
        accounting = {"received_attempts": 6, "rate_limited_attempts": 1, "accepted_records": 5}
        prefix = {"start": 1, "end": 4, "source_accepted_records": 3}
        with patch.object(TRANSFER.cold_recovery, "flush_old", return_value=6), \
                patch.object(TRANSFER, "source_accounting", return_value=accounting), \
                patch.object(TRANSFER, "tail_prefix", return_value=prefix), \
                patch.object(TRANSFER, "source_query_count", return_value=5), \
                patch.object(TRANSFER, "transfer", return_value={"source_distinct_records": 1}), \
                patch.object(TRANSFER.cold_recovery, "write_verified") as write:
            with self.assertRaisesRegex(RuntimeError, "every new accepted original"):
                TRANSFER.run_tail(Mock(), "synthetic", 11, False)
            write.assert_not_called()

    def test_full_pages_split_without_losing_boundary_records(self):
        rows = self.rows()

        def query(base, start, end, limit, direction="forward"):
            matching = [r for r in rows if start <= r[1] <= end]
            return (matching if direction == "forward" else list(reversed(matching)))[:limit]

        with patch.object(TRANSFER, "query", side_effect=query):
            result = [r for _, _, items in TRANSFER.windows("source", 0, 7, limit=3) for r in items]
        self.assertEqual(result, rows)

    def test_underfilled_merged_page_requires_both_traversals_to_agree(self):
        rows = self.rows()

        def query(base, start, end, limit, direction="forward"):
            matching = [r for r in rows if start <= r[1] <= end]
            matching = matching if direction == "forward" else list(reversed(matching))
            return matching[:2] if end - start > 3 else matching

        with patch.object(TRANSFER, "query", side_effect=query):
            found = [r for _, _, page in TRANSFER.windows("source", 0, 7, limit=7) for r in page]
        self.assertEqual(found, rows)

    def test_unprovable_single_timestamp_page_is_refused(self):
        rows = [({"job": "synthetic"}, 5, str(n)) for n in range(3)]
        with patch.object(TRANSFER, "query", return_value=rows):
            with self.assertRaisesRegex(RuntimeError, "one timestamp"):
                list(TRANSFER.windows("source", 5, 5, limit=3))

    def test_fingerprint_preserves_all_labels_and_content(self):
        stdout = ({"job": "synthetic", "stream": "stdout"}, 1, "same")
        stderr = ({"job": "synthetic", "stream": "stderr"}, 1, "same")
        other = ({"job": "other", "stream": "stdout"}, 1, "same")
        self.assertEqual(len({TRANSFER.fingerprint(r) for r in (stdout, stderr, other)}), 3)
        self.assertNotEqual(TRANSFER.fingerprint(stdout), TRANSFER.fingerprint((stdout[0], 1, "different")))

    def test_received_attempts_discount_only_explicit_rate_limit_refusals(self):
        metrics = (b'loki_distributor_lines_received_total{tenant="synthetic"} 4349882\n'
                   b'loki_discarded_samples_total{reason="rate_limited",tenant="synthetic"} 5249\n')
        with patch.object(TRANSFER.urllib.request, "urlopen", return_value=io.BytesIO(metrics)):
            self.assertEqual(TRANSFER.source_accounting(), {"received_attempts": 4349882,
                             "rate_limited_attempts": 5249, "accepted_records": 4344633})
        invalid = [metrics.replace(b"rate_limited", b"too_old"),
                   metrics.replace(b"4349882", b"NaN"), metrics.replace(b"5249", b"-1"),
                   metrics.replace(b"5249", b"1.5"), metrics.replace(b"5249", b"4349883"),
                   metrics.splitlines(keepends=True)[1]]
        for value in invalid:
            with self.subTest(metrics=value), patch.object(TRANSFER.urllib.request, "urlopen",
                    return_value=io.BytesIO(value)), self.assertRaises(RuntimeError):
                TRANSFER.source_accounting()

    def test_independent_source_count_requires_single_integral_vector(self):
        result = {"status": "success", "data": {"resultType": "vector",
                  "result": [{"metric": {}, "value": [10, "4344633"]}]}}
        with patch.object(TRANSFER, "get_json", return_value=result) as read:
            self.assertEqual(TRANSFER.source_query_count(5 * 10**9, 10 * 10**9), 4344633)
            self.assertIn("%5B7s%5D", read.call_args.args[0])
            self.assertIn("time=10000000000", read.call_args.args[0])
        for value in ("NaN", "-1", "1.5", "0"):
            changed = copy.deepcopy(result)
            changed["data"]["result"][0]["value"][1] = value
            with patch.object(TRANSFER, "get_json", return_value=changed), self.assertRaises(RuntimeError):
                TRANSFER.source_query_count(0, 10**9)
        for changed in ({"status": "error"}, {"status": "success", "data": {
                "resultType": "vector", "result": []}}):
            with patch.object(TRANSFER, "get_json", return_value=changed), self.assertRaises(RuntimeError):
                TRANSFER.source_query_count(0, 10**9)

    def test_audit_never_pushes_and_apply_sends_only_missing_originals(self):
        rows = self.rows()[:3]
        existing = {TRANSFER.fingerprint(rows[1])}
        all_rows = {TRANSFER.fingerprint(r) for r in rows}
        original = copy.deepcopy(rows)
        with patch.object(TRANSFER, "windows", return_value=[(0, 4, rows)]), \
                patch.object(TRANSFER, "observed", return_value=existing), patch.object(TRANSFER, "prove_missing", side_effect=lambda rows, *_: (rows, {})), patch.object(TRANSFER, "push") as push:
            result = TRANSFER.transfer(0, 4)
            push.assert_not_called()
        self.assertEqual(result["missing_before"], 2)
        self.assertFalse(result["all_source_records_visible"])
        with patch.object(TRANSFER, "windows", return_value=[(0, 4, rows)]), \
                patch.object(TRANSFER, "observed", side_effect=[existing, all_rows]), \
                patch.object(TRANSFER, "prove_missing", side_effect=lambda rows, *_: (rows, {})), patch.object(TRANSFER, "push") as push:
            result = TRANSFER.transfer(0, 4, apply=True)
            push.assert_called_once_with([rows[0], rows[2]])
        self.assertTrue(result["all_source_records_visible"])
        self.assertEqual(rows, original)

    def test_uncertain_post_is_not_retried_and_preserves_original_payload(self):
        rows = [({"job": "synthetic", "stream": "stderr"}, 123, "original Unicode \u03bb")]
        with patch.object(TRANSFER.urllib.request, "urlopen", side_effect=urllib.error.URLError("synthetic interrupted reply")) as send:
            with self.assertRaisesRegex(RuntimeError, "outcome uncertain"):
                TRANSFER.push(rows)
        self.assertEqual(send.call_count, 1)
        body = json.loads(send.call_args.args[0].data)
        self.assertEqual(body, {"streams": [{"stream": rows[0][0], "values": [["123", rows[0][2]]]}]})

    def test_failed_visibility_proof_never_blindly_reposts(self):
        rows = self.rows()[:1]
        with patch.object(TRANSFER, "windows", return_value=[(0, 2, rows)]), \
                patch.object(TRANSFER, "observed", return_value=set()), patch.object(TRANSFER, "prove_missing", side_effect=lambda rows, *_: (rows, {})), patch.object(TRANSFER, "push") as push, \
                patch.object(TRANSFER.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "not all query-visible"):
                TRANSFER.transfer(0, 2, apply=True)
            self.assertEqual(push.call_count, 1)

    def test_http_refusal_is_classified_without_exporting_body_or_retrying(self):
        error = urllib.error.HTTPError("http://synthetic", 400, "private explanation", {},
                                       io.BytesIO(b"entry too far behind: private original log"))
        with patch.object(TRANSFER.urllib.request, "urlopen", side_effect=error) as send, \
                patch.object(TRANSFER.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400; too_far_behind") as caught:
                TRANSFER.push(self.rows()[:1])
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(send.call_count, 1)

    def test_delayed_visibility_retries_only_reads(self):
        rows = self.rows()[:1]
        expected = {TRANSFER.fingerprint(rows[0])}
        with patch.object(TRANSFER, "windows", return_value=[(0, 2, rows)]), \
                patch.object(TRANSFER, "observed", side_effect=[set(), set(), expected]) as read, \
                patch.object(TRANSFER, "prove_missing", side_effect=lambda rows, *_: (rows, {})), patch.object(TRANSFER, "push") as push, patch.object(TRANSFER.time, "sleep") as sleep:
            self.assertTrue(TRANSFER.transfer(0, 2, apply=True)["all_source_records_visible"])
        self.assertEqual(read.call_count, 3)
        push.assert_called_once_with(rows)
        sleep.assert_called_once_with(2)

    def test_replay_refuses_receiver_label_transformation(self):
        config = "limits_config:\n  shard_streams:\n    enabled: false\n    time_sharding_enabled: false\nserver:\n"
        with patch.object(TRANSFER.urllib.request, "urlopen", return_value=io.BytesIO(config.encode())):
            TRANSFER.require_unsharded()
        for changed in (config.replace("enabled: false", "enabled: true", 1),
                        config.replace("time_sharding_enabled: false", "time_sharding_enabled: true"), "server:\n"):
            with self.subTest(config=changed), patch.object(TRANSFER.urllib.request, "urlopen",
                    return_value=io.BytesIO(changed.encode())), self.assertRaisesRegex(RuntimeError, "transform"):
                TRANSFER.require_unsharded()

    def test_query_rejects_out_of_window_and_invalid_results(self):
        values = [
            {"status": "error"},
            {"status": "success", "data": {"resultType": "streams", "result": [
                {"stream": {"job": "synthetic"}, "values": [["9", "outside"]]}]}},
            {"status": "success", "data": {"resultType": "streams", "result": [
                {"stream": {"job": 7}, "values": [["1", "invalid-label"]]}]}},
        ]
        for value in values:
            with self.subTest(value=value), patch.object(TRANSFER, "get_json", return_value=value):
                with self.assertRaises(RuntimeError):
                    TRANSFER.query("source", 0, 2)

    def test_query_converts_inclusive_end_to_exclusive_http_end(self):
        value = {"status": "success", "data": {"resultType": "streams", "result": []}}
        with patch.object(TRANSFER, "get_json", return_value=value) as read:
            TRANSFER.query("source", 5, 5)
        self.assertIn("start=5&end=6&", read.call_args.args[0])

    def test_canonical_windows_require_original_hashes_and_append_disjoint_tail(self):
        rows = self.rows()[:2]
        checksum = hashlib.sha256("\n".join(sorted(TRANSFER.fingerprint(r) for r in rows)).encode()).hexdigest()
        audit = {"start": 0, "end": 3, "windows": [{"start": 0, "end": 3,
                 "source_distinct_records": 2, "source_sha256": checksum}]}
        with patch.object(TRANSFER, "query", return_value=rows), \
                patch.object(TRANSFER, "windows", return_value=[(4, 7, [])]) as tail:
            self.assertEqual(list(TRANSFER.source_windows(0, 7, audit)), [(0, 3, rows), (4, 7, [])])
            tail.assert_called_once_with(TRANSFER.SOURCE, 4, 7)
        with patch.object(TRANSFER, "query", return_value=rows[:1]), self.assertRaisesRegex(RuntimeError, "no longer matches"):
            list(TRANSFER.source_windows(0, 3, audit))
        with self.assertRaisesRegex(RuntimeError, "range changed"):
            list(TRANSFER.source_windows(1, 3, audit))

    def test_preserved_audit_requires_exact_bytes_and_complete_received_count(self):
        audit = {"complete_source_quiescence": True, "applied": False,
                 "source_uid": TRANSFER.cold_recovery.BUFFER_POD_UID,
                 "source_distinct_records": 2, "source_received_counter": 2,
                 "windows": [{"source_distinct_records": 2}]}
        root = Mock()
        root.__truediv__ = Mock(return_value=Mock())
        data = json.dumps(audit).encode()
        root.__truediv__.return_value.read_bytes.return_value = data
        with patch.object(TRANSFER, "SOURCE_AUDIT_SHA256", hashlib.sha256(data).hexdigest()):
            self.assertEqual(TRANSFER.preserved_source_audit(root), audit)
            root.__truediv__.return_value.read_bytes.return_value = data + b" "
            with self.assertRaisesRegex(RuntimeError, "audit changed"):
                TRANSFER.preserved_source_audit(root)
        audit["source_received_counter"] = 3
        data = json.dumps(audit).encode()
        root.__truediv__.return_value.read_bytes.return_value = data
        with patch.object(TRANSFER, "SOURCE_AUDIT_SHA256", hashlib.sha256(data).hexdigest()), \
                self.assertRaisesRegex(RuntimeError, "complete originals"):
            TRANSFER.preserved_source_audit(root)

    def test_apply_absence_requires_empty_aggregate_or_correlated_exact_timestamp_reads(self):
        rows = self.rows()[:1]
        with patch.object(TRANSFER, "query_count", return_value=0), patch.object(TRANSFER, "query") as read:
            missing, proof = TRANSFER.prove_missing(rows, 0, 2)
            self.assertEqual(missing, rows)
            self.assertTrue(proof["target_empty_aggregate"])
            read.assert_not_called()
        for target, expected in (([], rows), (rows, [])):
            with patch.object(TRANSFER, "query_count", return_value=3), \
                    patch.object(TRANSFER, "stream_presence", return_value=(set(), False)), \
                    patch.object(TRANSFER, "query", side_effect=[rows, target, target]) as read:
                missing, proof = TRANSFER.prove_missing(rows, 0, 2)
                self.assertEqual(missing, expected)
                self.assertEqual(proof["targeted_presence_probes"], 3)
                self.assertEqual(read.call_args_list[0].args, (TRANSFER.SOURCE, 1, 1))
                self.assertEqual(read.call_args_list[0].kwargs["selector"], '{job="synthetic",stream="stdout"}')
        for replies in (([], [], []), (rows, rows, []), (rows, rows * 5000, rows * 5000)):
            with patch.object(TRANSFER, "query_count", return_value=1), \
                    patch.object(TRANSFER, "stream_presence", return_value=(set(), False)), \
                    patch.object(TRANSFER, "query", side_effect=replies), self.assertRaisesRegex(RuntimeError, "unproven"):
                TRANSFER.prove_missing(rows, 0, 2)

    def test_stream_aggregate_count_proves_complete_strict_interior(self):
        rows = [({"job": "synthetic"}, t * 10**9, str(t)) for t in (4, 5)]
        selector = '{job="synthetic"}'
        with patch.object(TRANSFER, "query_count", return_value=2) as count, \
                patch.object(TRANSFER, "query", side_effect=[rows, list(reversed(rows))]) as read:
            visible, complete = TRANSFER.stream_presence(selector, 5 * 10**9, 6 * 10**9)
            self.assertTrue(complete)
            self.assertEqual(visible, {TRANSFER.fingerprint(r) for r in rows})
            count.assert_called_once_with(TRANSFER.TARGET, 5 * 10**9, 6 * 10**9,
                                         allow_empty=True, selector=selector)
            self.assertEqual(read.call_args_list[0].args, (TRANSFER.TARGET, 3 * 10**9 - 1, 7 * 10**9 + 1))
        with patch.object(TRANSFER, "query_count", return_value=0), patch.object(TRANSFER, "query") as read:
            self.assertEqual(TRANSFER.stream_presence(selector, 5 * 10**9, 6 * 10**9), (set(), True))
            read.assert_not_called()

    def test_stream_completeness_refuses_underfill_duplicates_caps_boundaries_and_count_mismatch(self):
        rows = [({"job": "synthetic"}, t * 10**9, str(t)) for t in (4, 5)]
        boundary = [({"job": "synthetic"}, t * 10**9, str(t)) for t in (3, 7)]
        cases = [(2, rows[:1], rows[:1]), (2, rows, rows[:1]),
                 (2, rows[:1] * 2, rows[:1] * 2), (2, rows * 2500, rows * 2500),
                 (2, boundary, boundary), (1, rows, rows)]
        for count, forward, backward in cases:
            with self.subTest(count=count, page_lengths=(len(forward), len(backward))), \
                    patch.object(TRANSFER, "query_count", return_value=count), \
                    patch.object(TRANSFER, "query", side_effect=[forward, backward]):
                self.assertFalse(TRANSFER.stream_presence('{job="synthetic"}', 5 * 10**9, 6 * 10**9)[1])

    def test_complete_stream_proof_skips_point_reads_and_incomplete_proof_keeps_strict_fallback(self):
        rows = self.rows()[:2]
        first = {TRANSFER.fingerprint(rows[0])}
        with patch.object(TRANSFER, "query_count", return_value=2), \
                patch.object(TRANSFER, "stream_presence", return_value=(first, True)), \
                patch.object(TRANSFER, "query") as read:
            missing, proof = TRANSFER.prove_missing(rows, 0, 3)
            self.assertEqual(missing, rows[1:])
            self.assertEqual(proof["complete_stream_enumerations"], 1)
            self.assertEqual(proof["already_present"], 1)
            self.assertEqual(proof["targeted_presence_probes"], 0)
            read.assert_not_called()
        with patch.object(TRANSFER, "query_count", return_value=2), \
                patch.object(TRANSFER, "stream_presence", return_value=(first, False)), \
                patch.object(TRANSFER, "query", side_effect=[rows[1:], [], []]) as read:
            missing, proof = TRANSFER.prove_missing(rows, 0, 3)
            self.assertEqual(missing, rows[1:])
            self.assertEqual(proof["targeted_presence_probes"], 3)
            self.assertEqual(read.call_args_list[0].args, (TRANSFER.SOURCE, 2, 2))

    def test_target_zero_aggregate_rejects_failed_or_invalid_evidence(self):
        empty = {"status": "success", "data": {"resultType": "vector", "result": []}}
        with patch.object(TRANSFER, "get_json", return_value=empty) as read:
            self.assertEqual(TRANSFER.query_count(TRANSFER.TARGET, 0, 2, allow_empty=True), 0)
            self.assertIn("time=1000000002", read.call_args.args[0])
            with self.assertRaises(RuntimeError):
                TRANSFER.source_query_count(0, 2)
        for invalid in ({"status": "error"}, {"status": "success", "data": {"resultType": "vector"}},
                        {"status": "success", "data": {"resultType": "vector", "result": {}}}):
            with patch.object(TRANSFER, "get_json", return_value=invalid), self.assertRaises(RuntimeError):
                TRANSFER.query_count(TRANSFER.TARGET, 0, 2, allow_empty=True)

    def test_frozen_tail_unions_underfilled_directions_but_requires_exact_hash(self):
        rows = self.rows()
        checksum = hashlib.sha256("\n".join(sorted(TRANSFER.fingerprint(r) for r in rows)).encode()).hexdigest()
        audit = {"start": 0, "end": 7, "windows": [{"start": 0, "end": 7,
                 "source_distinct_records": 6, "source_sha256": checksum, "bidirectional": True}]}
        with patch.object(TRANSFER, "query", side_effect=[rows[:4], rows[2:]]):
            found = list(TRANSFER.source_windows(0, 7, audit))
        self.assertEqual({TRANSFER.fingerprint(r) for r in found[0][2]},
                         {TRANSFER.fingerprint(r) for r in rows})
        with patch.object(TRANSFER, "query", side_effect=[rows[:2], rows[:2]]), \
                self.assertRaisesRegex(RuntimeError, "no longer matches"):
            list(TRANSFER.source_windows(0, 7, audit))

    def test_frozen_proof_binds_original_anchor_identity_accounting_and_intervals(self):
        window = {"start": 0, "end": 3, "source_distinct_records": 2,
                  "source_sha256": "a" * 64, "bidirectional": False, "refinement_factor": 1}
        original = {"start": 0, "end": 3, "windows": [copy.deepcopy(window)]}
        accounting = {"accepted_records": 2, "received_attempts": 3, "rate_limited_attempts": 1}
        audit = {"format": 1, "source_uid": TRANSFER.cold_recovery.BUFFER_POD_UID,
                 "claim_uid": TRANSFER.cold_recovery.BUFFER_CLAIM_UID,
                 "original_anchor_sha256": TRANSFER.SOURCE_AUDIT_SHA256,
                 "source_accepted_records": 2, "source_received_attempts": 3,
                 "source_rate_limited_attempts": 1, "start": 0, "end": 3, "windows": [window]}
        def check(value):
            data = json.dumps(value).encode()
            with patch.object(TRANSFER, "FROZEN_SOURCE_SHA256", hashlib.sha256(data).hexdigest()):
                return TRANSFER.frozen_source_audit(original, accounting, Mock(read_bytes=Mock(return_value=data)))
        self.assertEqual(check(audit), audit)
        for key, value in (("source_uid", "other"), ("claim_uid", "other"),
                           ("source_accepted_records", 3), ("source_received_attempts", 4),
                           ("source_rate_limited_attempts", 2), ("original_anchor_sha256", "b" * 64)):
            changed = copy.deepcopy(audit)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                check(changed)
        for key, value in (("start", 1), ("end", 4), ("source_distinct_records", 1),
                           ("source_sha256", "b" * 64), ("bidirectional", True), ("refinement_factor", 4)):
            changed = copy.deepcopy(audit)
            changed["windows"][0][key] = value
            with self.subTest(window=key), self.assertRaises(RuntimeError):
                check(changed)
        with self.assertRaisesRegex(RuntimeError, "proof changed"):
            TRANSFER.frozen_source_audit(original, accounting, Mock(read_bytes=Mock(return_value=b"changed")))

    def test_stage_guard_binds_both_pods_services_claims_images_and_collector_route(self):
        fixture = cold_fixture.ColdRecoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.claim["metadata"]["uid"] = TRANSFER.CLAIM_UID
        selector = {"app.kubernetes.io/name": "loki", "app.kubernetes.io/instance": "loki",
                    "app.kubernetes.io/component": "single-binary"}
        fixture.source_pod["metadata"].update(name="loki-supported-0", uid="target", labels=selector)
        fixture.source_pod["status"] = {"containerStatuses": [{"ready": True,
            "imageID": "docker.io/grafana/loki@" + TRANSFER.IMAGE_DIGEST}]}
        fixture.buffer["metadata"]["labels"] = {"app.kubernetes.io/name": "loki-cutover-buffer"}
        fixture.buffer["spec"]["volumes"] = [{"name": "data", "persistentVolumeClaim": {"claimName": "loki-cutover-buffer"}}]
        fixture.buffer["status"]["containerStatuses"][0]["imageID"] = "docker.io/grafana/loki@" + TRANSFER.IMAGE_DIGEST
        services = {"loki": selector, "loki-cutover-buffer": {"app.kubernetes.io/name": "loki-cutover-buffer"}}

        def api(path):
            if "/services/" in path:
                return {"spec": {"selector": services[path.rsplit("/", 1)[-1]]}}
            return fixture.api(path)

        with patch.object(TRANSFER.cold_recovery, "api", side_effect=api):
            TRANSFER.require_stage("target", "bulk")
            with self.assertRaises(RuntimeError):
                TRANSFER.require_stage("wrong-target", "bulk")
            with self.assertRaises(RuntimeError):
                TRANSFER.require_stage("target", "final")
            fixture.pods.append({"metadata": {"uid": "other-consumer"}, "status": {},
                                 "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "loki-data"}}]}})
            with self.assertRaises(RuntimeError):
                TRANSFER.require_stage("target", "bulk")
            fixture.pods.pop()
            services["loki"] = services["loki-cutover-buffer"]
            with self.assertRaises(RuntimeError):
                TRANSFER.require_stage("target", "bulk")


if __name__ == "__main__":
    unittest.main()
