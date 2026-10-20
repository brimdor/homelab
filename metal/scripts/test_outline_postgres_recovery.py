#!/usr/bin/env python3
"""Guard the fixed Outline source, password-free archives and native isolation."""
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import outline_postgres_recovery as recovery


class OutlineRecoveryGuards(unittest.TestCase):
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

    def test_source_identity_refuses_runtime_credentials_and_storage_drift(self):
        pod = {'metadata': {'uid': recovery.IDENTITY[0], 'ownerReferences': [
                    {'uid': recovery.IDENTITY[1], 'kind': 'StatefulSet', 'controller': True}]},
               'spec': {'nodeName': 'pikachu', 'containers': [{'name': 'main', 'env': [
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
                                       (pod['status']['containerStatuses'][0], 'restartCount', 1),
                                       (claim['metadata'], 'uid', 'other'),
                                       (pv['spec']['csi'], 'driver', 'unknown')):
                old = target[key]; target[key] = wrong
                with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.source_identity()
                target[key] = old

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
                'RestartPolicy': {'Name': 'no'}}
        original = {'HostConfig': host, 'Config': {'Image': recovery.IMAGE, 'User': '999:999', 'Labels': {recovery.LABEL: runid},
                    'Entrypoint': ['/bin/sh'], 'Cmd': ['-c', 'exec sleep 2147483647'], 'Env': ['PG_MAJOR=18']},
                    'Mounts': [{'Type': 'bind', 'Source': str(scratch / 'data'), 'Destination': recovery.MOUNT, 'RW': True}]}
        recovery.require_container(original, scratch, runid)
        for section, key, value in (('HostConfig', 'NetworkMode', 'host'), ('HostConfig', 'ReadonlyRootfs', False),
                                   ('HostConfig', 'Privileged', True), ('HostConfig', 'CapAdd', ['SYS_ADMIN']),
                                   ('HostConfig', 'PidMode', 'host'), ('HostConfig', 'Devices', [{'PathOnHost': '/dev/sda'}]),
                                   ('HostConfig', 'PortBindings', {'5432/tcp': [{'HostPort': '5432'}]}),
                                   ('Config', 'User', '0'), ('Config', 'Image', 'postgres:18'),
                                   ('Config', 'Entrypoint', ['docker-entrypoint.sh']),
                                   ('Config', 'Env', ['PGPASSWORD=synthetic'])):
            changed = copy.deepcopy(original); changed[section][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, runid)
        changed = copy.deepcopy(original); changed['Mounts'][0]['Source'] = '/production'
        with self.assertRaises(RuntimeError): recovery.require_container(changed, scratch, runid)


if __name__ == '__main__': unittest.main()
