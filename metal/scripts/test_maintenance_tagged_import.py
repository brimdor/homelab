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

    def test_atomic_stage_preserves_original_and_observes_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            source, profile, original_hash, _ = self.fixture(directory)
            staged = Path(directory) / 'staged.tar'; os.link(source, staged)
            candidate = Path(directory) / 'candidate.tar'
            result = tagged.convert(source, candidate, profile, original_hash)
            intent = Path(directory) / 'stage-intent.json'
            before = tagged.identity(source.stat())
            arguments = (source, candidate, staged, intent, original_hash, result['archive_sha256'])
            self.assertTrue(tagged.stage(*arguments)['mutation_performed'])
            self.assertTrue(staged.samefile(candidate)); self.assertFalse(staged.samefile(source))
            self.assertEqual(tagged.identity(source.stat())[:4], before[:4])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
            with patch.object(tagged.os, 'replace') as replace:
                observed = tagged.stage(*arguments)
            replace.assert_not_called(); self.assertTrue(observed['already_staged'])

    def test_interrupted_stage_recovers_only_proven_original_mapping(self):
        for location in ('before-replace', 'after-replace', 'changed-source'):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as directory:
                source, profile, original_hash, _ = self.fixture(directory)
                staged = Path(directory) / 'staged.tar'; os.link(source, staged)
                candidate = Path(directory) / 'candidate.tar'
                result = tagged.convert(source, candidate, profile, original_hash)
                intent = Path(directory) / 'stage-intent.json'
                arguments = (source, candidate, staged, intent, original_hash, result['archive_sha256'])
                if location == 'after-replace':
                    original_sync = tagged.sync_directory
                    def interrupted_sync(path):
                        if staged.samefile(candidate): raise InterruptedError('after atomic replace')
                        original_sync(path)
                    interrupt = patch.object(tagged, 'sync_directory', side_effect=interrupted_sync)
                else:
                    interrupt = patch.object(tagged.os, 'replace', side_effect=InterruptedError('before atomic replace'))
                with interrupt, self.assertRaises(InterruptedError): tagged.stage(*arguments)
                self.assertTrue(intent.exists())
                if location == 'changed-source':
                    os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1))
                    with self.assertRaises(RuntimeError), patch.object(tagged.os, 'replace') as replace:
                        tagged.stage(*arguments)
                    replace.assert_not_called(); self.assertTrue(staged.samefile(source))
                elif location == 'after-replace':
                    with patch.object(tagged.os, 'replace') as replace:
                        self.assertTrue(tagged.stage(*arguments)['already_staged'])
                    replace.assert_not_called()
                else:
                    self.assertTrue(tagged.stage(*arguments)['mutation_performed'])
                    self.assertTrue(staged.samefile(candidate))
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)

    def test_native_aliases_refuse_tag_collision_and_require_canonical(self):
        profile = {'image': 'registry/app@sha256:' + 'a' * 64,
                   'declared': 'registry/app:existing@sha256:' + 'a' * 64, 'digest': 'sha256:' + 'a' * 64}
        def output(arguments, **kwargs):
            reference = arguments[-1].removeprefix('name==')
            digest = 'sha256:' + ('b' if reference == 'registry/app:existing' else 'a') * 64
            return 'REF TYPE DIGEST SIZE PLATFORMS LABELS\n' + reference + ' type ' + digest + ' 1 B linux/amd64 -\n'
        with patch.object(tagged.subprocess, 'check_output', side_effect=output):
            with self.assertRaisesRegex(RuntimeError, 'another image'): tagged.native_aliases(profile)
        with patch.object(tagged.subprocess, 'check_output', return_value='REF TYPE DIGEST SIZE PLATFORMS LABELS\n'):
            with self.assertRaisesRegex(RuntimeError, 'disappeared'): tagged.native_aliases(profile)

    def test_native_host_requires_original_machine_runtime_and_idle_owner(self):
        original = json.loads(Path('metal/maintenance/tagged-image-import-inputs-103.json').read_text())
        def output(arguments, **kwargs):
            if arguments[0] == 'findmnt': return original['identity']['root_uuid'] + '\n'
            if arguments[0] == 'sha256sum':
                return ('0' * 64 if case == 'foreign-executable' else original['running_sha256']) + '  /proc/123/exe\n'
            if arguments[0] == '/proc/123/exe': return 'exe version v1.33.13+k3s2 (reviewed)\n'
            if arguments[-1] == '--version': return 'k3s version v1.33.13+k3s2 (reviewed)\n'
            if arguments[1] == 'show': return '123\n'
            return 'active\n'
        values = {'/etc/machine-id': original['identity']['machine'],
                  '/proc/sys/kernel/random/boot_id': '11111111-2222-3333-4444-555555555555',
                  '/proc/123/stat': '123 (k3s server) ' + ' '.join(['0'] * 19 + ['9876'])}
        for case in ('valid', 'cpu-changed', 'hash', 'foreign-executable', 'held-owner', 'reused-process'):
            with self.subTest(case=case):
                reads = []
                def read(path):
                    value = values[str(path)]
                    if str(path) == '/proc/123/stat':
                        reads.append(True)
                        if len(reads) > 1 and case == 'cpu-changed':
                            value = '123 (k3s server) ' + ' '.join(['0'] * 11 + ['1'] + ['0'] * 7 + ['9876'])
                        if len(reads) > 1 and case == 'reused-process': value = value.replace('9876', '9999')
                    return value
                inputs = {**original, 'runtime_sha256': '0' * 64} if case == 'hash' else original
                with patch.object(tagged.os, 'geteuid', return_value=0), \
                        patch.object(tagged.socket, 'gethostname', return_value='pikachu'), \
                        patch.object(Path, 'read_text', read), \
                        patch.object(Path, 'exists', return_value=case == 'held-owner'), \
                        patch.object(tagged, 'checked_file'), \
                        patch.object(tagged.subprocess, 'check_output', side_effect=output):
                    if case in ('valid', 'cpu-changed'):
                        self.assertEqual(tagged.native_host(inputs)['start_ticks'], '9876')
                    else:
                        with self.assertRaises(RuntimeError): tagged.native_host(inputs)

    def test_native_workflow_requires_new_success_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, profile, original_hash, _ = self.fixture(directory)
            key = 'fixture'; suffix = profile['digest'][7:15]
            original = root / 'recovery' / ('squirtle-image-' + key + '-' + suffix) / 'image.tar'
            original.parent.mkdir(parents=True); source.rename(original)
            staged = root / 'images' / ('maintenance103-squirtle-' + key + '-' + suffix + '.tar')
            staged.parent.mkdir(); os.link(original, staged)
            verified = original.parent / 'verified.json'; verified.write_bytes(b'protected verification')
            verified.chmod(0o600)
            before = original.stat()
            inputs = {'images': {key: {'original': '/var/lib/homelab-recovery/maintenance-103/' + original.parent.name + '/image.tar',
                       'staged': '/var/lib/rancher/k3s/agent/images/' + staged.name,
                       'archive_sha256': original_hash, 'verified_receipt_sha256': hashlib.sha256(verified.read_bytes()).hexdigest(),
                       'device': before.st_dev, 'inode': before.st_ino, 'bytes': before.st_size, 'links': 2}}}
            runtime = {'pid': 123, 'boot': '11111111-2222-3333-4444-555555555555'}
            journal = []
            def routed(value):
                value = str(value)
                for prefix, replacement in (('/var/lib/homelab-recovery/maintenance-103', root / 'recovery'),
                                            ('/var/lib/rancher/k3s/agent/images', root / 'images')):
                    if value == prefix or value.startswith(prefix + '/'):
                        return Path(str(replacement) + value[len(prefix):])
                return Path(value)
            def output(arguments, **kwargs):
                if arguments[0] == 'findmnt': return 'ext4\n'
                if '-n' in arguments:
                    return json.dumps({'_BOOT_ID': runtime['boot'].replace('-', ''), '__CURSOR': 'before'}) + '\n'
                self.assertEqual(arguments[:5], ['journalctl', '-u', 'k3s', '--after-cursor', 'before'])
                return ''.join(json.dumps(row) + '\n' for row in journal)
            aliases = {reference: {'digest': profile['digest'], 'CRI_pinned': True, 'K3s_pinned': True}
                       for reference in (profile['image'], profile['declared'].split('@')[0])}
            with patch.object(tagged, 'Path', side_effect=routed), patch.object(tagged, 'native_host', return_value=runtime), \
                    patch.object(tagged, 'native_aliases', return_value=aliases), \
                    patch.object(tagged.subprocess, 'check_output', side_effect=output):
                self.assertTrue(tagged.repair('prepare', key, inputs, profile)['prepared'])
                self.assertTrue(tagged.repair('stage', key, inputs, profile)['result']['mutation_performed'])
                with self.assertRaisesRegex(RuntimeError, 'success not observed'):
                    tagged.repair('observe', key, inputs, profile)
                journal.append({'_BOOT_ID': 'different-boot', '__CURSOR': 'foreign',
                                'MESSAGE': 'Imported 1 images from ' + str(staged) + ' in 1s'})
                with self.assertRaisesRegex(RuntimeError, 'success not observed'):
                    tagged.repair('observe', key, inputs, profile)
                journal.append({**journal[0], '_BOOT_ID': runtime['boot'].replace('-', ''), '__CURSOR': 'after'})
                self.assertTrue(tagged.repair('observe', key, inputs, profile)['accepted'])
                with patch.object(tagged.os, 'replace') as replace:
                    self.assertFalse(tagged.repair('stage', key, inputs, profile)['result']['mutation_performed'])
                replace.assert_not_called()
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), original_hash)
            self.assertEqual(original.stat().st_nlink, 1)
            self.assertEqual(verified.read_bytes(), b'protected verification')


if __name__ == '__main__':
    unittest.main()
