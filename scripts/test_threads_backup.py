#!/usr/bin/env python3
"""Exercise backup publication and retention with synthetic, offline clients."""

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "apps/postgres/scripts/backup-threads.sh"
OWNER = "homelab-postgres-threads-v1\n"


class ThreadsBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="threads-backup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "threads"
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.tool("pg_dump", """
import os, sys
from pathlib import Path
target = Path(next(arg[7:] for arg in sys.argv[1:] if arg.startswith('--file=')))
mode = os.environ.get('FAKE_MODE', '')
if mode == 'dump-failure':
    print(os.environ['PGPASSWORD'], file=sys.stderr)
    sys.exit(1)
target.write_bytes(b'' if mode == 'empty' else b'VALID synthetic archive')
if mode == 'warning':
    print(os.environ['PGPASSWORD'], file=sys.stderr)
if mode == 'collision':
    (target.parent.parent / target.name).write_bytes(b'FOREIGN')
""")
        self.tool("pg_restore", """
import os, sys
from pathlib import Path
sys.exit(1 if os.environ.get('FAKE_MODE') == 'bad-archive' else
         0 if Path(sys.argv[-1]).read_bytes().startswith(b'VALID') else 1)
""")
        self.tool("sha256sum", """
import hashlib, sys
from pathlib import Path
name = next(arg for arg in sys.argv[1:] if arg != '--')
print(hashlib.sha256(Path(name).read_bytes()).hexdigest() + '  ' + name)
""")

    def tool(self, name, source):
        import sys

        target = self.bin / name
        target.write_text("#!" + sys.executable + "\n" + source)
        target.chmod(0o700)

    def run_backup(self, mode="", success=True):
        environment = dict(os.environ, BACKUP_DIR=str(self.root),
                           PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                           FAKE_MODE=mode, PGPASSWORD="synthetic-credential")
        result = subprocess.run(["/bin/bash", str(SCRIPT)], env=environment,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        self.assertNotIn(environment["PGPASSWORD"], result.stdout + result.stderr)
        self.assertEqual(list(self.root.glob(".partial.*")), [])
        return result

    def archives(self):
        return sorted(self.root.glob("threads-*.dump"))

    def expire(self, archive):
        old = time.time() - 16 * 86400
        for path in (archive, Path(str(archive) + ".sha256"), Path(str(archive) + ".owner")):
            if path.exists() or path.is_symlink():
                os.utime(path, (old, old), follow_symlinks=False)

    def test_complete_private_archive_with_checksum_and_owner(self):
        self.run_backup()
        archive, = self.archives()
        self.assertEqual(archive.read_bytes(), b"VALID synthetic archive")
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(Path(str(archive) + ".owner").read_text(), OWNER)
        self.assertEqual(Path(str(archive) + ".sha256").read_text(),
                         hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")

    def test_failed_empty_warning_or_unreadable_dump_is_never_published(self):
        for mode in ("dump-failure", "empty", "warning", "bad-archive"):
            with self.subTest(mode=mode):
                self.run_backup(mode, success=False)
                self.assertEqual(self.archives(), [])

    def test_existing_name_is_never_overwritten_or_claimed(self):
        self.run_backup("collision", success=False)
        archive, = self.archives()
        self.assertEqual(archive.read_bytes(), b"FOREIGN")
        self.assertFalse(Path(str(archive) + ".owner").exists())
        self.assertFalse(Path(str(archive) + ".sha256").exists())

    def test_transient_empty_nfs_directory_cleanup_preserves_success(self):
        self.tool("rm", """
import shutil, sys
from pathlib import Path
directory = Path(sys.argv[-1])
for child in directory.iterdir():
    if child.is_dir():
        shutil.rmtree(child)
    else:
        child.unlink()
sys.exit(1)  # Simulate NFS ENOTEMPTY after every owned entry was removed.
""")
        self.run_backup()
        self.assertEqual(len(self.archives()), 1)

    def test_only_expired_complete_owned_generation_is_removed(self):
        unrelated = self.directory / "db-existing.dump"
        unrelated.write_bytes(b"PREEXISTING")
        self.run_backup()
        old, = self.archives()
        self.expire(old)
        self.run_backup()
        self.assertFalse(old.exists())
        self.assertFalse(Path(str(old) + ".owner").exists())
        self.assertFalse(Path(str(old) + ".sha256").exists())
        self.assertEqual(len(self.archives()), 1)
        self.assertEqual(unrelated.read_bytes(), b"PREEXISTING")

    def test_corrupt_expired_backup_is_preserved_and_reported(self):
        self.run_backup()
        old, = self.archives()
        old.write_bytes(b"CORRUPT")
        self.expire(old)
        self.run_backup(success=False)
        self.assertEqual(old.read_bytes(), b"CORRUPT")
        self.assertEqual(len(self.archives()), 2)

    def test_foreign_expired_owner_is_preserved(self):
        self.run_backup()
        old, = self.archives()
        Path(str(old) + ".owner").write_text("foreign\n")
        self.expire(old)
        self.run_backup(success=False)
        self.assertTrue(old.exists())

    def test_checksum_cannot_name_another_path(self):
        self.run_backup()
        old, = self.archives()
        Path(str(old) + ".sha256").write_text("0" * 64 + "  ../another-file\n")
        self.expire(old)
        self.run_backup(success=False)
        self.assertTrue(old.exists())

    def test_expired_symlink_cannot_delete_its_target(self):
        self.run_backup()
        victim = self.directory / "protected"
        victim.write_bytes(b"PROTECTED")
        link = self.root / "threads-20000101T000000Z-abcdef.dump"
        link.symlink_to(victim)
        self.expire(link)
        self.run_backup(success=False)
        self.assertTrue(link.is_symlink())
        self.assertEqual(victim.read_bytes(), b"PROTECTED")

    def test_unowned_existing_directory_is_not_adopted(self):
        self.root.mkdir()
        original = self.root / "original"
        original.write_bytes(b"ORIGINAL")
        self.run_backup(success=False)
        self.assertFalse((self.root / ".owner").exists())
        self.assertEqual(original.read_bytes(), b"ORIGINAL")

    def test_symlinked_directory_is_not_followed(self):
        protected = self.directory / "protected"
        protected.mkdir()
        self.root.symlink_to(protected, target_is_directory=True)
        self.run_backup(success=False)
        self.assertEqual(list(protected.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
