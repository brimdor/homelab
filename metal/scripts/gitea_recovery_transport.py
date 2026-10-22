"""Prefetch exact repository code and stream protected points over existing SSH.

Native responses can contain role verifiers. Keep responses in RAM; publish only
explicit sanitized summaries. No backup or credential is written on the caller.
"""

import base64
import ipaddress
import json
from pathlib import Path
import re
import shlex
import subprocess

import etcd_recovery as common


MODULES = ['etcd_recovery', 'prometheus_recovery', 'grafana_recovery', 'sporecast_recovery',
           'arr_database_recovery', 'pointguide_files_recovery', 'mariadb_recovery',
           'point_postgres_recovery', 'gitea_postgres_control', 'gitea_postgres_account_recovery',
           'maintenance_actor_hold', 'gitea_postgres_lifecycle', 'gitea_postgres_startup_guard',
           'gitea_postgres_cold_point', 'gitea_postgres_fresh_restore', 'gitea_postgres_guarded_source',
           'gitea_git_recovery', 'gitea_init_guard', 'gitea_shared_guarded_source',
           'gitea_capture_only_qualification', 'valkey_recovery', 'valkey_cohort_point',
           'valkey_cluster_qualification', 'valkey_data_fingerprint',
           'valkey_write_pause_qualification', 'valkey_cluster_recovery', 'gitea_cohort_point',
           'valkey_long_lease_qualification', 'valkey_source_aof', 'gitea_postgres_maintained_qualification']
BOOT = '''import base64,json,sys,types
from pathlib import Path
stream=sys.stdin.buffer
line=stream.readline(2097153)
if not line.endswith(b'\\n') or len(line)>2097152:raise RuntimeError('native code frame differs')
request=json.loads(line)
for name,source in request['sources'].items():
 module=types.ModuleType(name);module.__file__='/repository/metal/scripts/'+name+'.py';sys.modules[name]=module
 if name=='pointguide_files_recovery':module.PROFILE_DATA=request['profiles']
 exec(compile(source,module.__file__,'exec'),module.__dict__)
common=sys.modules['etcd_recovery'];cold=sys.modules['gitea_postgres_cold_point']
guard=sys.modules['gitea_postgres_guarded_source'];restore=sys.modules['gitea_postgres_fresh_restore']
task,args=request['task'],request['args']
try:
 if task=='capture_qualify':
  result=sys.modules['gitea_capture_only_qualification'].qualify(args['run_id'])
 elif task=='observe':
  binding,control=guard.observe(args['core'],args['namespace_pid']);result={'binding':binding,'control':control}
 elif task=='capture':
  result=guard.capture(args['core'],args['namespace_pid'],args['run_id'])
 elif task=='send':
  guard.send(Path(args['point']),args['checksum'],args['expected'],sys.stdout.buffer);sys.exit(0)
 elif task=='receive':
  common.require_host('pikachu');common.private_root();common.run_identifier(args['run_id'])
  point=common.ROOT/('gitea-postgres-guarded-'+args['run_id'])
  manifest,checksum=cold.receive(stream,point)
  if manifest['format'] not in (cold.GUARDED_FORMAT,cold.MAINTAINED_FORMAT) or manifest['source']!=args['expected']:
   raise RuntimeError('received guarded point provenance differs; protected partial retained')
  result={'point':str(point),'manifest_sha256':checksum,'source':manifest['source']}
 elif task=='restore':
  summary,catalog=restore.restore(Path(args['point']),args['checksum'],args['credentials'],
                                  base64.b64decode(args['hba'],validate=True),args['run_id'])
  result={'summary':summary,'catalog':catalog}
 elif task=='postgres_image_qualify':
  result=sys.modules['gitea_postgres_maintained_qualification'].run(
   Path(args['point']),args['checksum'],args['credentials'],base64.b64decode(args['hba'],validate=True),
   args['run_id'],args['payload'])
 elif task=='intent':
  result=guard.intent(Path(args['point']),args['checksum'],args['expected'],args['catalog_sha256'],
                      args['secret_uid'],args['application_uid'])
 elif task=='cohort_store':result=sys.modules['gitea_cohort_point'].store(args['run_id'],args['value'])
 elif task.startswith('valkey_'):
  valkey=sys.modules['valkey_cohort_point']
  if task=='valkey_observe':result=valkey.observe(args['core'])
  elif task=='valkey_probe':valkey.probe(args['core'],request['sources']['valkey_data_fingerprint'].encode())
  elif task=='valkey_send':
   valkey.send(args['core'],sys.stdout.buffer);sys.exit(0)
  elif task=='valkey_receive':result=valkey.receive(args['run_id'],args['expected'],stream)
  elif task=='valkey_finalize':result=valkey.finalize(args['run_id'],args['manifest'])
  elif task=='valkey_aof_send':
   sys.modules['valkey_source_aof'].send(args['core'],sys.stdout.buffer);sys.exit(0)
  elif task=='valkey_aof_receive':result=sys.modules['valkey_source_aof'].receive(args['run_id'],args['expected'],stream)
  elif task=='valkey_aof_finalize':
   result=sys.modules['valkey_source_aof'].finalize(args['run_id'],args['rdb_manifest_sha256'],args['nodes'])
  elif task=='valkey_lease_qualify':
   result=sys.modules['valkey_long_lease_qualification'].run(args['run_id'],request['sources']['valkey_data_fingerprint'].encode())
  elif task=='valkey_restore':
   result=sys.modules['valkey_cluster_recovery'].run(args['run_id'],request['sources']['valkey_data_fingerprint'].encode(),
      cohort_run_id=args['cohort_run_id'],checksum=args['checksum'],source_aof_checksum=args.get('source_aof_checksum'))
  else:raise RuntimeError('unreviewed Valkey operation')
 elif task.startswith('shared_'):
  shared=sys.modules['gitea_shared_guarded_source']
  if task=='shared_observe':result={'binding':shared.observe(args['core'],args['namespace_pid'])}
  elif task=='shared_capture':result=shared.capture(args['core'],args['namespace_pid'],args['run_id'])
  elif task=='shared_send':
   shared.send(Path(args['point']),args['checksum'],args['expected'],sys.stdout.buffer);sys.exit(0)
  elif task=='shared_receive':
   common.require_host('pikachu');common.private_root();common.run_identifier(args['run_id'])
   point=common.ROOT/('gitea-shared-guarded-'+args['run_id'])
   manifest,checksum=cold.receive(stream,point,validator=shared.validate)
   if manifest['source']!=args['expected']:
    raise RuntimeError('received shared-file provenance differs; protected partial retained')
   result={'point':str(point),'manifest_sha256':checksum,'source':manifest['source']}
  elif task=='shared_restore':
   result=sys.modules['gitea_git_recovery'].restore(args['run_id'],guarded_point=args['point'],checksum=args['checksum'])
  else:raise RuntimeError('unreviewed shared-file operation')
 else:raise RuntimeError('unreviewed native recovery operation')
 print(json.dumps(result),flush=True)
except Exception as error:
 print(json.dumps({'accepted':False,'error_type':type(error).__name__,
  'error':str(error) if isinstance(error,RuntimeError) else 'native operation failed; details withheld'}),file=sys.stderr,flush=True)
 sys.exit(70)
'''


class Bundle:
    def __init__(self, root, revision, nodes):
        if not re.fullmatch('[a-f0-9]{40}', revision):
            raise RuntimeError('prefetch revision differs')
        self.nodes = dict(nodes)
        if not self.nodes or 'pikachu' not in self.nodes:
            raise RuntimeError('prefetch active inventory missing')
        for name, address in self.nodes.items():
            if (not re.fullmatch('[a-z][a-z0-9-]*', name) or
                    ipaddress.ip_address(address) not in ipaddress.ip_network('10.0.20.0/24')):
                raise RuntimeError('prefetch inventory target differs')
        self.revision = revision
        self.sources = {}
        for name in MODULES:
            relative = 'metal/scripts/' + name + '.py'
            raw = self.exact(root, revision, relative)
            self.sources[name] = raw.decode()
        self.profiles = json.loads(self.exact(root, revision, 'metal/maintenance/gitea-postgres-files-103.json'))

    @staticmethod
    def exact(root, revision, relative):
        raw = (root / relative).read_bytes()
        result = subprocess.run(['git', '-C', str(root), 'show', revision + ':' + relative], capture_output=True)
        if result.returncode or result.stdout != raw:
            raise RuntimeError('prefetched source is not the exact canonical candidate')
        return raw

    def request(self, task, args):
        if task not in {'observe', 'capture', 'send', 'receive', 'restore', 'intent', 'capture_qualify',
                        'shared_observe', 'shared_capture', 'shared_send', 'shared_receive', 'shared_restore',
                        'valkey_observe', 'valkey_probe', 'valkey_send', 'valkey_receive', 'valkey_finalize', 'valkey_restore',
                        'cohort_store', 'valkey_lease_qualify', 'valkey_aof_send', 'valkey_aof_receive', 'valkey_aof_finalize',
                        'postgres_image_qualify'}:
            raise RuntimeError('unreviewed native recovery task')
        # Preserve dependency order: the remote host has no repository imports.
        return json.dumps({'sources': self.sources, 'profiles': self.profiles,
                           'task': task, 'args': args}, separators=(',', ':')).encode() + b'\n'

    def command(self, node):
        if node not in self.nodes:
            raise RuntimeError('native recovery target is not active inventory')
        return [*common.SSH[:-1], '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                'root@' + self.nodes[node], 'python3', '-B', '-c', shlex.quote(BOOT)]

    @staticmethod
    def response(result):
        if result.returncode:
            try:
                value = json.loads(result.stderr)
                message = value['error'] if value.get('accepted') is False else 'native transport failed'
            except (ValueError, KeyError, TypeError):
                message = 'native transport failed; raw output withheld'
            raise RuntimeError(message)
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise RuntimeError('native response framing differs; raw output withheld') from None

    def run(self, node, task, **args):
        return self.response(subprocess.run(self.command(node), input=self.request(task, args), capture_output=True))

    def transfer(self, node, point, checksum, expected, run_id, *, shared=False):
        receiver_id = common.run_identifier('received-' + run_id)
        prefix = 'shared_' if shared else ''
        result = self.stream(node, prefix + 'send', {'point': point, 'checksum': checksum, 'expected': expected},
                             prefix + 'receive', {'expected': expected, 'run_id': receiver_id})
        if result['manifest_sha256'] != checksum or result['source'] != expected:
            raise RuntimeError('guarded point receiver readback differs')
        return result

    def valkey_transfer(self, node, core, run_id):
        return self.stream(node, 'valkey_send', {'core': core}, 'valkey_receive', {'expected': core, 'run_id': run_id})

    def stream(self, node, source_task, source_args, sink_task, sink_args):
        """Pipe native bytes directly into protected storage; retain no caller copy."""
        source = sink = None
        try:
            source = subprocess.Popen(self.command(node), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            source.stdin.write(self.request(source_task, source_args))
            source.stdin.close()
            source.stdin = None
            sink = subprocess.Popen(self.command('pikachu'), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            sink.stdin.write(self.request(sink_task, sink_args))
            sink.stdin.flush()
            for chunk in iter(lambda: source.stdout.read(1048576), b''):
                sink.stdin.write(chunk)
            sink.stdin.close()
            sink.stdin = None
            output, errors = sink.communicate()
            source_output, _source_errors = source.communicate()
            if source.returncode or source_output:
                raise RuntimeError('guarded point sender failed; raw output withheld')
            return self.response(subprocess.CompletedProcess([], sink.returncode, output, errors))
        finally:
            for child in (source, sink):
                if child is None:
                    continue
                if child.poll() is None:
                    if child.stdin and not child.stdin.closed:
                        child.stdin.close()
                        child.stdin = None
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream and not stream.closed:
                        stream.close()

def restore_args(point, checksum, credentials, hba, run_id):
    return {'point': point, 'checksum': checksum, 'credentials': credentials,
            'hba': base64.b64encode(hba).decode(), 'run_id': run_id}
