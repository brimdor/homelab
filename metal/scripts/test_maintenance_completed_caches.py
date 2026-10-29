"""Cache cleanup must refuse a different host before any cache command."""

from pathlib import Path
import unittest
from unittest.mock import patch

import maintenance_completed_caches as cleanup


class CacheIdentityTests(unittest.TestCase):
    def test_unknown_node_has_no_cleanup_program(self):
        with self.assertRaises(KeyError):
            cleanup.program('sprigatito')

    def test_reviewed_profiles_compile(self):
        for node in cleanup.PROFILES:
            compile(cleanup.program(node), node, 'exec')

    def test_wrong_identity_never_reaches_cleanup(self):
        for node, profile in cleanup.PROFILES.items():
            for mismatch in ('hostname', 'machine', 'root'):
                with self.subTest(node=node, mismatch=mismatch), \
                        patch('os.geteuid', return_value=0), \
                        patch('socket.gethostname', return_value='foreign' if mismatch == 'hostname' else node), \
                        patch.object(Path, 'read_text', return_value='foreign' if mismatch == 'machine' else profile['machine']), \
                        patch('subprocess.check_output', return_value='foreign'), \
                        patch('subprocess.run') as run:
                    with self.assertRaises(AssertionError):
                        exec(cleanup.program(node), {})
                    run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
