"""Exercise stream parsing, secret containment and refusal before transaction."""

import json
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gitea_postgres_recovery_controller as controller
from test_gitea_postgres_account_recovery import catalog


class ControllerTests(unittest.TestCase):
    def test_actual_child_catalog_stream_with_prompt_and_eof_failure(self):
        raw = b'backend> HOMELAB103:' + json.dumps(catalog()).encode().hex().encode() + b'\nbackend> '
        for payload, accepted in ((raw, True), (b'backend> no catalog\n', False)):
            child = subprocess.Popen([sys.executable, '-B', '-c', 'import sys;sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))', payload.hex()],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                if accepted:
                    self.assertEqual(controller.Controller.read_catalog(child), catalog())
                else:
                    with self.assertRaises(RuntimeError):
                        controller.Controller.read_catalog(child)
            finally:
                child.communicate()
                child.stdout.close()
                child.stderr.close()

    def test_client_existing_password_only_on_attached_stdin(self):
        instance = controller.Controller(['kubectl'], None)
        instance.credentials = {'admin': "synthetic'$(never)", 'app': 'synthetic-app'}
        with patch.object(instance, 'execute', return_value=SimpleNamespace(stdout=b'accepted')) as execute:
            self.assertEqual(instance.client({}, 'postgres', 'psql', '-X'), b'accepted')
            self.assertNotIn('synthetic', str(execute.call_args.args))
            self.assertEqual(execute.call_args.kwargs['data'], b"synthetic'$(never)\n")

    def test_missing_prefetched_baseline_never_contacts_cluster(self):
        instance = controller.Controller(['kubectl'], None)
        with patch.object(instance, 'call') as call:
            with self.assertRaises(RuntimeError):
                instance.recover('fixture-103', lambda *_a, **_k: None)
            call.assert_not_called()

    def test_foreign_cluster_refused_before_any_secret_read(self):
        instance = controller.Controller(['kubectl'], None)
        with patch.object(instance, 'get', return_value={'metadata': {'uid': 'foreign'}}) as get:
            with self.assertRaises(RuntimeError):
                instance.baseline()
            self.assertEqual(get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
