"""Firmware work must use the reviewed installed kernel and reject stale intents."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import maintenance_host_security as security


class FirmwareKernelTests(unittest.TestCase):
    def native(self, kernel, package=None):
        calls = []

        def native(*argv):
            calls.append(argv)
            if argv == ('uname', '-r'):
                return kernel
            if argv == ('rpm', '-qf', '/boot/vmlinuz-' + kernel,
                        '--qf', '%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}'):
                return package if package is not None else 'kernel-core ' + kernel
            if argv == ('getenforce',):
                return 'Enforcing'
            self.fail('unexpected native call: ' + repr(argv))

        return native, calls

    def test_both_reviewed_kernels_require_exact_package_ownership(self):
        for kernel in security.FIRMWARE_KERNELS:
            with self.subTest(kernel=kernel):
                native, calls = self.native(kernel)
                self.assertEqual(security.firmware_kernel(native), kernel)
                self.assertEqual(len(calls), 2)

    def test_unreviewed_kernel_stops_before_package_or_dispatch(self):
        for kernel in ('7.2.13-200.fc44.x86_64', '7.2.12-100.fc43.x86_64', '../other'):
            with self.subTest(kernel=kernel):
                native, calls = self.native(kernel)
                with self.assertRaisesRegex(AssertionError, 'review current Fedora 44 kernel'):
                    security.firmware_kernel(native)
                self.assertEqual(calls, [('uname', '-r')])

    def test_changed_package_name_or_version_is_refused(self):
        kernel = security.FIRMWARE_KERNELS[1]
        for package in ('kernel-core ' + security.FIRMWARE_KERNELS[0], 'custom-kernel ' + kernel):
            with self.subTest(package=package):
                native, _ = self.native(kernel, package)
                with self.assertRaisesRegex(AssertionError, 'running kernel package differs'):
                    security.firmware_kernel(native)

    def test_old_or_changed_intent_cannot_authorize_the_new_kernel(self):
        kernel = security.FIRMWARE_KERNELS[1]
        for recorded in (None, security.FIRMWARE_KERNELS[0]):
            with self.subTest(recorded=recorded), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = {'owner': 'owned', 'identity': {'machine': 'exact'}}
                if recorded is not None:
                    record['kernel'] = recorded
                (root / 'host-firmware-owned.json').write_text(json.dumps(record))
                journal = SimpleNamespace(token='owned', hold=SimpleNamespace(state=root))
                native, calls = self.native(kernel)
                with self.assertRaisesRegex(AssertionError, 'firmware record kernel differs'):
                    security.firmware('observe-security-firmware', journal, native,
                                      lambda: {'machine': 'exact'}, {})
                self.assertFalse(any(call[0] == 'systemctl' for call in calls))
                self.assertEqual(sorted(p.name for p in root.iterdir()), ['host-firmware-owned.json'])


if __name__ == '__main__':
    unittest.main()
