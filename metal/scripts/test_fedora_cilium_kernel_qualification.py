#!/usr/bin/env python3
"""Keep native image, payload and fresh policy-evidence acceptance strict."""

import copy
import datetime
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import cilium_native_runtime as runtime
import fedora_cilium_kernel_qualification as subject


class NativeCiliumEvidence(unittest.TestCase):
    def test_reviewed_k3s_release_keeps_binary_and_airgap_paired(self):
        self.assertEqual(set(subject.K3S_RELEASES), set(runtime.SUPPORTED_K3S))
        baseline = subject.k3s_release_inputs('v1.33.6+k3s1')
        self.assertEqual(baseline, {'version': 'v1.33.6+k3s1', 'kubernetes_version': '1.33.6',
                                   'k3s': subject.K3S, 'airgap.tar.zst': subject.AIRGAP})
        target = subject.k3s_release_inputs('v1.36.5+k3s1')
        self.assertEqual(target, {
            'version': 'v1.36.5+k3s1', 'kubernetes_version': '1.36.5',
            'k3s': 'd73847bcd3c5fccef0115b372e2f9a91f3032dc84bbf71518a4617565294d313',
            'airgap.tar.zst': '7d939471907df2d4e537a9c308bf94173e453fff4a2e9e77e9ae92a64be3007f'})
        for foreign in ('latest', 'v1.36.6+k3s1', 'v1.36.5+k3s2', None, []):
            with self.subTest(release=foreign), self.assertRaises(RuntimeError):
                subject.k3s_release_inputs(foreign)

    def test_native_k3s_requires_exact_binary_and_node_version(self):
        for release in ('v1.33.6+k3s1', 'v1.36.5+k3s1'):
            output = ('k3s version ' + release + ' (3dd98cc)\ngo version go1.26.0\n').encode()
            self.assertEqual(runtime.require_k3s_version(release, binary_output=output,
                                                        kubelet_version=release), release)
            for foreign in ('v1.33.6+k3s2', 'v1.36.5+k3s2', '1.36.5', None):
                with self.subTest(expected=release, node=foreign), self.assertRaises(RuntimeError):
                    runtime.require_k3s_version(release, kubelet_version=foreign)
            for output in (b'foreign k3s version v1.36.5+k3s1 (3dd98cc)',
                           b'k3s version v1.36.5+k3s10 (3dd98cc)', b'k3s version foreign', b''):
                with self.subTest(output=output), self.assertRaises(RuntimeError):
                    runtime.require_k3s_version(release, binary_output=output)
        for foreign in ('latest', 'v1.36.6+k3s1', None):
            with self.subTest(release=foreign), self.assertRaises(RuntimeError):
                runtime.require_k3s_version(foreign)

    def agent_fixture(self):
        pod = {'metadata': {'uid': 'current-pod', 'name': 'cilium-owned', 'namespace': 'kube-system'},
               'status': {'containerStatuses': [{'name': 'cilium-agent', 'ready': True,
                          'state': {'running': {}}, 'containerID': 'containerd://current-container'}]}}
        container = {'id': 'current-container', 'state': 'CONTAINER_RUNNING',
                     'metadata': {'name': 'cilium-agent'}, 'labels': {
                         'io.kubernetes.pod.uid': 'current-pod', 'io.kubernetes.pod.name': 'cilium-owned',
                         'io.kubernetes.pod.namespace': 'kube-system'}}
        return pod, container

    def test_current_agent_refuses_pre_reboot_foreign_unready_or_duplicate_containers(self):
        pod, container = self.agent_fixture()
        self.assertTrue(runtime.current_agent_running(pod, [container]))
        for path, value in ((('id',), 'old-container'), (('state',), 'CONTAINER_EXITED'),
                            (('metadata', 'name'), 'foreign'),
                            (('labels', 'io.kubernetes.pod.uid'), 'old-pod'),
                            (('labels', 'io.kubernetes.pod.name'), 'foreign'),
                            (('labels', 'io.kubernetes.pod.namespace'), 'foreign')):
            changed = copy.deepcopy(container)
            selected = changed
            for key in path[:-1]:
                selected = selected[key]
            selected[path[-1]] = value
            with self.subTest(path=path):
                self.assertFalse(runtime.current_agent_running(pod, [changed]))
        self.assertFalse(runtime.current_agent_running(pod, []))
        self.assertFalse(runtime.current_agent_running(pod, [container, container]))
        pod['status']['containerStatuses'][0]['ready'] = False
        self.assertFalse(runtime.current_agent_running(pod, [container]))
        pod['status']['containerStatuses'][0]['ready'] = True
        pod['metadata']['deletionTimestamp'] = 'deleting'
        self.assertFalse(runtime.current_agent_running(pod, [container]))

    def test_agent_waits_for_current_runtime_and_only_exact_kubelet_missing_container(self):
        from unittest.mock import patch

        pod, container = self.agent_fixture()
        missing = RuntimeError(json.dumps({'exit': 1, 'stderr': [
            'error: Internal error occurred: unable to upgrade connection: container not found ("cilium-agent")']}))
        with patch.dict(runtime.EVIDENCE, {'agent_runtime_readiness': []}), \
                patch.object(runtime, 'agent_pod', return_value=pod), \
                patch.object(runtime, 'native', side_effect=[json.dumps({'containers': rows}).encode()
                                                           for rows in ([], [container], [container])]), \
                patch.object(runtime, 'kubectl', side_effect=[missing, b'{"accepted-native-status": true}']) as execute, \
                patch.object(runtime.time, 'sleep') as sleep:
            self.assertEqual(runtime.wait_agent_status(), {'accepted-native-status': True})
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(sleep.call_count, 2)
            self.assertFalse(runtime.EVIDENCE['agent_runtime_readiness'][0][0]['current_ready_container_running'])
            self.assertTrue(runtime.EVIDENCE['agent_runtime_readiness'][0][1]['kubelet_container_lookup_pending'])
            self.assertTrue(runtime.EVIDENCE['agent_runtime_readiness'][0][-1]['exec_succeeded'])
        for error in (RuntimeError(json.dumps({'exit': 1, 'stderr': ['Forbidden']})),
                      RuntimeError(json.dumps({'exit': 1, 'stderr': ['container not found ("foreign")']})),
                      RuntimeError(json.dumps({'exit': 2, 'stderr': []}))):
            with self.subTest(error=error), patch.dict(runtime.EVIDENCE, {'agent_runtime_readiness': []}), \
                    patch.object(runtime, 'agent_pod', return_value=pod), \
                    patch.object(runtime, 'native', return_value=json.dumps({'containers': [container]}).encode()), \
                    patch.object(runtime, 'kubectl', side_effect=error), \
                    patch.object(runtime.time, 'sleep') as sleep, self.assertRaises(RuntimeError):
                runtime.wait_agent_status()
            sleep.assert_not_called()
        with patch.dict(runtime.EVIDENCE, {'agent_runtime_readiness': []}), \
                patch.object(runtime, 'agent_pod', return_value=pod), \
                patch.object(runtime, 'native', return_value=b'{"containers": []}'), \
                patch.object(runtime.time, 'monotonic', side_effect=[0, 901, 901]), \
                patch.object(runtime.time, 'sleep') as sleep, self.assertRaisesRegex(RuntimeError, '900 seconds'):
            runtime.wait_agent_status()
        sleep.assert_not_called()

    def test_kubelet_proxy_requires_real_health_before_exec_and_retries_gateway_startup(self):
        from unittest.mock import patch

        path = '/api/v1/nodes/' + runtime.NODE + '/proxy/healthz'
        with patch.dict(runtime.EVIDENCE, {'api_readiness': []}), \
                patch.object(runtime, 'native_api_tls', return_value=(object(), {})), \
                patch.object(runtime, 'api_response', side_effect=[(502, b'not ready'), (200, b'ok')]) as response, \
                patch.object(runtime.time, 'sleep') as sleep:
            runtime.wait_api_ready(path)
            self.assertEqual(sleep.call_count, 1)
            self.assertEqual([call.args[1] for call in response.call_args_list], [path, path])
            self.assertTrue(runtime.EVIDENCE['api_readiness'][0][-1]['ready'])
        for foreign in ('https://foreign/healthz', '/api/v1/nodes/foreign/proxy/healthz', '/readyz?verbose'):
            with self.subTest(path=foreign), patch.object(runtime, 'native_api_tls') as credentials:
                with self.assertRaises(AssertionError):
                    runtime.wait_api_ready(foreign)
                credentials.assert_not_called()
        for status in (401, 403, 302, 404, 429):
            with self.subTest(status=status), patch.dict(runtime.EVIDENCE, {'api_readiness': []}), \
                    patch.object(runtime, 'native_api_tls', return_value=(object(), {})), \
                    patch.object(runtime, 'api_response', return_value=(status, b'refused')), \
                    patch.object(runtime.time, 'sleep') as sleep, self.assertRaises(RuntimeError):
                runtime.wait_api_ready(path)
            sleep.assert_not_called()

    def test_http_readiness_waits_for_status_and_never_records_response_body(self):
        from unittest.mock import patch

        responses = [ConnectionRefusedError(), (503, b'PRIVATE_SENTINEL'), (500, b'any evolving readyz report'),
                     (200, b'ok\n')]
        with patch.dict(runtime.EVIDENCE, {'api_readiness': [], 'api_readiness_tls': []}), \
                patch.object(runtime, 'native_api_tls', return_value=(object(), {'verified': True})), \
                patch.object(runtime, 'api_response', side_effect=responses), \
                patch.object(runtime.time, 'sleep') as sleep:
            runtime.wait_api_ready()
            self.assertEqual(sleep.call_count, 3)
            attempts = runtime.EVIDENCE['api_readiness'][0]
            self.assertEqual([row.get('http_status') for row in attempts], [None, 503, 500, 200])
            self.assertTrue(attempts[-1]['ready'])
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(runtime.EVIDENCE))

    def test_http_readiness_refuses_authentication_redirect_unknown_and_bad_success(self):
        from unittest.mock import patch

        for status, body in [(value, b'PRIVATE_SENTINEL') for value in (401, 403, 302, 404, 429, 502)] + [(200, b'bad')]:
            with self.subTest(status=status), patch.dict(runtime.EVIDENCE, {'api_readiness': []}), \
                    patch.object(runtime, 'native_api_tls', return_value=(object(), {})), \
                    patch.object(runtime, 'api_response', return_value=(status, body)), \
                    patch.object(runtime.time, 'sleep') as sleep, self.assertRaises((RuntimeError, AssertionError)):
                runtime.wait_api_ready()
            sleep.assert_not_called()
        with patch.dict(runtime.EVIDENCE, {'api_readiness': []}), \
                patch.object(runtime, 'native_api_tls', return_value=(object(), {})), \
                patch.object(runtime, 'api_response', side_effect=runtime.ssl.SSLCertVerificationError('untrusted')), \
                patch.object(runtime.time, 'sleep') as sleep, self.assertRaises(runtime.ssl.SSLCertVerificationError):
            runtime.wait_api_ready()
        sleep.assert_not_called()

    def test_http_readiness_has_bounded_timeout(self):
        from unittest.mock import patch

        with patch.dict(runtime.EVIDENCE, {'api_readiness': []}), \
                patch.object(runtime, 'native_api_tls', return_value=(object(), {})), \
                patch.object(runtime, 'api_response', return_value=(500, b'unready')), \
                patch.object(runtime.time, 'monotonic', side_effect=[0, 901, 901]), \
                patch.object(runtime.time, 'sleep') as sleep, self.assertRaisesRegex(RuntimeError, '900 seconds'):
            runtime.wait_api_ready()
        sleep.assert_not_called()

    def credentials(self):
        return {'clusters': [{'name': 'fixture', 'cluster': {'server': 'https://127.0.0.1:6443',
                'certificate-authority-data': runtime.base64.b64encode(b'authority').decode()}}],
                'users': [{'name': 'fixture', 'user': {
                    'client-certificate-data': runtime.base64.b64encode(b'certificate').decode(),
                    'client-key-data': runtime.base64.b64encode(b'PRIVATE_SENTINEL').decode()}}],
                'contexts': [{'name': 'fixture', 'context': {'cluster': 'fixture', 'user': 'fixture'}}],
                'current-context': 'fixture'}

    def test_exact_loopback_mutual_tls_identity_and_foreign_credentials_refused(self):
        expected = self.credentials()
        self.assertEqual(runtime.api_credentials(expected), (b'authority', b'certificate', b'PRIVATE_SENTINEL'))
        changes = []
        for key, value in (('server', 'https://10.0.20.50:6443'), ('proxy-url', 'http://proxy'),
                           ('insecure-skip-tls-verify', True), ('tls-server-name', 'foreign')):
            changed = copy.deepcopy(expected)
            changed['clusters'][0]['cluster'][key] = value
            changes.append(changed)
        for key in ('token', 'exec', 'auth-provider'):
            changed = copy.deepcopy(expected)
            changed['users'][0]['user'][key] = 'foreign'
            changes.append(changed)
        changed = copy.deepcopy(expected)
        changed['contexts'][0]['context']['cluster'] = 'foreign'
        changes.append(changed)
        changed = copy.deepcopy(expected)
        changed['clusters'].append(copy.deepcopy(changed['clusters'][0]))
        changes.append(changed)
        changed = copy.deepcopy(expected)
        changed['users'][0]['user']['client-key-data'] = 'invalid%'
        changes.append(changed)
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises((AssertionError, ValueError)):
                runtime.api_credentials(changed)

    def test_native_tls_loads_private_files_then_removes_them(self):
        import os
        import stat
        from unittest.mock import patch

        private_paths = []
        class Context:
            check_hostname = True
            verify_mode = runtime.ssl.CERT_REQUIRED

            def load_cert_chain(self, certificate, key):
                for filename, content in ((certificate, b'certificate'), (key, b'PRIVATE_SENTINEL')):
                    path = Path(filename)
                    self_case.assertEqual(path.read_bytes(), content)
                    self_case.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    self_case.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                    private_paths.append(path)

        self_case = self
        original = tempfile.TemporaryDirectory
        with patch.object(runtime, 'native', return_value=json.dumps(self.credentials()).encode()), \
                patch.object(runtime.ssl, 'create_default_context', return_value=Context()) as create, \
                patch.object(runtime.tempfile, 'TemporaryDirectory',
                             side_effect=lambda **kwargs: original(prefix=kwargs['prefix'], dir=os.environ['TMPDIR'])):
            _context, evidence = runtime.native_api_tls()
        create.assert_called_once_with(cadata='authority')
        self.assertTrue(evidence['certificate_and_hostname_verified'])
        self.assertTrue(evidence['temporary_keyfiles_removed'])
        self.assertTrue(all(not path.exists() for path in private_paths))
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(evidence))

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
