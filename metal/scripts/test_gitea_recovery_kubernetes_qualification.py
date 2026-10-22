"""Bind synthetic fixture payloads to the actual recovery profile."""

from pathlib import Path
import unittest

import gitea_init_guard as application
import gitea_postgres_startup_guard as postgres
import gitea_recovery_kubernetes_qualification as fixture


class KubernetesFixtureTests(unittest.TestCase):
    def test_payloads_are_exact(self):
        root = Path(__file__).resolve().parents[2] / 'metal/maintenance/gitea-recovery-qualification/files'
        for name, body in [('maintenance-startup.sh', postgres.STARTUP),
                           ('maintenance-gitea-init.sh', application.STARTUP)]:
            self.assertEqual((root / name).read_text(), '#!/bin/bash\n' + body)

    def test_mutating_exec_stays_in_fixture_namespace(self):
        class Child:
            returncode = 0
            stdout = b'{}'
        calls = []
        q = fixture.Qualification(['kubectl', '--kubeconfig', '/existing/authorized/config'])
        q.pod = lambda name: calls.append(('identity', name))
        q.call = lambda *args, **kwargs: calls.append((args, kwargs)) or Child()
        q.execute(fixture.PG, 'postgresql', '/bin/true')
        self.assertEqual(calls[0], ('identity', fixture.PG))
        self.assertEqual(calls[1][0], ('exec', '-i', '-n', fixture.NAMESPACE, fixture.PG,
                                     '-c', 'postgresql', '--', '/bin/true'))


if __name__ == '__main__':
    unittest.main()
