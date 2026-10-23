#!/usr/bin/env python3
"""Refusal tests for native CSI archive, process and manifest identities."""

import ast
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import fedora_nfs_csi_qualification as profile
import nfs_csi_native_runtime as runtime


class NativeCSI(unittest.TestCase):
    def test_k3s_failure_evidence_excludes_credentials_and_bounds_selected_messages(self):
        raw = (b'normal service start\n'
               b'failed to register node: connection refused\n'
               b'error token=PRIVATE_SENTINEL\n'
               b'failed private key PRIVATE_SENTINEL\n'
               b'error opaque AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n')
        messages = runtime.k3s_failure_messages(raw)
        self.assertEqual(messages, ['failed to register node: connection refused', 'error opaque [redacted]'])
        self.assertNotIn('PRIVATE_SENTINEL', str(messages))
        bounded = runtime.k3s_failure_messages((b'error ' + b'x' * 600 + b'\n') * 30)
        self.assertEqual(len(bounded), 12)
        self.assertTrue(all(len(line) <= 500 for line in bounded))

    def archive(self, root, *, architecture='amd64', extra=False, symlink=False, corrupt=False):
        blobs = {}

        def blob(raw):
            digest = hashlib.sha256(raw).hexdigest()
            blobs['blobs/sha256/' + digest] = raw
            return {'digest': 'sha256:' + digest, 'size': len(raw)}

        config = blob(json.dumps({'architecture': architecture, 'os': 'linux'}).encode())
        layer = blob(b'synthetic-layer')
        manifest = blob(json.dumps({'schemaVersion': 2, 'config': config, 'layers': [layer]}).encode())
        record = {'image': 'registry.k8s.io/sig-storage/nfsplugin:v4.13.5', 'digest': manifest['digest']}
        index = {'schemaVersion': 2, 'manifests': [{**manifest, 'annotations': {
            'org.opencontainers.image.ref.name': record['image']}}]}
        files = {'oci-layout': b'{"imageLayoutVersion":"1.0.0"}', 'index.json': json.dumps(index).encode(), **blobs}
        if extra:
            files['blobs/sha256/' + hashlib.sha256(b'foreign').hexdigest()] = b'foreign'
        if corrupt:
            files['blobs/sha256/' + layer['digest'].split(':')[1]] = b'corrupt'
        path = root / 'image.tar'
        with tarfile.open(path, 'w') as archive:
            for name, raw in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(raw)
                archive.addfile(entry, io.BytesIO(raw))
            if symlink:
                entry = tarfile.TarInfo('foreign-link')
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/etc/passwd'
                archive.addfile(entry)
        return path, record

    def test_exact_reachable_amd64_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path, record = self.archive(Path(directory))
            self.assertEqual(profile.archive_identity(path, record), hashlib.sha256(path.read_bytes()).hexdigest())
            for changed in ({**record, 'digest': 'sha256:' + '0' * 64}, {**record, 'image': 'foreign:tag'}):
                with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                    profile.archive_identity(path, changed)

    def test_unsafe_foreign_corrupt_and_wrong_platform_refused(self):
        for options in ({'architecture': 'arm64'}, {'extra': True}, {'symlink': True}, {'corrupt': True}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                path, record = self.archive(Path(directory), **options)
                with self.assertRaises(RuntimeError):
                    profile.archive_identity(path, record)

    def process(self):
        pod = {'metadata': {'name': 'a', 'namespace': runtime.CLIENT_NS, 'uid': 'pod-uid'},
               'status': {'containerStatuses': [{'name': 'client', 'ready': True,
                                                'state': {'running': {}}, 'containerID': 'containerd://abc'}]}}
        inspected = {'info': {'pid': 42}, 'status': {'id': 'abc', 'metadata': {'name': 'client'}, 'labels': {
            'io.kubernetes.pod.uid': 'pod-uid', 'io.kubernetes.pod.name': 'a',
            'io.kubernetes.pod.namespace': runtime.CLIENT_NS}}}
        return pod, inspected

    def test_current_ready_process_identity(self):
        pod, inspected = self.process()
        result = runtime.bound_domain(pod, 'client', inspected, 'system_u:system_r:container_t:s0:c1,c2')
        self.assertEqual((result['pod_uid'], result['container_id'], result['pid']), ('pod-uid', 'abc', 42))

    def test_stale_unready_foreign_or_non_native_process_refused(self):
        for key in ('pod_uid', 'container_id', 'container_name', 'pid_bool', 'pid_root', 'pid_string',
                    'label_namespace', 'deleting', 'unready', 'terminated', 'context'):
            pod, inspected = self.process()
            context = 'system_u:system_r:container_t:s0:c1,c2'
            if key == 'pod_uid':
                inspected['status']['labels']['io.kubernetes.pod.uid'] = 'other'
            elif key == 'container_id':
                inspected['status']['id'] = 'old'
            elif key == 'container_name':
                inspected['status']['metadata']['name'] = 'other'
            elif key.startswith('pid_'):
                inspected['info']['pid'] = {'pid_bool': True, 'pid_root': 1, 'pid_string': '42'}[key]
            elif key == 'label_namespace':
                inspected['status']['labels']['io.kubernetes.pod.namespace'] = 'other'
            elif key == 'deleting':
                pod['metadata']['deletionTimestamp'] = '2026-10-23T00:00:00Z'
            elif key == 'unready':
                pod['status']['containerStatuses'][0]['ready'] = False
            elif key == 'terminated':
                pod['status']['containerStatuses'][0]['state'] = {'terminated': {'exitCode': 0}}
            else:
                context = 'unbound'
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                runtime.bound_domain(pod, 'client', inspected, context)

    def test_consumer_security_and_root_backup_are_distinct(self):
        image = profile.image_records()[-1]
        reference = image['image'].rsplit(':', 1)[0] + '@' + image['digest']
        pod = runtime.pod_manifest('a', 'builder', reference)
        spec = pod['spec']
        self.assertEqual(spec['securityContext']['fsGroup'], 1000)
        self.assertEqual(spec['securityContext']['fsGroupChangePolicy'], 'OnRootMismatch')
        self.assertTrue(spec['securityContext']['runAsNonRoot'])
        self.assertFalse(spec['automountServiceAccountToken'])
        container = spec['containers'][0]
        self.assertEqual(container['imagePullPolicy'], 'Never')
        self.assertEqual(container['securityContext'], {'allowPrivilegeEscalation': False,
                                                       'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}})
        self.assertNotIn('seLinuxOptions', spec['securityContext'])
        backup = runtime.pod_manifest('backup', 'backup', reference, uid=0, group=0, fs_group=None)
        self.assertEqual(backup['metadata']['namespace'], runtime.BACKUP_NS)
        self.assertNotIn('fsGroup', backup['spec']['securityContext'])
        self.assertEqual(backup['spec']['securityContext']['runAsUser'], 0)

    def test_binding_and_replacement_identities(self):
        volume = {'metadata': {'name': 'qualification-builder', 'uid': 'pv-uid'}, 'status': {'phase': 'Bound'},
                  'spec': {'claimRef': {'name': 'builder', 'namespace': runtime.CLIENT_NS, 'uid': 'claim-uid'},
                           'persistentVolumeReclaimPolicy': 'Retain', 'csi': {
                               'driver': 'nfs.csi.k8s.io', 'volumeHandle': 'qualification-builder',
                               'volumeAttributes': {'server': '127.0.0.1', 'share': '/builder', 'mountPermissions': '0'}}}}
        pvc = {'metadata': {'name': 'builder', 'namespace': runtime.CLIENT_NS, 'uid': 'claim-uid'},
               'status': {'phase': 'Bound'}, 'spec': {'volumeName': 'qualification-builder'}}
        expected = runtime.require_binding(volume, pvc, 'builder', runtime.CLIENT_NS)
        self.assertEqual(expected['claim_uid'], 'claim-uid')
        for key in ('pv_uid', 'claim_uid', 'server', 'share', 'policy', 'ref'):
            changed, claim = copy.deepcopy(volume), copy.deepcopy(pvc)
            if key == 'pv_uid':
                changed['metadata']['uid'] = 'replacement'
            elif key == 'claim_uid':
                claim['metadata']['uid'] = 'replacement'
                changed['spec']['claimRef']['uid'] = 'replacement'
            elif key in ('server', 'share'):
                changed['spec']['csi']['volumeAttributes'][key] = 'foreign'
            elif key == 'policy':
                changed['spec']['persistentVolumeReclaimPolicy'] = 'Delete'
            else:
                changed['spec']['claimRef']['namespace'] = 'foreign'
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                runtime.require_binding(changed, claim, 'builder', runtime.CLIENT_NS, expected)

    def chart(self):
        images = profile.image_records()
        plugin = {'name': 'nfs', 'image': images[0]['image'], 'securityContext': {'privileged': True}}
        workloads = [{'kind': kind, 'spec': {'template': {'spec': {'hostNetwork': True, 'containers': [
            copy.deepcopy(plugin), *[{'name': str(i), 'image': image['image']} for i, image in enumerate(images[1:5])]]}}}}
                     for kind in ('Deployment', 'DaemonSet')]
        return [*workloads, {'kind': 'CSIDriver', 'spec': {'fsGroupPolicy': 'File'}},
                *[{'kind': 'ClusterRole'} for _ in range(6)]]

    def test_chart_keeps_security_and_refuses_contract_drift(self):
        objects = self.chart()
        accepted = profile.reviewed_chart(copy.deepcopy(objects), profile.image_records())
        self.assertTrue(accepted[0]['spec']['template']['spec']['containers'][0]['securityContext']['privileged'])
        self.assertTrue(all('@sha256:' in c['image'] and c['imagePullPolicy'] == 'Never'
                            for o in accepted[:2] for c in o['spec']['template']['spec']['containers']))
        for key in ('image', 'host_network', 'privileged', 'ownership', 'storage'):
            changed = copy.deepcopy(objects)
            spec = changed[0]['spec']['template']['spec']
            if key == 'image':
                spec['containers'][0]['image'] = 'foreign:latest'
            elif key == 'host_network':
                spec['hostNetwork'] = False
            elif key == 'privileged':
                spec['containers'][0]['securityContext']['privileged'] = False
            elif key == 'ownership':
                changed[2]['spec']['fsGroupPolicy'] = 'None'
            else:
                changed[-1]['kind'] = 'PersistentVolume'
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                profile.reviewed_chart(changed, profile.image_records())

    def test_embedded_consumer_programs_compile(self):
        tree = ast.parse(Path(runtime.__file__).read_text())
        programs = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and
                    isinstance(n.value, str) and n.value.startswith('import ') and '\n' in n.value]
        self.assertGreaterEqual(len(programs), 7)
        for program in programs:
            compile(program, '<native-consumer>', 'exec')


if __name__ == '__main__':
    unittest.main()
