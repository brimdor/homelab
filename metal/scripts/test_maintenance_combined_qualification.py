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
        self.assertEqual(len(bodies), 2)
        for body in bodies:
            compile(body, '<actual-guest-body>', 'exec')


if __name__ == '__main__':
    unittest.main()
