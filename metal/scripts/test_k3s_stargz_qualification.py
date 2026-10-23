#!/usr/bin/env python3
"""Require real runtime evidence and confine the snapshotter creation flag."""

import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import k3s_stargz_qualification as subject


class StargzTests(unittest.TestCase):
    def fixture(self):
        return ({'version': 3, 'plugins': {'io.containerd.cri.v1.images': {
                    'snapshotter': 'stargz', 'disable_snapshot_annotations': False}}},
                'TYPE ID PLATFORMS STATUS\nio.containerd.snapshotter.v1 stargz linux/arm64 ok\n',
                {'a' * 64: {'ID': 'a' * 64, 'Snapshotter': 'stargz', 'SnapshotKey': 'owned-snapshot'}})

    def test_config_plugin_and_actual_running_snapshots_are_all_required(self):
        original = self.fixture()
        self.assertEqual(subject.require_runtime(*original)['plugin_status'], 'ok')
        for fault in ('snapshotter', 'annotations', 'plugin', 'platform', 'empty', 'foreign', 'snapshot'):
            config, plugins, containers = copy.deepcopy(original)
            if fault == 'snapshotter':
                config['plugins']['io.containerd.cri.v1.images']['snapshotter'] = 'overlayfs'
            elif fault == 'annotations':
                config['plugins']['io.containerd.cri.v1.images']['disable_snapshot_annotations'] = True
            elif fault == 'plugin':
                plugins = plugins.replace(' ok', ' error')
            elif fault == 'platform':
                plugins = plugins.replace('arm64', 'amd64')
            elif fault == 'empty':
                containers = {}
            elif fault == 'foreign':
                containers['a' * 64]['ID'] = 'b' * 64
            else:
                containers['a' * 64]['Snapshotter'] = 'overlayfs'
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                subject.require_runtime(config, plugins, containers)

    def test_creation_adds_only_exact_upstream_flag_without_mutating_caller(self):
        fixture = object.__new__(subject.Qualification)
        fixture.args = SimpleNamespace(k3d='owned-k3d', name='qualification-1234abcd')
        command = ['owned-k3d', 'cluster', 'create', fixture.args.name, '--servers=3', '--agents=2']
        with patch.object(subject.ha.Qualification, 'command', return_value=b'accepted') as parent:
            self.assertEqual(fixture.command(command, private=True), b'accepted')
        parent.assert_called_once_with([*command, subject.FLAG], private=True)
        self.assertNotIn(subject.FLAG, command)
        for changed in ([*command, '--snapshotter=overlayfs'], [*command[:3], 'foreign']):
            with self.assertRaisesRegex(RuntimeError, 'creation contract'):
                fixture.command(changed)
        with patch.object(subject.ha.Qualification, 'command', return_value=b'read') as parent:
            fixture.command(['docker', 'inspect', 'owned'])
        parent.assert_called_once_with(['docker', 'inspect', 'owned'])


if __name__ == '__main__':
    unittest.main()
