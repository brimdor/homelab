"""Refuse unrelated policy and unsafe local transcode trees before writes."""

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import maintenance_emby_hostpath as hostpath


class EmbyHostpathTests(unittest.TestCase):
    def test_only_exact_compatible_policy_can_be_reused(self):
        self.assertFalse(hostpath.desired_policy([]))
        self.assertTrue(hostpath.desired_policy([hostpath.PATTERN + ' all files ' + hostpath.LABEL]))
        for lines in ([hostpath.PATTERN + ' all files system_u:object_r:var_lib_t:s0'],
                      [hostpath.PATTERN + ' all files ' + hostpath.LABEL] * 2):
            with self.assertRaisesRegex(RuntimeError, 'conflicting'):
                hostpath.desired_policy(lines)

    def test_inventory_rejects_foreign_roots_links_and_special_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'emby-transcode'
            root.mkdir()
            (root / 'transcoding-temp').mkdir()
            file = root / 'transcoding-temp/data'
            file.write_bytes(b'preserved fixture')
            original_stat = Path.stat
            device = root.stat().st_dev

            def selected_stat(path, *args, **kwargs):
                if str(path) == '/' and kwargs.get('follow_symlinks', True):
                    return SimpleNamespace(st_dev=device)
                return original_stat(path, *args, **kwargs)

            with patch.object(hostpath, 'ROOT', root), patch.object(Path, 'stat', selected_stat):
                self.assertEqual(len(hostpath.inventory(root)), 3)
                with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                    hostpath.inventory(root.parent)
                link = root / 'foreign'
                for create in (lambda: link.symlink_to(file),
                               lambda: os.link(file, link), lambda: os.mkfifo(link)):
                    create()
                    with self.assertRaisesRegex(RuntimeError, 'unsafe'):
                        hostpath.inventory(root)
                    link.unlink()
                self.assertEqual(file.read_bytes(), b'preserved fixture')


if __name__ == '__main__':
    unittest.main()
