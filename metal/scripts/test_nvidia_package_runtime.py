"""Keep independent vendor policy and driver identities exact."""

import unittest

import nvidia_package_runtime as runtime


class NvidiaRuntimePackageTests(unittest.TestCase):
    def inventory(self):
        names = ('nvidia-open', 'kmod-nvidia-open-dkms', 'nvidia-kmod-common',
                 'nvidia-driver-cuda', 'nvidia-driver', 'nvidia-driver-libs', 'libnvidia-fbc')
        return [name + ' 3:' + runtime.VERSION + '-1.fc44.x86_64' for name in names] + [
            'nvidia-driver-selinux 0:0.1-2.fc44.noarch', 'unrelated-package 0:1.0-1.fc44.noarch']

    def test_policy_has_exact_independent_edition_and_remains_in_comparison_inventory(self):
        packages = runtime.installed_packages('\n'.join(self.inventory()))
        self.assertEqual(packages['nvidia-driver-selinux'], '0:0.1-2.fc44.noarch')
        self.assertEqual(packages['nvidia-driver'], '3:' + runtime.VERSION + '-1.fc44.x86_64')
        self.assertNotIn('unrelated-package', packages)

    def test_policy_cannot_be_missing_duplicated_or_use_another_edition(self):
        rows = self.inventory()
        for edition in ('0:0.1-3.fc44.noarch', '0:0.1-2.fc43.noarch',
                        '0:0.1-2.fc44.x86_64', '3:' + runtime.VERSION + '-1.fc44.noarch'):
            with self.subTest(edition=edition), self.assertRaises(AssertionError):
                runtime.installed_packages('\n'.join(rows[:-2] + ['nvidia-driver-selinux ' + edition]))
        for invalid in (rows[:-2], rows + [rows[-2]]):
            with self.subTest(rows=invalid), self.assertRaises(AssertionError):
                runtime.installed_packages('\n'.join(invalid))

    def test_driver_checks_and_required_packages_remain_enforced(self):
        rows = self.inventory()
        for invalid in (rows[1:], rows + [rows[0]],
                        ['nvidia-open 0:0.1-2.fc44.noarch'] + rows[1:],
                        [rows[0].replace(runtime.VERSION, '615.71.09')] + rows[1:]):
            with self.subTest(rows=invalid), self.assertRaises(AssertionError):
                runtime.installed_packages('\n'.join(invalid))


if __name__ == '__main__':
    unittest.main()
