"""Observe exact GitOps Valkey partitions and use only normal manual failover.

The caller owns validated canonical commits and Argo refresh. This controller
never patches a workload, seeds production keys, forces failover or deletes data.
"""

import re

import gitea_cohort_recovery as cohort


cache = cohort.valkey
DEFAULT_MASTERS = tuple(cache.SLOTS)


class Rollout(cohort.Controller):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pg_runtime = None
        self.node_ids = None

    def preserved(self):
        for name, expected in self.secrets.items():
            value = self.get('secret', name)
            if (value['metadata']['uid'], value['data']) != expected:
                raise RuntimeError('Valkey rollout changed an existing Secret')
        if self.pg_runtime is not None:
            pod = self.get('pod', cohort.postgres.PG)
            if (pod['metadata']['uid'], pod['status'].get('containerStatuses')) != self.pg_runtime:
                raise RuntimeError('Valkey rollout changed the PostgreSQL runtime')

    def baseline(self):
        super().baseline()
        pod = self.get('pod', cohort.postgres.PG)
        self.pg_runtime = (pod['metadata']['uid'], pod['status']['containerStatuses'])
        owner = self.identity()
        if (owner['status']['sync']['status'] != 'Synced' or owner['status']['health']['status'] != 'Healthy' or
                not re.fullmatch('[a-f0-9]{40}', owner['status']['sync']['revision'])):
            raise RuntimeError('Valkey rollout baseline is not a healthy exact GitOps revision')
        self.revision = owner['status']['sync']['revision']
        self.wait_health()

    def cli(self, core, *args):
        raw = self.valkey_cli(core, *args)
        if raw.startswith((b'ERR ', b'NOAUTH ', b'NOPERM ', b'CLUSTERDOWN ', b'error:')):
            raise RuntimeError('Valkey rollout native command refused; no alternate access permitted')
        return raw

    @staticmethod
    def original(ordinal):
        return ordinal if ordinal in cache.SLOTS else cache.REPLICAS[ordinal]

    def health(self, masters=DEFAULT_MASTERS):
        """Bind every claim, node ID, slot, replica and acknowledged offset."""
        if (len(masters) != 3 or len(set(masters)) != 3 or not set(masters) <= set(cache.CLAIMS) or
                {self.original(n) for n in masters} != set(cache.SLOTS)):
            raise RuntimeError('Valkey rollout primary map differs')
        cores = self.valkey_core()
        ids = {n: self.cli(c, 'CLUSTER', 'MYID').decode() for n, c in cores.items()}
        if len(set(ids.values())) != 6 or any(not re.fullmatch('[a-f0-9]{40}', v) for v in ids.values()):
            raise RuntimeError('Valkey rollout node identities differ')
        if self.node_ids is not None and ids != self.node_ids:
            raise RuntimeError('Valkey rollout regenerated a retained node identity')
        digests, offsets = [], {}
        for n, core in cores.items():
            cluster = cache.recovery.info(self.cli(core, 'CLUSTER', 'INFO'))
            replication = cache.recovery.info(self.cli(core, 'INFO', 'replication'))
            persistence = cache.recovery.info(self.cli(core, 'INFO', 'persistence'))
            server = cache.recovery.info(self.cli(core, 'INFO', 'server'))
            if (any(cluster.get(k) != v for k, v in {
                    'cluster_state': 'ok', 'cluster_slots_assigned': '16384', 'cluster_slots_ok': '16384',
                    'cluster_slots_pfail': '0', 'cluster_slots_fail': '0', 'cluster_known_nodes': '6'}.items()) or
                    any(persistence.get(k) != v for k, v in {
                    'loading': '0', 'aof_enabled': '1', 'aof_last_write_status': 'ok',
                    'aof_last_bgrewrite_status': 'ok', 'aof_rewrite_in_progress': '0',
                    'aof_rewrite_scheduled': '0'}.items()) or
                    server.get('valkey_version') != cache.SOURCE_VERSIONS[core['image']]):
                raise RuntimeError('Valkey rollout cluster/version/persistence is not healthy')
            raw = self.cli(core, 'CLUSTER', 'NODES')
            rows = {r.split()[0]: r.split() for r in raw.decode().splitlines()}
            if set(rows) != set(ids.values()):
                raise RuntimeError('Valkey rollout membership changed')
            try:
                digests.append(cache.recovery.topology(raw))
            except RuntimeError as error:
                raise RuntimeError('Valkey rollout consensus differs; ' + str(error)) from None
            for ordinal, identity in ids.items():
                row = rows[identity]
                owner = next(m for m in masters if self.original(m) == self.original(ordinal))
                flags = set(row[2].split(',')) - {'myself'}
                if ordinal in masters:
                    if (flags != {'master'} or row[3] != '-' or
                            row[8:] != ['-'.join(map(str, cache.SLOTS[self.original(ordinal)]))]):
                        raise RuntimeError('Valkey rollout slot owner differs')
                elif flags != {'slave'} or row[3] != ids[owner] or row[8:]:
                    raise RuntimeError('Valkey rollout replica consensus differs')
            if n in masters:
                if replication.get('role') != 'master' or replication.get('connected_slaves') != '1':
                    raise RuntimeError('Valkey rollout primary lacks its connected replica')
                offsets[n] = int(replication['master_repl_offset'])
            else:
                if (replication.get('role') != 'slave' or replication.get('master_link_status') != 'up' or
                        replication.get('master_sync_in_progress') != '0' or replication.get('master_port') != '6379'):
                    raise RuntimeError('Valkey rollout replica is not synchronized')
        if len(set(digests)) != 1:
            raise RuntimeError('Valkey rollout six-node consensus differs')
        for n in set(cores) - set(masters):
            owner = next(m for m in masters if self.original(m) == self.original(n))
            replication = cache.recovery.info(self.cli(cores[n], 'INFO', 'replication'))
            if int(replication.get('slave_repl_offset', '-1')) < offsets[owner]:
                raise RuntimeError('Valkey rollout replica has not acknowledged the observed primary offset')
        self.node_ids = ids
        return cores

    def wait_health(self, masters=DEFAULT_MASTERS):
        def accepted():
            try:
                self.health(masters)
                return True
            except RuntimeError as error:
                # Retry convergence only; an access/identity/storage refusal is final.
                if any(word in str(error) for word in ('not healthy', 'not synchronized', 'offset',
                        'consensus differs', 'slot owner differs', 'connected replica')):
                    return False
                raise
        self.wait_for(accepted, 'Valkey rollout did not converge', seconds=300)
        return self.health(masters)

    def failover(self, replica, masters):
        if replica not in masters or replica not in cache.CLAIMS:
            raise RuntimeError('Valkey rollout unreviewed failover target')
        previous = tuple(next(n for n in cache.CLAIMS if self.original(n) == self.original(m) and n != m)
                         if m == replica else m for m in masters)
        cores = self.wait_health(previous)
        if self.cli(cores[replica], 'CLUSTER', 'FAILOVER') != b'OK':
            raise RuntimeError('Valkey rollout normal manual failover was not acknowledged')
        # OK only schedules failover. Require the new role and six-member consensus.
        return self.wait_health(masters)

    def partition(self, revision, partition, expected_images):
        if (not re.fullmatch('[a-f0-9]{40}', revision) or type(partition) is not int or
                not 0 <= partition <= 6 or set(expected_images) != set(cache.CLAIMS) or
                any(image not in cache.SOURCE_VERSIONS for image in expected_images.values())):
            raise RuntimeError('Valkey rollout exact candidate differs')
        self.revision = revision
        self.identity()
        owner = self.get('statefulset', 'gitea-valkey-cluster')
        if (owner['metadata']['uid'] != cache.recovery.OWNER or owner['spec']['replicas'] != 6 or
                owner['spec']['updateStrategy'] != {'type': 'RollingUpdate', 'rollingUpdate': {'partition': partition}}):
            raise RuntimeError('Valkey rollout owning partition differs')
        cores = self.valkey_core()
        if {n: c['image'] for n, c in cores.items()} != expected_images:
            raise RuntimeError('Valkey rollout observed images differ from the exact candidate')
        return cores
