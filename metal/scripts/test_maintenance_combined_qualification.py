"""Reject unsafe OCI fixture inputs and compile every actual guest program."""

import ast
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import maintenance_combined_qualification as fixture


class CombinedQualificationInputs(unittest.TestCase):
    def archive(self, path, extra=None, wrong_digest=False):
        blob = b'{"synthetic":"root only"}'
        checksum = hashlib.sha256(blob).hexdigest()
        index = {'schemaVersion': 2, 'manifests': [{'digest': 'sha256:' + (('0' * 64) if wrong_digest else checksum),
                 'annotations': {'org.opencontainers.image.ref.name': 'ghcr.io/kubereboot/kured:1.21.0'}}]}
        with tarfile.open(path, 'w') as archive:
            for name, data in [('index.json', json.dumps(index).encode()), ('oci-layout', b'{"imageLayoutVersion":"1.0.0"}'),
                               ('blobs/sha256/' + checksum, blob)]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            if extra:
                info = tarfile.TarInfo(extra)
                info.type = tarfile.SYMTYPE
                info.linkname = '/never-read'
                archive.addfile(info)
        return checksum

    def test_exact_root_and_complete_blob_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.tar'
            checksum = self.archive(path)
            with patch.object(fixture, 'KURED', checksum):
                self.assertEqual(fixture.archive_identity(path), hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(RuntimeError, 'root blob missing'):
                fixture.archive_identity(path)

    def test_unsafe_members_and_changed_root_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.tar'
            for name in ('../../escape', 'blobs/sha256/' + 'a' * 64):
                self.archive(path, extra=name)
                with self.assertRaisesRegex(RuntimeError, 'archive member'):
                    fixture.archive_identity(path)
            checksum = self.archive(path, wrong_digest=True)
            with patch.object(fixture, 'KURED', checksum), self.assertRaisesRegex(RuntimeError, 'root digest differs'):
                fixture.archive_identity(path)

    def test_every_embedded_guest_body_compiles(self):
        tree = ast.parse(Path(fixture.__file__).read_text())
        bodies = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and
                  isinstance(node.func, ast.Attribute) and node.func.attr == 'guest' and node.args and
                  isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
        self.assertEqual(len(bodies), 3)
        for body in bodies:
            compile(body, '<actual-guest-body>', 'exec')

    def test_complete_guest_header_compiles(self):
        qualification = object.__new__(fixture.Qualification)
        qualification.args = SimpleNamespace(revision='a' * 40)
        qualification.ssh = []
        captured = []
        qualification.command = lambda _args, **kwargs: captured.append(kwargs['data']) or b'{}'
        self.assertEqual(qualification.guest('print(json.dumps({}))'), {})
        compile(captured[0], '<actual-complete-guest-program>', 'exec')

    def test_actual_vendor_install_step_refuses_wrong_context_or_enforcement(self):
        tree = ast.parse(Path(fixture.__file__).read_text())
        body = next(node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Attribute) and node.func.attr == 'guest' and node.args and
                    isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and
                    'binary_context=' in node.args[0].value)
        # Execute the actual installation security boundary, before any service can start.
        program = compile(body[body.index("assert enforcement=='1'"):body.index("assert b'v1.33.6+k3s1'")],
                          '<actual-vendor-install-step>', 'exec')
        for enforcing, policy, context, fails in (
                ('1', True, b'system_u:object_r:container_runtime_exec_t:s0\0', False),
                ('0', True, b'system_u:object_r:container_runtime_exec_t:s0\0', True),
                ('1', False, b'system_u:object_r:container_runtime_exec_t:s0\0', True),
                ('1', True, b'system_u:object_r:init_var_lib_t:s0\0', True)):
            calls = []
            namespace = {'enforcement': enforcing, 'state': SimpleNamespace(read_text=lambda: enforcing),
                         'pathlib': SimpleNamespace(Path=lambda _: SimpleNamespace(is_file=lambda: policy)),
                         'os': SimpleNamespace(getxattr=lambda *args: context),
                         'native': lambda *args: calls.append(args)}
            with self.subTest(enforcing=enforcing, policy=policy, context=context):
                if fails:
                    with self.assertRaises(AssertionError):
                        exec(program, namespace)
                else:
                    exec(program, namespace)
                self.assertEqual(calls, [] if enforcing != '1' or not policy else [
                    ('chcon', '-u', 'system_u', '-r', 'object_r', '-t',
                     'container_runtime_exec_t', '/usr/local/bin/k3s')])

    def test_actual_digest_import_requires_exact_native_cri_reference(self):
        tree = ast.parse(Path(fixture.__file__).read_text())
        body = next(node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Attribute) and node.func.attr == 'guest' and node.args and
                    isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and
                    'digest_ref=' in node.args[0].value)
        program = compile(body[body.index("native('/usr/local/bin/k3s','ctr'"):body.index('# No host channel')],
                          '<actual-offline-digest-import>', 'exec')
        reference = 'ghcr.io/kubereboot/kured@sha256:' + fixture.KURED
        for digests, fails in (([reference], False), ([], True), ([reference[:-1] + '0'], True)):
            calls = []
            def native(*args):
                calls.append(args)
                return json.dumps({'status': {'repoDigests': digests}}).encode()
            namespace = {'native': native, 'images': Path('/owned'), 'json': json,
                         'global_owner': SimpleNamespace(IMAGE=reference.replace('@', ':1.21.0@'))}
            with self.subTest(digests=digests):
                if fails:
                    with self.assertRaises(AssertionError):
                        exec(program, namespace)
                else:
                    exec(program, namespace)
                self.assertEqual(calls[0], ('/usr/local/bin/k3s', 'ctr', 'images', 'import', '--local',
                                           '--digests', '--all-platforms', '--no-unpack', '--base-name',
                                           'ghcr.io/kubereboot/kured', '/owned/kured.tar'))


if __name__ == '__main__':
    unittest.main()
