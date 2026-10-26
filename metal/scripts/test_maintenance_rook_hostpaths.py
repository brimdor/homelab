"""Narrow hostPath labels must never recurse through the Rook parent/OSD data."""
import json
from pathlib import PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import maintenance_host_security as security


class LocalPath:
    def __init__(self, value):
        self.value = PurePosixPath(value)

    def __str__(self):
        return str(self.value)

    def __eq__(self, other):
        return isinstance(other, LocalPath) and self.value == other.value

    def __lt__(self, other):
        return str(self) < str(other)

    @property
    def name(self):
        return self.value.name

    @property
    def parents(self):
        return tuple(LocalPath(p) for p in self.value.parents)

    def is_dir(self):
        return True

    def is_symlink(self):
        return False

    def stat(self):
        return SimpleNamespace(st_dev=7)

    lstat = stat

    def glob(self, pattern):
        assert str(self) == '/var/lib/rook' and pattern == 'mon-*'
        return (LocalPath('/var/lib/rook/mon-o'),)

    def rglob(self, pattern):
        assert str(self) != '/var/lib/rook', 'would traverse OSD data'
        return (LocalPath(str(self) + '/data'),) if self.name == 'mon-o' else ()


class RookHostPaths(unittest.TestCase):
    def exercise(self, extra_mount):
        calls = []

        def native(*argv):
            calls.append(argv)
            if argv[0] == 'findmnt':
                return json.dumps({'filesystems': [{'target': '/', 'fstype': 'ext4'}, extra_mount]})
            if argv[0] == 'matchpathcon':
                return 'system_u:object_r:container_file_t:s0'
            return ''

        with patch.object(security, 'Path', LocalPath), patch.object(
                security.os, 'getxattr', return_value=b'system_u:object_r:container_file_t:s0\0', create=True):
            security.rook_hostpaths(native)
        return calls

    def test_parent_is_not_recursive_and_monitor_is(self):
        calls = self.exercise({'target': '/var/lib/rook/osd-owned/mount', 'fstype': 'xfs'})
        self.assertIn(('restorecon', '-F', '-x', '/var/lib/rook'), calls)
        self.assertIn(('restorecon', '-R', '-F', '-x', '/var/lib/rook/mon-o'), calls)
        self.assertNotIn(('restorecon', '-R', '-F', '-x', '/var/lib/rook'), calls)
        self.assertIn(('semanage', 'fcontext', '-a', '-t', 'container_file_t', '-r', 's0',
                       '/var/lib/rook/mon-o(/.*)?'), calls)

    def test_monitor_nested_mount_refused(self):
        with self.assertRaisesRegex(AssertionError, 'mounted data under Rook hostPath'):
            self.exercise({'target': '/var/lib/rook/mon-o/data', 'fstype': 'ext4'})


if __name__ == '__main__':
    unittest.main()
