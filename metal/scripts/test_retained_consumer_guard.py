"""Refuse stale, active, writable or unproven shared-store consumers."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import retained_consumer_guard as subject


class ReadonlyConsumers(unittest.TestCase):
    def config(self):
        return {'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'default',
                'contexts': [{'name': 'default', 'context': {'cluster': 'default', 'user': 'default'}}],
                'clusters': [{'name': 'default', 'cluster': {'server': 'https://10.0.20.50:6443',
                                                           'certificate-authority-data': 'synthetic-ca'}}],
                'users': [{'name': 'default', 'user': {'client-certificate-data': 'synthetic-certificate',
                                                     'client-key-data': 'synthetic-key'}}]}

    def test_anonymous_configuration_child_access_cleanup_and_cancellation(self):
        previous = os.environ.get('KUBECONFIG')
        for fail in (False, True):
            path = None
            try:
                with subject.operator_access(self.config()) as path:
                    cache = subject.CACHE
                    self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)
                    self.assertEqual(json.loads(Path(path).read_bytes()), self.config())
                    child = subprocess.run([sys.executable, '-B', '-c',
                                            'import json,os;assert json.load(open(os.environ["KUBECONFIG"]))["kind"]=="Config"'])
                    self.assertEqual(child.returncode, 0)
                    if fail:
                        raise InterruptedError('synthetic cancellation')
            except InterruptedError:
                self.assertTrue(fail)
            self.assertFalse(Path(path).exists())
            self.assertFalse(Path(cache).exists())
            self.assertIsNone(subject.CACHE)
            self.assertEqual(os.environ.get('KUBECONFIG'), previous)

    def test_operator_transport_refuses_foreign_api_paths_or_weakened_trust(self):
        for field, value in (('server', 'http://10.0.20.50:6443'), ('insecure-skip-tls-verify', True),
                             ('proxy-url', 'http://foreign'), ('certificate-authority', '/host/credential')):
            config = self.config()
            config['clusters'][0]['cluster'][field] = value
            with self.assertRaises(RuntimeError):
                with subject.operator_access(config):
                    self.fail('untrusted configuration accepted')
        config = self.config()
        config['users'][0]['user']['exec'] = {'command': 'unreviewed'}
        with self.assertRaises(RuntimeError):
            with subject.operator_access(config):
                self.fail('external credential execution accepted')

    def setUp(self):
        spec = {'restartPolicy': 'OnFailure',
                'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'data'}}],
                'containers': [{'name': 'backup', 'volumeMounts': [{'name': 'data', 'readOnly': True}],
                                'securityContext': {'allowPrivilegeEscalation': False,
                                                    'capabilities': {'drop': ['ALL']}}}]}
        def resource(kind, name, value, parent=None):
            meta = {'name': name, 'uid': name + '-uid', 'namespace': 'fixture'}
            if parent:
                meta['ownerReferences'] = [{'apiVersion': 'batch/v1', 'kind': parent[0],
                                            'name': parent[1], 'uid': parent[1] + '-uid', 'controller': True}]
            return {'kind': kind, 'metadata': meta, 'spec': copy.deepcopy(value), 'status': {}}
        cron = resource('CronJob', 'schedule', {'jobTemplate': {'spec': {'template': {'spec': spec}}}})
        job = resource('Job', 'job', {'template': {'spec': spec}}, ('CronJob', 'schedule'))
        job['status'] = {'succeeded': 1, 'conditions': [{'type': 'Complete', 'status': 'True'}]}
        pod = resource('Pod', 'completed', spec, ('Job', 'job'))
        pod['status'] = {'phase': 'Succeeded', 'containerStatuses': [
            {'name': 'backup', 'state': {'terminated': {'exitCode': 0}}}]}
        main = resource('Pod', 'main', spec)
        main['status'] = {'phase': 'Running'}
        self.resources = [cron, job, pod, main]
        self.profile = {'claim': 'data', 'pod_uid': 'main-uid', 'readonly_job_consumers': {}}
        for key, item in zip(('cronjobs', 'jobs', 'pods'), self.resources):
            self.profile['readonly_job_consumers'][key] = {item['metadata']['name']: {
                'uid': item['metadata']['uid'],
                'spec_sha256': hashlib.sha256(subject.common.canonical(item['spec'])).hexdigest()}}

    def check(self):
        return subject.check(self.resources, 'fixture', self.profile)

    def test_exact_completion_and_native_observation_only_reads(self):
        self.assertEqual(self.check(), {'cronjobs': ['schedule-uid'], 'jobs': ['job-uid'], 'pods': ['completed-uid']})
        result = SimpleNamespace(stdout=json.dumps({'kind': 'List', 'items': self.resources}).encode())
        with patch.object(subject.common, 'command', return_value=result) as command:
            with subject.operator_access(self.config()):
                cache = subject.CACHE
                self.assertEqual(subject.observe('fixture', self.profile), self.check())
        self.assertEqual(command.call_args.args[0], ['/usr/local/bin/k3s', 'kubectl', '--cache-dir=' + cache, 'get',
                                                     'pods,jobs,cronjobs', '-n', 'fixture', '-o', 'json'])

    def test_stale_missing_extra_deleting_and_changed_spec_refused(self):
        original = copy.deepcopy(self.resources)
        for index in range(4):
            for mutate in (lambda r: r['metadata'].update(uid='foreign'),
                           lambda r: r['metadata'].update(deletionTimestamp='now'),
                           lambda r: r['metadata'].update(namespace='foreign')):
                self.resources = copy.deepcopy(original)
                mutate(self.resources[index])
                with self.assertRaises(RuntimeError):
                    self.check()
        for items in (original[1:], original + [copy.deepcopy(original[2])], original[:-1]):
            self.resources = copy.deepcopy(items)
            with self.assertRaises(RuntimeError):
                self.check()
        for index in range(3):
            self.resources = copy.deepcopy(original)
            self.resources[index]['spec']['changed'] = True
            with self.assertRaises(RuntimeError):
                self.check()

    def test_phase_alone_owners_failed_containers_and_active_work_refused(self):
        original = copy.deepcopy(self.resources)
        changes = [(0, 'status', {'active': [{'uid': 'new'}]}),
                   (1, 'status', {'succeeded': 1}),
                   (1, 'status', {'succeeded': 1, 'active': 1, 'conditions': [{'type': 'Complete', 'status': 'True'}]}),
                   (1, 'status', {'succeeded': 1, 'failed': 1, 'conditions': [{'type': 'Complete', 'status': 'True'}]}),
                   (2, 'status', {'phase': 'Succeeded'}),
                   (2, 'status', {'phase': 'Succeeded', 'containerStatuses': [
                       {'name': 'backup', 'state': {'terminated': {'exitCode': 1}}}]}),
                   (2, 'status', {'phase': 'Succeeded', 'initContainerStatuses': [{'name': 'unreviewed'}]})]
        for index, key, value in changes:
            self.resources = copy.deepcopy(original)
            self.resources[index][key] = value
            with self.assertRaises(RuntimeError):
                self.check()
        for index in (1, 2):
            for value in ([], [{'controller': True, 'kind': 'Job', 'apiVersion': 'batch/v1',
                               'name': 'job', 'uid': ''}]):
                self.resources = copy.deepcopy(original)
                self.resources[index]['metadata']['ownerReferences'] = value
                with self.assertRaises(RuntimeError):
                    self.check()

    def test_writable_mount_and_escape_paths_refused_even_with_new_pin(self):
        spec = self.resources[2]['spec']
        variants = []
        for key, value in (('readOnly', False), ('subPath', 'data'), ('subPathExpr', 'data')):
            other = copy.deepcopy(spec)
            other['containers'][0]['volumeMounts'][0][key] = value
            variants.append(other)
        for key, value in (('privileged', True), ('allowPrivilegeEscalation', True),
                           ('capabilities', {'drop': ['ALL'], 'add': ['SYS_ADMIN']})):
            other = copy.deepcopy(spec)
            other['containers'][0]['securityContext'][key] = value
            variants.append(other)
        for key, value in (('hostPID', True), ('hostNetwork', True), ('hostIPC', True),
                           ('initContainers', [{'name': 'writer'}]), ('ephemeralContainers', [{'name': 'writer'}])):
            variants.append({**copy.deepcopy(spec), key: value})
        other = copy.deepcopy(spec)
        other['volumes'].append({'name': 'host', 'hostPath': {'path': '/'}})
        variants.append(other)
        for value in variants:
            with self.assertRaises(RuntimeError):
                subject.readonly(value, 'data')


if __name__ == '__main__':
    unittest.main()
