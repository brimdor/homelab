"""Reject unsafe source and mismatched native compiler inputs without a GPU."""

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fedora_nvidia_kernel_qualification as driver
import nvidia_kernel_build as build


class NvidiaBuildTests(unittest.TestCase):
    def test_full_install_plan_includes_reverse_dependents_and_refuses_unsafe_items(self):
        actions = SimpleNamespace(TransactionItemAction_INSTALL=1, TransactionItemAction_UPGRADE=2,
                                  TransactionItemAction_REPLACED=6, TransactionItemAction_REASON_CHANGE=7,
                                  transaction_item_action_to_string=str)
        configured = {}
        requested = []

        def package(name, architecture='x86_64', repository='ceph-updates', location=None):
            return SimpleNamespace(get_nevra=lambda: name, get_arch=lambda: architecture,
                                   get_repo_id=lambda: repository,
                                   get_location=lambda: location or 'Packages/p/' + name + '.rpm')

        old = package('openssl-old')

        def item(name, action=1, replacements=(), **kwargs):
            return SimpleNamespace(get_action=lambda: action, get_package=lambda: package(name, **kwargs),
                                   get_replaces=lambda: replacements)

        items = [item('gcc'), item('openssl', 2, (old,)), item('glibc-langpack-en'),
                 SimpleNamespace(get_action=lambda: 6, get_package=lambda: old)]
        transaction = SimpleNamespace(get_problems=lambda: problem,
                                      get_transaction_packages=lambda: items)
        sack = SimpleNamespace(create_repo=lambda name: SimpleNamespace(
            get_config=lambda: configured.setdefault(name, SimpleNamespace())), load_repos=lambda: None)
        config = SimpleNamespace()
        base = SimpleNamespace(load_config=lambda: None, get_config=lambda: config, setup=lambda: None,
                               get_repo_sack=lambda: sack)
        bindings = SimpleNamespace(transaction=actions, base=SimpleNamespace(
            Base=lambda: base, GoalProblem_NO_PROBLEM=0,
            Goal=lambda _base: SimpleNamespace(add_rpm_install=requested.append, resolve=lambda: transaction)))
        problem = 0
        plan = driver.package_plan(bindings, ['gcc'], driver.GUEST_ROOT)
        self.assertEqual(requested, ['gcc'])
        self.assertEqual(len(plan['transaction']), 4)
        self.assertEqual(len(plan['urls']), 3)
        self.assertTrue(any('/openssl.rpm' in url for url in plan['urls']))
        self.assertTrue(any('/glibc-langpack-en.rpm' in url for url in plan['urls']))
        self.assertFalse(config.plugins or config.install_weak_deps or config.skip_broken or config.skip_unavailable)
        self.assertTrue(config.gpgcheck)
        self.assertEqual(set(configured), {'ceph-base', 'ceph-updates'})
        for change in ({'action': 3}, {'action': 5}, {'architecture': 'i686'},
                       {'repository': 'foreign'}, {'location': 'Packages/../foreign.rpm'},
                       {'location': '/Packages/foreign.rpm'}, {'location': 'Packages//foreign.rpm'}):
            items.append(item('unsafe', **change))
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                driver.package_plan(bindings, ['gcc'], driver.GUEST_ROOT)
            items.pop()
        items.pop()
        with self.assertRaisesRegex(RuntimeError, 'unexplained'):
            driver.package_plan(bindings, ['gcc'], driver.GUEST_ROOT)
        problem = 1
        with self.assertRaisesRegex(RuntimeError, 'solver'):
            driver.package_plan(bindings, ['gcc'], driver.GUEST_ROOT)
        problem = 0
        items.clear()
        with self.assertRaisesRegex(RuntimeError, 'empty'):
            driver.package_plan(bindings, ['gcc'], driver.GUEST_ROOT)

    def test_source_inventory_refuses_links_traversal_duplicates_and_missing_entries(self):
        members = [tarfile.TarInfo(build.SOURCE_ROOT + '/Makefile')]
        members += [tarfile.TarInfo(build.SOURCE_ROOT + '/file' + str(i)) for i in range(4641)]
        self.assertEqual(build.source_members(SimpleNamespace(getmembers=lambda: members)), members)
        for bad in ('../foreign', '/foreign', build.SOURCE_ROOT + '/../foreign',
                    'foreign/file', build.SOURCE_ROOT + '//file'):
            with self.subTest(path=bad), self.assertRaises(RuntimeError):
                build.source_members(SimpleNamespace(getmembers=lambda: [tarfile.TarInfo(bad)]))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE):
            member = tarfile.TarInfo(build.SOURCE_ROOT + '/special')
            member.type = kind
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                build.source_members(SimpleNamespace(getmembers=lambda: [member]))
        for items in (members[:-1], members + [members[0]]):
            with self.assertRaises(RuntimeError):
                build.source_members(SimpleNamespace(getmembers=lambda: items))

    def test_exact_kernel_compiler_version_is_required(self):
        build.compiler_matches('CONFIG_GCC_VERSION=160201\n', '16.2.1')
        for config, compiler in [('CONFIG_GCC_VERSION=160201\n', '16.2.0'),
                                 ('CONFIG_GCC_VERSION=160201\n', '16.2'),
                                 ('', '16.2.1'), ('CONFIG_GCC_VERSION=160201\n' * 2, '16.2.1')]:
            with self.subTest(config=config, compiler=compiler), self.assertRaises(RuntimeError):
                build.compiler_matches(config, compiler)

    def test_actual_complete_guest_programs_compile_and_refuse_unaccepted_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'source.tar.gz'
            archive.write_bytes(b'synthetic-public-source')
            fixture = object.__new__(driver.Qualification)
            fixture.args = SimpleNamespace(work_dir=root, source_archive=archive)
            fixture.root = root
            fixture.ssh = []
            fixture.upload = lambda *args: None
            fixture.identity = lambda: {}
            programs = []
            accepted = True

            def command(_arguments, **kwargs):
                if 'data' in kwargs:
                    programs.append(kwargs['data'])
                    return b'{"urls":[],"native_signed_install":true}'
                return json.dumps({'accepted': accepted}).encode()

            fixture.command = command
            with patch.object(driver.repository, 'mirror', return_value={'files': {}, 'base': 'unused'}), \
                    patch.object(driver.Kernel, 'run', return_value={'accepted': True}), \
                    patch.object(driver.tarfile, 'open'), patch.object(build, 'source_members'), \
                    patch.object(build, 'SOURCE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()):
                self.assertTrue(fixture.run()['accepted'])
                for program in programs:
                    compile(program, '<actual-NVIDIA-guest-program>', 'exec')
                (root / 'nvidia-repositories').rmdir()
                accepted = False
                with self.assertRaisesRegex(RuntimeError, 'module build failed'):
                    fixture.run()
                self.assertFalse(json.loads((root / 'nvidia-build-result.json').read_text())['accepted'])


if __name__ == '__main__':
    unittest.main()
