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

import buffer_transfer as TRANSFER
import test_cold_recovery as cold_fixture


class BufferTransferTests(unittest.TestCase):
    def rows(self):
        return [({"job": "synthetic", "stream": "stdout"}, n, "original-" + str(n)) for n in range(1, 7)]

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
                patch.object(TRANSFER, "observed", return_value=existing), patch.object(TRANSFER, "push") as push:
            result = TRANSFER.transfer(0, 4)
            push.assert_not_called()
        self.assertEqual(result["missing_before"], 2)
        self.assertFalse(result["all_source_records_visible"])
        with patch.object(TRANSFER, "windows", return_value=[(0, 4, rows)]), \
                patch.object(TRANSFER, "observed", side_effect=[existing, all_rows]), \
                patch.object(TRANSFER, "push") as push:
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
                patch.object(TRANSFER, "observed", return_value=set()), patch.object(TRANSFER, "push") as push, \
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
                patch.object(TRANSFER, "push") as push, patch.object(TRANSFER.time, "sleep") as sleep:
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
