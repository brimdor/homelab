#!/usr/bin/env python3
"""Reject old-boot status without replaying a combined ownership operation."""

import ast
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch

import maintenance_boot_qualification as subject
from test_maintenance_coordination import API


class BootReadinessTests(unittest.TestCase):
    def fixture(self):
        api = API()
        api.nodes = api.nodes[:1]
        api.nodes[0]['status']['nodeInfo'] = {'bootID': 'current-boot'}
        api.pods = api.pods[:1]
        api.pods[0]['status'].update(conditions=[{'type': key, 'status': 'True'} for key in
                                              ('PodReadyToStartContainers', 'ContainersReady', 'Ready')])
        api.pods[0]['status']['containerStatuses'][0]['state'] = {'running': {'startedAt': '2026-10-23T05:02:09Z'}}
        api.ds['status'] = {key: 1 for key in api.ds['status']}
        expected = {'daemonset_uid': 'ds-uid', 'node_uids': {'fixture-a': 'fixture-a-uid'}}
        started = datetime.fromisoformat('2026-10-23T04:58:00+00:00').timestamp()
        return api, expected, started

    def test_old_boot_or_container_cannot_pass_previously_ready_status(self):
        for changed in ('boot', 'container', 'condition', 'rollout', 'node'):
            api, expected, started = self.fixture()
            if changed == 'boot':
                api.nodes[0]['status']['nodeInfo']['bootID'] = 'previous-boot'
            elif changed == 'container':
                api.pods[0]['status']['containerStatuses'][0]['state']['running']['startedAt'] = '2026-10-23T04:55:04Z'
            elif changed == 'condition':
                api.pods[0]['status']['conditions'][0]['status'] = 'False'
            elif changed == 'rollout':
                api.ds['status']['numberAvailable'] = 0
            else:
                api.nodes[0]['status']['conditions'][0]['status'] = 'False'
            with self.subTest(changed=changed):
                self.assertFalse(subject.fresh_boot(api.ds, api.pods, api.nodes, expected, 'current-boot', started))
                self.assertEqual(api.writes, 0)

    def test_current_boot_requires_original_identity_runtime_and_digest(self):
        api, expected, started = self.fixture()
        self.assertTrue(subject.fresh_boot(api.ds, api.pods, api.nodes, expected, 'current-boot', started))
        for changed in ('uid', 'owner', 'image'):
            altered, _, _ = self.fixture()
            if changed == 'uid':
                altered.nodes[0]['metadata']['uid'] = 'foreign'
            elif changed == 'owner':
                altered.pods[0]['metadata']['ownerReferences'][0]['uid'] = 'foreign'
            else:
                altered.pods[0]['status']['containerStatuses'][0]['imageID'] = 'foreign'
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                subject.fresh_boot(altered.ds, altered.pods, altered.nodes, expected, 'current-boot', started)

    def test_actual_resume_is_transformed_once_and_original_failure_never_replayed(self):
        tree = ast.parse(Path(subject.diagnostic.combined.__file__).read_text())
        body = next(node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Attribute) and node.func.attr == 'guest' and node.args and
                    isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and
                    subject.RESUME in node.args[0].value)
        fixture = object.__new__(subject.Qualification)
        original = RuntimeError('actual refusal')
        with patch.object(subject.diagnostic.Qualification, 'guest', side_effect=original) as guest:
            with self.assertRaises(RuntimeError) as error:
                fixture.guest(body)
        self.assertIs(error.exception, original)
        guest.assert_called_once()
        program = guest.call_args.args[0]
        compile(program, '<actual-current-boot-resume>', 'exec')
        self.assertNotIn(subject.RESUME, program)
        self.assertEqual(program.count('value=context();post_boot_ready(value);'), 1)


if __name__ == '__main__':
    unittest.main()
