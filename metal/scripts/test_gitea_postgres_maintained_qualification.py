"""Refuse altered runtime payloads and candidate-container access before native work."""

import copy
import unittest
from unittest.mock import patch

import gitea_postgres_maintained_qualification as candidate


class MaintainedQualificationTests(unittest.TestCase):
    def test_official_native_digest_alias_preserves_exact_image_contract(self):
        value = {'Architecture': 'amd64', 'Os': 'linux',
                 'Config': {'Volumes': {'/var/lib/postgresql/data': {}}},
                 'RepoDigests': [candidate.IMAGE.removeprefix('docker.io/library/')]}
        candidate.require_image(value, candidate.IMAGE)
        for mutate in (lambda v: v.update(Architecture='arm64'),
                       lambda v: v.update(RepoDigests=['postgres@sha256:' + '0' * 64]),
                       lambda v: v['Config']['Volumes'].update({'/foreign': {}})):
            changed = copy.deepcopy(value)
            mutate(changed)
            with self.assertRaises(RuntimeError):
                candidate.require_image(changed, candidate.IMAGE)

    def test_payload_requires_exact_files_and_published_checksums(self):
        for value in ({}, {'extra': 'YQ=='}, {name: 'YQ==' for name in candidate.FILES},
                      {name: 'not base64' for name in candidate.FILES}):
            with self.subTest(value=list(value)), self.assertRaisesRegex(RuntimeError, 'payload differs'):
                candidate.validate_payload(value)

    def test_missing_or_foreign_point_refused_before_docker(self):
        with patch.object(candidate.common, 'run_identifier'), patch.object(candidate.common, 'require_host'), \
                patch.object(candidate.common, 'private_root'), patch.object(candidate.common, 'docker') as docker, \
                self.assertRaisesRegex(RuntimeError, 'exact protected existing-account source'):
            candidate.run(candidate.Path('/tmp/foreign'), 'a' * 64, {}, b'', 'test', {})
        docker.assert_not_called()

    def test_candidate_isolation_rejects_foreign_mount_secret_and_privilege(self):
        mounted = {'/var/lib/postgresql/data': ('/owned/empty', True)}
        host = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 1073741824,
                'NanoCpus': 1000000000, 'Tmpfs': candidate.TMPFS, 'LogConfig': {'Type': 'none', 'Config': {}},
                'RestartPolicy': {'Name': 'no'}}
        config = {'Image': candidate.IMAGE, 'User': '1001:1001', 'Entrypoint': ['/bin/sh'],
                  'Cmd': ['-c', 'exec sleep 2147483647'], 'WorkingDir': '/tmp',
                  'Labels': {candidate.LABEL: 'test'}, 'Healthcheck': {'Test': ['NONE']},
                  'Env': [k + '=' + v for k, v in candidate.legacy.ENV.items()]}
        value = {'Config': config, 'HostConfig': host, 'Image': 'image-id',
                 'Mounts': [{'Type': 'bind', 'Destination': '/var/lib/postgresql/data',
                             'Source': '/owned/empty', 'RW': True}]}
        with patch.object(candidate.common, 'inspect', return_value=value):
            candidate.require_candidate('container', mounted, 'none', 'test', 'image-id')
        mutations = (lambda v: v['HostConfig'].update(NetworkMode='host'),
                     lambda v: v['HostConfig'].update(Privileged=True),
                     lambda v: v['HostConfig'].update(CapAdd=['SYS_ADMIN']),
                     lambda v: v['Config']['Env'].append('PGPASSWORD=forbidden-fixture'),
                     lambda v: v['Config'].update(User='0:0'),
                     lambda v: v['Mounts'][0].update(Source='/production/data'),
                     lambda v: v['Config'].update(Image='unreviewed'))
        for mutation in mutations:
            changed = copy.deepcopy(value); mutation(changed)
            with patch.object(candidate.common, 'inspect', return_value=changed), self.assertRaises(RuntimeError):
                candidate.require_candidate('container', mounted, 'none', 'test', 'image-id')


if __name__ == '__main__':
    unittest.main()
