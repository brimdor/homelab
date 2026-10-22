"""Capture-only refusal and actual blocked-probe cleanup contracts."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import gitea_cohort_recovery as cohort
from test_valkey_cohort_point import core


class CohortControllerTests(unittest.TestCase):
    def test_finite_pause_integer_crosses_actual_subprocess_argv_as_text(self):
        instance = cohort.Controller(['kubectl'], None)
        def execute(_item, *args):
            return subprocess.run([sys.executable, '-B', '-c',
                'import json,sys;print(json.dumps(sys.argv[1:]))', *args], capture_output=True, check=True)
        with patch.object(instance, 'execute', side_effect=execute):
            raw = instance.valkey_cli(core(), 'CLIENT', 'PAUSE', 60000, 'WRITE')
        self.assertEqual(json.loads(raw), ['valkey-cli', '--raw', 'CLIENT', 'PAUSE', '60000', 'WRITE'])

    def test_unbound_capture_never_contacts_cluster_or_enters_role_recovery(self):
        instance = cohort.Controller(['kubectl'], None)
        self.assertTrue(instance.capture_only)
        with patch.object(instance, 'call') as call:
            with self.assertRaises(RuntimeError):
                instance.capture('unbound-103', 'a' * 40, lambda *_a, **_k: None)
            with self.assertRaises(RuntimeError):
                instance.recover('unbound-103', lambda *_a, **_k: None)
            call.assert_not_called()

    def test_uncertain_pause_acknowledgement_always_unpauses(self):
        instance = cohort.Controller(['kubectl'], None)
        cores = {'0': {'ordinal': '0'}}
        with patch.object(instance, 'assert_held'), patch.object(instance, 'valkey_core', return_value=cores), \
                patch.object(instance, 'topology', return_value='a' * 64), \
                patch.object(instance, 'native_bindings', return_value={}), \
                patch.object(instance, 'valkey_cli', side_effect=[RuntimeError('uncertain acknowledgement'), b'OK']) as cli:
            with self.assertRaisesRegex(RuntimeError, 'uncertain acknowledgement'):
                instance.capture_valkey({}, 'uncertain-103', lambda *_a, **_k: None)
            self.assertEqual(cli.call_count, 2)
            self.assertEqual(cli.call_args.args, (cores['0'], 'CLIENT', 'UNPAUSE'))

    def test_expired_common_lease_refuses_commit_and_reaps_actual_probes(self):
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary) / 'release'
            script = ("import pathlib,sys,time;sys.stdin.buffer.readline();"
                      "print('HOMELAB103:WRITE-BLOCKED',flush=True)\n"
                      "while not pathlib.Path(sys.argv[1]).exists():time.sleep(0.01)\n"
                      "print('HOMELAB103:WRITE-RELEASED',flush=True)\n")
            bundle = Mock()
            bundle.command.return_value = [sys.executable, '-B', '-c', script, str(release)]
            bundle.request.return_value = b'{}\n'
            bundle.valkey_transfer.return_value = {'synthetic': True}
            instance = cohort.Controller(['kubectl'], bundle)
            cores = {n: core(n) for n in cohort.valkey.CLAIMS}
            children, original = [], subprocess.Popen
            def spawn(*args, **kwargs):
                child = original(*args, **kwargs)
                children.append(child)
                return child
            def cli(_core, *args):
                if args == ('CLIENT', 'UNPAUSE'):
                    release.touch()
                return b'OK'
            try:
                with patch.object(instance, 'assert_held'), patch.object(instance, 'valkey_core', return_value=cores), \
                        patch.object(instance, 'topology', return_value='a' * 64), \
                        patch.object(instance, 'native_bindings', return_value={}), \
                        patch.object(instance, 'valkey_cli', side_effect=cli), \
                        patch.object(cohort.subprocess, 'Popen', side_effect=spawn), \
                        patch.object(cohort.time, 'monotonic', side_effect=[0, 61]):
                    with self.assertRaisesRegex(RuntimeError, 'common WRITE exclusion interval was lost'):
                        instance.capture_valkey({}, 'expired-103', lambda *_a, **_k: None)
                bundle.run.assert_not_called()
                self.assertEqual(len(children), 6)
                self.assertTrue(all(c.poll() == 0 and c.stdout.closed and c.stderr.closed for c in children))
            finally:
                release.touch()
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.communicate()
                    for stream in (child.stdout, child.stderr):
                        if not stream.closed:
                            stream.close()

if __name__ == '__main__':
    unittest.main()
