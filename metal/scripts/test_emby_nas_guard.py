"""Reject foreign tasks, writers and mutable runtime identities before API changes."""

import copy
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('emby_nas_guard',
    Path(__file__).resolve().parents[2] / 'apps/emby/scripts/maintenance_nas_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class NasGuardTests(unittest.TestCase):
    def test_only_idle_exact_backup_task_can_change(self):
        task = {'Key': 'EmbyServerBackup', 'Name': 'Emby Server Backup', 'Id': 'a1e4a796-2c72-ac5e-4914-97598d1ee479',
                'State': 'Idle', 'Triggers': [{'Type': 'DailyTrigger', 'TimeOfDayTicks': 72000000000}]}
        self.assertEqual(guard.task_contract(task)['triggers'], task['Triggers'])
        with self.assertRaisesRegex(RuntimeError, 'not paused'):
            guard.task_contract(task, accepted=True)
        for field, value in [('Key', 'OtherTask'), ('Name', 'Other Task'), ('State', 'Running'),
                             ('Id', 'foreign/endpoint'), ('Triggers', {})]:
            changed = copy.deepcopy(task)
            changed[field] = value
            with self.assertRaises(RuntimeError):
                guard.task_contract(changed)
        task['Triggers'] = []
        self.assertEqual(guard.task_contract(task, accepted=True)['triggers'], [])

    def test_every_nas_mount_and_original_configuration_identity_required(self):
        context = {'pod_uid': 'fixture-pod', 'pv': 'pvc-original'}
        source = '/var/lib/kubelet/pods/fixture-pod/volumes/kubernetes.io~csi/pvc-original/mount'
        runtime = {'status': {'state': 'CONTAINER_RUNNING', 'labels': {'io.kubernetes.pod.uid': 'fixture-pod',
                    'io.kubernetes.pod.namespace': 'emby', 'io.kubernetes.container.name': 'main'}},
                   'info': {'pid': 1234, 'runtimeSpec': {'mounts': [
                       {'destination': path, 'options': ['rbind', 'ro']} for path in sorted(guard.NAS_PATHS)] +
                       [{'destination': '/config', 'source': source, 'options': ['rbind', 'rw']}]}}}
        self.assertEqual(guard.runtime_contract(runtime, context), (1234, Path(source)))
        variants = []
        changed = copy.deepcopy(runtime)
        changed['info']['runtimeSpec']['mounts'][0]['options'] = ['rbind', 'rw']
        variants.append(changed)
        changed = copy.deepcopy(runtime)
        changed['info']['runtimeSpec']['mounts'].pop(0)
        variants.append(changed)
        changed = copy.deepcopy(runtime)
        changed['info']['runtimeSpec']['mounts'][-1]['source'] = '/another-volume'
        variants.append(changed)
        changed = copy.deepcopy(runtime)
        changed['status']['labels']['io.kubernetes.pod.uid'] = 'another-pod'
        variants.append(changed)
        changed = copy.deepcopy(runtime)
        changed['info']['pid'] = True
        variants.append(changed)
        for changed in variants:
            with self.assertRaises(RuntimeError):
                guard.runtime_contract(changed, context)


if __name__ == '__main__':
    unittest.main()
