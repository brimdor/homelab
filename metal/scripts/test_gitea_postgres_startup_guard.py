"""Keep the deployable startup guardian bound to its native-qualified payload."""

from pathlib import Path
import unittest

import gitea_postgres_startup_guard as guard


class StartupGuardPayloadTests(unittest.TestCase):
    def test_chart_payload_matches_the_native_qualification(self):
        path = Path(__file__).resolve().parents[2] / 'platform/gitea/files/maintenance-startup.sh'
        header, body = path.read_text().split('\n', 1)
        self.assertEqual(header, '#!/bin/bash')
        self.assertEqual(body, guard.STARTUP)

    def test_capture_claim_cannot_dispatch_a_native_child(self):
        self.assertTrue(guard.CAPTURE_CLAIM.endswith('IFS= read -r _ || exit 0\nexit 64\n'))
        for forbidden in ('"$@"', 'native-child', '--single', 'request', 'wait "$child"'):
            self.assertNotIn(forbidden, guard.CAPTURE_CLAIM)


if __name__ == '__main__':
    unittest.main()
