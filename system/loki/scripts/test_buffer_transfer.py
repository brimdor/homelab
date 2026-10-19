#!/usr/bin/env python3
"""Exercise complete pagination, exact labels and idempotent recovery boundaries."""

import copy
import json
import unittest
import urllib.error
from unittest.mock import patch

import buffer_transfer as TRANSFER
import test_cold_recovery as cold_fixture


class BufferTransferTests(unittest.TestCase):
    def rows(self):
        return [({"job": "synthetic", "stream": "stdout"}, n, "original-" + str(n)) for n in range(1, 7)]

    def test_full_pages_split_without_losing_boundary_records(self):
        rows = self.rows()

        def query(base, start, end, limit):
            return [r for r in rows if start <= r[1] <= end][:limit]

        with patch.object(TRANSFER, "query", side_effect=query):
            result = [r for _, _, items in TRANSFER.windows("source", 0, 7, limit=3) for r in items]
        self.assertEqual(result, rows)

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
                patch.object(TRANSFER, "observed", return_value=set()), patch.object(TRANSFER, "push") as push:
            with self.assertRaisesRegex(RuntimeError, "not all query-visible"):
                TRANSFER.transfer(0, 2, apply=True)
            self.assertEqual(push.call_count, 1)

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
