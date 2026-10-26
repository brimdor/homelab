"""Unavailable read-only recovery sources must remove their private mountpoint."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import maintenance_squirtle_images as IMAGES


class ReadOnlySourceTests(unittest.TestCase):
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
