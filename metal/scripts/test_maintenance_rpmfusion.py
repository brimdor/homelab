"""Signed coverage and a single retry of the proven pre-transaction failure."""

from contextlib import nullcontext
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import maintenance_rpmfusion as coverage
from maintenance_node_drain import private_json


class RpmFusionTests(unittest.TestCase):
    def test_private_repositories_preserve_trust_and_exclude_nonfree_driver_provider(self):
        for release in (41, 43, 44):
            with self.subTest(release=release), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                keys = root / 'keys'; keys.mkdir()
                hashes = {}
                for component in coverage.KEYS:
                    raw = (component + ' synthetic key').encode()
                    (keys / ('RPM-GPG-KEY-rpmfusion-' + component + '-fedora-2020')).write_bytes(raw)
                    hashes[component] = hashlib.sha256(raw).hexdigest()
                calls = []
                with patch.dict(coverage.KEYS, hashes):
                    result = coverage.configure(root, release, lambda *a: calls.append(a), keys)
                    content = (root / 'rpmfusion.repo').read_text()
                    self.assertEqual(content.count('gpgcheck=1'), 3)
                    self.assertEqual(content.count('sslverify=1'), 3)
                    self.assertEqual(content.count('protocol=https'), 3)
                    self.assertIn('repo=free-fedora-updates-released-' + str(release), content)
                    self.assertTrue(content.endswith('includepkgs=rpmfusion-nonfree-release\n'))
                    self.assertNotIn('nonfree-fedora-updates', content)
                    self.assertEqual(coverage.configure(root, release, lambda *a: None, keys), result)
                    (root / 'rpmfusion.repo').write_text(content + '# foreign\n')
                    with self.assertRaisesRegex(RuntimeError, 'repository differs'):
                        coverage.configure(root, release, lambda *a: None, keys)
                    (root / 'rpmfusion.repo').write_text(content)
                    key = keys / 'RPM-GPG-KEY-rpmfusion-free-fedora-2020'
                    key.write_text('changed key')
                    with self.assertRaisesRegex(RuntimeError, 'trust anchor'):
                        coverage.configure(root, release, lambda *a: None, keys)
                self.assertEqual(len(calls), 3)

    def test_conflicting_repository_symlink_and_unknown_release_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, 'release'):
                coverage.configure(root, 42, lambda *a: None)
            keys = root / 'keys'; keys.mkdir()
            (keys / 'RPM-GPG-KEY-rpmfusion-free-fedora-2020').symlink_to('/dev/null')
            with self.assertRaises(RuntimeError):
                coverage.configure(root, 41, lambda *a: None, keys)

    def test_repair_preserves_failure_chain_and_never_replays_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); calls = []
            owner = {'owner': coverage.OWNER}
            state = {'pending': {'sha256': coverage.PENDING}}
            before = {'installed_sha256': 'original', 'pending': state['pending']}
            hold = SimpleNamespace(state=root, serialized=nullcontext)
            journal = SimpleNamespace(hold=hold, owners=lambda **kw: {'global': owner}, read=lambda: state)
            with patch.object(coverage, 'failed_download', return_value=before), \
                    patch.object(coverage, 'configure', return_value={'signed': True}), \
                    patch.object(coverage, 'repository_hashes', return_value={'rpmfusion.repo': 'signed'}), \
                    patch.object(coverage, 'installed', return_value='original'):
                first = coverage.repair(journal, lambda *a: calls.append(a), lambda: {'fresh': True})
                self.assertTrue(first['dispatched_recovery'])
                second = coverage.repair(journal, lambda *a: calls.append(a), lambda: {'fresh': True})
                self.assertTrue(second['observe_only'])
                self.assertEqual(calls, [('systemctl', 'start', coverage.OWNER + '-download-release.service')])
                self.assertEqual(private_json(root / ('rpmfusion-download-before-' + coverage.OWNER + '.json')), before)
                with patch.object(coverage, 'status', return_value={'InvocationID': 'a' * 32}):
                    journal.token = coverage.OWNER
                    self.assertTrue(coverage.accepted(journal, lambda *a: '')['original_failed_download_retained'])
                with patch.object(coverage, 'status', return_value={'InvocationID': coverage.INVOCATION}):
                    with self.assertRaisesRegex(RuntimeError, 'invocation'):
                        coverage.accepted(journal, lambda *a: '')
                with patch.object(coverage, 'installed', return_value='changed'):
                    with self.assertRaisesRegex(RuntimeError, 'inputs changed'):
                        coverage.accepted(journal, lambda *a: '')

    def test_changed_prerequisites_or_packages_never_dispatch(self):
        for fault in ('prerequisites', 'packages', 'failure'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); calls = []
                before = {'installed_sha256': 'original'}
                journal = SimpleNamespace(hold=SimpleNamespace(state=root, serialized=nullcontext),
                    owners=lambda **kw: {'global': {'owner': coverage.OWNER}}, read=lambda: {'pending': 7})
                values = iter([{'fresh': 1}, {'fresh': 2}])
                with patch.object(coverage, 'failed_download', side_effect=[before, {'changed': True}] if fault == 'failure' else None,
                                  return_value=before), \
                        patch.object(coverage, 'configure', return_value={}), \
                        patch.object(coverage, 'installed', return_value='changed' if fault == 'packages' else 'original'):
                    with self.assertRaises(RuntimeError):
                        coverage.repair(journal, lambda *a: calls.append(a), lambda: next(values))
                self.assertFalse(calls)
                self.assertFalse((root / ('rpmfusion-download-dispatch-' + coverage.OWNER + '.json')).exists())

    def test_failed_download_refuses_other_owner_or_intent_before_native_work(self):
        owner = {'owner': coverage.OWNER, 'node': 'arcanine',
                 'node_uid': '88aa2572-09df-40b9-8a00-960e9682917c', 'source': 39, 'target': 41}
        state = {'completed': ['cordon', 'drain', 'prepare_source'],
                 'pending': {'sha256': coverage.PENDING, 'sequence': 7, 'step': 'download_release'}}
        for key, value in (('owner', 'foreign'), ('node', 'pikachu'), ('source', 41), ('target', 43)):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'owner'):
                coverage.failed_download(dict(owner, **{key: value}), state, lambda *a: self.fail('native'), Path('/private'))
        for key, value in (('sha256', '0' * 64), ('sequence', 8), ('step', 'offline_transaction')):
            bad = dict(state, pending=dict(state['pending'], **{key: value}))
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'intent'):
                coverage.failed_download(owner, bad, lambda *a: self.fail('native'), Path('/private'))

    def test_failed_download_requires_original_stopped_invocation_boot_log_and_empty_cache(self):
        owner = {'owner': coverage.OWNER, 'node': 'arcanine',
                 'node_uid': '88aa2572-09df-40b9-8a00-960e9682917c', 'source': 39, 'target': 41}
        state = {'completed': ['cordon', 'drain', 'prepare_source'],
                 'pending': {'sha256': coverage.PENDING, 'sequence': 7, 'step': 'download_release'}}
        for fault in (None, 'boot', 'release', 'cache', 'offline', 'invocation', 'actor', 'command', 'log'):
            with self.subTest(fault=fault):
                boot = MagicMock(); boot.read_text.return_value = 'foreign' if fault == 'boot' else coverage.BOOT
                cache = MagicMock(); cache.rglob.return_value = [Path('existing.rpm')] if fault == 'cache' else []
                observed = {'LoadState': 'loaded', 'ActiveState': 'failed', 'Result': 'exit-code',
                    'ExecMainStatus': '1', 'MainPID': '0', 'ControlPID': '0', 'InvocationID': coverage.INVOCATION,
                    'ExecStart': '{ argv[]=/usr/bin/dnf --setopt=reposdir=/private --setopt=gpgcheck=True '
                    '--setopt=localpkg_gpgcheck=True -y system-upgrade download --releasever=41 ; }'}
                if fault == 'invocation':observed['InvocationID'] = 'other'
                if fault == 'actor':observed['MainPID'] = '123'
                if fault == 'command':observed['ExecStart'] = '/usr/bin/dnf erase data'
                def native(*args):
                    if args[0] == 'journalctl':return 'changed' if fault == 'log' else 'original failure'
                    return '41' if fault == 'release' else '39'
                with patch.object(coverage, 'Path', side_effect=lambda value: boot if value.startswith('/proc/') else cache), \
                        patch.object(coverage.os.path, 'lexists', return_value=fault == 'offline'), \
                        patch.object(coverage, 'status', return_value=observed), \
                        patch.object(coverage, 'installed', return_value='unchanged'), \
                        patch.object(coverage, 'FAILURE', hashlib.sha256(b'original failure').hexdigest()):
                    if fault:
                        with self.assertRaises(RuntimeError):coverage.failed_download(owner, state, native, Path('/private'))
                    else:
                        self.assertEqual(coverage.failed_download(owner, state, native, Path('/private'))['installed_sha256'], 'unchanged')


if __name__ == '__main__':
    unittest.main()
