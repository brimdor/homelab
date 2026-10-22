"""Coordinate capture-only Gitea recovery; never dispatch offline role SQL.

Publish the exact reviewed capture profile before calling capture(). The owner
must restore ordinary desired state in finally, including failure/cancellation.
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
import traceback

import gitea_postgres_recovery_controller as postgres
import valkey_cohort_point as valkey
import gitea_cohort_point as joint


class Controller(postgres.Controller):
    def __init__(self, kubectl, bundle):
        super().__init__(kubectl, bundle, capture_only=True)

    def valkey_core(self):
        self.identity()
        self.preserved()
        pods = self.get('pods')['items']
        result = {}
        for ordinal, (claim_uid, pv_uid) in valkey.CLAIMS.items():
            name = 'gitea-valkey-cluster-' + ordinal
            pod = self.get('pod', name)
            statuses = pod['status'].get('containerStatuses', [])
            if (pod['metadata'].get('deletionTimestamp') or len(statuses) != 1 or
                    not statuses[0]['ready'] or statuses[0]['imageID'] != valkey.recovery.IMAGE or
                    not any(o.get('controller') and o['kind'] == 'StatefulSet' and o['uid'] == valkey.recovery.OWNER
                            for o in pod['metadata'].get('ownerReferences', []))):
                raise RuntimeError('native Valkey source workload changed')
            mounts = [v for v in pod['spec']['containers'][0]['volumeMounts']
                      if v['mountPath'] == '/bitnami/valkey/data' and not v.get('readOnly')]
            if len(mounts) != 1:
                raise RuntimeError('native Valkey source mount changed')
            volume = next(v for v in pod['spec']['volumes'] if v['name'] == mounts[0]['name'])
            claim_name = volume['persistentVolumeClaim']['claimName']
            claim = self.get('persistentvolumeclaim', claim_name)
            pv = self.get('persistentvolume', 'pvc-' + claim_uid, namespace=None)
            consumers = [p['metadata']['uid'] for p in pods if any(
                v.get('persistentVolumeClaim', {}).get('claimName') == claim_name for v in p['spec']['volumes'])]
            if (claim['metadata']['uid'] != claim_uid or claim['status']['phase'] != 'Bound' or
                    claim['spec']['volumeName'] != pv['metadata']['name'] or pv['metadata']['uid'] != pv_uid or
                    pv['spec']['claimRef']['uid'] != claim_uid or pv['spec']['claimRef']['namespace'] != 'gitea' or
                    pv['spec']['csi']['driver'] != 'rook-ceph.rbd.csi.ceph.com' or
                    claim['spec']['accessModes'] != ['ReadWriteOnce'] or
                    claim['spec']['storageClassName'] != 'standard-rwo' or consumers != [pod['metadata']['uid']]):
                raise RuntimeError('native Valkey source claim binding or exclusive consumer differs')
            node = self.get('node', pod['spec']['nodeName'], namespace=None)
            conditions = {c['type']: c['status'] for c in node['status']['conditions']}
            if (node['metadata']['name'] not in self.bundle.nodes or conditions.get('Ready') != 'True' or
                    any(conditions.get(c) != 'False' for c in ('MemoryPressure', 'DiskPressure', 'PIDPressure'))):
                raise RuntimeError('native Valkey source active node is not ready')
            cid = statuses[0]['containerID']
            if not cid.startswith('containerd://'):
                raise RuntimeError('native Valkey source container runtime differs')
            result[ordinal] = valkey.validate_core({'ordinal': ordinal, 'cluster_uid': postgres.common.CLUSTER_UID,
                'namespace': 'gitea', 'pod': name, 'pod_uid': pod['metadata']['uid'],
                'controller_uid': valkey.recovery.OWNER, 'node': node['metadata']['name'],
                'container_id': cid.removeprefix('containerd://'), 'image': statuses[0]['imageID'],
                'claim': claim_name, 'claim_uid': claim_uid, 'pv': pv['metadata']['name'],
                'pv_uid': pv_uid, 'revision': self.revision})
        return result

    def valkey_cli(self, core, *args):
        return self.execute({'pod': core['pod'], 'uid': core['pod_uid'], 'container': 'gitea-valkey-cluster'},
                            'valkey-cli', '--raw', *(str(arg) for arg in args)).stdout.rstrip(b'\r\n')

    def topology(self, cores, *, full=False):
        ids, rows = {}, {}
        for ordinal, core in cores.items():
            raw = self.valkey_cli(core, 'CLUSTER', 'NODES')
            rows[ordinal] = (valkey.recovery.topology(raw), raw)
            ids[ordinal] = self.valkey_cli(core, 'CLUSTER', 'MYID').decode()
            if full:
                cluster = valkey.recovery.info(self.valkey_cli(core, 'CLUSTER', 'INFO'))
                persistence = valkey.recovery.info(self.valkey_cli(core, 'INFO', 'persistence'))
                server = valkey.recovery.info(self.valkey_cli(core, 'INFO', 'server'))
                if (cluster.get('cluster_state') != 'ok' or cluster.get('cluster_slots_assigned') != '16384' or
                        cluster.get('cluster_slots_fail') != '0' or cluster.get('cluster_slots_pfail') != '0' or
                        persistence.get('loading') != '0' or persistence.get('rdb_bgsave_in_progress') != '0' or
                        persistence.get('rdb_last_bgsave_status') != 'ok' or persistence.get('aof_enabled') != '1' or
                        persistence.get('aof_rewrite_in_progress') != '0' or
                        persistence.get('aof_rewrite_scheduled') != '0' or
                        persistence.get('aof_last_bgrewrite_status') != 'ok' or
                        persistence.get('aof_last_write_status') != 'ok' or
                        server.get('valkey_version') != '8.1.3' or server.get('tcp_port') != '6379' or
                        self.valkey_cli(core, 'MODULE', 'LIST') or
                        self.valkey_cli(core, 'CONFIG', 'GET', 'dir') != b'dir\n/bitnami/valkey/data' or
                        self.valkey_cli(core, 'CONFIG', 'GET', 'dbfilename') != b'dbfilename\ndump.rdb'):
                    raise RuntimeError('native Valkey source persistence/configuration is not qualified')
        if len(set(ids.values())) != 6 or len({v[0] for v in rows.values()}) != 1:
            raise RuntimeError('native Valkey source topology lacks six-member consensus')
        parsed = {row.split()[0]: row.split() for row in rows['0'][1].decode().splitlines()}
        for ordinal, identity in ids.items():
            row = parsed[identity]
            flags = set(row[2].split(',')) - {'myself'}
            if ordinal in valkey.SLOTS:
                if flags != {'master'} or row[3] != '-' or row[8:] != ['-'.join(map(str, valkey.SLOTS[ordinal]))]:
                    raise RuntimeError('native Valkey primary slot ownership differs')
            elif flags != {'slave'} or row[3] != ids[valkey.REPLICAS[ordinal]] or row[8:]:
                raise RuntimeError('native Valkey replica ownership differs')
        return next(iter(rows.values()))[0]

    def native_bindings(self, cores):
        with ThreadPoolExecutor(max_workers=6) as pool:
            pairs = list(pool.map(lambda pair: (pair[0], self.bundle.run(pair[1]['node'], 'valkey_observe', core=pair[1])),
                                  cores.items()))
        return dict(pairs)

    def capture_valkey(self, held, run_id, persist):
        self.assert_held(held)
        cores = self.valkey_core()
        topology = self.topology(cores, full=True)
        bindings = self.native_bindings(cores)
        probes, paused = [], []
        started = time.monotonic()
        try:
            for ordinal, core in cores.items():
                # Include uncertain acknowledgements in cleanup; never retry the pause.
                paused.append(ordinal)
                if self.valkey_cli(core, 'CLIENT', 'PAUSE', valkey.LEASE_MS, 'WRITE') != b'OK':
                    raise RuntimeError('native Valkey finite WRITE exclusion was not acknowledged')
            for core in cores.values():
                child = subprocess.Popen(self.bundle.command(core['node']), stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                probes.append(child)
                child.stdin.write(self.bundle.request('valkey_probe', {'core': core}))
                child.stdin.close()
                child.stdin = None
            for child in probes:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    if not selector.select(10) or child.stdout.readline() != b'HOMELAB103:WRITE-BLOCKED\n':
                        raise RuntimeError('native Valkey blocked-write handshake missing')
            self.assert_held(held)
            shards = {}
            for ordinal in valkey.SLOTS:
                if self.valkey_cli(cores[ordinal], 'SAVE') != b'OK':
                    raise RuntimeError('native Valkey SAVE did not finish')
                shards[ordinal] = self.bundle.valkey_transfer(cores[ordinal]['node'], cores[ordinal], run_id)
            if self.native_bindings(cores) != bindings or self.topology(cores) != topology:
                raise RuntimeError('native Valkey source binding changed during finite capture')
            self.assert_held(held)
            elapsed = int((time.monotonic() - started) * 1000)
            if not 0 < elapsed < valkey.LEASE_MS or any(c.poll() is not None for c in probes):
                raise RuntimeError('native Valkey common WRITE exclusion interval was lost: elapsed_ms=' +
                                   str(elapsed) + ', lease_ms=' + str(valkey.LEASE_MS) +
                                   ', probe_exits=' + repr([c.poll() for c in probes]))
            manifest = {'format': valkey.FORMAT, 'cluster_uid': postgres.common.CLUSTER_UID,
                        'owner_uid': valkey.recovery.OWNER, 'image': valkey.recovery.IMAGE,
                        'sources': bindings, 'shards': shards, 'replicas': valkey.REPLICAS,
                        'slots': valkey.SLOTS, 'write_exclusion': {'lease_ms': valkey.LEASE_MS,
                            'elapsed_ms': elapsed, 'all_six_probes_blocked': True},
                        'source_quiesced': True, 'cross_shard_atomic': False, 'topology_sha256': topology}
            result = self.bundle.run('pikachu', 'valkey_finalize', run_id=run_id, manifest=manifest)
            # Recheck the common interval after the durable commit, not only before I/O.
            if time.monotonic() - started >= valkey.LEASE_MS / 1000 or any(c.poll() is not None for c in probes):
                raise RuntimeError('native Valkey lease ended before durable point acceptance; point retained')
            persist('valkey-write-excluded-point', **result, elapsed_ms=elapsed, topology_sha256=topology)
            return result
        finally:
            errors = []
            for ordinal in paused:
                try:
                    if self.valkey_cli(cores[ordinal], 'CLIENT', 'UNPAUSE') != b'OK':
                        errors.append(ordinal)
                except Exception:
                    errors.append(ordinal)
            for child in probes:
                try:
                    output, stderr = child.communicate(timeout=10)
                    if child.returncode or output != b'HOMELAB103:WRITE-RELEASED\n' or stderr:
                        errors.append('probe')
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate()
                    errors.append('probe-timeout')
                finally:
                    for stream in (child.stdout, child.stderr):
                        stream.close()
            if errors:
                raise RuntimeError('native Valkey lease release/owned-probe cleanup unverified; finite lease remains bounded')

    def capture(self, run_id, ordinary_revision, persist):
        postgres.common.run_identifier(run_id)
        if self.credentials is None or not self.old_uids or not self.revision:
            raise RuntimeError('prefetched capture-only baseline/candidate missing')
        with self.held() as held:
            pg_core, shared_core = self.source_core(held), self.shared_core(held)
            pg = self.bundle.run(pg_core['node'], 'capture', core=pg_core,
                                 namespace_pid=held['postgresql']['namespace_pid'], run_id=run_id)
            persist('postgres-source-point', **pg)
            files = self.bundle.run(shared_core['node'], 'shared_capture', core=shared_core,
                                    namespace_pid=held['application']['namespace_pid'], run_id=run_id)
            persist('shared-source-point', **files)
            self.assert_held(held)
            received_pg = self.bundle.transfer(pg_core['node'], pg['point'], pg['manifest_sha256'], pg['source'], run_id)
            received_files = self.bundle.transfer(shared_core['node'], files['point'], files['manifest_sha256'],
                                                  files['source'], run_id, shared=True)
            persist('separate-host-points', postgres=received_pg, shared=received_files)
            cache = self.capture_valkey(held, run_id, persist)
            pg_restore = self.bundle.run('pikachu', 'restore', **postgres.transport.restore_args(
                received_pg['point'], received_pg['manifest_sha256'], self.credentials, self.hba, run_id))
            summary, catalog = pg_restore['summary'], pg_restore['catalog']
            if not summary['accepted'] or summary['independent_copies'] != 2:
                raise RuntimeError('cohort PostgreSQL independent restores did not pass')
            persist('postgres-independent-restores', **summary)
            git_restore = self.bundle.run('pikachu', 'shared_restore', run_id=run_id,
                point=received_files['point'], checksum=received_files['manifest_sha256'])
            if not git_restore['accepted']:
                raise RuntimeError('cohort independent native Git recovery did not pass')
            persist('shared-independent-restores', **git_restore)
            cache_restore = self.bundle.run('pikachu', 'valkey_restore', run_id=run_id,
                                            cohort_run_id=run_id, checksum=cache['manifest_sha256'])
            if not cache_restore['accepted']:
                raise RuntimeError('cohort six-node native Valkey recovery did not pass')
            persist('valkey-independent-restore', **cache_restore)
            self.assert_held(held)
            self.bundle.run(pg_core['node'], 'observe', core=pg_core,
                            namespace_pid=held['postgresql']['namespace_pid'])
            self.bundle.run(shared_core['node'], 'shared_observe', core=shared_core,
                            namespace_pid=held['application']['namespace_pid'])
            # EOF releases ordinary startup. Capture-only leases have no SQL path.
            item = held['postgresql']
            output, errors = item['child'].communicate()
            if item['child'].returncode or output or errors:
                raise RuntimeError('capture-only PostgreSQL release differs')
            self.call('wait', '--for=condition=Ready', 'pod/' + postgres.PG, '-n', 'gitea', '--timeout=300s')
            after = json.loads(self.client(item, 'postgres', 'psql', '-XAtq', '-d', 'postgres', '-c', postgres.recovery.CATALOG))
            if after != catalog:
                raise RuntimeError('cohort ordinary PostgreSQL startup changed complete catalog')
            expected = summary['copies'][0]['full_dump_sha256']
            for role in ('gitea', 'postgres'):
                for database in ('gitea', 'postgres', 'template1'):
                    raw = self.client(item, role, 'pg_dump', '--no-comments', '--dbname=' + database)
                    if hashlib.sha256(postgres.recovery.logical.normalized_dump(raw)).hexdigest() != expected[database]:
                        raise RuntimeError('cohort ordinary PostgreSQL startup changed complete logical data')
            if self.execute(item, '/bin/cat', '/opt/bitnami/postgresql/conf/pg_hba.conf').stdout != self.hba:
                raise RuntimeError('cohort ordinary PostgreSQL startup changed HBA')
            self.assert_held({'application': held['application']})
            self.preserved()
            descriptor = {'format': joint.FORMAT, 'cluster_uid': postgres.common.CLUSTER_UID,
                'profile_revision': self.revision, 'ordinary_revision': ordinary_revision,
                'points': {'postgres': received_pg, 'shared': received_files, 'valkey': cache},
                'proofs': {'postgres': summary, 'shared': git_restore, 'valkey': cache_restore},
                'secrets': {name: {'uid': uid, 'data': data} for name, (uid, data) in self.secrets.items()},
                'source_holds_reverified': True, 'normal_postgres_verified': True}
            protected = self.bundle.run('pikachu', 'cohort_store', run_id=run_id, value=descriptor)
            persist('cohort-recovery-qualified', **protected, postgres=received_pg, shared=received_files, valkey=cache,
                    unchanged_catalog_hba_and_complete_data=True, both_existing_roles_authenticate=True,
                    offline_sql_dispatched=False, role_intent_replayed=False)
            output, errors = held['application']['child'].communicate()
            if held['application']['child'].returncode or output or errors:
                raise RuntimeError('cohort Gitea application release differs')
            self.call('rollout', 'status', 'deployment/gitea', '-n', 'gitea', '--timeout=300s')
            self.preserved()
            persist('application-restarted', production_images_and_claims_unchanged=True,
                    existing_secrets_and_valkey_preserved=True)


def main():
    request = json.load(sys.stdin)
    root = Path(__file__).resolve().parents[2]
    if (set(request) != {'code_revision', 'profile_revision', 'ordinary_revision', 'nodes', 'kubectl', 'run_id'} or
            not re.fullmatch('[a-f0-9]{40}', request['profile_revision']) or
            not re.fullmatch('[a-f0-9]{40}', request['ordinary_revision']) or
            subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip() != request['profile_revision'] or
            subprocess.check_output(['git', '-C', str(root), 'remote', 'get-url', 'origin']).decode().strip() !=
            'git@git.eaglepass.io:ops/homelab.git'):
        raise RuntimeError('prefetched cohort checkout/candidate differs')
    for name in ('gitea_cohort_recovery', 'gitea_postgres_recovery_controller'):
        postgres.transport.Bundle.exact(root, request['code_revision'], 'metal/scripts/' + name + '.py')
    bundle = postgres.transport.Bundle(root, request['code_revision'], request['nodes'])
    instance = Controller(request['kubectl'], bundle)
    def interrupted(_number, _frame):
        raise RuntimeError('owned capture coordinator interrupted; release holds and observe ordinary startup')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    def persist(stage, **summary):
        print(json.dumps({'stage': stage, **summary}), flush=True)
    instance.baseline()
    instance.revision = request['profile_revision']
    persist('prefetched-ready', code_revision=request['code_revision'], profile_revision=instance.revision)
    instance.capture(request['run_id'], request['ordinary_revision'], persist)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'stage': 'failed', 'error_type': type(error).__name__,
                          'error': str(error) if isinstance(error, RuntimeError) else 'cohort failed; raw details withheld',
                          'frames': [{'function': f.name, 'line': f.lineno}
                                     for f in traceback.extract_tb(error.__traceback__)]}), flush=True)
        sys.exit(70)
