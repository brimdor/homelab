#!/usr/bin/env python3
"""Keep native image, payload and fresh policy-evidence acceptance strict."""

import copy
import datetime
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import cilium_native_runtime as runtime
import fedora_cilium_kernel_qualification as subject


class NativeCiliumEvidence(unittest.TestCase):
    def test_api_readiness_waits_only_for_observed_startup_states(self):
        from unittest.mock import patch

        def failure(message):
            return SimpleNamespace(returncode=1, stderr=message.encode(), stdout=b'')

        messages = ['Error from server (ServiceUnavailable): apiserver not ready',
                    'The connection to the server 127.0.0.1:6443 was refused - did you specify the right host or port?']
        with patch.dict(runtime.EVIDENCE, {'api_readiness': []}), \
                patch.object(runtime.subprocess, 'run', side_effect=[*[failure(value) for value in messages],
                                                                   SimpleNamespace(returncode=0, stdout=b'ok', stderr=b'')]), \
                patch.object(runtime.time, 'sleep') as sleep:
            runtime.wait_api_ready()
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(len(runtime.EVIDENCE['api_readiness'][0]), 3)
            self.assertTrue(runtime.EVIDENCE['api_readiness'][0][-1]['ready'])
        for message in ('Error from server (Forbidden): forbidden', 'x509: certificate unknown',
                        'Error from server (ServiceUnavailable): unrelated failure'):
            with self.subTest(message=message), patch.dict(runtime.EVIDENCE, {'api_readiness': []}), \
                    patch.object(runtime.subprocess, 'run', return_value=failure(message)), \
                    patch.object(runtime.time, 'sleep') as sleep, self.assertRaises(RuntimeError):
                runtime.wait_api_ready()
            sleep.assert_not_called()
        with patch.dict(runtime.EVIDENCE, {'api_readiness': []}), \
                patch.object(runtime.subprocess, 'run', return_value=failure(messages[0])), \
                patch.object(runtime.time, 'monotonic', side_effect=[0, 901, 901]), \
                patch.object(runtime.time, 'sleep') as sleep, self.assertRaisesRegex(RuntimeError, '900 seconds'):
            runtime.wait_api_ready()
        sleep.assert_not_called()

    def test_complete_readyz_startup_report_and_unknown_truncated_or_mixed_refusals(self):
        checks = '[+]ping ok\n[+]etcd ok\n' + ''.join(
            '[-]poststarthook/fixture-' + str(index) + ' failed: reason withheld\n' for index in range(20))
        report = checks + 'readyz check failed'
        prefix = 'Error from server (InternalError): an error on the server ('
        suffix = ') has prevented the request from succeeding'
        message = (prefix + json.dumps(report) + suffix).encode()
        self.assertGreater(len(message), 500)
        actual = runtime.api_readiness_failure(message)
        self.assertEqual(actual['state'], 'readyz-startup-checks')
        self.assertEqual(len(actual['checks']), 22)
        for bad in (message[:500], message + b' PRIVATE_SENTINEL',
                    (prefix + json.dumps(report.replace('reason withheld', 'PRIVATE_SENTINEL')) + suffix).encode(),
                    (prefix + json.dumps(report.replace('[-]', '[+]')) + suffix).encode(),
                    (prefix + json.dumps(checks) + suffix).encode(),
                    b'Error from server (InternalError): unrelated failure', b'\xff'):
            with self.subTest(bad=bad[:40]):
                self.assertIsNone(runtime.api_readiness_failure(bad))

    def cri_info(self, configuration, binaries):
        return {'config': {'cni': {'binDir': '', 'binDirs': [str(binaries)],
                                  'confDir': str(configuration), 'maxConfNum': 1}},
                'status': {'conditions': [{'type': name, 'status': True}
                                           for name in ('RuntimeReady', 'NetworkReady')]},
                'cniconfig': {'PluginDirs': [str(binaries)], 'PluginConfDir': str(configuration),
                              'PluginMaxConfNum': 1, 'Networks': [{'IFName': 'eth0', 'Config': {
                                  'Source': json.dumps({'plugins': [{'type': 'cilium-cni'}]}),
                                  'Plugins': [{'Network': {'type': 'cilium-cni'}}]}}]}}

    def test_actual_containerd_cni_paths_and_foreign_or_ambiguous_refusals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration = root / 'configuration'
            binaries = root / 'binaries'
            configuration.mkdir()
            binaries.mkdir()
            manifest = configuration / '05-cilium.conflist'
            manifest.write_text(json.dumps({'plugins': [{'type': 'cilium-cni'}]}))
            binary = binaries / 'cilium-cni'
            binary.write_bytes(b'owned synthetic executable')
            binary.chmod(0o700)
            info = self.cri_info(configuration, binaries)
            header = '[plugins."io.containerd.cri.v1.runtime".cni]\nconf_dir=' + json.dumps(str(configuration)) + '\n'
            for option in ('bin_dir=' + json.dumps(str(binaries)), 'bin_dirs=[' + json.dumps(str(binaries)) + ']'):
                actual = runtime.cni_identity(header + option, info)
                self.assertEqual(actual['binary'], str(binary))
                self.assertEqual(actual['active_configuration'], str(manifest))
                self.assertEqual(actual['binary_sha256'], hashlib.sha256(binary.read_bytes()).hexdigest())
            settings = header + 'bin_dirs=[' + json.dumps(str(binaries)) + ']'
            manifest.write_text(json.dumps({'plugins': [{'type': 'foreign'}]}))
            with self.assertRaises(AssertionError):
                runtime.cni_identity(settings, info)
            manifest.write_text(json.dumps({'plugins': [{'type': 'cilium-cni'}]}))
            extra = configuration / '10-foreign.conf'
            extra.write_text('{}')
            with self.assertRaises(AssertionError):
                runtime.cni_identity(settings, info)
            extra.unlink()
            with self.assertRaises(AssertionError):
                runtime.cni_identity(settings + '\nbin_dir=' + json.dumps(str(binaries)), info)
            binary.unlink()
            with self.assertRaises(AssertionError):
                runtime.cni_identity(settings, info)

    def test_native_cri_defaults_and_contradictory_or_unready_runtime_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration, binaries = root / 'configuration', root / 'binaries'
            configuration.mkdir()
            binaries.mkdir()
            (configuration / '05-cilium.conflist').write_text(json.dumps({'plugins': [{'type': 'cilium-cni'}]}))
            (binaries / 'cilium-cni').write_bytes(b'owned synthetic executable')
            (binaries / 'cilium-cni').chmod(0o700)
            info = self.cri_info(configuration, binaries)
            actual = runtime.cni_identity('[plugins]\n', info)
            self.assertFalse(actual['toml_cni_explicit'])
            self.assertTrue(actual['native_cri_ready_and_loaded_config_verified'])
            legacy = copy.deepcopy(info)
            legacy['config']['cni'].update(binDir=str(binaries), binDirs=[])
            self.assertEqual(runtime.cni_identity('[plugins]\n', legacy), actual)
            changes = [
                ('config', 'cni', 'binDirs', ['relative']),
                ('config', 'cni', 'binDir', str(binaries)),
                ('config', 'cni', 'binDirs', [str(binaries), str(binaries)]),
                ('cniconfig', 'PluginDirs', ['foreign']),
                ('cniconfig', 'PluginConfDir', '/foreign'),
                ('cniconfig', 'PluginMaxConfNum', 2),
                ('cniconfig', 'Networks', []),
                ('cniconfig', 'Networks', info['cniconfig']['Networks'] * 2),
                ('cniconfig', 'Networks', [{'IFName': 'eth0', 'Config': {
                    'Source': '{}', 'Plugins': [{'Network': {'type': 'cilium-cni'}}]}}]),
                ('status', 'conditions', [{'type': 'NetworkReady', 'status': False}]),
            ]
            for *path, replacement in changes:
                with self.subTest(path=path):
                    changed = copy.deepcopy(info)
                    selected = changed
                    for key in path[:-1]:
                        selected = selected[key]
                    selected[path[-1]] = replacement
                    with self.assertRaises(AssertionError):
                        runtime.cni_identity('[plugins]\n', changed)
            for fields in ('bin_dirs=["/foreign"]', 'conf_dir="/foreign"', 'max_conf_num=2'):
                with self.subTest(fields=fields), self.assertRaises(AssertionError):
                    runtime.cni_identity('[plugins."io.containerd.cri.v1.runtime".cni]\n' + fields, info)

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
