"""Restore protected real shards into six isolated nodes and prove full values."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import traceback
import zlib

import valkey_cluster_qualification as protocol
import valkey_data_fingerprint as values
import valkey_write_pause_qualification as write_pause


recovery, common = protocol.recovery, protocol.common
POINT = 'gitea-valkey-20261019-a'
MANIFEST = '568346a2078080432e6ffa64ff4e04a4c8f2e2378d0f45b568d703af57918639'


def copied_digest(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)) != (1001, 1001, 0o600)):
            raise RuntimeError('owned application copy has unexpected metadata')
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
        after = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after):
            raise RuntimeError('owned application copy changed while hashing')
    return {'bytes': before.st_size, 'sha256': digest.hexdigest()}


class Cluster(protocol.Cluster):
    def enable_aof(self):
        for node in range(6):
            assert self.cli(node, 'CONFIG', 'SET', 'appendonly', 'yes') == b'OK'
        self.aof = True
        self.wait_aof()

    def wait_aof(self):
        def ready():
            for node in range(6):
                item = recovery.info(self.cli(node, 'INFO', 'persistence'))
                if (item.get('aof_enabled') != '1' or item.get('aof_rewrite_in_progress') != '0' or
                        item.get('aof_rewrite_scheduled') != '0' or item.get('aof_last_bgrewrite_status') != 'ok' or
                        item.get('aof_last_write_status') != 'ok' or item.get('aof_pending_bio_fsync') != '0'):
                    return False
            return True
        protocol.poll(ready, 'owned AOF rewrite/write/fsync did not finish cleanly')

    def check_aof(self):
        for node in range(6):
            path = self.mount + '/node-' + str(node) + '/appendonlydir/appendonly.aof.manifest'
            result = common.docker('exec', self.identity, 'valkey-check-aof', path, check=False)
            if result.returncode or result.stderr:
                raise RuntimeError('owned complete AOF manifest check failed; private output withheld')

    def synthetic_aof_precedence(self, expected):
        self.enable_aof()
        self.verify_values(expected)
        for node in range(6):
            assert self.cli(node, 'SAVE') == b'OK'
        keys = {master: protocol.fixture_keys(master)[0] for master in protocol.SLOTS}
        for master, key in keys.items():
            assert self.cli(master, 'SET', key, 'synthetic-aof-tail-only-' + str(master)) == b'OK'
        changed = {master: self.fingerprint(master) for master in protocol.SLOTS}
        if any(changed[master] == expected[master] for master in protocol.SLOTS):
            raise RuntimeError('synthetic AOF tail mutation was not detected on every shard')
        self.verify_values(changed)
        self.wait_aof()
        for node in range(6):
            self.cli(node, 'SHUTDOWN', 'NOSAVE')
            protocol.poll(lambda n=node: common.docker('exec', self.identity, 'test', '!', '-e',
                          '/tmp/node-' + str(n) + '.pid', check=False).returncode == 0,
                          'owned AOF precedence node did not stop')
        self.check_aof()
        # The RDB predates the tail mutation; only AOF startup can recover it.
        for node in range(6):
            self.start(node)
        self.verify_values(changed)
        for master, key in keys.items():
            assert self.cli(master, 'EVAL', "return redis.call('SET',KEYS[1],string.char(0,255)..'0\\nλ')", 1, key) == b'OK'
        self.verify()
        self.verify_values(expected)
        for node in range(6):
            assert self.cli(node, 'CONFIG', 'SET', 'appendonly', 'no') == b'OK'
        self.aof = False

    def fingerprint(self, node, replica=False):
        state = common.inspect(self.identity)
        recovery.require_isolation(state, self.scratch, self.run_id, self.mount)
        program = base64.b64encode(self.observer).decode()
        command = ['nsenter', '--target', str(state['State']['Pid']), '--net', '--',
                   'python3', '-I', '-B', '-c',
                   'import base64;exec(compile(base64.b64decode(' + repr(program) + '),"<private-observer>","exec"))',
                   str(17000 + node)]
        if replica:
            command.append('replica')
        result = json.loads(common.command(command).stdout)
        if 'observer_failed' in result:
            raise RuntimeError('private observer failed: ' + json.dumps(result))
        if set(result) != {'keys', 'types', 'expiring_keys', 'sha256'}:
            raise RuntimeError('complete private fingerprint contract differs')
        return result

    def verify_values(self, expected, masters=(0, 3, 5)):
        protocol.poll(lambda: self.healthy(masters), 'restored cluster did not converge')
        offsets = {n: int(recovery.info(self.cli(n, 'INFO', 'replication'))['master_repl_offset']) for n in masters}
        def acknowledged():
            for n in set(range(6)) - set(masters):
                item = recovery.info(self.cli(n, 'INFO', 'replication'))
                owner = int(item.get('master_port', '0')) - 17000
                if owner not in offsets or int(item.get('slave_repl_offset', '-1')) < offsets[owner]:
                    return False
            return True
        protocol.poll(acknowledged, 'restored replicas did not acknowledge their complete source offset')
        for n in range(6):
            original = n if n in protocol.SLOTS else protocol.REPLICAS[n]
            if self.fingerprint(n, n not in masters) != expected[original]:
                raise RuntimeError('complete restored keys/types/values/expiry differ; private output withheld')


def require_point(cohort_run_id=None, checksum=None):
    if cohort_run_id is not None:
        import valkey_cohort_point as cohort
        point, original = cohort.verify(cohort_run_id, checksum)
        manifest = {'shards': {ordinal: header['file'] for ordinal, header in original['shards'].items()},
                    'cross_shard_atomic': original['cross_shard_atomic'],
                    'source_quiesced': original['source_quiesced']}
        return point, manifest
    if checksum is not None:
        raise RuntimeError('historical point checksum override is not allowed')
    point = recovery.point_path(POINT)
    recovery.protected.protected_file(point / 'verified.json')
    raw = (point / 'verified.json').read_bytes()
    manifest = json.loads(raw)
    recovery.require_manifest(manifest)
    if hashlib.sha256(raw).hexdigest() != MANIFEST:
        raise RuntimeError('original protected Valkey manifest differs')
    for shard, evidence in manifest['shards'].items():
        if recovery.protected.file_digest(point / ('shard-' + shard + '.rdb')) != {
                k: evidence[k] for k in ('bytes', 'sha256')}:
            raise RuntimeError('original protected RDB differs')
    return point, manifest


def run(run_id, observer, *, cohort_run_id=None, checksum=None, source_aof_checksum=None):
    def interrupted(_number, _frame):
        raise RuntimeError('owned Valkey cluster recovery interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    common.run_identifier(run_id)
    point, manifest = require_point(cohort_run_id, checksum)
    source_aof_point = None
    if source_aof_checksum is not None:
        import valkey_source_aof as source_aof
        source_aof_point, source_aof_manifest = source_aof.verify(cohort_run_id, source_aof_checksum)
        if source_aof_manifest['rdb_manifest_sha256'] != checksum:
            raise RuntimeError('actual source AOFs and recovery RDBs are not the same interval')
    if common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip():
        raise RuntimeError('another owned Valkey operation is active')
    before = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=run_id + '-real-cluster-', dir=common.ROOT))
    scratch.chmod(0o700)
    identity = None
    images, removed = set(), []
    result = {'accepted': False, 'run_id': run_id, 'manifest_sha256': checksum if cohort_run_id else MANIFEST,
              'cross_shard_atomic': manifest['cross_shard_atomic'],
              'source_quiesced': manifest['source_quiesced'], 'stages': []}
    stage = 'prepare'
    try:
        data = scratch / 'data'
        data.mkdir(mode=0o700)
        os.chown(data, 1001, 1001)
        for n in range(6):
            directory = data / ('node-' + str(n))
            directory.mkdir(mode=0o700)
            os.chown(directory, 1001, 1001)
        expected = {}
        for iteration, reference in enumerate((recovery.IMAGE, recovery.CANDIDATE, recovery.IMAGE)):
            stage = 'image-' + str(iteration)
            common.docker('pull', reference)
            image = json.loads(common.docker('image', 'inspect', reference).stdout)[0]
            images.add(image['Id'])
            mount = recovery.image_mount(image, reference)
            identity = common.docker('create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=1001:1001',
                '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=256', '--cpus=1', '--memory=1g',
                '--log-driver=none', '--label=' + recovery.LABEL + '=' + run_id,
                '--mount=type=bind,source=' + str(data) + ',target=' + mount,
                '--tmpfs=/tmp:rw,nosuid,nodev', '--entrypoint=/bin/sh', reference,
                '-c', 'exec sleep 2147483647').stdout.decode().strip()
            recovery.require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker('start', identity)
            state = common.inspect(identity)
            recovery.require_isolation(state, scratch, run_id, mount)
            ns = ['nsenter', '--target', str(state['State']['Pid']), '--net', '--']
            links = json.loads(common.command([*ns, 'ip', '-j', 'address']).stdout)
            routes = sum((json.loads(common.command([*ns, 'ip', family, '-j', 'route', 'show', 'table', 'all']).stdout)
                          for family in ('-4', '-6')), [])
            common.require_network(links, routes)
            if common.command([*ns, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
                raise RuntimeError('owned recovery can route to production')
            version = '8.1.10' if reference == recovery.CANDIDATE else '8.1.3'
            if ('v=' + version).encode() not in common.docker('exec', identity, 'valkey-server', '--version').stdout:
                raise RuntimeError('native recovery version differs')
            cluster = Cluster(identity, mount)
            cluster.scratch, cluster.run_id, cluster.observer = scratch, run_id, observer
            if source_aof_point is not None:
                # Match the observed production replication mode and timeout in the owned restore.
                cluster.native_args = ['--cluster-node-timeout', '15000', '--databases', '1', '--repl-diskless-sync', 'no']
            if iteration == 0:
                stage = 'empty-cluster-and-verifier'
                for n in range(6):
                    cluster.start(n)
                    assert cluster.cli(n, 'CLUSTER', 'SET-CONFIG-EPOCH', n + 1) == b'OK'
                for n, (lower, upper) in protocol.SLOTS.items():
                    assert cluster.cli(n, 'CLUSTER', 'ADDSLOTSRANGE', lower, upper) == b'OK'
                for n in range(1, 6):
                    assert cluster.cli(n, 'CLUSTER', 'MEET', '127.0.0.1', 17000) == b'OK'
                protocol.poll(lambda: all(recovery.info(cluster.cli(n, 'CLUSTER', 'INFO')).get('cluster_known_nodes') == '6'
                                         for n in range(6)), 'empty recovery membership did not converge')
                for replica, master in protocol.REPLICAS.items():
                    assert cluster.cli(replica, 'CLUSTER', 'REPLICATE', cluster.cli(master, 'CLUSTER', 'MYID').decode()) == b'OK'
                protocol.poll(cluster.healthy, 'empty recovery cluster is unhealthy')
                for master in protocol.SLOTS:
                    keys = protocol.fixture_keys(master)
                    assert cluster.cli(4, 'EVAL', protocol.WRITE, len(keys), *keys) == b'fixture-created'
                cluster.verify()
                full = {master: cluster.fingerprint(master) for master in protocol.SLOTS}
                cluster.verify_values(full)
                key = protocol.fixture_keys(0)[0]
                assert cluster.cli(4, 'SET', key, 'synthetic-corruption') == b'OK'
                if cluster.fingerprint(0) == full[0]:
                    raise RuntimeError('complete fingerprint accepted changed value')
                assert cluster.cli(4, 'EVAL', "return redis.call('SET',KEYS[1],string.char(0,255)..'0\\nλ')", 1, key) == b'OK'
                cluster.verify()
                cluster.verify_values(full)
                stage = 'synthetic-finite-write-exclusion'
                result['native_write_pause'] = write_pause.qualify(ns, observer, key + ':lease-expiry')
                cluster.verify_values(full)
                stage = 'synthetic-aof-precedence'
                cluster.synthetic_aof_precedence(full)
                result['native_synthetic_aof_precedence'] = True
                for master in protocol.SLOTS:
                    assert cluster.cli(master, 'FLUSHALL') == b'OK'
                zero = {master: {'keys': 0, 'types': {}, 'expiring_keys': 0,
                                'sha256': hashlib.sha256(b'').hexdigest()} for master in protocol.SLOTS}
                cluster.verify_values(zero)
                cluster.save_stop()
                # These are exclusively owned synthetic AOFs, never protected/source files.
                for node in range(6):
                    directory = data / ('node-' + str(node)) / 'appendonlydir'
                    if (directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid != 1001):
                        raise RuntimeError('owned synthetic AOF directory identity differs')
                    shutil.rmtree(directory)
                stage = 'independent-original-shard-values'
                for master in protocol.SLOTS:
                    target = data / ('node-' + str(master)) / 'dump.rdb'
                    shutil.copyfile(point / ('shard-' + str(master) + '.rdb'), target)
                    target.chmod(0o600)
                    os.chown(target, 1001, 1001)
                    count = recovery.checked_keys(common.docker('exec', identity, 'valkey-check-rdb',
                        mount + '/node-' + str(master) + '/dump.rdb', check=False))
                    common.docker('exec', identity, 'valkey-server', '--daemonize', 'yes', '--bind', '127.0.0.1',
                        '--port', str(17000 + master), '--cluster-enabled', 'no', '--dir', mount + '/node-' + str(master),
                        '--dbfilename', 'dump.rdb', '--appendonly', 'no', '--save', '',
                        '--pidfile', '/tmp/node-' + str(master) + '.pid', '--logfile', '/tmp/node-' + str(master) + '.log')
                    protocol.poll(lambda: cluster.cli(master, 'PING', check=False) == b'PONG', 'standalone original shard did not start')
                    expected[master] = cluster.fingerprint(master)
                    counts = recovery.load_counts(recovery.info(cluster.cli(master, 'INFO', 'persistence')),
                                                  recovery.info(cluster.cli(master, 'INFO', 'keyspace')), count)
                    result.setdefault('original_key_accounting', {})[master] = counts
                    # Native wall-clock expiry is expected for dated session/cache points.
                    if counts['expired_after_load'] or expected[master]['keys'] != counts['current_keys']:
                        raise RuntimeError('expiry during baseline prevents exact restored-value acceptance')
                    cluster.cli(master, 'SHUTDOWN', 'NOSAVE')
                    protocol.poll(lambda: common.docker('exec', identity, 'test', '!', '-e',
                                  '/tmp/node-' + str(master) + '.pid', check=False).returncode == 0,
                                  'original standalone shard did not stop')
                    if copied_digest(target) != {k: manifest['shards'][str(master)][k] for k in ('bytes', 'sha256')}:
                        raise RuntimeError('copied original shard changed before cluster recovery')
                result['native_complete_verifier_rejects_corruption'] = True
                result['original_shard_values'] = expected
                if source_aof_point is not None:
                    stage = 'independent-six-actual-source-aof-values'
                    for node in range(6):
                        directory = data / ('node-' + str(node)) / 'appendonlydir'
                        directory.mkdir(mode=0o700)
                        os.chown(directory, 1001, 1001)
                        for name, record in source_aof_manifest['nodes'][str(node)]['files'].items():
                            target = directory / name
                            shutil.copyfile(source_aof_point / ('node-' + str(node)) / name, target)
                            target.chmod(0o600)
                            os.chown(target, 1001, 1001)
                            if copied_digest(target) != {k: record[k] for k in ('bytes', 'sha256')}:
                                raise RuntimeError('actual source AOF owned copy differs')
                    cluster.check_aof()
                    for node in range(6):
                        common.docker('exec', identity, 'valkey-server', '--daemonize', 'yes', '--bind', '127.0.0.1',
                            '--port', str(17000 + node), '--cluster-enabled', 'no', '--dir', mount + '/node-' + str(node),
                            '--dbfilename', 'dump.rdb', '--appendonly', 'yes', '--appenddirname', 'appendonlydir',
                            '--aof-load-truncated', 'no', '--save', '', '--pidfile', '/tmp/node-' + str(node) + '.pid',
                            '--logfile', '/tmp/node-' + str(node) + '.log', *cluster.native_args)
                        protocol.poll(lambda n=node: cluster.cli(n, 'PING', check=False) == b'PONG',
                            'independent actual source AOF did not start')
                        original = node if node in protocol.SLOTS else protocol.REPLICAS[node]
                        if cluster.fingerprint(node) != expected[original]:
                            raise RuntimeError('actual source AOF complete values differ before replication can repair them')
                        persistence = recovery.info(cluster.cli(node, 'INFO', 'persistence'))
                        if persistence.get('aof_enabled') != '1' or persistence.get('loading') != '0':
                            raise RuntimeError('actual source AOF was not the native startup source')
                        cluster.cli(node, 'SHUTDOWN', 'NOSAVE')
                        protocol.poll(lambda n=node: common.docker('exec', identity, 'test', '!', '-e',
                            '/tmp/node-' + str(n) + '.pid', check=False).returncode == 0,
                            'independent actual source AOF did not stop')
                    result['actual_source_aofs_complete_before_replication'] = True
                    result['source_aof_manifest_sha256'] = source_aof_checksum
            stage = version + ':complete-cluster'
            cluster.aof = iteration > 0 or source_aof_point is not None
            for n in range(6):
                cluster.start(n)
            cluster.verify_values(expected)
            if iteration == 0:
                stage = 'legacy-real-data-aof-conversion'
                cluster.enable_aof()
                cluster.verify_values(expected)
            if iteration == 1:
                stage = 'maintained-manual-failover-failback'
                replica = next(n for n, owner in protocol.REPLICAS.items() if owner == 0)
                assert cluster.cli(replica, 'CLUSTER', 'FAILOVER') == b'OK'
                cluster.verify_values(expected, (replica, 3, 5))
                assert cluster.cli(0, 'CLUSTER', 'FAILOVER') == b'OK'
                cluster.verify_values(expected)
                stage = 'maintained-real-data-aof-rewrite'
                for n in range(6):
                    response = cluster.cli(n, 'BGREWRITEAOF')
                    if response not in (b'Background append only file rewriting started',
                                        b'Background append only file rewriting scheduled'):
                        raise RuntimeError('owned AOF rewrite acknowledgement differs')
                cluster.wait_aof()
                cluster.verify_values(expected)
                stage = 'maintained-persistence-restart'
                cluster.save_stop()
                cluster.check_aof()
                for n in range(6):
                    cluster.start(n)
                cluster.verify_values(expected)
            cluster.save_stop()
            cluster.check_aof()
            result['stages'].append({'version': version, 'complete_six_node_data': True,
                                    'failover_restart': iteration == 1, 'complete_aof_checked': True})
            recovery.require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker('rm', '-f', identity)
            identity = None
        require_point(cohort_run_id, checksum)
        if source_aof_point is not None:
            source_aof.verify(cohort_run_id, source_aof_checksum)
        result.update(accepted=True, keys=sum(v['keys'] for v in expected.values()), protected_original_unchanged=True,
                      network_none=True, production_unroutable=True, production_mutated=False,
                      original_replica_map=protocol.REPLICAS)
    except Exception as error:
        result.update(failed_stage=stage, failure_class=type(error).__name__,
                      failure_frames=[{'function': f.name, 'line': f.lineno}
                                      for f in traceback.extract_tb(error.__traceback__)])
        if isinstance(error, RuntimeError):
            # Helpers raise fixed messages; private protocol errors never embed replies.
            result['failure_reason'] = str(error)
    finally:
        if identity:
            recovery.require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker('rm', '-f', identity)
        # Stop native writers before walking files that they can rename.
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file())
        shutil.rmtree(scratch)
        for image in images - before:
            if not common.docker('ps', '-aq', '--filter=ancestor=' + image).stdout.strip():
                common.docker('image', 'rm', image)
                if common.docker('image', 'inspect', image, check=False).returncode == 0:
                    raise RuntimeError('owned recovery image remains')
                removed.append(image)
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'new_images_removed': len(removed),
            'allocated_bytes_removed': allocated,
            'owned_containers_absent': not common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip()}
    recovery.protected.write_json(common.ROOT / ('valkey-real-cluster-' + run_id + '-' + str(time.time_ns()) + '.json'), result)
    return result


def remote(run_id):
    code = 'import base64,sys,types;'
    for name in ('etcd_recovery', 'mariadb_recovery', 'valkey_recovery', 'valkey_cluster_qualification',
                 'valkey_data_fingerprint', 'valkey_write_pause_qualification', 'valkey_cluster_recovery'):
        source = base64.b64encode(Path(__file__).with_name(name + '.py').read_bytes()).decode()
        code += 'm=types.ModuleType(' + repr(name) + ');sys.modules[' + repr(name) + ']=m;'
        code += 'exec(base64.b64decode(' + repr(source) + '),m.__dict__);'
    observer = base64.b64encode(Path(__file__).with_name('valkey_data_fingerprint.py').read_bytes()).decode()
    code += 'result=m.run(sys.argv[1],base64.b64decode(' + repr(observer) + '));print(m.json.dumps(result));sys.exit(0 if result["accepted"] else 1)'
    encoded = base64.b64encode(zlib.compress(code.encode())).decode()
    program = 'import base64,zlib;exec(zlib.decompress(base64.b64decode(' + repr(encoded) + ')))'
    return [*common.SSH[:-1], '-o', 'ControlMaster=no', common.SSH[-1], shlex.join(['python3', '-B', '-c', program, run_id])]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', type=common.run_identifier, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    response = subprocess.run(remote(args.run_id), capture_output=True)
    if response.stderr:
        raise RuntimeError('remote recovery failed; private output withheld')
    result = json.loads(response.stdout)
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if response.returncode == 0 and result.get('accepted') else 1)
