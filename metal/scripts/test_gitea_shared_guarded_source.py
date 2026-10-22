"""Refuse unheld sources, changed protected streams and historical provenance."""

import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gitea_shared_guarded_source as shared


def binding():
    uid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    return {'cluster_uid': shared.common.CLUSTER_UID, 'namespace': 'gitea',
            'pod': 'gitea-synthetic-test', 'pod_uid': uid, 'controller_uid': shared.OWNER_UID,
            'node': 'pikachu', 'container_id': 'a' * 64, 'image': shared.application.IMAGE,
            'claim': 'gitea-shared-storage', 'claim_uid': shared.CLAIM_UID,
            'pv': 'pvc-' + shared.CLAIM_UID, 'pv_uid': shared.PV_UID, 'revision': 'b' * 40,
            'volume': {'source': '/var/lib/kubelet/pods/' + uid + '/volumes/kubernetes.io~csi/pvc-' +
                                 shared.CLAIM_UID + '/mount', 'device': 1, 'inode': 2},
            'guard': {'namespace_pid': 3, 'host_pid': 4, 'start_ticks': 5, 'lock_device': 6, 'lock_inode': 7}}


class SharedGuardedTests(unittest.TestCase):
    def test_source_binding_and_extra_native_writer_refusals(self):
        original = binding()
        self.assertEqual(shared.validate_source(original), original)
        for change in (lambda v: v.update(namespace='other'), lambda v: v.update(claim_uid='c' * 36),
                       lambda v: v.update(image='other'), lambda v: v['guard'].update(host_pid=True),
                       lambda v: v['volume'].update(source='/unknown'),
                       lambda v: v.update(extra='foreign')):
            altered = copy.deepcopy(original)
            change(altered)
            with self.assertRaises(RuntimeError):
                shared.validate_source(altered)
        tasks = {100: ({}, 1, shared.STARTUP), 101: ({}, 3, shared.CONTROLLER),
                 102: ({}, 4, ['flock', '-x', '9'])}
        self.assertEqual(shared.guard_tasks(tasks, 100, 3)[0], 101)
        tasks[103] = ({}, 5, ['/usr/local/bin/gitea', 'web'])
        with self.assertRaises(RuntimeError):
            shared.guard_tasks(tasks, 100, 3)
        with patch.object(shared.common, 'require_host') as host:
            with self.assertRaises(RuntimeError):
                shared.observe({}, 3)
            host.assert_not_called()

    def test_complete_shared_stream_is_separate_and_refuses_damage(self):
        # Synthetic parser metadata does not establish an actual production hold.
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(shared.cold.retained.os, 'listxattr', return_value=[], create=True), \
                patch.object(shared.cold.retained, 'available_memory', return_value=1024 * 1024), \
                patch.object(shared.cold.retained, 'require_capacity'):
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / 'binary').write_bytes(b'\0\xff\r\n')
            (source / 'empty').write_bytes(b'')
            value, checksum = shared.cold.capture(source, root / 'point', {'application_started': False},
                source_binding=binding(), validator=shared.validate, source_format=shared.FORMAT)
            self.assertEqual(shared.cold.verify(root / 'point', checksum, validator=shared.validate), value)
            with self.assertRaises(RuntimeError):
                shared.cold.verify(root / 'point', checksum)
            stream = io.BytesIO()
            shared.cold.send(root / 'point', checksum, stream, validator=shared.validate)
            raw = stream.getvalue()
            self.assertEqual(shared.cold.receive(io.BytesIO(raw), root / 'received', validator=shared.validate),
                             (value, checksum))
            for number, damaged in enumerate((raw[:-1], raw + b'foreign', raw.replace(b'\0\xff\r\n', b'bad!'))):
                target = root / ('bad-' + str(number))
                with self.assertRaises((RuntimeError, ValueError)):
                    shared.cold.receive(io.BytesIO(damaged), target, validator=shared.validate)
                self.assertFalse((target / 'verified.json').exists())
            with patch.object(shared, 'observe', return_value={}), self.assertRaises(RuntimeError):
                shared.send(root / 'point', checksum, value['source'], io.BytesIO())
            for change in (lambda v: v.update(format=shared.cold.GUARDED_FORMAT),
                           lambda v: v['control'].update(application_started=True),
                           lambda v: v['control'].update(application_started=0),
                           lambda v: v['tree'].update({'../foreign': v['tree']['binary']})):
                altered = copy.deepcopy(value)
                change(altered)
                with self.assertRaises(RuntimeError):
                    shared.validate(altered)


if __name__ == '__main__':
    unittest.main()
