"""Compose the published native guards for Issue 103's one-server cold copy.

The ordinary hop stays pending until SOURCE has returned and the isolated native
checker has passed. Datastore bytes travel only between the two trusted hosts.
"""

import hashlib
import base64
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid
import zlib

import maintenance_actor_hold as actors
import maintenance_control_plane as quorum
import maintenance_etcd_cycle as cycles
import maintenance_etcd_legacy as legacy
import maintenance_etcd_ownership as ownership
import maintenance_etcd_transfer as transfer
import maintenance_hop_journal as hops
from maintenance_etcd_native_api import Reader, ENDPOINTS
from maintenance_node_drain import private_json


MODULES = ('maintenance_control_plane', 'maintenance_etcd_stopped', 'maintenance_etcd_cycle',
           'maintenance_etcd_legacy', 'maintenance_etcd_transfer', 'maintenance_etcd_ownership',
           'maintenance_etcd_native_api', 'maintenance_etcd_production')
SOURCE, TARGET = 'v1.33.10+k3s1', 'v1.33.13+k3s2'
DATA = Path('/var/lib/rancher/k3s/server/db/etcd')
ROOT = Path('/var/lib/homelab-recovery/maintenance-103')


def source_baseline(hold, owner, before):
    """Keep the original baseline; accept only the journaled SOURCE cycle's new PID."""
    receipt = private_json(hold.state / ('legacy-accepted-' + owner['owner'] + '.json'))
    actors.require(receipt['owner'] == owner and receipt['original_before'] == before and
                   receipt['accepted'] is True, 'accepted legacy owner or original runtime differs')
    path = hold.state / 'etcd-cycles' / owner['owner']
    hops.private_directory(path)
    actors.require(set(p.name for p in path.iterdir()) == set(receipt['cycle_files']) and
                   all(hashlib.sha256((path / name).read_bytes()).hexdigest() == digest
                       for name, digest in receipt['cycle_files'].items()), 'accepted native cycle changed')
    returned = private_json(path / 'source-returned.json')
    actors.require(returned == receipt['SOURCE_returned'], 'accepted returned SOURCE changed')
    runtime = returned['runtime']
    actors.require(set(runtime) == set(before) and runtime['pid'] > 1 and runtime['pid'] != before['pid'] and
                   all(runtime[k] == value for k, value in before.items() if k != 'pid'),
                   'accepted SOURCE runtime differs beyond its PID')
    accepted = private_json(hold.state / 'transactions' / owner['owner'] / '00000006.json')
    actors.require(accepted['kind'] == 'accepted' and accepted['step'] == 'check_legacy_etcd' and
                   accepted['receipt_sha256'] == hops.digest(hops.canonical(receipt)),
                   'legacy acceptance is not in the original hop')
    return runtime


class Context:
    def __init__(self, owner, identities, identity, native, initialize=False):
        from maintenance_coordination import Ownership
        from maintenance_k3s_production import runtime
        actors.require(owner.get('component') == 'k3s' and owner['node'] in ENDPOINTS and
                       (owner['source'], owner['target']) == (SOURCE, TARGET), 'unreviewed legacy cycle')
        self.owner, self.native = owner, native
        endpoint = next(value for name, value in ENDPOINTS.items() if name != owner['node'])
        self.api = Reader(owner['node'], endpoint, native)
        try:
            self.controller = Ownership(self.api, '4abc4fee-c3be-440e-8945-34bb3fb15ce1', identities)
            self.hold = actors.Hold(actors.Systemd(), identity, lambda token: self.owned(token))
            self.baseline_path = self.hold.state / ('legacy-ownership-' + owner['owner'] + '.json')
            self.hop_path = self.hold.state / ('legacy-hop-' + owner['owner'] + '.json')
            if initialize:
                actors.require(self.controller.resume(owner['owner']) == owner, 'initial legacy owner differs')
                baseline = ownership.capture(self.controller, owner['owner'])
                self.baseline = baseline
                header = hops.Journal(self.controller, self.hold, owner['owner']).inspect()
                for path, value in ((self.baseline_path, baseline), (self.hop_path, header)):
                    if not path.exists(): actors.exclusive_file(path, hops.canonical(value), 0o600)
                    actors.require(private_json(path) == value, 'original legacy capture changed')
            self.baseline = private_json(self.baseline_path)
            header = private_json(self.hop_path)
            before = private_json(self.hold.state / ('k3s-before-' + owner['owner'] + '.json'))
            self.cycle = cycles.Cycle(self.hold, owner, header, before, native,
                                      lambda: self.owned(owner['owner']))
            self.runtime = lambda: runtime(native, SOURCE)
        except BaseException:
            self.api.close()
            raise

    def owned(self, token):
        return token == self.owner['owner'] and ownership.observe(self.controller, self.baseline) is True

    def voters(self, stopped=False):
        nodes = self.api.snapshot()[2]
        versions = {n['metadata']['name']: n['status']['nodeInfo']['kubeletVersion'] for n in nodes
                    if n['metadata']['name'] in ENDPOINTS}
        # dispatch_start already holds the native lock; its proof must not acquire it again.
        confirm = (lambda: cycles.stopped.observe(self.native, self.cycle.before,
            self.cycle.header['owners']['host']['identity'], self.cycle.guard)['accepted']) if stopped else None
        quorum.native_observe(self.owner['node'], versions, confirm_stopped=confirm)
        return True

    def close(self):
        self.api.close()


def native_operation(owner, identities, identity, native, operation, binding=None, expected=None):
    initialize = operation == 'initialize' or (operation == 'resume' and not
        (actors.STATE / ('legacy-ownership-' + owner['owner'] + '.json')).exists())
    context = Context(owner, identities, identity, native, initialize=initialize)
    try:
        cycle = context.cycle
        plan_path = context.hold.state / ('legacy-copy-' + owner['owner'] + '.json')
        if operation in ('initialize', 'resume'):
            if initialize: quorum.native_install(owner['node'])
            receipt = context.hold.state / ('legacy-accepted-' + owner['owner'] + '.json')
            if receipt.exists() and (context.hold.state / 'transactions' / owner['owner'] / '00000006.json').exists():
                baseline = source_baseline(context.hold, owner, cycle.before)
                actors.require(context.runtime() == baseline and context.voters(), 'accepted SOURCE has changed')
                result = {'legacy_already_accepted': private_json(receipt)}
            else:
                result = cycle.read() if cycle.path.exists() else cycle.initialize()
        elif operation == 'plan':
            result = private_json(plan_path)
        elif operation == 'stop':
            result = cycle.dispatch_stop(context.voters, context.runtime)
        elif operation == 'observe-stopped':
            result = cycle.observe_stopped()
        elif operation == 'manifest':
            cycle.observe_stopped()
            manifest = legacy.member_manifest(DATA)
            cycle.observe_stopped()
            if not plan_path.exists():
                point_id = 'legacy-' + owner['node'] + '-' + uuid.uuid4().hex
                value = {'manifest': manifest, 'sha256': legacy.manifest_sha256(manifest),
                         'binding': {'owner': owner, 'hop_sha256': cycle.header['pending']['sha256'],
                                     'source_identity': identity(), 'point_id': point_id},
                         'point': str(ROOT / point_id)}
                actors.exclusive_file(plan_path, hops.canonical(value), 0o600)
            result = private_json(plan_path)
            actors.require(result['manifest'] == manifest and result['sha256'] ==
                           legacy.manifest_sha256(manifest), 'original cold-copy plan changed')
        elif operation == 'send':
            actors.require(binding['owner'] == owner and binding['hop_sha256'] ==
                           cycle.header['pending']['sha256'], 'cold-copy binding differs')
            transfer.send(DATA, sys.stdout.buffer, binding, expected,
                          lambda: cycle.observe_stopped()['accepted'])
            return
        elif operation == 'start':
            result = cycle.dispatch_start(lambda: context.voters(stopped=True))
        elif operation == 'observe-returned':
            result = cycle.observe_returned(context.runtime, context.voters)
        elif operation == 'accept-check':
            state = cycle.read(); plan = private_json(plan_path)
            checked = expected['check']; copied = expected['copy']
            actors.require(expected['owner'] == owner and expected['binding'] == plan['binding'] and
                           expected['source_manifest_sha256'] == plan['sha256'] and
                           copied['accepted'] is True and copied['point'] == plan['point'] and
                           copied['source_manifest_sha256'] == plan['sha256'] and
                           checked['protected_manifest_sha256'] == copied['received_manifest_sha256'] and
                           checked['accepted'] is True and checked['tool_sha256'] == legacy.BINARY_SHA256 and
                           checked['version'] == legacy.VERSION and checked['checker_exit'] == 0 and
                           checked['protected_point_unchanged'] is True and checked['one_checker_dispatch'] is True and
                           checked['cleanup']['scratch_absent'] is True and
                           expected['SOURCE_returned'] == state['source-returned.json'] and
                           context.runtime() == state['source-returned.json']['runtime'] and context.voters(),
                           'legacy native check or returned SOURCE proof differs')
            value = dict(expected, original_before=cycle.before,
                cycle_files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in cycle.path.iterdir()})
            receipt = context.hold.state / ('legacy-accepted-' + owner['owner'] + '.json')
            if not receipt.exists(): actors.exclusive_file(receipt, hops.canonical(value), 0o600)
            actors.require(private_json(receipt) == value, 'original legacy acceptance changed')
            journal = hops.Journal(context.controller, context.hold, owner['owner'])
            result = journal.accept(cycle.header['pending']['sha256'], hops.digest(hops.canonical(value)),
                lambda step, digest: step == 'check_legacy_etcd' and digest == hops.digest(hops.canonical(value)) and
                cycle.read() == state and context.runtime() == state['source-returned.json']['runtime'])
        else:
            raise RuntimeError('unreviewed native legacy operation')
        print(json.dumps(result), flush=True)
    finally:
        context.close()


def program(bundle, owner, identities, identity, mac, operation, binding=None, expected=None):
    """Use existing SSH trust and native client certificates; no credentials are copied."""
    source = '''
import json,sys,types,pathlib,socket,subprocess,os
for name,source in BUNDLE.items():
 module=types.ModuleType(name);sys.modules[name]=module;exec(compile(source,name+'.py','exec'),module.__dict__)
def native(*args):return sys.modules['maintenance_actor_hold'].Systemd.call(*args).decode().strip()
def identity():
 actual={'machine':pathlib.Path('/etc/machine-id').read_text().strip(),'root_uuid':native('findmnt','-n','-o','UUID','/')}
 assert os.geteuid()==0 and socket.gethostname()==OWNER['node'] and actual==IDENTITY
 assert MAC in{p.read_text().strip()for p in pathlib.Path('/sys/class/net').glob('*/address')}
 return actual
identity()
sys.modules['maintenance_etcd_production'].native_operation(OWNER,IDENTITIES,identity,native,OPERATION,BINDING,EXPECTED)
'''
    return ('BUNDLE=' + repr(bundle) + '\nOWNER=' + repr(owner) + '\nIDENTITIES=' + repr(identities) +
            '\nIDENTITY=' + repr(identity) + '\nMAC=' + repr(mac) + '\nOPERATION=' + repr(operation) +
            '\nBINDING=' + repr(binding) + '\nEXPECTED=' + repr(expected) + '\n' + source)


def run(args, owner, identities, bundle):
    """Resume uncertain service returns by observing; SOURCE start survives copy failure."""
    import maintenance_production_node as production
    def command(value):
        compressed = base64.b64encode(zlib.compress(value.encode())).decode()
        bootstrap = 'import base64,zlib;exec(compile(zlib.decompress(base64.b64decode(' + repr(compressed) + ')),"native-etcd-cycle","exec"))'
        actors.require(len(bootstrap) < 100000, 'native cycle bootstrap exceeds reviewed argument bound')
        return 'python3 -B -c ' + shlex.quote(bootstrap)
    def source(operation, binding=None, expected=None):
        return program(bundle, owner, identities, production.IDENTITY, production.MAC,
                       operation, binding, expected)
    state = production.remote(args, source('resume'))
    if 'legacy_already_accepted' in state:
        return state['legacy_already_accepted']
    returned = state.get('source-returned.json')
    manifest = None
    copied = None
    try:
        if 'start-intent.json' not in state:
            if 'stop-intent.json' not in state:
                production.remote(args, source('stop'))
            production.remote(args, source('observe-stopped'))
            manifest = production.remote(args, source('manifest'))
        else:
            manifest = production.remote(args, source('plan'))
        binding, point = manifest['binding'], manifest['point']
        receive = '''
import json,os,pathlib,socket,subprocess,sys,types
for name,source in BUNDLE.items():
 module=types.ModuleType(name);sys.modules[name]=module;exec(compile(source,name+'.py','exec'),module.__dict__)
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0a7daf8b33244d9d85f46223c3582da9'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='76e53a95-725a-4430-9d7b-a8db413f3997'
def native(*args):return subprocess.check_output(args,text=True).strip()
point=pathlib.Path(POINT)
if (point/'verified.json').exists():
 header=sys.modules['maintenance_node_drain'].private_json(point/'verified.json')
 legacy=sys.modules['maintenance_etcd_legacy'];expected=header['manifest']
 assert header['binding']==BINDING and legacy.manifest_sha256(expected)==DIGEST
 actual=legacy.member_manifest(point/'data');assert legacy.contents(actual)==legacy.contents(expected)
 result={'accepted':True,'point':POINT,'source_manifest_sha256':DIGEST,'received_manifest_sha256':legacy.manifest_sha256(actual),'binding_sha256':__import__('hashlib').sha256(sys.modules['maintenance_etcd_transfer'].canonical(BINDING)).hexdigest(),'complete_WAL_and_database':True,'original_recovery_point_preserved':True}
else:
 assert MAY_RECEIVE,'SOURCE has returned but original cold-copy commit is absent; preserve the point'
 result=sys.modules['maintenance_etcd_transfer'].receive(sys.stdin.buffer,point,BINDING,DIGEST,native)
print(json.dumps(result),flush=True)
'''
        receive = ('BUNDLE=' + repr(bundle) + '\nPOINT=' + repr(point) + '\nBINDING=' + repr(binding) +
                   '\nDIGEST=' + repr(manifest['sha256']) + '\nMAY_RECEIVE=' +
                   repr('start-intent.json' not in state) + '\n' + receive)
        sender = receiver = None
        try:
            if 'start-intent.json' not in state:
                sender = subprocess.Popen(production.ssh(args) + [command(source('send', binding, manifest['manifest']))],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            receiver = subprocess.Popen(production.ssh(args, '10.0.20.14') + [command(receive)],
                stdin=sender.stdout if sender else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if sender: sender.stdout.close()
            output, _ = receiver.communicate()
            if sender: sender.wait()
            actors.require(receiver.returncode == 0 and (sender is None or sender.returncode == 0),
                           'cold etcd copy incomplete; retain partial protected point and restore SOURCE')
            copied = json.loads(output)
            actors.require(copied['accepted'] is True and copied['source_manifest_sha256'] == manifest['sha256'],
                           'cold-copy receipt differs')
        finally:
            for child in (sender, receiver):
                if child is not None and child.poll() is None: child.terminate();child.wait()
    finally:
        # Re-read the persisted one-shot intents. Never repeat an uncertain start.
        state = production.remote(args, source('resume'))
        if 'stop-intent.json' in state and 'start-intent.json' not in state:
            proof = production.remote(args, source('observe-stopped'))
            actors.require(proof['accepted'] is True, 'SOURCE stop unproven; inspect original journal')
            production.remote(args, source('start'))
    returned = production.remote(args, source('observe-returned'))
    actors.require(copied is not None, 'SOURCE recovered but cold-copy acceptance missing')
    check = '''
import json,os,pathlib,socket,subprocess,sys,types
for name,source in BUNDLE.items():
 module=types.ModuleType(name);sys.modules[name]=module;exec(compile(source,name+'.py','exec'),module.__dict__)
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0a7daf8b33244d9d85f46223c3582da9'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='76e53a95-725a-4430-9d7b-a8db413f3997'
def native(*args):return subprocess.check_output(args,text=True).strip()
legacy=sys.modules['maintenance_etcd_legacy'];actors=sys.modules['maintenance_actor_hold']
point=pathlib.Path(POINT);header=json.loads((point/'verified.json').read_bytes())
assert header['binding']==BINDING and legacy.manifest_sha256(header['manifest'])==DIGEST
expected=legacy.member_manifest(point/'data');assert legacy.contents(expected)==legacy.contents(header['manifest'])
receipt_path=point/'legacy-check.json';actors.safe(receipt_path)
if receipt_path.exists():
 result=sys.modules['maintenance_node_drain'].private_json(receipt_path)
 assert result['protected_manifest_sha256']==legacy.manifest_sha256(expected)
else:
 tool=legacy.install_tool(pathlib.Path('/var/lib/homelab-recovery/tools'),native)
 intent=point/'legacy-check-intent.json'
 actors.exclusive_file(intent,sys.modules['maintenance_hop_journal'].canonical({'tool':tool,'manifest_sha256':legacy.manifest_sha256(expected)}),0o600)
 result=legacy.check_copy(point/'data',expected,pathlib.Path(tool['tool']),point.parent,native)
 actors.exclusive_file(receipt_path,sys.modules['maintenance_hop_journal'].canonical(result),0o600)
assert result['accepted'] is True and result['protected_point_unchanged'] and result['cleanup']['scratch_absent']
print(json.dumps(result),flush=True)
'''
    check = ('BUNDLE=' + repr(bundle) + '\nPOINT=' + repr(point) + '\nBINDING=' + repr(binding) +
             '\nDIGEST=' + repr(manifest['sha256']) + '\n' + check)
    checked = production.remote(args, check, '10.0.20.14')
    return {'owner': owner, 'copy': copied, 'binding': binding, 'SOURCE_returned': returned,
            'check': checked, 'source_manifest_sha256': manifest['sha256'], 'accepted': True}
