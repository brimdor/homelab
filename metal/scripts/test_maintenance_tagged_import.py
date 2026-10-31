"""Tagged OCI metadata conversion preserves protected hard-linked originals."""

import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import maintenance_tagged_import as tagged


class TaggedImportTests(unittest.TestCase):
    def fixture(self, directory, *, damaged=False, duplicate=False):
        config, layer = b'{"architecture":"amd64","os":"linux"}', b'unchanged compressed layer'
        def descriptor(data):
            return {'digest': 'sha256:' + hashlib.sha256(data).hexdigest(), 'size': len(data)}
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'config': descriptor(config), 'layers': [descriptor(layer), descriptor(layer)]}
        raw = json.dumps(manifest).encode(); digest = descriptor(raw)['digest']
        profile = {'image': 'registry.example:32309/app@' + digest,
                   'declared': 'registry.example:32309/app:existing-tag@' + digest,
                   'digest': digest, 'config': descriptor(config)['digest'], 'blobs': 3}
        index = {'schemaVersion': 2, 'manifests': [{**descriptor(raw), 'mediaType': manifest['mediaType'],
                 'platform': {'architecture': 'amd64', 'os': 'linux'},
                 'annotations': {'org.opencontainers.image.ref.name': profile['image']}}]}
        content = {'oci-layout': b'{"imageLayoutVersion":"1.0.0"}', 'index.json': json.dumps(index).encode()}
        content.update({'blobs/sha256/' + descriptor(data)['digest'][7:]: data for data in (raw, config, layer)})
        if damaged:
            content['blobs/sha256/' + descriptor(layer)['digest'][7:]] = b'X' + layer[1:]
        source = Path(directory) / 'original.tar'
        with tarfile.open(source, 'w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in content.items():
                entry = tarfile.TarInfo(name); entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            if duplicate:
                entry = tarfile.TarInfo('oci-layout'); entry.size = len(content['oci-layout'])
                archive.addfile(entry, io.BytesIO(content['oci-layout']))
        source.chmod(0o600)
        return source, profile, hashlib.sha256(source.read_bytes()).hexdigest(), content

    def test_only_reference_changes_and_hardlinked_original_stays_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            source, profile, original_hash, content = self.fixture(directory)
            staged = Path(directory) / 'old-staged.tar'; os.link(source, staged)
            before = tagged.identity(source.stat()); destination = Path(directory) / 'new.tar'
            result = tagged.convert(source, destination, profile, original_hash)
            self.assertEqual(tagged.identity(source.stat()), before)
            self.assertTrue(source.samefile(staged)); self.assertFalse(source.samefile(destination))
            self.assertEqual(hashlib.sha256(staged.read_bytes()).hexdigest(), original_hash)
            self.assertEqual(result['tagged_reference'], 'registry.example:32309/app:existing-tag')
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            with tarfile.open(destination) as archive:
                self.assertEqual(set(archive.getnames()), set(content))
                for name, data in content.items():
                    observed = archive.extractfile(name).read()
                    if name == 'index.json':
                        index = json.loads(data)
                        index['manifests'][0]['annotations']['org.opencontainers.image.ref.name'] = result['tagged_reference']
                        self.assertEqual(json.loads(observed), index)
                    else:
                        self.assertEqual(observed, data)

    def test_refuses_wrong_hash_blob_duplicate_tag_and_existing_destination(self):
        for case in ('hash', 'blob', 'duplicate', 'tag', 'existing'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                source, profile, original_hash, _ = self.fixture(directory, damaged=case == 'blob', duplicate=case == 'duplicate')
                destination = Path(directory) / 'new.tar'
                if case == 'hash': original_hash = '0' * 64
                if case == 'tag': profile['declared'] = profile['image']
                if case == 'existing': destination.write_bytes(b'preserve existing')
                with self.assertRaises(RuntimeError):
                    tagged.convert(source, destination, profile, original_hash)
                if case == 'existing': self.assertEqual(destination.read_bytes(), b'preserve existing')
                else: self.assertFalse(destination.exists())

    def test_refuses_symlink_and_removes_only_own_incomplete_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            source, profile, original_hash, _ = self.fixture(directory)
            link = Path(directory) / 'source-link.tar'; link.symlink_to(source)
            destination = Path(directory) / 'new.tar'
            with self.assertRaises(RuntimeError): tagged.convert(link, destination, profile, original_hash)
            self.assertFalse(destination.exists())
            original_copy = tagged.copy.copy
            def changed(member):
                os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1))
                return original_copy(member)
            with patch.object(tagged.copy, 'copy', side_effect=changed):
                with self.assertRaisesRegex(RuntimeError, 'source changed'):
                    tagged.convert(source, destination, profile, original_hash)
            self.assertFalse(destination.exists()); self.assertTrue(source.exists())


if __name__ == '__main__':
    unittest.main()
