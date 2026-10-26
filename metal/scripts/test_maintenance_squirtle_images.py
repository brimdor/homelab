"""Unavailable read-only recovery sources must remove their private mountpoint."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import shutil
import types
import unittest
from unittest.mock import patch

import maintenance_squirtle_images as IMAGES


class ReadOnlySourceTests(unittest.TestCase):
    def test_original_oci_bytes_export_and_changed_blob_refusal(self):
        for damaged in (False, True):
            with self.subTest(damaged=damaged), tempfile.TemporaryDirectory() as directory:
                mount = Path(directory) / 'owned-mount';root = mount / 'test/blobs/sha256'
                root.mkdir(parents=True)
                config, layer = b'{"architecture":"amd64","os":"linux"}', b'original compressed layer'
                descriptor = lambda data: {'digest': 'sha256:' + hashlib.sha256(data).hexdigest(), 'size': len(data)}
                manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                            'config': descriptor(config), 'layers': [descriptor(layer), descriptor(layer)]}
                raw = json.dumps(manifest).encode();digest = descriptor(raw)['digest']
                for data in (raw, config, layer): (root / descriptor(data)['digest'][7:]).write_bytes(data)
                if damaged: (root / descriptor(layer)['digest'][7:]).write_bytes(b'X' + layer[1:])
                active = [False]
                def run(argv, **kwargs):
                    if argv[0] == 'mount': active[0] = True
                    elif argv[0] == 'umount':
                        active[0] = False
                        shutil.rmtree(mount / 'test')
                    else: self.fail('unexpected command')
                    return subprocess.CompletedProcess(argv, 0, b'', b'')
                view = {'filesystems': [{'source': IMAGES.NAS, 'fstype': 'nfs',
                                        'options': 'ro,nosuid,nodev,noexec,nosharecache'}]}
                output = io.BytesIO()
                values = {'NAS': IMAGES.NAS, 'REPOSITORY': 'test', 'DIGEST': digest,
                          'CONFIG': descriptor(config)['digest'], 'BLOB_COUNT': 3, 'IMAGE': 'example/test:original'}
                with patch('os.geteuid', return_value=0), patch('socket.gethostname', return_value='pikachu'), \
                        patch.object(Path, 'read_text', return_value='0a7daf8b33244d9d85f46223c3582da9'), \
                        patch('subprocess.check_output', side_effect=['76e53a95-725a-4430-9d7b-a8db413f3997\n', json.dumps(view).encode()]), \
                        patch('os.readlink', side_effect=lambda path: path), patch('tempfile.mkdtemp', return_value=str(mount)), \
                        patch('os.path.ismount', side_effect=lambda _: active[0]), patch('subprocess.run', side_effect=run), \
                        patch('sys.stdout', types.SimpleNamespace(buffer=output)):
                    if damaged:
                        with self.assertRaises(AssertionError): exec(compile(IMAGES.NAS_EXPORT, 'original-export', 'exec'), values)
                    else:
                        exec(compile(IMAGES.NAS_EXPORT, 'original-export', 'exec'), values)
                self.assertFalse(active[0]);self.assertFalse(mount.exists())
                if not damaged:
                    with tarfile.open(fileobj=io.BytesIO(output.getvalue())) as archive:
                        self.assertEqual(len(archive.getnames()), len(set(archive.getnames())))
                        index = json.load(archive.extractfile('index.json'))
                        self.assertEqual(index['manifests'][0]['digest'], digest)
                        self.assertEqual(archive.extractfile('blobs/sha256/' + digest[7:]).read(), raw)
                        self.assertEqual(archive.extractfile('blobs/sha256/' + descriptor(layer)['digest'][7:]).read(), layer)

    def test_failed_mount_never_reads_or_changes_source_and_removes_owned_directory(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: root.rmdir() if root.exists() else None)
        output = io.StringIO()
        with patch('os.geteuid', return_value=0), patch('socket.gethostname', return_value='pikachu'), \
                patch.object(Path, 'read_text', return_value='0a7daf8b33244d9d85f46223c3582da9'), \
                patch('subprocess.check_output', return_value='76e53a95-725a-4430-9d7b-a8db413f3997\n'), \
                patch('os.readlink', side_effect=lambda path: path), patch('tempfile.mkdtemp', return_value=str(root)), \
                patch('os.path.ismount', return_value=False), \
                patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, b'', b'')) as run, \
                contextlib.redirect_stdout(output):
            exec(compile(IMAGES.NAS_READ, 'readonly-source', 'exec'),
                 {'NAS': IMAGES.NAS, 'PV_UID': IMAGES.PV_UID, 'PVC_UID': IMAGES.PVC_UID, 'BLOBS': IMAGES.BLOBS})
        options = run.call_args.args[0][4].split(',')
        self.assertTrue({'ro', 'nosuid', 'nodev', 'noexec', 'nosharecache'} <= set(options))
        self.assertNotIn('rw', options)
        result = json.loads(output.getvalue())
        self.assertFalse(result['accepted'])
        self.assertTrue(result['owned_mount_removed'])
        self.assertFalse(root.exists())


if __name__ == '__main__':
    unittest.main()
