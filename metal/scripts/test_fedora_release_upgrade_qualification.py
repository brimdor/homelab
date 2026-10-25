#!/usr/bin/env python3
"""Refuse foreign upgrade requests, releases and unverified cache inputs."""

import hashlib
import base64
import io
import json
import copy
import errno
import http.client
from pathlib import Path
import tempfile
import ssl
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

import fedora_release_upgrade_qualification as upgrade
import fedora_upgrade_repository as repository
from fedora_upgrade_bridge import bridge


class UpgradeRefusals(unittest.TestCase):
    @staticmethod
    def offline_fixture(source, target):
        fixture = object.__new__(upgrade.Qualification)
        fixture.ssh = ['ssh', 'owned-synthetic-guest']
        fixture.reference_corpus = {'unchanged': True}
        fixture.checkpoint_states = {}
        fixture.server = SimpleNamespace(errors=[])
        before = {'machine': 'same', 'root_uuid': 'same',
                  'architecture': 'x86_64', 'boot': 'before'}
        fixture.identity = unittest.mock.Mock(side_effect=[before, {**before, 'boot': 'after'}])
        fixture.guest = unittest.mock.Mock(return_value={
            'release': target, 'boot': 'after', 'offline_pending': False})
        for name in ('repositories', 'filesystems', 'command', 'signatures',
                     'persist', 'checkpoint', 'state', 'wait_ready'):
            setattr(fixture, name, unittest.mock.Mock())
        return fixture

    def test_reboot_probe_disconnect_retries_only_reads_and_preserves_refusals(self):
        closed = b'Connection to 127.0.0.1 closed by remote host.\n'
        for phase in ('readiness', 'state', 'authentication'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                fixture = self.offline_fixture(41, 43)
                fixture.root = Path(temporary)
                fixture.number = 46
                (fixture.root / '46.log').write_bytes(closed)
                failure = RuntimeError('qualification command 46 exit 255')
                if phase == 'readiness':
                    fixture.wait_ready.side_effect = [failure, None]
                elif phase == 'state':
                    fixture.guest.side_effect = [failure, fixture.guest.return_value]
                else:
                    fixture.guest.side_effect = RuntimeError('fixture SSH authentication refused')
                with patch.object(upgrade.time, 'sleep') as sleep:
                    if phase == 'authentication':
                        with self.assertRaisesRegex(RuntimeError, 'authentication refused'):
                            fixture.offline(41, 43)
                        sleep.assert_not_called()
                    else:
                        fixture.offline(41, 43)
                        sleep.assert_called_once_with(5)
                        fixture.persist.assert_any_call(
                            'offline-reboot-probe-disconnected', source=41, target=43,
                            command=46, exit=255, output=closed.decode(), output_bytes=len(closed),
                            output_sha256=hashlib.sha256(closed).hexdigest())
                        self.assertEqual(fixture.wait_ready.call_count, 2)
                self.assertEqual(fixture.command.call_count, 3)

    def test_reboot_disconnect_refuses_every_other_failure(self):
        error = RuntimeError('qualification command 46 exit 255')
        closed = b'Connection to 127.0.0.1 closed by remote host.\n'
        warning = (b'** WARNING: connection is not using a post-quantum key exchange algorithm.\n'
                   b'** This session may be vulnerable to "store now, decrypt later" attacks.\n'
                   b'** The server may need to be upgraded. See https://openssh.com/pq.html\n')
        for output in (closed, warning + closed, b'\nstatus: done\n' + warning + closed):
            self.assertTrue(upgrade.reboot_probe_disconnect(error, 46, output))
        for output in (b'', warning, closed + closed, b'Permission denied\n' + closed,
                       b'Host key verification failed\n' + closed,
                       b'REMOTE HOST IDENTIFICATION HAS CHANGED\n' + closed,
                       closed.replace(b'127.0.0.1', b'other-host'),
                       b'{"release": 41}\n' + closed, b'unknown warning\n' + closed):
            with self.subTest(output=output):
                self.assertFalse(upgrade.reboot_probe_disconnect(error, 46, output))
        for failure, number in ((RuntimeError('qualification command 46 exit 1'), 46),
                                (RuntimeError('fixture SSH authentication refused'), 46), (error, 45)):
            self.assertFalse(upgrade.reboot_probe_disconnect(failure, number, closed))

    def test_each_native_offline_reboot_is_noninteractive(self):
        for source, target in ((39, 41), (41, 43), (43, 44)):
            with self.subTest(source=source, target=target):
                fixture = self.offline_fixture(source, target)
                fixture.offline(source, target)
                dnf = '/usr/bin/dnf' if source == 39 else '/usr/bin/dnf5'
                verb = 'system-upgrade' if source == 39 else 'offline'
                fixture.command.assert_any_call(fixture.ssh + [
                    'sudo systemd-run --on-active=2s --unit=qualification-upgrade-' +
                    str(source) + '-' + str(target) + ' ' + dnf + ' -y ' + verb + ' reboot'])
                fixture.persist.assert_called_with('offline-upgrade-prepared', source=source,
                                                   target=target, signatures=fixture.signatures.return_value)
                fixture.wait_ready.assert_called_once_with()

    def test_only_exact_timestamp_drift_can_restore_native_package_metadata(self):
        import ast

        functions = [node for node in ast.parse(upgrade.GUEST).body
                     if isinstance(node, ast.FunctionDef) and node.name == 'verify_packages']
        self.assertEqual(len(functions), 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'customizable_types'
            path.write_bytes(b'unchanged synthetic policy')
            enforcement = Path(temporary) / 'enforce'; enforcement.write_text('1\n')
            guest_os = SimpleNamespace(listxattr=lambda value: [], getxattr=lambda *args: b'')
            namespace = {'hashlib': hashlib, 'json': json, 'os': guest_os,
                         'pathlib': SimpleNamespace(Path=lambda value: enforcement
                                                   if value == '/sys/fs/selinux/enforce' else path)}
            exec(compile(ast.Module(body=functions, type_ignores=[]), '<actual-guest-verify>', 'exec'), namespace)
            exact = '.......T.  c /etc/selinux/targeted/contexts/customizable_types\n'
            failure = {'command': ['rpm', '-V', 'fedora-release-common', 'selinux-policy-targeted'],
                       'exit': 1, 'stderr': '', 'verification_stdout': exact,
                       'verification_stdout_bytes': len(exact.encode()),
                       'verification_stdout_sha256': hashlib.sha256(exact.encode()).hexdigest()}
            verify = namespace['verify_packages']
            with patch.dict(namespace, native=unittest.mock.Mock(return_value='')):
                self.assertIsNone(verify())
                namespace['native'].assert_called_once_with(*failure['command'])
            for change in ({'verification_stdout': exact.replace('.......T.', 'S.5....T.')},
                           {'verification_stdout': exact.replace('customizable_types', 'foreign')},
                           {'verification_stdout': exact + exact}, {'stderr': 'failure'}, {'exit': 2}):
                with self.subTest(change=change), patch.dict(namespace, native=unittest.mock.Mock(
                        side_effect=RuntimeError(json.dumps({**failure, **change})))):
                    with self.assertRaises(RuntimeError):
                        verify()
                    self.assertEqual(namespace['native'].call_count, 1)
            for ending in ('', 'unexpected output', RuntimeError('restore failed')):
                native = unittest.mock.Mock(side_effect=[RuntimeError(json.dumps(failure)), ending, ''])
                with self.subTest(ending=ending), patch.dict(namespace, native=native):
                    if ending == '':
                        result = verify()
                        self.assertEqual(result['before'], result['after'])
                        self.assertEqual(result['original_failure'], failure)
                    else:
                        with self.assertRaises((RuntimeError, AssertionError)):
                            verify()
                    self.assertEqual(native.call_args_list[1],
                                     unittest.mock.call('rpm', '--restore', 'selinux-policy-targeted'))
            with patch.dict(namespace, native=unittest.mock.Mock(side_effect=[
                    RuntimeError(json.dumps(failure)), '', RuntimeError('verification still failed')])):
                with self.assertRaisesRegex(RuntimeError, 'verification still failed'):
                    verify()
            path.unlink(); path.symlink_to(enforcement)
            native = unittest.mock.Mock(side_effect=RuntimeError(json.dumps(failure)))
            with patch.dict(namespace, native=native), self.assertRaises(AssertionError):
                verify()
            self.assertEqual(native.call_count, 1)
            path.unlink()
            for mutation in ('content', 'mode', 'xattr'):
                path.write_bytes(b'unchanged synthetic policy'); path.chmod(0o600)

                def restore(*args):
                    if args == tuple(failure['command']):
                        if native.call_count == 1:
                            raise RuntimeError(json.dumps(failure))
                        return ''
                    if mutation == 'content':
                        path.write_bytes(b'changed synthetic policy')
                    elif mutation == 'mode':
                        path.chmod(0o640)
                    return ''

                native = unittest.mock.Mock(side_effect=restore)
                attrs = [[], ['user.synthetic']] if mutation == 'xattr' else [[], []]
                with self.subTest(mutation=mutation), patch.dict(namespace, native=native), \
                        patch.object(guest_os, 'listxattr', side_effect=attrs), \
                        patch.object(guest_os, 'getxattr', return_value=b'changed'):
                    with self.assertRaises(AssertionError):
                        verify()

    def test_partial_transport_failure_retries_identical_url_and_verified_bytes(self):
        base = repository.BASES['41-updates']
        relative = 'Packages/f/fwupd-plugin-modem-manager-2.0.16-1.fc41.x86_64.rpm'
        payload = b'complete synthetic public package'

        class Response(io.BytesIO):
            status = 200
            url = base + relative

        class Partial(Response):
            def read(self, size=-1):
                if self.tell():
                    raise urllib.error.URLError(TimeoutError('synthetic TLS handshake timeout'))
                return super().read(4)

        partial, complete = Partial(payload), Response(payload)
        attempts = []
        with tempfile.TemporaryDirectory() as temporary, \
                patch('urllib.request.urlopen', side_effect=[partial, complete]) as request, \
                patch('time.sleep') as sleep:
            path = Path(temporary) / 'package.rpm'
            expected = hashlib.sha256(payload).hexdigest()
            self.assertEqual(repository.fetch(base, relative, path, expected, attempts), expected)
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(request.call_args_list, [unittest.mock.call(base + relative, timeout=90)] * 2)
            sleep.assert_called_once_with(2)
        self.assertTrue(partial.closed and complete.closed)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]['reason_type'], 'TimeoutError')
        self.assertTrue(attempts[0]['retrying'])

    def test_transport_exhaustion_remains_fatal_and_removes_partial_input(self):
        errors = [urllib.error.URLError(TimeoutError('synthetic timeout')) for _ in range(3)]
        attempts = []
        with tempfile.TemporaryDirectory() as temporary, \
                patch('urllib.request.urlopen', side_effect=errors) as request, \
                patch('time.sleep') as sleep:
            path = Path(temporary) / '41-updates/repodata/repomd.xml'
            with self.assertRaises(urllib.error.URLError):
                repository.mirror(Path(temporary), '41-updates', attempts)
            self.assertFalse(path.exists())
            self.assertEqual(request.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
        self.assertEqual([row['retrying'] for row in attempts], [True, True, False])

    def test_unreachable_route_recovery_is_bounded_and_keeps_exact_verified_origin(self):
        base = repository.BASES['41-updates']
        relative = 'Packages/l/libblkid.rpm'
        payload = b'complete synthetic package'
        expected = hashlib.sha256(payload).hexdigest()
        class Response(io.BytesIO):
            status = 200
            url = base + relative
        for code in (errno.EHOSTUNREACH, errno.ENETUNREACH):
            for recovered in (True, False):
                failure = urllib.error.URLError(OSError(code, 'synthetic unreachable route'))
                outcomes = [failure, Response(payload)] if recovered else [failure] * 3
                attempts = []
                with self.subTest(code=code, recovered=recovered), tempfile.TemporaryDirectory() as temporary, \
                        patch('urllib.request.urlopen', side_effect=outcomes) as request, \
                        patch('time.sleep') as sleep:
                    path = Path(temporary) / 'package.rpm'
                    if recovered:
                        self.assertEqual(repository.fetch(base, relative, path, expected, attempts), expected)
                        self.assertEqual(path.read_bytes(), payload)
                    else:
                        with self.assertRaises(urllib.error.URLError):
                            repository.fetch(base, relative, path, expected, attempts)
                        self.assertFalse(path.exists())
                    count = 2 if recovered else 3
                    self.assertEqual(request.call_args_list,
                                     [unittest.mock.call(base + relative, timeout=90)] * count)
                    self.assertEqual(sleep.call_count, count - 1)
                self.assertEqual([row['errno'] for row in attempts], [code] * len(attempts))
                self.assertEqual([row['retrying'] for row in attempts], [True] if recovered else [True, True, False])

    def test_trust_access_and_unknown_failures_are_never_retried(self):
        base = repository.BASES['41-updates']
        for error in (urllib.error.URLError(ssl.SSLCertVerificationError('synthetic trust failure')),
                      urllib.error.URLError('unclassified failure'),
                      *(urllib.error.URLError(OSError(code, 'synthetic refusal'))
                        for code in (errno.EACCES, errno.EPERM, errno.EIO, errno.ECONNREFUSED)),
                      *(urllib.error.HTTPError(base, code, 'synthetic refusal', {}, io.BytesIO())
                        for code in (401, 403, 429))):
            body = error.fp if isinstance(error, urllib.error.HTTPError) else None
            with self.subTest(error=type(error).__name__, code=getattr(error, 'code', None)), \
                    tempfile.TemporaryDirectory() as temporary, \
                    patch('urllib.request.urlopen', side_effect=error) as request, \
                    patch('time.sleep') as sleep:
                path = Path(temporary) / 'package.rpm'
                with self.assertRaises(type(error)):
                    repository.fetch(base, 'Packages/k/kernel.rpm', path)
                self.assertFalse(path.exists())
                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()
                if body is not None:
                    self.assertTrue(body.closed)
        for error in (TimeoutError(), ConnectionResetError(), ConnectionAbortedError(),
                      http.client.IncompleteRead(b'synthetic'),
                      *(urllib.error.HTTPError(base, code, '', {}, None) for code in (500, 502, 503, 504))):
            self.assertTrue(repository.retryable_fetch_error(error))

    def test_failed_package_verification_retains_diagnostics_without_accepting_drift(self):
        import ast
        import subprocess

        function = next(node for node in ast.parse(upgrade.GUEST).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'native')
        namespace = {'subprocess': subprocess, 'json': json, 'hashlib': hashlib}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<actual-guest-native>', 'exec'), namespace)
        commands = (('rpm', '-V', 'fedora-release-common', 'selinux-policy-targeted'),
                    ('rpm', '-V', 'container-selinux', 'k3s-selinux'))
        output = b'S.5....T.  c /owned/synthetic/package-file\n'
        for arguments in (*commands, ('rpm', '-V', 'foreign-package'), ('other', 'command')):
            result = subprocess.CompletedProcess(arguments, 1, output, b'')
            with self.subTest(command=arguments), patch.object(subprocess, 'run', return_value=result), \
                    self.assertRaises(RuntimeError) as failure:
                namespace['native'](*arguments)
            retained = json.loads(str(failure.exception))
            self.assertEqual(retained['exit'], 1)
            if arguments in commands:
                self.assertEqual(retained['verification_stdout'], output.decode())
                self.assertEqual(retained['verification_stdout_bytes'], len(output))
                self.assertEqual(retained['verification_stdout_sha256'], hashlib.sha256(output).hexdigest())
            else:
                self.assertNotIn('verification_stdout', retained)
        for command in commands:
            with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(command, 0, b'', b'')):
                self.assertEqual(namespace['native'](*command), '')

    def test_public_key_armor_preserves_bytes_and_known_crc24(self):
        for raw in (b'123456789', bytes(range(256)) * 5):
            armored = upgrade.armor_public_key(raw)
            lines = armored.splitlines()
            self.assertEqual(lines[0], b'-----BEGIN PGP PUBLIC KEY BLOCK-----')
            self.assertEqual(lines[1], b'')
            self.assertEqual(lines[-1], b'-----END PGP PUBLIC KEY BLOCK-----')
            self.assertEqual(base64.b64decode(b''.join(lines[2:-2]), validate=True), raw)
            self.assertTrue(all(len(line) <= 76 for line in lines[2:-2]))
            if raw == b'123456789':
                self.assertEqual(lines[-2], b'=Ic8C')

    def test_rollback_requires_exact_packages_data_and_stable_identity(self):
        expected = {'identity': {'machine': 'machine', 'root_uuid': 'root',
                                'architecture': 'x86_64', 'kernel': 'kernel', 'boot': 'before'},
                    'native': {'package_inventory': ['exact']}, 'corpus': {'sha256': 'same'}}
        current = copy.deepcopy(expected)
        current['identity']['boot'] = 'new-boot'
        upgrade.require_checkpoint_state(current, expected)
        for section, key, value in (('identity', 'machine', 'foreign'),
                                    ('identity', 'root_uuid', 'foreign'),
                                    ('identity', 'kernel', 'foreign'),
                                    ('native', 'package_inventory', ['other']),
                                    ('corpus', 'sha256', 'other')):
            changed = copy.deepcopy(current)
            changed[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaisesRegex(RuntimeError, 'checkpoint'):
                upgrade.require_checkpoint_state(changed, expected)

    def test_corrupted_or_redirected_response_never_becomes_a_cached_package(self):
        base = repository.BASES['39-base']
        relative = 'Packages/k/kernel.rpm'

        class Response(io.BytesIO):
            status = 200
            url = base + relative

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'package.rpm'
            with patch('urllib.request.urlopen', return_value=Response(b'owned public bytes')):
                digest = repository.fetch(base, relative, path, hashlib.sha256(b'owned public bytes').hexdigest())
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            path.unlink()
            with patch('urllib.request.urlopen', return_value=Response(b'corrupted')) as request, \
                    patch('time.sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    repository.fetch(base, relative, path, '0' * 64)
                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()
            self.assertFalse(path.exists())
            redirected = Response(b'owned public bytes')
            redirected.url = 'https://foreign.example/package.rpm'
            with patch('urllib.request.urlopen', return_value=redirected) as request, \
                    patch('time.sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, 'origin'):
                    repository.fetch(base, relative, path)
                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()
            self.assertFalse(path.exists())

    def test_actual_generated_guest_programs_compile(self):
        fixture = object.__new__(upgrade.Qualification)
        fixture.contract = json.loads((upgrade.MAINTENANCE / 'fedora-upgrade-inputs.json').read_bytes())
        programs = []
        generated = []

        def compile_guest(body):
            generated.append(body)
            programs.append(compile(upgrade.GUEST + body, '<actual-upgrade-guest>', 'exec'))
            return {}

        fixture.guest = compile_guest
        fixture.identity = lambda: {}
        fixture.corpus = lambda: {'unchanged': True}
        with tempfile.TemporaryDirectory() as temporary:
            fixture.args = SimpleNamespace(keys_dir=Path(temporary))
            for release in fixture.contract['keys']:
                (fixture.args.keys_dir / ('fedora' + release + '.gpg')).write_bytes(b'owned public bytes')
            fixture.configure()
            self.assertIn('timeout=300', generated[0])
            self.assertIn('max_parallel_downloads=1', generated[0])
        fixture.signatures()
        fixture.filesystems()
        fixture.state(39, {'unchanged': True})
        self.assertEqual(len(programs), 4)

    def test_only_declared_native_hops(self):
        self.assertEqual(upgrade.require_hop(39, 41), '/usr/bin/dnf')
        for source, target in ((41, 43), (43, 44)):
            self.assertEqual(upgrade.require_hop(source, target), '/usr/bin/dnf5')
        for source, target in ((39, 44), (44, 43), (39, 40), (43, 45), ('39', 41), (39, True)):
            with self.subTest(source=source, target=target), self.assertRaisesRegex(RuntimeError, 'foreign'):
                upgrade.require_hop(source, target)

    def test_path_binds_exact_origin_and_metadata_or_package(self):
        record = {'base': repository.BASES['39-base'],
                  'files': {'repodata/repomd.xml': 'a' * 64},
                  'packages': {'Packages/k/kernel-core.rpm': 'b' * 64,
                               'Packages/l/libstdc++-13.3.1-3.fc39.x86_64.rpm': 'c' * 64,
                               'Packages/t/tool-1^2026-1.fc44.x86_64.rpm': 'd' * 64}}
        repositories = {'39-base': record}
        self.assertEqual(repository.requested_path('/39-base/repodata/repomd.xml', repositories),
                         ('39-base', 'repodata/repomd.xml', 'a' * 64))
        self.assertEqual(repository.requested_path('/39-base/Packages/k/kernel-core.rpm', repositories),
                         ('39-base', 'Packages/k/kernel-core.rpm', 'b' * 64))
        for spelling in ('libstdc++', 'libstdc%2b%2b', 'libstdc%2B%2B', 'libstdc%2b%2B'):
            self.assertEqual(repository.requested_path('/39-base/Packages/l/' + spelling +
                                                     '-13.3.1-3.fc39.x86_64.rpm', repositories),
                             ('39-base', 'Packages/l/libstdc++-13.3.1-3.fc39.x86_64.rpm', 'c' * 64))
        self.assertEqual(repository.requested_path('/39-base/Packages/t/tool-1%5E2026-1.fc44.x86_64.rpm',
                                                  repositories),
                         ('39-base', 'Packages/t/tool-1^2026-1.fc44.x86_64.rpm', 'd' * 64))
        for value in ('/39-base/../private', '/39-base//repodata/repomd.xml',
                      '/39-base/repodata/missing.xml', '/44-base/repodata/repomd.xml',
                      '/39-base/Packages/k/kernel-core.rpm?token=x',
                      '/39-base/Packages/k/kernel-core.rpm#x', '/39-base/%2e%2e/private',
                      '/39-base/Packages/l/libstdc%252b%252b-13.3.1-3.fc39.x86_64.rpm',
                      '/39-base/Packages%2Fl/libstdc++-13.3.1-3.fc39.x86_64.rpm',
                      '/39-base/Packages/l/libstdc%2-13.3.1-3.fc39.x86_64.rpm',
                      '/39-base/Packages%5cl/libstdc++-13.3.1-3.fc39.x86_64.rpm',
                      '/39-base/Packages/l/libstdc%ff.rpm', '/39-base/Packages/l/libstdc%00.rpm',
                      '/39-base/Packages/l/libstdc%3frpm', '/39-base/Packages/l/libstdc%23rpm',
                      'https://foreign.example/private', None):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                repository.requested_path(value, repositories)
        record['base'] = 'https://foreign.example/'
        with self.assertRaisesRegex(RuntimeError, 'unverified'):
            repository.requested_path('/39-base/Packages/k/kernel-core.rpm', repositories)

    def test_foreign_origin_and_existing_or_redirected_output_refused_before_network(self):
        with tempfile.TemporaryDirectory() as temporary, patch('urllib.request.urlopen') as network:
            root = Path(temporary)
            output = root / 'package.rpm'
            with self.assertRaisesRegex(RuntimeError, 'foreign'):
                repository.fetch('https://foreign.example/', 'Packages/k/kernel.rpm', output)
            output.write_bytes(b'existing')
            with self.assertRaisesRegex(RuntimeError, 'exists'):
                repository.fetch(repository.BASES['39-base'], 'Packages/k/kernel.rpm', output)
            redirected = root / 'link'
            redirected.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'redirected'):
                repository.fetch(repository.BASES['39-base'], 'Packages/k/kernel.rpm', redirected / 'new')
            network.assert_not_called()

    def test_only_loopback_bridge_and_private_repository_root(self):
        with patch('socket.create_connection') as network:
            for port in (0, 65536, True, '8080', None):
                with self.subTest(port=port), self.assertRaisesRegex(RuntimeError, 'invalid'):
                    bridge(port)
            network.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            redirected = root / 'redirected'
            redirected.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'redirected'):
                repository.RepositoryServer(redirected / 'output')

    def test_exact_published_key_and_signed_image_inventory(self):
        inventory = json.loads((upgrade.MAINTENANCE / 'fedora-upgrade-inputs.json').read_bytes())
        self.assertEqual(set(inventory['keys']), {'39', '41', '43', '44'})
        self.assertEqual(inventory['cloud']['sha256'],
                         'ab5be5058c5c839528a7d6373934e0ce5ad6c8f80bd71ed3390032027da52f37')
        for record in inventory['keys'].values():
            self.assertRegex(record['fingerprint'], '^[0-9A-F]{40}$')
            self.assertRegex(record['sha256'], '^[0-9a-f]{64}$')
            self.assertRegex(record['dns'], '^[0-9a-f]{56}._openpgpkey.fedoraproject.org$')


if __name__ == '__main__':
    unittest.main()
