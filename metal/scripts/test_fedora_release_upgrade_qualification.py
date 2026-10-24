#!/usr/bin/env python3
"""Refuse foreign upgrade requests, releases and unverified cache inputs."""

import hashlib
import base64
import io
import json
import copy
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import fedora_release_upgrade_qualification as upgrade
import fedora_upgrade_repository as repository
from fedora_upgrade_bridge import bridge


class UpgradeRefusals(unittest.TestCase):
    def test_public_key_armor_preserves_bytes_and_known_crc24(self):
        for raw in (b'123456789', bytes(range(256)) * 5):
            armored = upgrade.armor_public_key(raw)
            lines = armored.splitlines()
            self.assertEqual(lines[0], b'-----BEGIN PGP PUBLIC KEY BLOCK-----')
            self.assertEqual(lines[1], b'')
            self.assertEqual(lines[-1], b'-----END PGP PUBLIC KEY BLOCK-----')
            self.assertEqual(base64.b64decode(b''.join(lines[2:-2]), validate=True), raw)
            self.assertTrue(all(len(line) <= 76 for line in lines[2:-2]))
            if raw == b'123456789':
                self.assertEqual(lines[-2], b'=Ic8C')

    def test_rollback_requires_exact_packages_data_and_stable_identity(self):
        expected = {'identity': {'machine': 'machine', 'root_uuid': 'root',
                                'architecture': 'x86_64', 'kernel': 'kernel', 'boot': 'before'},
                    'native': {'package_inventory': ['exact']}, 'corpus': {'sha256': 'same'}}
        current = copy.deepcopy(expected)
        current['identity']['boot'] = 'new-boot'
        upgrade.require_checkpoint_state(current, expected)
        for section, key, value in (('identity', 'machine', 'foreign'),
                                    ('identity', 'root_uuid', 'foreign'),
                                    ('identity', 'kernel', 'foreign'),
                                    ('native', 'package_inventory', ['other']),
                                    ('corpus', 'sha256', 'other')):
            changed = copy.deepcopy(current)
            changed[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaisesRegex(RuntimeError, 'checkpoint'):
                upgrade.require_checkpoint_state(changed, expected)

    def test_corrupted_or_redirected_response_never_becomes_a_cached_package(self):
        base = repository.BASES['39-base']
        relative = 'Packages/k/kernel.rpm'

        class Response(io.BytesIO):
            status = 200
            url = base + relative

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'package.rpm'
            with patch('urllib.request.urlopen', return_value=Response(b'owned public bytes')):
                digest = repository.fetch(base, relative, path, hashlib.sha256(b'owned public bytes').hexdigest())
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            path.unlink()
            with patch('urllib.request.urlopen', return_value=Response(b'corrupted')):
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    repository.fetch(base, relative, path, '0' * 64)
            self.assertFalse(path.exists())
            redirected = Response(b'owned public bytes')
            redirected.url = 'https://foreign.example/package.rpm'
            with patch('urllib.request.urlopen', return_value=redirected):
                with self.assertRaisesRegex(RuntimeError, 'origin'):
                    repository.fetch(base, relative, path)
            self.assertFalse(path.exists())

    def test_actual_generated_guest_programs_compile(self):
        fixture = object.__new__(upgrade.Qualification)
        fixture.contract = json.loads((upgrade.MAINTENANCE / 'fedora-upgrade-inputs.json').read_bytes())
        programs = []

        def compile_guest(body):
            programs.append(compile(upgrade.GUEST + body, '<actual-upgrade-guest>', 'exec'))
            return {}

        fixture.guest = compile_guest
        fixture.identity = lambda: {}
        fixture.corpus = lambda: {'unchanged': True}
        with tempfile.TemporaryDirectory() as temporary:
            fixture.args = SimpleNamespace(keys_dir=Path(temporary))
            for release in fixture.contract['keys']:
                (fixture.args.keys_dir / ('fedora' + release + '.gpg')).write_bytes(b'owned public bytes')
            fixture.configure()
        fixture.signatures()
        fixture.state(39, {'unchanged': True})
        self.assertEqual(len(programs), 3)

    def test_only_declared_native_hops(self):
        self.assertEqual(upgrade.require_hop(39, 41), '/usr/bin/dnf')
        for source, target in ((41, 43), (43, 44)):
            self.assertEqual(upgrade.require_hop(source, target), '/usr/bin/dnf5')
        for source, target in ((39, 44), (44, 43), (39, 40), (43, 45), ('39', 41), (39, True)):
            with self.subTest(source=source, target=target), self.assertRaisesRegex(RuntimeError, 'foreign'):
                upgrade.require_hop(source, target)

    def test_path_binds_exact_origin_and_metadata_or_package(self):
        record = {'base': repository.BASES['39-base'],
                  'files': {'repodata/repomd.xml': 'a' * 64},
                  'packages': {'Packages/k/kernel-core.rpm': 'b' * 64}}
        repositories = {'39-base': record}
        self.assertEqual(repository.requested_path('/39-base/repodata/repomd.xml', repositories),
                         ('39-base', 'repodata/repomd.xml', 'a' * 64))
        self.assertEqual(repository.requested_path('/39-base/Packages/k/kernel-core.rpm', repositories),
                         ('39-base', 'Packages/k/kernel-core.rpm', 'b' * 64))
        for value in ('/39-base/../private', '/39-base//repodata/repomd.xml',
                      '/39-base/repodata/missing.xml', '/44-base/repodata/repomd.xml',
                      '/39-base/Packages/k/kernel-core.rpm?token=x',
                      '/39-base/Packages/k/kernel-core.rpm#x', '/39-base/%2e%2e/private',
                      'https://foreign.example/private', None):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                repository.requested_path(value, repositories)
        record['base'] = 'https://foreign.example/'
        with self.assertRaisesRegex(RuntimeError, 'unverified'):
            repository.requested_path('/39-base/Packages/k/kernel-core.rpm', repositories)

    def test_foreign_origin_and_existing_or_redirected_output_refused_before_network(self):
        with tempfile.TemporaryDirectory() as temporary, patch('urllib.request.urlopen') as network:
            root = Path(temporary)
            output = root / 'package.rpm'
            with self.assertRaisesRegex(RuntimeError, 'foreign'):
                repository.fetch('https://foreign.example/', 'Packages/k/kernel.rpm', output)
            output.write_bytes(b'existing')
            with self.assertRaisesRegex(RuntimeError, 'exists'):
                repository.fetch(repository.BASES['39-base'], 'Packages/k/kernel.rpm', output)
            redirected = root / 'link'
            redirected.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'redirected'):
                repository.fetch(repository.BASES['39-base'], 'Packages/k/kernel.rpm', redirected / 'new')
            network.assert_not_called()

    def test_only_loopback_bridge_and_private_repository_root(self):
        with patch('socket.create_connection') as network:
            for port in (0, 65536, True, '8080', None):
                with self.subTest(port=port), self.assertRaisesRegex(RuntimeError, 'invalid'):
                    bridge(port)
            network.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            redirected = root / 'redirected'
            redirected.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'redirected'):
                repository.RepositoryServer(redirected / 'output')

    def test_exact_published_key_and_signed_image_inventory(self):
        inventory = json.loads((upgrade.MAINTENANCE / 'fedora-upgrade-inputs.json').read_bytes())
        self.assertEqual(set(inventory['keys']), {'39', '41', '43', '44'})
        self.assertEqual(inventory['cloud']['sha256'],
                         'ab5be5058c5c839528a7d6373934e0ce5ad6c8f80bd71ed3390032027da52f37')
        for record in inventory['keys'].values():
            self.assertRegex(record['fingerprint'], '^[0-9A-F]{40}$')
            self.assertRegex(record['sha256'], '^[0-9a-f]{64}$')
            self.assertRegex(record['dns'], '^[0-9a-f]{56}._openpgpkey.fedoraproject.org$')


if __name__ == '__main__':
    unittest.main()
