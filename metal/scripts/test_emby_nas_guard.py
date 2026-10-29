"""Reject foreign tasks, writers and mutable runtime identities before API changes."""

import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace


spec = importlib.util.spec_from_file_location('emby_nas_guard',
    Path(__file__).resolve().parents[2] / 'apps/emby/scripts/maintenance_nas_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class NasGuardTests(unittest.TestCase):
    def test_replacement_pod_observes_only_the_same_accepted_paused_task(self):
        context = {'pod_uid': 'old-pod', 'container_id': 'old-container',
                   'pv': 'original-volume', 'recovery_manifest_sha256': 'original-recovery'}
        task = {'id': 'original-task', 'key': 'EmbyServerBackup', 'triggers': []}
        saved = {'context': context, 'original': task, 'desired_triggers': []}
        changed = {**context, 'pod_uid': 'new-pod', 'container_id': 'new-container'}
        guard.intent_contract(saved, context, task, False)
        guard.intent_contract(saved, changed, task, True)
        with self.assertRaises(RuntimeError):
            guard.intent_contract(saved, changed, task, False)
        with self.assertRaises(RuntimeError):
            guard.intent_contract(saved, changed, {**task, 'triggers': [{'Type': 'DailyTrigger'}]}, True)
        for key in ('pv', 'recovery_manifest_sha256'):
            with self.assertRaises(RuntimeError):
                guard.intent_contract(saved, {**changed, key: 'foreign'}, task, True)
        with self.assertRaises(RuntimeError):
            guard.intent_contract(saved, changed, {**task, 'id': 'foreign-task'}, True)

    def test_media_selection_excludes_remote_backup_traversal_and_unsupported_sources(self):
        source = {'Protocol': 'File', 'Path': '/data/movies/fixture.mkv',
                  'MediaStreams': [{'Type': 'Video', 'Codec': 'h264', 'PixelFormat': 'yuv420p'}]}
        self.assertEqual(guard.select_media({'Items': [{'MediaSources': [source]}]}), source['Path'])
        for field, value in [('Protocol', 'Http'), ('Path', '/backups/file.mkv'),
                             ('Path', '/data/movies/../private.mkv'), ('Path', '/data/movies-other/file.mkv'),
                             ('MediaStreams', [{'Type': 'Video', 'Codec': 'av1', 'PixelFormat': 'yuv420p'}]),
                             ('MediaStreams', [{'Type': 'Video', 'Codec': 'h264', 'PixelFormat': 'yuv420p10le'}])]:
            changed = copy.deepcopy(source)
            changed[field] = value
            with self.assertRaises(RuntimeError):
                guard.select_media({'Items': [{'MediaSources': [changed]}]})

    def test_media_uses_service_working_directory_and_identity(self):
        path = '/data/movies/fixture.mkv'
        items = {'Items': [{'MediaSources': [{'Protocol': 'File', 'Path': path,
                 'MediaStreams': [{'Type': 'Video', 'Codec': 'h264', 'PixelFormat': 'yuv420p'}]}]}]}
        raw = guard.json.dumps(items).encode()
        context = {'container_id': 'original-container'}
        metadata = b'81a4:1:2:1000:1234\n'

        def command(*argv):
            self.assertEqual(list(argv[:6]), ['/usr/local/bin/k3s', 'crictl', 'exec',
                                             'original-container', '/usr/bin/s6-setuidgid', 'abc'])
            if argv[-2:] == ('id', '-u'):
                return b'99\n'
            if argv[-2:] == ('id', '-g'):
                return b'100\n'
            if argv[6:8] == ('/bin/sh', '-ec'):
                self.assertIn('mktemp /emby/transcode/transcoding-temp/.maintenance103.XXXXXX', argv[8])
                self.assertIn('trap', argv[8])
                return b'transcode-write-cleaned'
            if 'readlink' in argv:
                return path.encode() + b'\n'
            if 'stat' in argv:
                return metadata
            self.fail('unexpected command')

        result = SimpleNamespace(returncode=0, stdout=b'frame=48\nout_time_us=2000000\nprogress=end\n', stderr=b'')
        with patch.object(guard, 'command', side_effect=command), \
                patch.object(guard, 'runtime_contract', return_value=(1234, Path('/original'))), \
                patch.object(guard.subprocess, 'run', return_value=result) as launch:
            accepted = guard.verify_media(context, lambda _: raw, lambda: {}, 1234, Path('/original'))
            argv = launch.call_args.args[0]
            self.assertIn('cd /app/emby && exec timeout -k 5 -s TERM 90 "$@"', argv)
            self.assertEqual(argv[4:6], ['/usr/bin/s6-setuidgid', 'abc'])
            self.assertEqual(accepted['uid'], 99)
            self.assertEqual(accepted['gid'], 100)
            self.assertTrue(accepted['local_transcode_write_and_cleanup'])
            self.assertTrue(accepted['source_metadata_unchanged'])
        with patch.object(guard, 'command', return_value=b'0\n'), \
                patch.object(guard.subprocess, 'run') as launch:
            with self.assertRaisesRegex(RuntimeError, 'user differs'):
                guard.verify_media(context, lambda _: raw, lambda: {}, 1234, Path('/original'))
            launch.assert_not_called()

    def test_media_progress_requires_completed_nonempty_meaningful_encode(self):
        self.assertEqual(guard.media_progress(b'frame= 48\nout_time_us=2000000\nprogress=end\n')['frames'], 48)
        for raw in (b'frame=0\nout_time_us=2000000\nprogress=end',
                    b'frame=48\nout_time_us=1000\nprogress=end',
                    b'frame=48\nout_time_us=2000000\nprogress=continue',
                    b'frame=48\nout_time_us=private\nprogress=end'):
            with self.assertRaises(RuntimeError):
                guard.media_progress(raw)

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
