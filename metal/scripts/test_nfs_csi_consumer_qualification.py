"""Guard consumer identity and native cache evidence without touching storage."""

import unittest

import nfs_csi_consumer_qualification as consumer


class ConsumerContractTests(unittest.TestCase):
    def test_current_consumer_identities_and_mount_ownership(self):
        builder = consumer.consumer_manifest('qualification-owned', 'claim', 'builder', 0, 1000, 1000)
        backup = consumer.consumer_manifest('qualification-owned', 'claim', 'backup', 1, 0)
        security = builder['spec']['securityContext']
        self.assertEqual((security['runAsUser'], security['runAsGroup'], security['fsGroup']), (1000, 1000, 1000))
        self.assertEqual(security['fsGroupChangePolicy'], 'OnRootMismatch')
        self.assertNotIn('fsGroup', backup['spec']['securityContext'])
        self.assertEqual(backup['spec']['securityContext']['runAsUser'], 0)
        self.assertNotEqual(builder['spec']['nodeName'], backup['spec']['nodeName'])
        for value in (builder, backup):
            self.assertFalse(value['spec']['automountServiceAccountToken'])
            self.assertEqual(value['spec']['volumes'], [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'claim'}}])
            self.assertEqual(value['spec']['containers'][0]['securityContext']['capabilities'], {'drop': ['ALL']})

    def test_exact_cache_lock_and_superblock_evidence_required(self):
        record = {'filesystem': 'nfs4', 'source': consumer.nfs.SERVER + ':/consumer-owned',
                  'options': 'rw,vers=4.1,hard,nosharecache,local_lock=none', 'device': '0:41'}
        consumer.require_consumer_mount([record], '4.1')
        for change in ({'device': ''}, {'options': 'rw,vers=4.1,hard,local_lock=none'},
                       {'options': 'rw,vers=4.1,hard,nosharecache,local_lock=all'},
                       {'source': '10.0.40.3:/production'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                consumer.require_consumer_mount([record | change], '4.1')


if __name__ == '__main__':
    unittest.main()
