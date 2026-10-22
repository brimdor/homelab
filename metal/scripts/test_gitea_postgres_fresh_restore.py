"""Keep fresh production restoration on the exact protected point contract."""

from pathlib import Path
import unittest
from unittest.mock import patch

import gitea_postgres_fresh_restore as restore


class FreshRestoreTests(unittest.TestCase):
    def test_foreign_point_never_reaches_docker(self):
        with patch.object(restore.common, 'require_host'), patch.object(restore.common, 'private_root'), \
                patch.object(restore.common, 'docker') as docker:
            with self.assertRaises(RuntimeError):
                restore.restore(Path('/tmp/foreign'), 'a' * 64, {}, b'', 'fixture-103')
            docker.assert_not_called()

    def test_historical_provenance_is_not_production_recovery_evidence(self):
        hba = b'synthetic parser fixture'
        class Digest:
            def hexdigest(self):
                return '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05'
        with patch.object(restore.common, 'require_host'), patch.object(restore.common, 'private_root'), \
                patch.object(restore.hashlib, 'sha256', return_value=Digest()), \
                patch.object(restore.cold, 'verify', return_value={'format': restore.cold.FORMAT}), \
                patch.object(restore.common, 'docker') as docker:
            with self.assertRaises(RuntimeError):
                restore.restore(restore.common.ROOT / 'gitea-postgres-guarded-fixture', 'a' * 64,
                                {'admin': 'synthetic', 'app': 'synthetic'}, hba, 'fixture-103')
            docker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
