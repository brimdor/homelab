#!/usr/bin/env python3
"""Exercise six-node Valkey protocol and rollback with isolated synthetic data."""
import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import zlib

import valkey_recovery as recovery

common = recovery.common
protected = recovery.protected
SLOTS = {0: (0, 5460), 3: (10923, 16383), 5: (5461, 10922)}
REPLICAS = {1: 0, 2: 3, 4: 5}
COUNT = 30
WRITE = r"""
for i=1,#KEYS,5 do
 local v=tostring((i-1)/5);local binary=string.char(0,255)..v..'\nλ'
 redis.call('SET',KEYS[i],binary)
 redis.call('HSET',KEYS[i+1],'a',binary,'b',v)
 redis.call('RPUSH',KEYS[i+2],binary,v,binary)
 redis.call('SADD',KEYS[i+3],binary,v,'member')
 redis.call('ZADD',KEYS[i+4],-2.5,binary,1.25,v,9,'member')
end
return 'fixture-created'
"""
VERIFY = r"""
local function same(a,b) assert(#a==#b);for n=1,#a do assert(a[n]==b[n]) end end
for i=1,#KEYS,5 do
 local v=tostring((i-1)/5);local binary=string.char(0,255)..v..'\nλ'
 assert(redis.call('GET',KEYS[i])==binary)
 assert(redis.call('HLEN',KEYS[i+1])==2)
 same(redis.call('HMGET',KEYS[i+1],'a','b'),{binary,v})
 same(redis.call('LRANGE',KEYS[i+2],0,-1),{binary,v,binary})
 assert(redis.call('SCARD',KEYS[i+3])==3)
 for _,m in ipairs({binary,v,'member'}) do assert(redis.call('SISMEMBER',KEYS[i+3],m)==1) end
 same(redis.call('ZRANGE',KEYS[i+4],0,-1),{binary,v,'member'})
 for _,x in ipairs({{binary,-2.5},{v,1.25},{'member',9}}) do assert(tonumber(redis.call('ZSCORE',KEYS[i+4],x[1]))==x[2]) end
 assert(redis.call('ZCARD',KEYS[i+4])==3)
 for n=i,i+4 do assert(redis.call('PTTL',KEYS[n])==-1) end
end
return 'fixture-verified'
"""


def fixture_keys(master):
    lower, upper = SLOTS[master]
    for n in range(16384):
        tag = 'maintenance103-fixture-' + str(n)
        if lower <= binascii.crc_hqx(tag.encode(), 0) % 16384 <= upper:
            return ['{' + tag + '}:' + kind + ':' + str(i)
                    for i in range(COUNT) for kind in ('string', 'hash', 'list', 'set', 'zset')]
    raise RuntimeError('no synthetic tag in the reviewed slot range')


def poll(check, message):
    for _ in range(180):
        if check():
            return
        time.sleep(1)
    raise RuntimeError(message)


class Cluster:
    def __init__(self, identity, mount):
        self.identity, self.mount = identity, mount

    def cli(self, node, *args, check=True):
        response = common.docker('exec', self.identity, 'valkey-cli', '--raw', '-c', '-h', '127.0.0.1',
                                 '-p', str(17000 + node), *map(str, args), check=False)
        if check and (response.returncode or response.stderr or response.stdout.startswith((b'ERR ', b'CLUSTERDOWN ', b'error:'))):
            raise RuntimeError('isolated Valkey command failed without private output')
        return response.stdout.strip()

    def start(self, node):
        directory = self.mount + '/node-' + str(node)
        common.docker('exec', self.identity, 'valkey-server', '--daemonize', 'yes', '--bind', '127.0.0.1',
                      '--port', str(17000 + node), '--cluster-enabled', 'yes', '--cluster-announce-ip', '127.0.0.1',
                      '--cluster-node-timeout', '1000', '--cluster-config-file', 'nodes.conf',
                      '--dir', directory, '--dbfilename', 'dump.rdb', '--appendonly', 'no', '--save', '',
                      '--pidfile', '/tmp/node-' + str(node) + '.pid', '--logfile', '/tmp/node-' + str(node) + '.log')
        poll(lambda: self.cli(node, 'PING', check=False) == b'PONG', 'isolated node did not start')

    def healthy(self, masters=(0, 3, 5)):
        topology = []
        for node in range(6):
            cluster = recovery.info(self.cli(node, 'CLUSTER', 'INFO', check=False))
            replication = recovery.info(self.cli(node, 'INFO', 'replication', check=False))
            if (cluster.get('cluster_state') != 'ok' or cluster.get('cluster_slots_assigned') != '16384' or
                    cluster.get('cluster_slots_ok') != '16384' or cluster.get('cluster_slots_pfail') != '0' or
                    cluster.get('cluster_slots_fail') != '0' or cluster.get('cluster_known_nodes') != '6'):
                return False
            if node in masters:
                if replication.get('role') != 'master' or replication.get('connected_slaves') != '1':
                    return False
                owner = node if node in SLOTS else REPLICAS[node]
                own = [line.split()[8:] for line in self.cli(node, 'CLUSTER', 'NODES').decode().splitlines()
                       if 'myself' in line.split()[2].split(',')]
                lower, upper = SLOTS[owner]
                if own != [[str(lower) + '-' + str(upper)]]:
                    return False
            elif (replication.get('role') != 'slave' or replication.get('master_link_status') != 'up' or
                  replication.get('master_sync_in_progress') != '0'):
                return False
            try:
                topology.append(recovery.topology(self.cli(node, 'CLUSTER', 'NODES')))
            except RuntimeError:
                return False
        return len(set(topology)) == 1

    def verify(self, masters=(0, 3, 5)):
        poll(lambda: self.healthy(masters), 'six-node cluster did not converge')
        for master in SLOTS:
            keys = fixture_keys(master)
            # Always enter through a non-owner; the native client must follow MOVED.
            assert self.cli(4, 'EVAL_RO', VERIFY, len(keys), *keys) == b'fixture-verified'
        for node in masters:
            assert self.cli(node, 'DBSIZE') == str(5 * COUNT).encode()
        offsets = {node: int(recovery.info(self.cli(node, 'INFO', 'replication'))['master_repl_offset'])
                   for node in masters}
        def acknowledged():
            for node in set(range(6)) - set(masters):
                value = recovery.info(self.cli(node, 'INFO', 'replication'))
                owner = int(value.get('master_port', '0')) - 17000
                if owner not in offsets or int(value.get('slave_repl_offset', '-1')) < offsets[owner]:
                    return False
            return True
        poll(acknowledged, 'replicas did not acknowledge the complete fixture offset')

    def manual(self, replica, masters):
        assert self.cli(replica, 'CLUSTER', 'FAILOVER') == b'OK'
        self.verify(masters)

    def save_stop(self):
        for node in range(6):
            assert self.cli(node, 'SAVE') == b'OK'
        for node in range(6):
            self.cli(node, 'SHUTDOWN', 'NOSAVE')
            poll(lambda n=node: common.docker('exec', self.identity, 'test', '!', '-e',
                 '/tmp/node-' + str(n) + '.pid', check=False).returncode == 0, 'owned node failed to stop')


def run(run_id):
    def interrupted(_number, _frame):
        raise InterruptedError('Valkey qualification interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(number, interrupted)
    common.require_host('pikachu'); common.private_root()
    if common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip():
        raise RuntimeError('an owned Valkey operation is active')
    before = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=run_id + '-cluster-', dir=common.ROOT)); scratch.chmod(0o700)
    identity = None; images = set(); stage = 'container'; result = {'accepted': False, 'run_id': run_id, 'synthetic_only': True}
    try:
        data = scratch / 'data'; data.mkdir(mode=0o700); os.chown(data, 1001, 1001)
        for n in range(6):
            path = data / ('node-' + str(n)); path.mkdir(mode=0o700); os.chown(path, 1001, 1001)
        for reference, version in ((recovery.CANDIDATE, '8.1.10'), (recovery.IMAGE, '8.1.3')):
            common.docker('pull', reference)
            image = json.loads(common.docker('image', 'inspect', reference).stdout)[0]; images.add(image['Id'])
            mount = recovery.image_mount(image, reference)
            identity = common.docker('create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=1001:1001',
                '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=256', '--cpus=1', '--memory=1g',
                '--label=' + recovery.LABEL + '=' + run_id,
                '--mount=type=bind,source=' + str(data) + ',target=' + mount,
                '--tmpfs=/tmp:rw,nosuid,nodev', '--entrypoint=/bin/sh', reference, '-c', 'exec sleep 2147483647').stdout.decode().strip()
            recovery.require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker('start', identity); state = common.inspect(identity)
            recovery.require_isolation(state, scratch, run_id, mount)
            ns = ['nsenter', '--target', str(state['State']['Pid']), '--net', '--']
            links = json.loads(common.command([*ns, 'ip', '-j', 'address']).stdout)
            routes = sum((json.loads(common.command([*ns, 'ip', f, '-j', 'route', 'show', 'table', 'all']).stdout)
                          for f in ('-4', '-6')), [])
            common.require_network(links, routes)
            if common.command([*ns, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
                raise RuntimeError('isolated cluster can route to production')
            if ('v=' + version).encode() not in common.docker('exec', identity, 'valkey-server', '--version').stdout:
                raise RuntimeError('isolated executable version changed')
            cluster = Cluster(identity, mount); stage = version + ':startup'
            for n in range(6): cluster.start(n)
            if reference == recovery.CANDIDATE:
                for n in range(6): assert cluster.cli(n, 'CLUSTER', 'SET-CONFIG-EPOCH', n + 1) == b'OK'
                for n, (lower, upper) in SLOTS.items():
                    assert cluster.cli(n, 'CLUSTER', 'ADDSLOTSRANGE', lower, upper) == b'OK'
                for n in range(1, 6): assert cluster.cli(n, 'CLUSTER', 'MEET', '127.0.0.1', 17000) == b'OK'
                poll(lambda: all(recovery.info(cluster.cli(n, 'CLUSTER', 'INFO')).get('cluster_known_nodes') == '6'
                                 for n in range(6)), 'isolated membership did not converge')
                for replica, master in REPLICAS.items():
                    node_id = cluster.cli(master, 'CLUSTER', 'MYID').decode()
                    assert cluster.cli(replica, 'CLUSTER', 'REPLICATE', node_id) == b'OK'
                poll(cluster.healthy, 'isolated initial replication failed')
                stage = 'synthetic_corpus'
                for master in SLOTS:
                    keys = fixture_keys(master)
                    assert cluster.cli(4, 'EVAL', WRITE, len(keys), *keys) == b'fixture-created'
                cluster.verify(); result['candidate_startup_full_corpus'] = True
                keys = fixture_keys(0)
                assert cluster.cli(4, 'SET', keys[0], 'synthetic-corruption') == b'OK'
                try:
                    cluster.cli(4, 'EVAL_RO', VERIFY, len(keys), *keys)
                except RuntimeError:
                    pass
                else:
                    raise RuntimeError('complete fixture verifier accepted corrupt data')
                assert cluster.cli(4, 'EVAL', "return redis.call('SET',KEYS[1],string.char(0,255)..'0\\nλ')", 1, keys[0]) == b'OK'
                cluster.verify(); result['complete_verifier_rejects_corruption'] = True
                stage = 'manual_failover'
                cluster.manual(1, (1, 3, 5)); cluster.manual(0, (0, 3, 5))
                result['quorum_manual_failover_failback'] = True
                stage = 'automatic_failover'
                cluster.cli(0, 'SHUTDOWN', 'NOSAVE')
                poll(lambda: recovery.info(cluster.cli(1, 'INFO', 'replication')).get('role') == 'master',
                     'isolated automatic failover did not promote the replica')
                cluster.start(0); cluster.verify((1, 3, 5)); cluster.manual(0, (0, 3, 5))
                result['automatic_failover_rejoin_failback'] = True
                stage = 'candidate_persistence_restart'
                cluster.save_stop()
                for n in range(6): cluster.start(n)
                cluster.verify(); result['candidate_persistence_restart'] = True
            else:
                cluster.verify(); result['legacy_rollback_full_corpus'] = True
            cluster.save_stop()
            recovery.require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker('rm', '-f', identity); identity = None
        result.update(accepted=True, nodes=6, primary_nodes=3, replicas=3, slots=16384,
                      keys=3 * 5 * COUNT, network_none=True, production_unroutable=True,
                      candidate=recovery.CANDIDATE, rollback=recovery.IMAGE)
    except Exception as error:
        result.update(failed_stage=stage, failure_class=type(error).__name__)
    finally:
        if identity:
            recovery.require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker('rm', '-f', identity)
        shutil.rmtree(scratch)
        removed = []
        for image in images - before:
            if not common.docker('ps', '-aq', '--filter=ancestor=' + image).stdout.strip():
                common.docker('image', 'rm', image)
                if common.docker('image', 'inspect', image, check=False).returncode == 0:
                    raise RuntimeError('owned qualification image remains')
                removed.append(image)
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'new_images_removed': len(removed),
            'owned_containers_absent': not common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip()}
    protected.write_json(common.ROOT / ('valkey-cluster-' + run_id + '-' + str(time.time_ns()) + '.json'), result)
    return result


def remote(run_id):
    code = 'import base64,sys,types;'
    for name in ('etcd_recovery', 'mariadb_recovery', 'valkey_recovery', 'valkey_cluster_qualification'):
        data = base64.b64encode(Path(__file__).with_name(name + '.py').read_bytes()).decode()
        code += 'm=types.ModuleType(' + repr(name) + ');sys.modules[' + repr(name) + ']=m;'
        code += 'exec(base64.b64decode(' + repr(data) + '),m.__dict__);'
    code += 'result=m.run(sys.argv[1]);print(m.json.dumps(result));sys.exit(0 if result["accepted"] else 1)'
    encoded = base64.b64encode(zlib.compress(code.encode())).decode()
    program = 'import base64,zlib;exec(zlib.decompress(base64.b64decode(' + repr(encoded) + ')))'
    return [*common.SSH[:-1], '-o', 'ControlMaster=no', common.SSH[-1], shlex.join(['python3', '-B', '-c', program, run_id])]


if __name__ == '__main__':
    def interrupted(_number, _frame):
        raise InterruptedError('Valkey qualification interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(number, interrupted)
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--run-id', type=common.run_identifier, required=True)
    args = parser.parse_args(); os.umask(0o077)
    response = subprocess.run(remote(args.run_id), capture_output=True)
    if response.stderr:
        raise RuntimeError('remote qualification failed; private output not emitted')
    result = json.loads(response.stdout); print(json.dumps(result), flush=True)
    raise SystemExit(0 if response.returncode == 0 and result.get('accepted') else 1)
