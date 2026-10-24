#!/usr/bin/env python3
"""Keep native image, payload and fresh policy-evidence acceptance strict."""

import copy
import datetime
import hashlib
import io
import unittest

import cilium_native_runtime as runtime
import fedora_cilium_kernel_qualification as subject


class NativeCiliumEvidence(unittest.TestCase):
    def flow(self):
        return {'flow': {'time': '2026-10-24T05:00:01Z', 'verdict': 'DROPPED',
                         'drop_reason_desc': 'POLICY_DENIED',
                         'source': {'namespace': runtime.NAMESPACE, 'pod_name': 'client'},
                         'destination': {'namespace': runtime.NAMESPACE, 'pod_name': 'server'},
                         'l7': {'http': {'code': 403, 'url': 'http://echo:8080/blocked'}}}}

    def test_fresh_exact_policy_and_http_evidence(self):
        since = datetime.datetime(2026, 10, 24, 5, tzinfo=datetime.timezone.utc).timestamp()
        good = self.flow()
        self.assertEqual(runtime.matching_flows([good], since=since, denial=True), [good['flow']])
        self.assertEqual(runtime.matching_flows([good], since=since, blocked_http=True), [good['flow']])
        for key, value in (('time', '2026-10-24T04:59:59Z'), ('verdict', 'FORWARDED'),
                           ('drop_reason_desc', 'UNKNOWN'),
                           ('source', {'namespace': 'foreign', 'pod_name': 'client'}),
                           ('destination', {'namespace': runtime.NAMESPACE, 'pod_name': 'other'})):
            with self.subTest(key=key):
                changed = copy.deepcopy(good)
                changed['flow'][key] = value
                self.assertEqual(runtime.matching_flows([changed], since=since, denial=True), [])
        for http in ({'code': 200, 'url': '/blocked'}, {'code': 403, 'url': '/allowed'}):
            changed = copy.deepcopy(good)
            changed['flow']['l7']['http'] = http
            self.assertEqual(runtime.matching_flows([changed], since=since, blocked_http=True), [])

    def test_actual_server_program_delivers_complete_expected_bytes(self):
        # Execute the shipped server program with only its listening socket replaced.
        import http.server
        from unittest.mock import patch

        captured = {}

        def server(address, handler):
            captured.update(address=address, handler=handler)
            return type('NoListener', (), {'serve_forever': lambda self: None})()

        with patch.object(http.server, 'HTTPServer', server):
            exec(compile(runtime.SERVER, '<native-server>', 'exec'), {})
        handler = object.__new__(captured['handler'])
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: self.assertEqual(code, 200)
        headers = {}
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        handler.do_GET()
        payload = handler.wfile.getvalue()
        self.assertEqual(payload, b'qualification-cilium-complete-payload\n')
        self.assertEqual(hashlib.sha256(payload).hexdigest(), runtime.PAYLOAD)
        self.assertEqual(headers['Content-Length'], str(len(payload)))

    def test_reviewed_image_inventory_and_restricted_synthetic_app(self):
        records = subject.image_records()
        self.assertEqual(len(records), 5)
        pod = runtime.ordinary_pod('server', 'python@sha256:' + '1' * 64, runtime.SERVER)
        self.assertFalse(pod['spec']['automountServiceAccountToken'])
        self.assertNotIn('volumes', pod['spec'])
        self.assertTrue(pod['spec']['securityContext']['runAsNonRoot'])
        security = pod['spec']['containers'][0]['securityContext']
        self.assertFalse(security['allowPrivilegeEscalation'])
        self.assertTrue(security['readOnlyRootFilesystem'])
        self.assertEqual(security['capabilities'], {'drop': ['ALL']})


if __name__ == '__main__':
    unittest.main()
