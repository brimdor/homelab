"""Native object corruption, configuration refusals, isolation and cleanup."""

import copy
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gitea_git_recovery as recovery


class GiteaGitRecoveryContract(unittest.TestCase):
    def test_repository_identity_and_external_object_storage_refusals(self):
        roots = ['synthetic/a.git', 'synthetic/b.git', 'synthetic/c.git']
        tree = {}
        for root in roots:
            tree.update({root + '/' + name: {'kind': kind} for name, kind in (
                ('HEAD', 'file'), ('objects', 'directory'), ('refs', 'directory'), ('config', 'file'))})
        expected = {hashlib.sha256(root.encode()).hexdigest() for root in roots}
        with patch.object(recovery, 'ROOTS', expected):
            self.assertEqual(recovery.discover(tree), roots)
            for name, kind in [('objects/info/alternates', 'file'), ('objects/info/http-alternates', 'file'),
                               ('shallow', 'file'), ('commondir', 'file'), ('objects/pack/a.promisor', 'file'),
                               ('refs/replace/a', 'file'), ('objects/loose-link', 'symlink')]:
                changed = {**tree, roots[0] + '/' + name: {'kind': kind}}
                with self.assertRaises(RuntimeError):
                    recovery.discover(changed)
            changed = dict(tree)
            del changed[roots[0] + '/HEAD']
            with self.assertRaises(RuntimeError):
                recovery.discover(changed)
        with self.assertRaises(RuntimeError):
            recovery.discover(tree)

    def test_config_commands_never_request_credential_values(self):
        commands = []
        keys = b'core.repositoryformatversion\0core.bare\0core.filemode\0remote.origin.url\0remote.origin.mirror\0'
        def run(args):
            commands.append(args)
            self.assertIn('--name-only', args)
            if '--list' in args:
                return keys
            return args[-2][1:-1].replace('\\.', '.').encode() + b'\0'
        recovery.check_config(run, '/synthetic')
        self.assertEqual(len(commands), 5)
        self.assertTrue(all('--get-regexp' not in args or '.url' not in args[-2] for args in commands))
        for bad in (b'include.path', b'includeif.test.path', b'fsck.skiplist', b'fsck.missingemail',
                    b'extensions.partialclone', b'core.hookspath', b'unknown.setting', b'core.bare'):
            with self.assertRaises(RuntimeError):
                recovery.check_config(lambda _args: keys + bad + b'\0', '/synthetic')
        for bad in (keys[:-1], b'core.bare\0'):
            with self.assertRaises(RuntimeError):
                recovery.check_config(lambda _args: bad, '/synthetic')
        with self.assertRaises(RuntimeError):
            recovery.check_config(lambda args: keys if '--list' in args else b'', '/synthetic')

    def test_reference_fingerprints_refuse_replacement_malformed_and_duplicate_refs(self):
        raw = b'refs/heads/main\0' + b'a' * 40 + b'\0commit\n'
        self.assertEqual(recovery.references(raw), {'references': 1, 'sha256': hashlib.sha256(raw).hexdigest()})
        for bad in (b'', raw + raw, raw.replace(b'refs/heads/', b'refs/replace/'),
                    raw.replace(b'commit', b'unknown'), raw.replace(b'a' * 40, b'a' * 39)):
            with self.assertRaises(RuntimeError):
                recovery.references(bad)

    def container(self, root, volumes, args):
        return {'Image': 'sha256:owned', 'Config': {
            'Image': recovery.IMAGE, 'User': '1000:1000', 'Entrypoint': ['/usr/bin/git'],
            'Cmd': [*recovery.PREFIX, *args], 'WorkingDir': '/tmp', 'Healthcheck': {'Test': ['NONE']},
            'Env': [key + '=' + value for key, value in recovery.ENV.items()],
            'Labels': {recovery.LABEL: 'fixture'}}, 'HostConfig': {
                'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 1073741824,
                'NanoCpus': 1000000000, 'Tmpfs': recovery.TMPFS, 'RestartPolicy': {'Name': 'no'},
                'LogConfig': {'Type': 'none', 'Config': {}}},
            'Mounts': [{'Type': 'bind', 'RW': False, 'Source': source, 'Destination': target}
                       for target, source in recovery.mounts(root, volumes).items()]}

    def test_exact_isolation_and_failure_cleanup_keep_private_output_out_of_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, volumes = ['--version'], ['/data']
            value = self.container(root, volumes, args)
            recovery.require_container(value, root, volumes, 'fixture', args, 'sha256:owned')
            for mutate in (
                    lambda v: v['HostConfig'].update(NetworkMode='host'),
                    lambda v: v['HostConfig'].update(Privileged=True),
                    lambda v: v['HostConfig'].update(CapAdd=['SYS_ADMIN']),
                    lambda v: v['HostConfig'].update(LogConfig={'Type': 'json-file', 'Config': {}}),
                    lambda v: v['Config'].update(User='0:0'),
                    lambda v: v['Config'].update(Entrypoint=['/app/gitea/gitea']),
                    lambda v: v['Config'].update(Healthcheck={'Test': ['CMD-SHELL', 'unreviewed']}),
                    lambda v: v['Config']['Env'].append('GIT_CONFIG_SYSTEM=/private'),
                    lambda v: v['Mounts'][0].update(RW=True),
                    lambda v: v['Mounts'][0].update(Source='/original'),
                    lambda v: v['Mounts'].append({'Type': 'volume', 'RW': True})):
                changed = copy.deepcopy(value)
                mutate(changed)
                with self.assertRaises(RuntimeError):
                    recovery.require_container(changed, root, volumes, 'fixture', args, 'sha256:owned')
            calls = []
            def docker(*items, **_kwargs):
                calls.append(items)
                if items[0] == 'create':
                    return SimpleNamespace(stdout=('a' * 64).encode())
                if items[0] == 'start':
                    return SimpleNamespace(stdout=b'synthetic-private-record', stderr=b'', returncode=2)
                return SimpleNamespace(returncode=1 if items[0] == 'inspect' else 0)
            value['State'] = {'Running': False, 'ExitCode': 2, 'OOMKilled': False}
            with patch.object(recovery, 'POINT', root), patch.object(recovery.common, 'docker', side_effect=docker), \
                    patch.object(recovery.common, 'inspect', return_value=value):
                with self.assertRaises(RuntimeError) as caught:
                    recovery.operation(root, volumes, 'fixture', args, 'sha256:owned')
            self.assertNotIn('synthetic-private-record', str(caught.exception))
            self.assertEqual(list(root.glob('git-failure-*.log')), [])
            self.assertIn(('rm', '-f', 'a' * 64), calls)

    def test_native_git_detects_corruption_and_configuration_is_parsed_without_includes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'repository.git'
            environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
            environment.update(recovery.ENV)
            def git(*args, data=None):
                return subprocess.run(['git', *recovery.PREFIX, *args], input=data, env=environment,
                                      cwd=directory, capture_output=True)
            self.assertEqual(git('init', '--bare', '--quiet', str(root)).returncode, 0)
            (root / 'config').write_text('[core]\nrepositoryformatversion = 0\nbare = true\nfilemode = true\n')
            sentinel = b'https://synthetic:ghp_SYNTHETIC_SENTINEL_NEVER_REAL@invalid.example/repo'
            with (root / 'config').open('ab') as target:
                target.write(b'\n[remote "origin"]\nurl = ' + sentinel + b'\nmirror = true\n')
            def config_run(args):
                args = [item.replace('/fixture/config', str(root / 'config')) for item in args]
                result = git(*args)
                self.assertNotIn(sentinel, result.stdout + result.stderr)
                if result.returncode:
                    raise RuntimeError('native config query failed')
                return result.stdout
            recovery.check_config(config_run, '/fixture')
            for key, bad, good in (('core.bare', 'false', 'true'),
                                   ('core.repositoryformatversion', '1', '0'),
                                   ('core.filemode', 'invalid', 'true'),
                                   ('remote.origin.mirror', 'false', 'true')):
                self.assertEqual(git('config', '--file', str(root / 'config'), key, bad).returncode, 0)
                with self.assertRaises(RuntimeError):
                    recovery.check_config(config_run, '/fixture')
                self.assertEqual(git('config', '--file', str(root / 'config'), key, good).returncode, 0)
            object_id = git('--git-dir=' + str(root), 'hash-object', '-w', '--stdin', data=b'synthetic object').stdout.strip()
            self.assertRegex(object_id.decode(), '^[a-f0-9]{40}$')
            self.assertEqual(git('--git-dir=' + str(root), 'update-ref', 'refs/tags/fixture', object_id.decode()).returncode, 0)
            check = git('--git-dir=' + str(root), 'fsck', '--full', '--strict', '--no-dangling')
            self.assertEqual(check.returncode, 0, check.stderr.decode())
            refs = git('--git-dir=' + str(root), 'for-each-ref', '--sort=refname',
                       '--format=%(refname)%00%(objectname)%00%(objecttype)')
            self.assertEqual(recovery.references(refs.stdout)['references'], 1)
            path = root / 'objects' / object_id[:2].decode() / object_id[2:].decode()
            path.chmod(0o600)
            path.write_bytes(b'corrupt synthetic object')
            self.assertNotEqual(git('--git-dir=' + str(root), 'fsck', '--full', '--strict', '--no-dangling').returncode, 0)
            with (root / 'config').open('ab') as target:
                target.write(b'\n[include]\npath = /synthetic-missing-include\n')
            with self.assertRaises(RuntimeError):
                recovery.check_config(config_run, '/fixture')


if __name__ == '__main__':
    unittest.main()
