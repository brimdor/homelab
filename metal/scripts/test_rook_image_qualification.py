#!/usr/bin/env python3
"""Refuse legacy keys, foreign images and unsafe native image execution."""

import base64
import copy
import struct
import unittest

import rook_image_qualification as subject


class ImageTests(unittest.TestCase):
    def test_anonymous_profile_cannot_load_stored_auth_or_helpers(self):
        subject.require_anonymous_config(copy.deepcopy(subject.ANONYMOUS_CONFIG))
        for value in [{}, {'auths': {}}, subject.ANONYMOUS_CONFIG | {'credsStore': 'osxkeychain'},
                      subject.ANONYMOUS_CONFIG | {'credHelpers': {'quay.io': 'helper'}},
                      {'auths': {'quay.io': {'username': 'synthetic'}}}]:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                subject.require_anonymous_config(value)

    def test_native_key_header_and_legacy_or_malformed_refusal(self):
        modern = struct.pack('<HIIH', 2, 1, 999_999_999, 32) + bytes(32)
        self.assertEqual(subject.default_key_metadata(base64.b64encode(modern))['type'], 2)
        variants = [b'', b'!', modern[:-1], modern + b'0',
                    struct.pack('<HIIH', 1, 1, 0, 16) + bytes(16),
                    struct.pack('<HIIH', 2, 0, 0, 32) + bytes(32),
                    struct.pack('<HIIH', 2, 1, 1_000_000_000, 32) + bytes(32),
                    struct.pack('<HIIH', 2, 1, 0, 31) + bytes(32)]
        for raw in [None, b'a' * 129, *[base64.b64encode(v) for v in variants]]:
            with self.subTest(length=len(raw) if raw else 0), self.assertRaises(RuntimeError):
                subject.default_key_metadata(raw)

    def test_versions_are_exact_and_bounded(self):
        subject.require_version(b'rook: v1.21.0\ngo: go1.25.1\n', '1.21.0', rook=True)
        subject.require_version(b'ceph version 20.2.4 (public-hash) tentacle (stable)\n', '20.2.4')
        for raw in [b'rook: v1.21.01\ngo: go1.25.1\n', b'rook: v1.21.0\nextra',
                    b'rook: v1.21.0\n', b'rook: v1.21.0\ngo: go1.25.1\nextra', b'x' * 1025]:
            with self.assertRaises(RuntimeError):
                subject.require_version(raw, '1.21.0', rook=True)

    def test_foreign_platform_digest_and_image_volumes_refused(self):
        reference = subject.candidate.CEPH_IMAGE
        value = {'Os': 'linux', 'Architecture': 'arm64', 'RepoDigests': [reference],
                 'Id': 'sha256:' + 'a' * 64, 'Config': {}}
        subject.require_image(value, reference)
        for field, changed in [('Os', 'darwin'), ('Architecture', 'amd64'),
                               ('RepoDigests', []), ('Id', 'foreign'),
                               ('Config', {'Volumes': {'/host': {}}})]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                subject.require_image(value | {field: changed}, reference)

    def test_native_container_isolation_cannot_be_weakened(self):
        value = {'Name': '/qualification-12345678-image-check', 'Image': 'sha256:synthetic',
                 'Config': {'Entrypoint': ['/usr/bin/ceph'], 'Cmd': ['--version']},
                 'HostConfig': {'NetworkMode': 'none', 'Privileged': False, 'ReadonlyRootfs': True,
                                'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                                'LogConfig': {'Type': 'none'}, 'Memory': 512 * 1024**2,
                                'NanoCpus': 1_000_000_000, 'PidsLimit': 64, 'IpcMode': 'private',
                                'Tmpfs': {'/tmp': 'rw,noexec,nosuid,size=16m,mode=1777'}}}
        arguments = ('qualification-12345678-image-check', 'sha256:synthetic', '/usr/bin/ceph', ['--version'])
        subject.require_container(value, *arguments)
        for key, changed in [('NetworkMode', 'host'), ('Privileged', True),
                             ('ReadonlyRootfs', False), ('CapAdd', ['NET_ADMIN']),
                             ('SecurityOpt', []), ('LogConfig', {'Type': 'json-file'}),
                             ('Binds', ['/host:/host']), ('Devices', [{}]), ('PidMode', 'host'),
                             ('Tmpfs', {}), ('Memory', 0), ('PidsLimit', 0)]:
            unsafe = copy.deepcopy(value)
            unsafe['HostConfig'][key] = changed
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_container(unsafe, *arguments)


if __name__ == '__main__':
    unittest.main()
