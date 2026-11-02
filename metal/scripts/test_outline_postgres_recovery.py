#!/usr/bin/env python3
"""Guard the fixed Outline source, password-free archives and native isolation."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import outline_postgres_recovery as recovery


class OutlineRecoveryGuards(unittest.TestCase):
    def setUp(self):
        importlib.reload(recovery)
        self.addCleanup(importlib.reload, recovery)

    def manifest(self):
        before = {'features': recovery.FEATURES, 'schema_sha256': 'a' * 64, 'roles_sha256': 'b' * 64}
        return {'format': 1, 'cluster_uid': recovery.common.CLUSTER_UID, 'image': recovery.IMAGE,
                'identity': recovery.IDENTITY, 'before': before, 'after': copy.deepcopy(before),
                'role_passwords_omitted': True, 'writers_quiesced': False,
                'files': {n: {'bytes': 20, 'sha256': 'c' * 64} for n in ('globals.sql', 'database.dump')}}

    def test_manifest_refuses_wrong_source_features_hashes_partial_and_password_contract(self):
        original = self.manifest(); recovery.require_manifest(original)
        for key, value in (('cluster_uid', 'other'), ('image', 'postgres:latest'), ('identity', ['other']),
                           ('before', {}), ('after', {}), ('role_passwords_omitted', False),
                           ('writers_quiesced', True), ('files', {'database.dump': {}})):
            changed = copy.deepcopy(original); changed[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.require_manifest(changed)
        for key, value in (('bytes', 0), ('bytes', True), ('sha256', 'wrong')):
            changed = copy.deepcopy(original); changed['files']['database.dump'][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.require_manifest(changed)
        changed = copy.deepcopy(original); changed['before']['roles_sha256'] = 'invalid'; changed['after'] = copy.deepcopy(changed['before'])
        with self.assertRaises(RuntimeError): recovery.require_manifest(changed)

    def test_source_client_uses_declared_principal_readonly_without_password_in_arguments(self):
        args = recovery.source_client('pg_dump', '--format=custom'); shell = args[-1]
        self.assertIn('PGPASSWORD="$POSTGRES_PASSWORD"', shell); self.assertIn('PGUSER="$POSTGRES_USER"', shell)
        self.assertIn('default_transaction_read_only=on', shell); self.assertIn('lock_timeout=10s', shell)
        self.assertIn('outline-postgres-0', args); self.assertNotIn('sudo', shell)
        self.assertNotIn('password', ' '.join(args[:-1]).lower())

    def source_identity_guards(self):
        pod = {'metadata': {'uid': recovery.IDENTITY[0], 'ownerReferences': [
                    {'uid': recovery.IDENTITY[1], 'kind': 'StatefulSet', 'controller': True}]},
               'spec': {'nodeName': recovery.SOURCE_NODE, 'containers': [{'name': 'main', 'env': [
                   {'name': k, 'valueFrom': {'secretKeyRef': {'key': v, 'name': 'secrets'}}}
                   for k, v in {'POSTGRES_USER': 'postgres-user', 'POSTGRES_PASSWORD': 'postgres-password',
                                'POSTGRES_DB': 'postgres-db'}.items()],
                   'volumeMounts': [{'name': 'data', 'mountPath': recovery.MOUNT}]}],
                   'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'outline'}}]},
               'status': {'containerStatuses': [{'ready': True, 'restartCount': 0, 'imageID': recovery.IMAGE,
                                                'containerID': 'containerd://' + recovery.CONTAINER}]}}
        claim = {'metadata': {'uid': recovery.IDENTITY[2]}, 'spec': {'volumeName': 'synthetic',
                 'storageClassName': 'standard-rwo'}, 'status': {'phase': 'Bound'}}
        pv = {'metadata': {'uid': recovery.IDENTITY[3]}, 'spec': {'csi': {
              'driver': 'rook-ceph.rbd.csi.ceph.com', 'volumeHandle': 'synthetic-handle'}}}
        values = [{'metadata': {'uid': recovery.common.CLUSTER_UID}}, pod,
                  {'metadata': {'uid': recovery.SECRET_UID}}, claim, pv]
        def command(args):
            kind = args[args.index('get') + 1]
            value = dict(zip(('namespace', 'pod', 'secret', 'pvc', 'pv'), values))[kind]
            return subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b'')
        with patch.object(recovery.common, 'command', side_effect=command), \
                patch.object(recovery, 'HANDLE_SHA256', recovery.postgres.digest(b'synthetic-handle')):
            self.assertEqual(recovery.source_identity(), recovery.IDENTITY)
            for target, key, wrong in ((pod['spec'], 'nodeName', 'other'),
                                       (pod['metadata'], 'uid', 'other'),
                                       (pod['metadata']['ownerReferences'][0], 'uid', 'other'),
                                       (pod['status']['containerStatuses'][0], 'imageID', 'postgres:latest'),
                                       (pod['status']['containerStatuses'][0], 'containerID', 'containerd://' + '0' * 64),
                                       (pod['status']['containerStatuses'][0], 'restartCount', 1),
                                       (values[2]['metadata'], 'uid', 'other'),
                                       (claim['metadata'], 'uid', 'other'),
                                       (pv['metadata'], 'uid', 'other'),
                                       (pv['spec']['csi'], 'driver', 'unknown')):
                old = target[key]; target[key] = wrong
                with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.source_identity()
                target[key] = old

    def test_source_identity_refuses_runtime_credentials_and_storage_drift(self):
        self.source_identity_guards()

    def test_current_source_preserves_every_runtime_credential_and_storage_refusal(self):
        recovery.configure_profile('post-maintenance-1365')
        self.source_identity_guards()

    def test_current_profile_changes_only_reviewed_runtime_and_propagates_to_receiver(self):
        original_identity = recovery.IDENTITY[:]
        original_features = copy.deepcopy(recovery.FEATURES)
        recovery.configure_profile('post-maintenance-1365')
        self.assertEqual(recovery.SOURCE_NODE, 'squirtle')
        self.assertEqual(recovery.RECEIVER_VERSION, 'v1.36.5+k3s1')
        self.assertEqual(recovery.IDENTITY[1:], original_identity[1:])
        self.assertEqual(recovery.IDENTITY[0], '863899db-7ea5-42fd-9d09-78e47a1e6552')
        self.assertEqual(recovery.CONTAINER, '68c65dfddde05f8659c8aaadc741c17eaf50fa73aab62f51f4216d35ef795d26')
        self.assertEqual(recovery.IMAGE, 'docker.io/library/postgres@sha256:882236b897e39051d2368c5ccc6cda944904723506b2dfc97f2a8f5bc9afa382')
        self.assertEqual(recovery.FEATURES, original_features)
        recovery.require_manifest(self.manifest())
        self.assertIn('--profile post-maintenance-1365', recovery.remote('receive', 'synthetic', '--file', 'globals.sql')[-1])
        with self.assertRaises(RuntimeError): recovery.configure_profile('legacy')

    def test_legacy_archive_remains_valid_on_reviewed_current_receiver(self):
        original = self.manifest()
        source = (recovery.IMAGE, recovery.IDENTITY[:], recovery.CONTAINER, recovery.SOURCE_NODE)
        recovery.configure_profile('legacy-on-1365')
        recovery.require_manifest(original)
        self.assertEqual((recovery.IMAGE, recovery.IDENTITY, recovery.CONTAINER, recovery.SOURCE_NODE), source)
        self.assertEqual(recovery.RECEIVER_VERSION, 'v1.36.5+k3s1')
        with patch.object(recovery.common, 'require_host') as host, patch.object(recovery.common, 'private_root'), \
                patch.object(recovery.common, 'ROOT', Path('/owned/synthetic')):
            recovery.point_path('synthetic')
        host.assert_called_once_with('pikachu', 'v1.36.5+k3s1')

    def test_profiles_refuse_arbitrary_sources_and_cross_profile_archives(self):
        original = self.manifest()
        with self.assertRaises(RuntimeError): recovery.configure_profile('any-pod')
        recovery.configure_profile('post-maintenance-1365')
        with self.assertRaises(RuntimeError): recovery.require_manifest(original)

    def test_source_metadata_requires_exact_native_features_empty_other_databases_and_hashes(self):
        features = recovery.FEATURES
        def response(data): return subprocess.CompletedProcess([], 0, data, b'')
        values = [response(json.dumps(features).encode()), response(b'0\n0\n'), response(b'0\n0\n'),
                  response(b'CREATE TABLE public.synthetic (n integer);\n'), response(b'a' * 64 + b'\n')]
        with patch.object(recovery.common, 'command', side_effect=values): self.assertEqual(recovery.source_metadata()['features'], features)
        changed = dict(features, version='18.6')
        with patch.object(recovery.common, 'command', return_value=response(json.dumps(changed).encode())):
            with self.assertRaises(RuntimeError): recovery.source_metadata()
        with patch.object(recovery.common, 'command', side_effect=[values[0], response(b'1\n0\n')]):
            with self.assertRaises(RuntimeError): recovery.source_metadata()

    def test_native_restore_refuses_mount_network_privilege_password_and_entrypoint_changes(self):
        scratch = Path('/owned/synthetic'); runid = 'synthetic'
        host = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 1073741824, 'NanoCpus': 1000000000, 'Tmpfs': {'/tmp': 'rw,nosuid,nodev'},
                'RestartPolicy': {'Name': 'no'}, 'Binds': [str(scratch / 'data') + ':' + recovery.MOUNT + ':Z']}
        original = {'HostConfig': host, 'Config': {'Image': recovery.IMAGE, 'User': '999:999', 'Labels': {recovery.LABEL: runid},
                    'Entrypoint': ['/bin/sh'], 'Cmd': ['-c', 'exec sleep 2147483647'], 'Env': ['PG_MAJOR=18']},
                    'ProcessLabel': 'system_u:system_r:container_t:s0:c100,c200',
                    'MountLabel': 'system_u:object_r:container_file_t:s0:c100,c200',
                    'Mounts': [{'Type': 'bind', 'Source': str(scratch / 'data'), 'Destination': recovery.MOUNT, 'Mode': 'Z', 'RW': True}]}
        recovery.require_container(original, scratch, runid)
        for section, key, value in (('HostConfig', 'NetworkMode', 'host'), ('HostConfig', 'ReadonlyRootfs', False),
                                   ('HostConfig', 'Privileged', True), ('HostConfig', 'CapAdd', ['SYS_ADMIN']),
                                   ('HostConfig', 'PidMode', 'host'), ('HostConfig', 'Devices', [{'PathOnHost': '/dev/sda'}]),
                                   ('HostConfig', 'PortBindings', {'5432/tcp': [{'HostPort': '5432'}]}),
                                   ('HostConfig', 'Binds', [str(scratch / 'data') + ':' + recovery.MOUNT + ':z']),
                                   ('Config', 'User', '0'), ('Config', 'Image', 'postgres:18'),
                                   ('Config', 'Entrypoint', ['docker-entrypoint.sh']),
                                   ('Config', 'Env', ['PGPASSWORD=synthetic'])):
            changed = copy.deepcopy(original); changed[section][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, runid)
        changed = copy.deepcopy(original); changed['Mounts'][0]['Source'] = '/production'
        with self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, runid)
        for key, value in (('ProcessLabel', ''), ('ProcessLabel', 'system_u:system_r:unconfined_t:s0:c100,c200'),
                           ('MountLabel', 'system_u:object_r:container_file_t:s0'),
                           ('MountLabel', 'system_u:object_r:container_file_t:s0:c101,c201')):
            changed = copy.deepcopy(original); changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                recovery.require_container(changed, scratch, runid)


if __name__ == '__main__': unittest.main()
