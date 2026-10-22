"""Bind Gitea's initialization hold to the reviewed common lock algorithm."""

import unittest
from pathlib import Path

import gitea_init_guard as guard
import gitea_postgres_startup_guard as postgres


class GiteaInitGuardTests(unittest.TestCase):
    def test_deployable_payload_matches_native_qualification(self):
        path = Path(__file__).resolve().parents[2] / 'platform/gitea/files/maintenance-gitea-init.sh'
        header, body = path.read_text().split('\n', 1)
        self.assertEqual(header, '#!/bin/bash')
        self.assertEqual(body, guard.STARTUP)

    def test_shared_startup_changes_only_app_identity_path_and_completion(self):
        self.assertEqual(guard.STARTUP, postgres.STARTUP.replace(postgres.STATE, guard.STATE).replace(
            '1001:', '1000:').replace('flock --exclusive 9', 'flock -x 9').replace('exec "$@"', 'exit 0'))
        self.assertNotIn('1001', guard.STARTUP)
        self.assertNotIn(postgres.STATE, guard.STARTUP)
        self.assertNotIn('exec "$@"', guard.STARTUP)

    def test_claim_never_executes_input(self):
        self.assertIn('flock -xn 9', guard.CLAIM)
        self.assertTrue(guard.CLAIM.endswith('IFS= read -r _ || exit 0\nexit 64\n'))
        self.assertNotIn('"$@"', guard.CLAIM)


if __name__ == '__main__':
    unittest.main()
