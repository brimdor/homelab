"""Refuse wrong backends and ambiguous protocol/binding evidence."""

import copy
import unittest

import nfs_csi_qualification as nfs


class NfsContractTests(unittest.TestCase):
    def test_binding_refusals(self):
        claim = {'metadata': {'uid': 'claim-uid', 'name': 'owned-claim'}}
        pv = {'metadata': {'uid': 'pv-uid'}, 'status': {'phase': 'Bound'}, 'spec': {
            'claimRef': {'uid': 'claim-uid', 'name': 'owned-claim', 'namespace': nfs.NAMESPACE},
            'csi': {'driver': 'nfs.csi.k8s.io', 'volumeHandle': 'owned-volume',
                    'volumeAttributes': {'server': nfs.SERVER, 'share': '/'}}}}
        nfs.require_pv(pv, claim, '/')
        for path, value in [(('spec', 'csi', 'volumeAttributes', 'server'), '10.0.40.3'),
                            (('spec', 'claimRef', 'uid'), 'another-claim'),
                            (('spec', 'csi', 'volumeAttributes', 'share'), '/production'),
                            (('status', 'phase'), 'Released')]:
            changed = copy.deepcopy(pv)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                nfs.require_pv(changed, claim, '/')

    def test_real_kernel_protocol_required(self):
        record = {'filesystem': 'nfs4', 'source': nfs.SERVER + ':/pvc-owned', 'options': 'rw,vers=4.1,hard'}
        nfs.require_mount([record], '4.1')
        for records in ([], [record, record], [record | {'source': '10.0.40.3:/data'}],
                        [record | {'filesystem': 'tmpfs'}], [record | {'options': 'rw,vers=3,hard'}]):
            with self.subTest(records=records), self.assertRaises(RuntimeError):
                nfs.require_mount(records, '4.1')


if __name__ == '__main__':
    unittest.main()
