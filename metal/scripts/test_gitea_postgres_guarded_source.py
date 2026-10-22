"""Refuse a changed or already running source before any capture or SQL."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gitea_postgres_guarded_source as source
from test_gitea_postgres_control import SYNTHETIC


class GuardedSourceTests(unittest.TestCase):
    def test_sync_framing_preserves_exact_native_control_bytes(self):
        self.assertEqual(source.parse_sync_control(SYNTHETIC + b'\n\n'),
                         source.cold.control.parse_control(SYNTHETIC))
        for raw in (SYNTHETIC, SYNTHETIC + b'\n', SYNTHETIC + b'\n\n\n',
                    SYNTHETIC + b'WARNING: checksum differs\n\n\n'):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                source.parse_sync_control(raw)

    def test_durable_intent_is_exclusive_and_contains_no_credential(self):
        uid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(source.common, 'ROOT', Path(temporary)), \
                patch.object(source.common, 'require_host'), patch.object(source.common, 'private_root'), \
                patch.object(source.cold, 'verify', return_value={'format': source.cold.GUARDED_FORMAT, 'source': {}}):
            result = source.intent(Path(temporary) / 'point', 'a' * 64, {}, 'b' * 64, uid, uid)
            self.assertTrue(result['exclusive_creation'])
            path = Path(temporary) / 'gitea-postgres-role-103-intent.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('password', path.read_text())
            with self.assertRaises(FileExistsError):
                source.intent(Path(temporary) / 'point', 'a' * 64, {}, 'b' * 64, uid, uid)

    def test_exact_idle_tasks_and_readiness_only(self):
        tasks = {100: ({}, 1, source.STARTUP), 101: ({}, 10, source.CONTROLLER),
                 102: ({}, 11, ['flock', '--exclusive', '9'])}
        self.assertEqual(source.guard_tasks(tasks, 100, 10)[0], 101)
        tasks[101] = ({}, 10, source.CAPTURE_CONTROLLER)
        self.assertEqual(source.guard_tasks(tasks, 100, 10)[0], 101)
        tasks[103] = ({}, 12, source.READINESS)
        self.assertEqual(source.guard_tasks(tasks, 100, 10)[0], 101)
        tasks[103] = ({}, 12, ['postgres', '--single'])
        with self.assertRaises(RuntimeError):
            source.guard_tasks(tasks, 100, 10)
        tasks.pop(103)
        tasks.pop(102)
        with self.assertRaises(RuntimeError):
            source.guard_tasks(tasks, 100, 10)

    def test_foreign_request_never_reaches_host_or_runtime(self):
        with patch.object(source.common, 'require_host') as host, patch.object(source.common, 'command') as command:
            for core, pid in [({}, 10), ({'namespace': 'other'}, 10), ({}, True)]:
                with self.subTest(core=core), self.assertRaises(RuntimeError):
                    source.observe(core, pid)
            host.assert_not_called()
            command.assert_not_called()

    def test_maintained_guard_requires_exact_capture_only_tasks_and_probe(self):
        image = source.cold.control.MAINTAINED_IMAGE
        tasks = {100: ({}, 1, source.MAINTAINED_STARTUP),
                 101: ({}, 10, source.CAPTURE_CONTROLLER),
                 102: ({}, 11, ['flock', '--exclusive', '9']),
                 103: ({}, 12, source.MAINTAINED_READINESS)}
        self.assertEqual(source.guard_tasks(tasks, 100, 10, image=image)[0], 101)
        for pid, command in ((100, source.STARTUP), (101, source.CONTROLLER), (103, source.READINESS)):
            changed = copy.deepcopy(tasks)
            changed[pid] = (*changed[pid][:2], command)
            with self.assertRaises(RuntimeError):
                source.guard_tasks(changed, 100, 10, image=image)

    def test_running_original_postmaster_cannot_be_captured(self):
        core = {'namespace': 'gitea', 'pod': 'gitea-postgresql-0', 'image': source.cold.control.IMAGE,
                'pv': 'pvc-4d6d356d-ec5d-4f2e-961e-090eae9e0c21',
                'pod_uid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', 'container_id': 'a' * 64,
                'node': 'totodile'}
        runtime = {'status': {'id': core['container_id'], 'state': 'CONTAINER_RUNNING',
                              'imageRef': core['image'], 'metadata': {'name': 'postgresql'}},
                   'info': {'runtimeSpec': {'process': {'args': ['postgres', '-D', source.recovery.DATA]}}}}
        class Result:
            stdout = json.dumps(runtime).encode()
        with patch.object(source.common, 'require_host'), patch.object(source.common, 'command', return_value=Result()) as command:
            with self.assertRaises(RuntimeError):
                source.observe(core, 123)
            self.assertEqual(command.call_count, 1)

    def test_capture_requires_same_guard_and_control_after_copy(self):
        binding = {'volume': {'source': '/exact/verified/source'}, 'image': source.cold.control.IMAGE}
        state = {'cluster_state': 'shut down'}
        changed = copy.deepcopy(binding)
        changed['volume']['source'] = '/changed/source'
        with patch.object(source, 'observe', side_effect=[(binding, state), (changed, state)]), \
                patch.object(source.common, 'run_identifier'), patch.object(source.common, 'private_root'), \
                patch.object(source.cold, 'capture', return_value=({'source': binding}, 'a' * 64)) as capture:
            with self.assertRaises(RuntimeError):
                source.capture({'node': 'totodile'}, 123, 'synthetic-test')
            self.assertEqual(capture.call_args.kwargs['source_binding'], binding)


if __name__ == '__main__':
    unittest.main()
