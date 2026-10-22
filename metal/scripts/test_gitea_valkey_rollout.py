"""Reject lost replication, changed identities and premature failover acceptance."""

import unittest
from unittest.mock import patch

import gitea_valkey_rollout as rollout
from test_valkey_cohort_point import core


class RolloutTests(unittest.TestCase):
    def native(self, *, lag=False, changed=False):
        instance = rollout.Rollout(['kubectl'], None)
        cores = {n: core(n) for n in rollout.cache.CLAIMS}
        identities = {n: n * 40 for n in cores}
        if changed:
            identities['4'] = 'a' * 40
        rows = []
        for n in cores:
            primary = n in rollout.cache.SLOTS
            owner = '-' if primary else identities[rollout.cache.REPLICAS[n]]
            slots = ' ' + '-'.join(map(str, rollout.cache.SLOTS[n])) if primary else ''
            rows.append(f"{identities[n]} 192.0.2.{int(n)+1}:6379@16379 {'master' if primary else 'slave'} {owner} 0 0 1 connected{slots}")
        def reply(value, *args):
            n = value['ordinal']
            if args == ('CLUSTER', 'MYID'):
                return identities[n].encode()
            if args == ('CLUSTER', 'NODES'):
                return '\n'.join(rows).encode()
            if args == ('CLUSTER', 'INFO'):
                return b'cluster_state:ok\ncluster_slots_assigned:16384\ncluster_slots_ok:16384\ncluster_slots_pfail:0\ncluster_slots_fail:0\ncluster_known_nodes:6'
            if args == ('INFO', 'server'):
                return b'valkey_version:8.1.3'
            if args == ('INFO', 'persistence'):
                return b'loading:0\naof_enabled:1\naof_last_write_status:ok\naof_last_bgrewrite_status:ok\naof_rewrite_in_progress:0\naof_rewrite_scheduled:0'
            if args == ('INFO', 'replication'):
                if n in rollout.cache.SLOTS:
                    return b'role:master\nconnected_slaves:1\nmaster_repl_offset:100'
                return (b'role:slave\nmaster_link_status:up\nmaster_sync_in_progress:0\nmaster_port:6379\nslave_repl_offset:' + (b'99' if lag else b'100'))
            raise AssertionError('unexpected synthetic command')
        return instance, cores, reply

    def test_complete_native_consensus_and_acknowledged_offsets(self):
        instance, cores, reply = self.native()
        with patch.object(instance, 'valkey_core', return_value=cores), patch.object(instance, 'cli', side_effect=reply):
            self.assertEqual(instance.health(), cores)
        self.assertEqual(instance.node_ids, {n: n * 40 for n in cores})

    def test_lag_and_regenerated_node_identity_refuse_acceptance(self):
        for lag, changed in ((True, False), (False, True)):
            instance, cores, reply = self.native(lag=lag, changed=changed)
            instance.node_ids = {n: n * 40 for n in cores}
            with patch.object(instance, 'valkey_core', return_value=cores), patch.object(instance, 'cli', side_effect=reply):
                with self.assertRaisesRegex(RuntimeError, 'offset|node identity'):
                    instance.health()

    def test_normal_failover_acknowledgement_requires_observed_convergence(self):
        instance, cores, _ = self.native()
        with patch.object(instance, 'wait_health', side_effect=[cores, RuntimeError('not converged')]) as health, \
                patch.object(instance, 'cli', return_value=b'OK') as cli:
            with self.assertRaisesRegex(RuntimeError, 'not converged'):
                instance.failover('1', ('0', '3', '1'))
        self.assertEqual(health.call_args_list[0].args, (('0', '3', '5'),))
        self.assertEqual(cli.call_args.args, (cores['1'], 'CLUSTER', 'FAILOVER'))

    def test_transient_consensus_can_converge_but_foreign_membership_refuses(self):
        instance, cores, reply = self.native()
        with patch.object(instance, 'valkey_core', return_value=cores), patch.object(instance, 'cli', side_effect=reply), \
                patch.object(rollout.cache.recovery, 'topology', side_effect=RuntimeError('cluster transition')):
            with self.assertRaisesRegex(RuntimeError, 'consensus differs; cluster transition'):
                instance.health()
        def foreign(value, *args):
            raw = reply(value, *args)
            return raw.replace(b'4' * 40, b'a' * 40) if args == ('CLUSTER', 'NODES') else raw
        with patch.object(instance, 'valkey_core', return_value=cores), patch.object(instance, 'cli', side_effect=foreign):
            with self.assertRaisesRegex(RuntimeError, 'membership changed'):
                instance.health()

    def test_unreviewed_partition_and_failover_never_contact_cluster(self):
        instance, _, _ = self.native()
        with patch.object(instance, 'call') as call:
            with self.assertRaises(RuntimeError):
                instance.partition('a' * 40, True, {})
            with self.assertRaises(RuntimeError):
                instance.failover('foreign', ('0', '3', '5'))
        call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
