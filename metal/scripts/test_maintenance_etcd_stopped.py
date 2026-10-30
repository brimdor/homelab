"""The stopped-member reader refuses live services, changed identity and writers."""

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import maintenance_etcd_stopped as stopped


class StoppedSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.identity = {'machine': 'original-machine', 'root_uuid': 'original-root'}
        self.files = {
            '/etc/machine-id': b'original-machine\n',
            '/proc/sys/kernel/random/boot_id': b'original-boot\n',
            '/sys/fs/selinux/enforce': b'1\n',
            '/usr/local/bin/k3s': b'synthetic executable',
            '/etc/rancher/k3s/config.yaml': b'original configuration',
            '/etc/systemd/system/k3s.service': b'original unit file',
        }
        for name, data in self.files.items():
            path = self.root / name.lstrip('/');path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data);path.chmod(0o600)
        self.unit = {'ActiveState': 'inactive', 'SubState': 'dead', 'MainPID': '0', 'ControlPID': '0',
                     'Job': '', 'KillMode': 'process', 'Delegate': 'yes'}
        self.before = {'version': stopped.SOURCE, 'binary_sha256': stopped.SHA256[stopped.SOURCE],
                       'pid': 123, 'selinux': 'Enforcing', 'boot': 'original-boot',
                       'configs': {name: hashlib.sha256(self.files[name]).hexdigest() for name in
                                   ('/etc/rancher/k3s/config.yaml', '/etc/systemd/system/k3s.service')},
                       'unit_sha256': hashlib.sha256(b'effective unit').hexdigest()}
        self.values = {
            ('systemctl', 'show', 'k3s', *[v for name in stopped.PROPERTIES for v in ('-p', name)]): self.unit_text(),
            ('findmnt', '-n', '-o', 'UUID', '/'): 'original-root',
            ('getenforce',): 'Enforcing', ('systemctl', 'cat', 'k3s'): 'effective unit',
            ('ss', '-H', '-lnt'): 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*',
        }
        self.proof = Mock(return_value=True)

    def unit_text(self):
        return '\n'.join(name + '=' + self.unit[name] for name in stopped.PROPERTIES)

    def native(self, *args):
        self.assertNotIn(args[:2], (('systemctl', 'start'), ('systemctl', 'stop'), ('systemctl', 'restart')))
        return self.values[args]

    def observe(self, before=None, digest=None):
        with patch.object(stopped, 'record', return_value={'sha256': digest or stopped.SHA256[stopped.SOURCE]}):
            return stopped.observe(self.native, before or self.before, self.identity, self.proof, self.root)

    def test_exact_stopped_source_accepts_without_service_or_data_mutation(self):
        original = {name: (self.root / name.lstrip('/')).read_bytes() for name in self.files}
        result = self.observe()
        self.assertTrue(result['accepted']);self.assertTrue(result['no_etcd_listener_or_process'])
        self.assertEqual(self.proof.call_count, 2)
        self.assertEqual(original, {name: (self.root / name.lstrip('/')).read_bytes() for name in self.files})

    def test_every_active_pending_or_nonpreserving_unit_state_is_rejected(self):
        key = next(k for k in self.values if k[:2] == ('systemctl', 'show'))
        for name, value in (('ActiveState', 'active'), ('SubState', 'failed'), ('MainPID', '123'),
                            ('ControlPID', '9'), ('Job', '42'), ('KillMode', 'control-group'), ('Delegate', 'no')):
            unit = dict(self.unit, **{name: value})
            self.values[key] = '\n'.join(k + '=' + unit[k] for k in stopped.PROPERTIES)
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'stopped and idle'):
                self.observe()
        self.values[key] = self.unit_text() + '\nMainPID=0'
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            self.observe()

    def test_changed_host_binary_config_and_security_are_rejected(self):
        for name in ('/etc/machine-id', '/proc/sys/kernel/random/boot_id', '/sys/fs/selinux/enforce',
                     '/etc/rancher/k3s/config.yaml', '/etc/systemd/system/k3s.service'):
            target = self.root / name.lstrip('/');original = target.read_bytes();target.write_bytes(b'changed')
            try:
                with self.subTest(name=name), self.assertRaises(RuntimeError):self.observe()
            finally:target.write_bytes(original)
        for key in (('findmnt', '-n', '-o', 'UUID', '/'), ('getenforce',), ('systemctl', 'cat', 'k3s')):
            original = self.values[key];self.values[key] = 'changed'
            try:
                with self.subTest(command=key), self.assertRaises(RuntimeError):self.observe()
            finally:self.values[key] = original
        with self.assertRaisesRegex(RuntimeError, 'executable changed'):self.observe(digest='0' * 64)
        for field, value in (('version', 'v1.33.6+k3s1'), ('pid', 0), ('selinux', 'Permissive')):
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'baseline'):
                self.observe(before=dict(self.before, **{field: value}))
        changed = copy.deepcopy(self.before);changed['configs'].pop('/etc/rancher/k3s/config.yaml')
        with self.assertRaisesRegex(RuntimeError, 'configuration missing'):self.observe(before=changed)

    def test_ipv4_ipv6_listener_and_independent_writers_are_rejected(self):
        key = ('ss', '-H', '-lnt');original = self.values[key]
        for address in ('0.0.0.0:2379', '[::]:2379', '*:2379'):
            self.values[key] = 'LISTEN 0 128 ' + address + ' 0.0.0.0:*'
            with self.subTest(address=address), self.assertRaisesRegex(RuntimeError, 'listener'):self.observe()
        self.values[key] = original
        process = self.root / 'proc/999';process.mkdir()
        for command in (b'/usr/bin/etcd\0', b'/usr/local/bin/k3s\0server\0'):
            (process / 'cmdline').write_bytes(command)
            with self.subTest(command=command), self.assertRaisesRegex(RuntimeError, 'process remains'):self.observe()
        (process / 'cmdline').write_bytes(b'/usr/bin/containerd-shim-runc-v2\0')
        self.assertTrue(self.observe()['accepted'])

    def test_new_or_symlinked_configuration_is_rejected(self):
        directory = self.root / 'etc/rancher/k3s/config.yaml.d';directory.mkdir()
        (directory / 'new.yaml').write_text('new configuration')
        with self.assertRaisesRegex(RuntimeError, 'membership changed'):self.observe()
        (directory / 'new.yaml').unlink()
        original = self.root / 'etc/rancher/k3s/config.yaml'
        moved = original.with_name('original');original.rename(moved);original.symlink_to(moved)
        with self.assertRaisesRegex(RuntimeError, 'unsafe actor ownership path'):self.observe()

    def test_changed_service_or_owner_cannot_produce_an_accepted_receipt(self):
        for values in ([False], [1], [True, False], [True, 1]):
            self.proof = Mock(side_effect=values)
            with self.subTest(proof=values), self.assertRaises(RuntimeError):self.observe()
        self.proof = Mock(return_value=True)
        original = self.native;calls = 0
        def changed(*args):
            nonlocal calls
            if args[:2] == ('systemctl', 'show'):
                calls += 1
                if calls == 2:return self.unit_text().replace('MainPID=0', 'MainPID=123')
            return original(*args)
        with patch.object(stopped, 'record', return_value={'sha256': stopped.SHA256[stopped.SOURCE]}), \
                self.assertRaisesRegex(RuntimeError, 'stopped and idle'):
            stopped.observe(changed, self.before, self.identity, self.proof, self.root)


if __name__ == '__main__':
    unittest.main()
