#!/usr/bin/env python3
"""Reject destructive device drift and preserve the fresh modern-key boundary."""

import copy
import unittest

import rook_native_candidate as subject


def inventory():
    return {'blockdevices': [
        {'path': '/dev/vd' + letter, 'type': 'disk', 'size': 8 * 1024**3,
         'serial': 'lima-rook-12345678-' + str(number), 'fstype': None,
         'mountpoints': [None], 'pkname': None, 'maj:min': '254:' + str(32 + number * 16),
         'ro': False}
        for number, letter in enumerate('cde')]}


class CandidateTests(unittest.TestCase):
    def test_foreign_cluster_disk_or_unsafe_guest_inventory_refused(self):
        for cluster, run in [('production', 'rook-12345678'),
                             ('qualification-12345678', 'production')]:
            with self.assertRaises(RuntimeError):
                subject.resources(cluster, run, inventory())
        for fields in ({'path': '/dev/sda'}, {'fstype': 'ceph_bluestore'},
                       {'mountpoints': ['/']}, {'ro': True}, {'children': [{}]},
                       {'pkname': '/dev/vda'}, {'type': 'part'}, {'size': 4096},
                       {'serial': 'foreign'}, {'maj:min': '254:48'}):
            value = inventory()
            value['blockdevices'][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                subject.resources('qualification-12345678', 'rook-12345678', value)
        value = inventory()
        value['blockdevices'].append(copy.deepcopy(value['blockdevices'][0]))
        with self.assertRaises(RuntimeError):
            subject.resources('qualification-12345678', 'rook-12345678', value)

    def test_generation_is_scoped_and_preserves_security_and_redundancy(self):
        value = subject.resources('qualification-12345678', 'rook-12345678', inventory())
        self.assertEqual([row['kind'] for row in value],
                         ['Namespace', 'ConfigMap', 'CephCluster', 'CephBlockPool'])
        self.assertEqual({row['metadata'].get('namespace', row['metadata']['name'])
                          for row in value}, {'rook-qualification'})
        spec = value[2]['spec']
        self.assertEqual(spec['security']['cephx']['allowedCiphers'], ['aes256k'])
        self.assertNotIn('keyType', spec['security']['cephx']['daemon'])
        self.assertTrue(spec['csi']['skipUserCreation'])
        self.assertTrue(spec['network']['connections']['encryption']['enabled'])
        self.assertFalse(spec['skipUpgradeChecks'])
        self.assertFalse(spec['continueUpgradeAfterChecksEvenIfNotHealthy'])
        self.assertFalse(spec['storage']['useAllNodes'])
        self.assertFalse(spec['storage']['useAllDevices'])
        self.assertEqual([row['devices'] for row in spec['storage']['nodes']],
                         [[{'name': '/dev/vdc'}], [{'name': '/dev/vdd'}], [{'name': '/dev/vde'}]])
        self.assertEqual(len({row['name'] for row in spec['storage']['nodes']}), 3)
        self.assertEqual(spec['cephConfig']['global']['osd_pool_default_size'], '2')
        self.assertEqual(spec['cephConfig']['global']['osd_pool_default_min_size'], '2')
        self.assertEqual(value[3]['spec']['replicated']['size'], 2)
        self.assertEqual(value[3]['spec']['parameters']['min_size'], '2')

    def test_unreviewed_operator_versions_and_render_bytes_refused(self):
        for version in ['1.20.8', '1.21.1', 'latest']:
            with self.assertRaises(RuntimeError):
                subject.operator_values(version)
        for version in subject.OPERATORS:
            values = subject.operator_values(version)
            self.assertFalse(values['csi']['installCsiOperator'])
            self.assertFalse(values['csi']['createCsiOperatorResources'])
            for raw in (b'', b'kind: Secret\n', b'foreign render', None):
                with self.assertRaises(RuntimeError):
                    subject.require_operator_render(version, raw)
                with self.assertRaises(RuntimeError):
                    subject.qualify_admission(version, raw, 'qualification-12345678',
                                              'rook-12345678', inventory(), 'synthetic')

    def test_admission_cannot_default_to_emergency_cipher_or_broader_devices(self):
        requested = subject.resources('qualification-12345678', 'rook-12345678', inventory())[2:]
        admitted = copy.deepcopy(requested)
        admitted[0]['metadata']['uid'] = 'synthetic-dry-run'
        subject.require_admitted_profile(requested, admitted)
        mutations = [
            ('daemon', 'keyType', 'aes'), ('daemon', 'keyType', 'aes256k'),
            ('storage', 'useAllDevices', True), ('storage', 'deviceFilter', '.*'),
            ('storage', 'storageClassDeviceSets', [{}]), ('spec', 'skipUpgradeChecks', True),
        ]
        for section, key, value in mutations:
            changed = copy.deepcopy(admitted)
            target = changed[0]['spec']
            if section == 'daemon':
                target = target['security']['cephx']['daemon']
            elif section == 'storage':
                target = target['storage']
            target[key] = value
            with self.subTest(section=section, key=key), self.assertRaises(RuntimeError):
                subject.require_admitted_profile(requested, changed)
        changed = copy.deepcopy(admitted)
        changed[0]['spec']['security']['cephx']['allowedCiphers'].append('aes')
        with self.assertRaises(RuntimeError):
            subject.require_admitted_profile(requested, changed)
        with self.assertRaises(RuntimeError):
            subject.require_admitted_profile(requested, admitted[:1])


if __name__ == '__main__':
    unittest.main()
