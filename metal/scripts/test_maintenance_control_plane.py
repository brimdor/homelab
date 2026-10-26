"""Exact quorum and transport checks before Squirtle's serial host work."""

import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import maintenance_control_plane as CP


class QuorumTests(unittest.TestCase):
    def setUp(self):
        self.urls = ['https://10.0.20.' + str(n) + ':2379' for n in (11, 12, 13)]
        self.values = {
            ('member', 'list'): {'members': [
                {'ID': n, 'clientURLs': [url], 'peerURLs': [url.replace('2379', '2380')]}
                for n, url in enumerate(self.urls, 1)]},
            ('endpoint', 'status'): [{'Endpoint': url, 'Status': {
                'header': {'cluster_id': 42, 'member_id': n}, 'leader': 1, 'version': '3.5.21'}}
                for n, url in enumerate(self.urls, 1)],
            ('endpoint', 'health'): [{'endpoint': url, 'health': True} for url in self.urls],
            ('alarm', 'list'): {},
        }

    def observe(self, values):
        def run(argv, **kwargs):
            self.assertIn('--cacert=/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt', argv)
            self.assertIn('--cert=/var/lib/rancher/k3s/server/tls/etcd/client.crt', argv)
            self.assertNotIn('--insecure-skip-tls-verify', argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps(values[tuple(argv[-2:])]).encode(), b'')
        with patch('os.geteuid', return_value=0), patch('socket.gethostname', return_value='squirtle'), \
                patch.object(Path, 'read_text', return_value=CP.IDENTITY), patch('subprocess.run', side_effect=run), \
                contextlib.redirect_stdout(io.StringIO()):
            exec(compile(CP.program(CP.OBSERVE), 'native-etcd-observation', 'exec'), {})

    def test_exact_three_voting_members_are_accepted(self):
        self.observe(self.values)

    def test_learner_failed_member_changed_cluster_leader_and_alarm_are_refused(self):
        for fault in ('learner', 'health', 'cluster', 'leader', 'alarm'):
            values = copy.deepcopy(self.values)
            if fault == 'learner': values[('member', 'list')]['members'][0]['isLearner'] = True
            if fault == 'health': values[('endpoint', 'health')][0]['health'] = False
            if fault == 'cluster': values[('endpoint', 'status')][0]['Status']['header']['cluster_id'] = 43
            if fault == 'leader': values[('endpoint', 'status')][0]['Status']['leader'] = 2
            if fault == 'alarm': values[('alarm', 'list')]['alarms'] = [{'alarm': 1}]
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                self.observe(values)


if __name__ == '__main__':
    unittest.main()
