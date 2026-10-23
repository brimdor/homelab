#!/usr/bin/env python3
"""Require real runtime evidence and confine the snapshotter creation flag."""

import copy
import json
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

    def test_checkpoint_uses_packaged_ctr_and_exact_native_socket(self):
        fixture = object.__new__(subject.Qualification)
        fixture.versions = {'owned-node': 'baseline'}
        fixture.stages = [{}]
        fixture.inspect = lambda _node: None
        fixture.persist = lambda: None
        identifier = 'a' * 64
        fixture.kubectl = lambda *_args: {'items': [{'metadata': {}, 'spec': {'nodeName': 'owned-node'},
            'status': {'containerStatuses': [{'ready': True, 'state': {'running': {}},
                                              'containerID': 'containerd://' + identifier}]}}]}
        calls = []
        def command(arguments):
            calls.append(arguments)
            if arguments[3] == 'cat':
                return b'version=3\n[plugins."io.containerd.cri.v1.images"]\nsnapshotter="stargz"\ndisable_snapshot_annotations=false\n'
            self.assertEqual(arguments[:4], ['docker', 'exec', 'owned-node', '/bin/ctr'])
            if arguments[4:] == ['--version']:
                return b'ctr containerd v2.1.5-k3s1.33\n'
            self.assertEqual(arguments[4:6], ['--address=/run/k3s/containerd/containerd.sock', '--namespace=k8s.io'])
            if arguments[6:] == ['plugins', 'list']:
                return self.fixture()[1].encode()
            self.assertEqual(arguments[6:], ['containers', 'info', identifier])
            return json.dumps(self.fixture()[2][identifier]).encode()
        fixture.command = command
        with patch.object(subject.ha.Qualification, 'checkpoint'):
            fixture.checkpoint('baseline', 'baseline')
        self.assertEqual(len(calls), 4)
        self.assertEqual(fixture.stages[0]['stargz_runtime']['owned-node']['ctr_client_version'],
                         'ctr containerd v2.1.5-k3s1.33')


if __name__ == '__main__':
    unittest.main()
