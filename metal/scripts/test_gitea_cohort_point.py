"""Joint acceptance requires complete independent proofs and protects secrets."""

import copy
import unittest

import gitea_cohort_point as joint


def descriptor():
    hashes = {name: str(number) * 64 for number, name in enumerate(('postgres', 'shared', 'valkey'), 1)}
    pg_copy = {'administrator_authentication': True, 'full_logical_data_equal': True,
               'unchanged_hba': True, 'clean_shutdown': True, 'full_dump_sha256': {'gitea': 'a' * 64}}
    cleanup = {'scratch_absent': True, 'containers_absent': True}
    return {'format': joint.FORMAT, 'cluster_uid': joint.common.CLUSTER_UID,
            'profile_revision': 'a' * 40, 'ordinary_revision': 'b' * 40,
            'points': {name: {'point': str(joint.common.ROOT / (name + '-synthetic')),
                             'manifest_sha256': checksum} for name, checksum in hashes.items()},
            'proofs': {'postgres': {'accepted': True, 'manifest_sha256': hashes['postgres'],
                                   'independent_copies': 2, 'copies': [pg_copy, copy.deepcopy(pg_copy)], 'cleanup': cleanup},
                       'shared': {'accepted': True, 'manifest_sha256': hashes['shared'], 'independent_restores': 2,
                                  'copies': [{'synthetic': 'refs'}, {'synthetic': 'refs'}],
                                  'copied_data_read_only': True, 'cleanup': cleanup},
                       'valkey': {'accepted': True, 'manifest_sha256': hashes['valkey'], 'source_quiesced': True,
                                  'cross_shard_atomic': False, 'original_replica_map': {'1': 5, '2': 3, '4': 0},
                                  'stages': [{'version': v, 'complete_six_node_data': True, 'complete_aof_checked': True}
                                             for v in ('8.1.3', '8.1.10', '8.1.3')], 'cleanup': cleanup}},
            'secrets': {name: {'uid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', 'data': {'synthetic': 'bm9uZQ=='}}
                        for name in ('gitea', 'gitea-init', 'gitea-inline-config', 'gitea-postgresql')},
            'source_holds_reverified': True, 'normal_postgres_verified': True}


class JointPointTests(unittest.TestCase):
    def test_incomplete_or_mismatched_proofs_never_earn_joint_acceptance(self):
        original = descriptor()
        self.assertEqual(joint.validate(original), original)
        changes = (lambda v: v.update(normal_postgres_verified=1),
                   lambda v: v.update(source_holds_reverified=False),
                   lambda v: v['points']['shared'].update(point='/foreign/point'),
                   lambda v: v['proofs']['postgres']['copies'][1].update(full_dump_sha256={'gitea': 'b' * 64}),
                   lambda v: v['proofs']['shared'].update(independent_restores=1),
                   lambda v: v['proofs']['valkey'].update(source_quiesced=False),
                   lambda v: v['proofs']['valkey']['stages'][1].update(complete_aof_checked=False),
                   lambda v: v['secrets']['gitea']['data'].update(synthetic='unencoded secret'),
                   lambda v: v['secrets']['gitea'].update(uid='foreign'),
                   lambda v: v['secrets'].pop('gitea-init'))
        for change in changes:
            value = copy.deepcopy(original)
            change(value)
            with self.assertRaises(RuntimeError) as error:
                joint.validate(value)
            self.assertNotIn('unencoded secret', str(error.exception))


if __name__ == '__main__':
    unittest.main()
