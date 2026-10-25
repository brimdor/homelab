"""Compose one actual native Fedora agent hop with surviving Kubernetes capacity."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shlex
import signal
import threading
import time

import fedora_package_dispatch_qualification as package
import fedora_release_upgrade_qualification as upgrade
import maintenance_actor_hold as actors
import maintenance_coordination as coordination
from maintenance_drain_qualification import fixtures, NAMESPACE, PAYLOAD
from maintenance_fedora_endpoint import Endpoint
from maintenance_fedora_endpoint_qualification import Qualification as Fleet
from maintenance_native_cluster import Cluster, WORKLOAD, transfer_private


MODULES = ('maintenance_coordination', 'maintenance_actor_hold', 'maintenance_hop_journal',
           'maintenance_package_dispatch', 'maintenance_node_drain',
           'maintenance_node_scheduling', 'maintenance_safe_release')
NATIVE = '''import types,sys,time
unit_query_attempts=[]
for name,source in bundle.items():
 module=types.ModuleType(name);module.__file__='/ram/'+name+'.py';sys.modules[name]=module
 exec(compile(source,module.__file__,'exec'),module.__dict__)
coordination=sys.modules['maintenance_coordination'];actors=sys.modules['maintenance_actor_hold']
hops=sys.modules['maintenance_hop_journal'];package=sys.modules['maintenance_package_dispatch']
drain=sys.modules['maintenance_node_drain'];scheduling=sys.modules['maintenance_node_scheduling']
release=sys.modules['maintenance_safe_release']
root=pathlib.Path('/var/lib/qualification-native-controller')
class API(coordination.Kubectl):
 def call(self,*args,data=None):
  if args[0]in('create','patch'):
   # The hop journal owns intent; this separate diagnostic counts attempted API mutations.
   row={'argv':list(args),'body':json.loads(data)if data is not None else None}
   with(root/'api-mutations.jsonl').open('a')as output:
    output.write(json.dumps(row,sort_keys=True)+'\\n');output.flush();os.fsync(output.fileno())
  return super().call(*args,data=data)
api=API('/usr/local/bin/qualification-kubectl')
def identity():
 return {'machine':pathlib.Path('/etc/machine-id').read_text().strip(),
  'root_uuid':native('findmnt','-n','-o','UUID','/').strip()}
def connect():
 value=json.loads((root/'context.json').read_bytes())
 controller=coordination.Ownership(api,value['daemonset_uid'],value['node_uids'])
 hold=actors.Hold(actors.Systemd(),identity,lambda token:controller.resume(token)==value['owner'])
 return value,hops.Journal(controller,hold,value['owner']['owner'])
def available():
 deployment=api.call('get','deployment','workload','-n','qualification-drain','-o','json')
 status=deployment['status']
 assert status['observedGeneration']==deployment['metadata']['generation']
 assert all(status.get(key)==3 for key in('replicas','readyReplicas','availableReplicas','updatedReplicas'))
 pods=api.call('get','pods','-n','qualification-drain','-l','app=qualification-drain','-o','json')['items']
 assert len(pods)==3 and all(not p['metadata'].get('deletionTimestamp')and
  len(p['status'].get('containerStatuses',[]))==1 and p['status']['containerStatuses'][0].get('ready')is True for p in pods)
 slices=api.call('get','endpointslice','-n','qualification-drain','-l','kubernetes.io/service-name=workload','-o','json')['items']
 ready={e['targetRef']['uid']for item in slices for e in item.get('endpoints',[])if e.get('conditions',{}).get('ready')is True}
 assert ready=={p['metadata']['uid']for p in pods}
 raw=native('/usr/local/bin/qualification-kubectl','get',
  '--raw=/api/v1/namespaces/qualification-drain/services/workload:8080/proxy/').encode()
 assert raw==b'{"maintenance":"103","service":"qualification-l2"}\\n'
 return {'deployment_uid':deployment['metadata']['uid'],'ready_pods':sorted(
  [p['metadata']['uid'],p['spec']['nodeName']]for p in pods),'endpoint_uids':sorted(ready),
  'http_sha256':hashlib.sha256(raw).hexdigest()}
'''


def program(body, hostname, revision):
    bundle = {name: Path(__file__).with_name(name + '.py').read_text() for name in MODULES}
    return (upgrade.guest_source(hostname) + 'bundle=' + repr(bundle) + '\nrevision=' + repr(revision) +
            '\n' + NATIVE + package.OBSERVATIONS + body)


class Target(Endpoint, package.Qualification):
    def package_guest(self, body, expected=0):
        raw = self.command(self.ssh + ['sudo python3 -B -'],
                           data=program(body, self.hostname, self.args.revision).encode(), expected=expected)
        return json.loads(raw) if expected == 0 else raw

    def wait_ready(self):
        super().wait_ready()
        if not getattr(self, 'cluster_started', False):
            return
        self.guest('''
import time
while True:
 fields=dict(line.split('=',1)for line in native('systemctl','show','qualification-k3s.service',
  '--property=ActiveState','--property=Result').splitlines())
 assert fields['ActiveState']in('activating','active')and fields['Result']=='success'
 node=json.loads(native('/usr/local/bin/qualification-kubectl','get','node',socket.gethostname(),'-o','json'))
 if(node['status'].get('nodeInfo',{}).get('bootID')==pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
  and any(c['type']=='Ready'and c['status']=='True'for c in node['status'].get('conditions',[]))):break
 time.sleep(2)
native('/usr/local/bin/qualification-kubectl','rollout','status','daemonset/kured','-n','kured','--timeout=1200s')
print(json.dumps({'native_fresh_boot_and_kured_ready':True}))
''')


class Qualification(Fleet):
    node_class = Target

    @property
    def target(self):
        return self.endpoints[0]

    def control(self, body):
        return self.target.package_guest(body)

    def kubectl(self, *args, data=None, json_output=True):
        node = self.endpoints[1]
        selected = (*args, '-o', 'json') if json_output else args
        raw = node.command(node.ssh + ['sudo /usr/local/bin/qualification-kubectl ' + shlex.join(selected)],
                           data=data)
        return json.loads(raw) if json_output else raw

    def ready(self):
        self.kubectl('wait', 'nodes', '--all', '--for=condition=Ready', '--timeout=1200s', json_output=False)
        nodes = self.kubectl('get', 'nodes')['items']
        actors.require(len(nodes) == 3 and {n['metadata']['name'] for n in nodes} ==
                       {'qualification-native-' + str(i) for i in range(3)}, 'native Node identities differ')
        for index, node in enumerate(self.endpoints):
            value = next(n for n in nodes if n['metadata']['name'] == node.hostname)
            actual_boot = node.identity()['boot']
            self.kubectl('wait', 'node/' + node.hostname,
                         '--for=jsonpath={.status.nodeInfo.bootID}=' + actual_boot,
                         '--timeout=1200s', json_output=False)
            addresses = {a['address'] for a in value['status']['addresses'] if a['type'] == 'InternalIP'}
            actors.require(addresses == {node.endpoint['address']}, 'native Node private IP differs')
        return nodes

    def availability(self):
        # Only the server endpoint's command counter is used by this monitor.
        spec = self.kubectl('get', 'deployment', 'workload', '-n', NAMESPACE)
        pods = self.kubectl('get', 'pods', '-n', NAMESPACE, '-l', 'app=qualification-drain')['items']
        status = spec['status']
        actors.require(status['observedGeneration'] == spec['metadata']['generation'] and
                       all(status.get(k) == 3 for k in ('replicas', 'readyReplicas', 'availableReplicas',
                                                       'updatedReplicas')) and len(pods) == 3 and
                       all(not p['metadata'].get('deletionTimestamp') and
                           len(p['status'].get('containerStatuses', [])) == 1 and
                           p['status']['containerStatuses'][0].get('ready') is True for p in pods),
                       'native survivor application is unready')
        slices = self.kubectl('get', 'endpointslice', '-n', NAMESPACE,
                              '-l', 'kubernetes.io/service-name=workload')['items']
        uids = {e['targetRef']['uid'] for item in slices for e in item.get('endpoints', [])
                if e.get('conditions', {}).get('ready') is True}
        actors.require(uids == {p['metadata']['uid'] for p in pods}, 'native service endpoints differ')
        raw = self.kubectl('get', '--raw=/api/v1/namespaces/' + NAMESPACE +
                           '/services/workload:8080/proxy/', json_output=False)
        actors.require(raw == PAYLOAD, 'native service HTTP differs')
        return {'at_ns': time.time_ns(), 'pod_uids': sorted(uids),
                'node_names': sorted(p['spec']['nodeName'] for p in pods),
                'http_sha256': hashlib.sha256(raw).hexdigest()}

    def recovery(self):
        target = self.target
        corpus = target.corpus(create=True)
        before = target.state(39, corpus)
        original_uids = {n['metadata']['name']: n['metadata']['uid'] for n in self.ready()}
        target.stop()
        target.command([self.args.qemu_img, 'snapshot', '-c', 'native-protected39', str(target.disk)])
        target.boot();target.wait_ready()
        mutation = target.guest('''
files=sorted(p for p in pathlib.Path('/var/tmp/qualification-upgrade-data/corpus').rglob('*')if p.is_file())
assert files
path=files[0];before=hashlib.sha256(path.read_bytes()).hexdigest()
path.write_bytes(path.read_bytes()+b'owned synthetic restore proof\\n')
after=hashlib.sha256(path.read_bytes()).hexdigest();assert before!=after
print(json.dumps({'synthetic_file':str(path),'before_sha256':before,'mutated_sha256':after}))
''')
        target.stop()
        target.command([self.args.qemu_img, 'snapshot', '-a', 'native-protected39', str(target.disk)])
        target.boot();target.wait_ready()
        restored = target.state(39, corpus)
        upgrade.require_checkpoint_state(restored, before)
        actors.require({n['metadata']['name']: n['metadata']['uid'] for n in self.ready()} == original_uids,
                       'native restore changed cluster Node identity')
        self.persist('protected-synthetic-disk-restored', before=before, mutation=mutation, restored=restored)
        return corpus

    def initialize(self):
        return self.control('''
root.mkdir(mode=0o700)
ds,_,nodes=api.snapshot();uids={n['metadata']['name']:n['metadata']['uid']for n in nodes}
assert set(uids)=={'qualification-native-'+str(i)for i in range(3)}
controller=coordination.Ownership(api,ds['metadata']['uid'],uids)
owner=controller.acquire(socket.gethostname(),39,41,revision)
hold=actors.Hold(actors.Systemd(),identity,lambda token:controller.resume(token)==owner)
hold.acquire(owner['owner'],identity(),revision)
journal=hops.Journal(controller,hold,owner['owner']);journal.initialize()
value={'owner':owner,'daemonset_uid':ds['metadata']['uid'],'node_uids':uids}
actors.exclusive_file(root/'context.json',hops.canonical(value),0o600)
print(json.dumps({'owner':value,'journal':journal.inspect(),'available':available()}))
''')

    def drain(self):
        prepared = self.control('''
value,journal=connect();current=available();checksum=drain.hashed(current)
worker=scheduling.Scheduling(journal,api);plan=worker.plan('cordon')
worker.dispatch(plan,drain.hashed(plan),checksum,lambda *_:available()==current)
accepted=worker.observe(plan,checksum,lambda *_:available()==current);assert accepted['accepted']
actors.exclusive_file(root/'cordon.json',hops.canonical(plan),0o600)
worker=drain.Drain(journal,api);plan=worker.inventory()
selected=[p for p in plan['pods']if not p['keep']]
assert len(selected)==1 and selected[0]['namespace']=='qualification-drain'
native('/usr/local/bin/qualification-kubectl','wait','pdb/workload','-n','qualification-drain',
 '--for=jsonpath={.status.disruptionsAllowed}=1','--timeout=180s')
worker.start(plan,drain.hashed(plan),checksum,lambda *_:available()==current)
queued=worker.advance(checksum,lambda *_:available()==current);assert queued['mutation_performed']
print(json.dumps({'cordon':accepted,'plan':plan,'queued':queued,'selected':selected[0]}))
''')
        selected = prepared['selected']
        self.kubectl('wait', 'pod/' + selected['name'], '-n', NAMESPACE, '--for=delete',
                     '--timeout=300s', json_output=False)
        self.kubectl('rollout', 'status', 'deployment/workload', '-n', NAMESPACE,
                     '--timeout=1200s', json_output=False)
        accepted = self.control('''
value,journal=connect();current=available();checksum=drain.hashed(current)
assert all(name!=socket.gethostname()for _,name in current['ready_pods'])
worker=drain.Drain(journal,api);assert 'observed'in worker.advance(checksum,lambda *_:available()==current)
outcome=worker.advance(checksum,lambda *_:available()==current);assert outcome['complete']
pending=journal.inspect()['pending']
journal.accept(pending['sha256'],drain.hashed(outcome),lambda *_:
 worker.read()['records_sha256']==outcome['records_sha256']and
 drain.hashed(worker.inventory())==outcome['inventory_sha256']and available()==current)
print(json.dumps({'outcome':outcome,'journal':journal.inspect(),'available':current}))
''')
        self.persist('actual-native-cordon-and-UID-drain', prepared=prepared, accepted=accepted)

    def package_hop(self, corpus):
        target = self.target
        initial = target.state(39, corpus)
        before_history = target.history()
        target.dispatch('prepare_source', lose_response=True)
        self.persist('controller-exit73-and-no-redispatch', result=target.refuse_replay('prepare_source'))
        unit = target.wait_unit('prepare_source');history = target.history()
        actors.require(history['id'] == before_history['id'] + 1, 'native source history differs')
        receipt = {'unit': unit, 'history_before': before_history, 'history_after': history,
                   'state': target.state(39, corpus), 'signatures': target.signatures()}
        self.persist('actual-native-source-package-accepted', receipt=receipt,
                     journal=target.accept('prepare_source', receipt, 39, unit))
        target.checkpoint('release39')
        source = target.state(39, corpus)
        actors.require(all(source['identity'][k] == initial['identity'][k]
                           for k in ('machine', 'root_uuid', 'architecture')), 'source reboot identity changed')
        target.prepare_plugin();history = target.history();target.repositories(41)
        target.dispatch('download_release');unit = target.wait_unit('download_release')
        actors.require(target.history()['id'] == history['id'], 'native download changed installed history')
        receipt = {'unit': unit, 'history': history, 'state': target.state(39, corpus),
                   'signatures': target.signatures()}
        self.persist('actual-native-download-accepted', receipt=receipt,
                     journal=target.accept('download_release', receipt, 39, unit))
        before = target.identity()
        try:target.dispatch('offline_transaction')
        except RuntimeError as error:
            raw = (target.root / (str(target.number) + '.log')).read_bytes()
            if not upgrade.reboot_probe_disconnect(error, target.number, raw):raise
            self.persist('offline-dispatch-response-lost', command=target.number,
                         output_sha256=hashlib.sha256(raw).hexdigest())
        while True:
            try:
                target.wait_ready()
                current = target.guest('''
print(json.dumps({'release':int(native('rpm','-E','%fedora').strip()),
 'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'pending':pathlib.Path('/system-update').is_symlink()}))
''')
            except RuntimeError as error:
                raw = (target.root / (str(target.number) + '.log')).read_bytes()
                if not upgrade.reboot_probe_disconnect(error, target.number, raw):raise
                self.persist('offline-observer-disconnected', output_sha256=hashlib.sha256(raw).hexdigest())
                time.sleep(5);continue
            if current['boot'] != before['boot'] and not current['pending']:
                actors.require(current['release'] == 41, 'native offline return is not Fedora41')
                break
            if current['boot'] == before['boot']:
                fields = target.package_guest("value,journal=connect();print(json.dumps(unit_state(value['owner'],'offline_transaction')))\n")
                package.service_complete(fields)
            time.sleep(5)
        final = target.state(41, corpus);after_history = target.history()
        actors.require(after_history['id'] == history['id'] + 1 and
                       all(final['identity'][k] == before[k] for k in ('machine', 'root_uuid', 'architecture')),
                       'offline history or stable identity differs')
        receipt = {'state': final, 'history': after_history, 'before': before,
                   'signatures': target.signatures(), 'transient_unit_not_required_after_reboot': True}
        actors.require(not target.server.errors, 'verified repository transport failed')
        self.persist('actual-native-offline-accepted', receipt=receipt,
                     journal=target.accept('offline_transaction', receipt, 41))
        return final

    def accept_infrastructure(self, corpus, final, before, hub_pid, survivor_pids, keys):
        for index in (1, 2):
            current = self.endpoints[index].private_identity()
            actors.require(current == before[index], 'surviving native endpoint changed')
        actors.require(self.hub.running() == hub_pid and
                       [n.child.pid for n in self.endpoints[1:]] == survivor_pids and
                       [n.prepared_keys() for n in self.endpoints] == keys, 'native process/key identity changed')
        private = self.target.private_identity()
        actors.require(private['private_endpoint'] == before[0]['private_endpoint'], 'target private identity changed')
        actors.require(self.target.corpus() == corpus, 'restored full corpus changed after package hop')
        result = self.control('final=' + repr(final['identity']) + '\n' + '''
value,journal=connect()
assert native('rpm','-E','%fedora').strip()=='41'
assert pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()==final['boot']
assert native('uname','-r').strip()==final['kernel']
assert all(identity()[k]==final[k]for k in('machine','root_uuid'))
for step in('trusted_reconnect','verify_infrastructure'):
 nodes=api.call('get','nodes','-o','json')['items']
 assert {n['metadata']['name']:n['metadata']['uid']for n in nodes}==value['node_uids']
 assert all(any(c['type']=='Ready'and c['status']=='True'for c in n['status']['conditions'])for n in nodes)
 state={'step':step,'nodes':value['node_uids'],'identity':identity(),'application':available(),'enforcing':True}
 checksum=drain.hashed(state)
 pending=journal.begin(step,checksum,checksum,lambda *_:available()==state['application'])
 journal.accept(pending['pending']['sha256'],checksum,lambda *_:available()==state['application'])
print(json.dumps({'journal':journal.inspect(),'actual_fixture_only':True}))
''')
        self.persist('actual-native-trusted-reconnect-and-infrastructure', result=result, private_identity=private)

    def restore_and_release(self):
        restored = self.control('''
value,journal=connect();current=available();checksum=drain.hashed(current)
worker=scheduling.Scheduling(journal,api)
plan=worker.plan('restore_scheduling',drain.private_json(root/'cordon.json'))
worker.dispatch(plan,drain.hashed(plan),checksum,lambda *_:available()==current)
accepted=worker.observe(plan,checksum,lambda *_:available()==current);assert accepted['accepted']
print(json.dumps({'restored':accepted}))
''')
        canary = copy.deepcopy(next(v for v in fixtures(2) if v['kind'] == 'Deployment'))
        canary['metadata']['name'] = 'native-canary';spec = canary['spec'];spec['replicas'] = 1
        labels = {'app': 'native-canary'}
        spec['selector']['matchLabels'] = labels;spec['template']['metadata']['labels'] = labels
        pod = spec['template']['spec'];pod.pop('affinity')
        pod['nodeSelector'] = {'kubernetes.io/hostname': self.target.hostname}
        pod['containers'][0]['image'] = WORKLOAD['image'].rsplit(':', 1)[0] + '@' + WORKLOAD['digest']
        pod['containers'][0]['imagePullPolicy'] = 'Never'
        self.kubectl('apply', '-f', '-', data=json.dumps(canary).encode(), json_output=False)
        self.kubectl('rollout', 'status', 'deployment/native-canary', '-n', NAMESPACE,
                     '--timeout=1200s', json_output=False)
        released = self.control('''
value,journal=connect()
def safety():
 assert native('rpm','-E','%fedora').strip()=='41'
 assert pathlib.Path('/sys/fs/selinux/enforce').read_text().strip()=='1'
 journal.hold.systemd.idle(journal.hold.marker)
 for name in('/run/reboot-required','/var/run/reboot-required','/system-update'):
  assert not pathlib.Path(name).exists()and not pathlib.Path(name).is_symlink()
 pods=api.call('get','pods','-n','qualification-drain','-l','app=native-canary','-o','json')['items']
 assert len(pods)==1
 pod=pods[0];assert pod['spec']['nodeName']==socket.gethostname()and not pod['metadata'].get('deletionTimestamp')
 assert len(pod['status'].get('containerStatuses',[]))==1 and pod['status']['containerStatuses'][0]['ready']
 raw=native('/usr/local/bin/qualification-kubectl','get',
  '--raw=/api/v1/namespaces/qualification-drain/pods/'+pod['metadata']['name']+':8080/proxy/').encode()
 assert raw==b'{"maintenance":"103","service":"qualification-l2"}\\n'
 return {'canary_uid':pod['metadata']['uid'],'http_sha256':hashlib.sha256(raw).hexdigest(),'available':available(),
  'native_idle':True,'reboot_sentinels_absent':True,'enforcing':True}
state=safety();checksum=drain.hashed(state)
pending=journal.begin('accept_applications',checksum,checksum,lambda *_:safety()==state)
journal.accept(pending['pending']['sha256'],checksum,lambda *_:safety()==state)
worker=release.Release(journal);verify=lambda _header,digest:digest==checksum and safety()==state
prepared=worker.prepare(checksum,verify)
host=worker.release_host(checksum,verify)
global_result=worker.release_global(checksum,verify)
final=worker.observe(checksum,verify)
assert final['complete']and not journal.hold.marker.exists()
assert worker.observe(checksum,verify)==final
mutations=[json.loads(line)for line in(root/'api-mutations.jsonl').read_text().splitlines()]
assert sum(v['argv'][:2]==['patch','node']for v in mutations)==2
assert sum(v['argv'][0]=='create'for v in mutations)==1
assert sum(v['argv'][:2]==['patch','daemonset']for v in mutations)==2
hop_records={p.name:json.loads(p.read_bytes())for p in sorted(journal.path.iterdir())}
release_records={p.name:json.loads(p.read_bytes())for p in sorted(worker.path.iterdir())}
assert len(hop_records)==19 and len(release_records)==5
print(json.dumps({'application':state,'prepared':prepared,'host':host,'global':global_result,
 'final':final,'mutations':mutations,'hop_records':hop_records,'release_records':release_records,
 'native_systemd_and_Kured_released':True}))
''')
        self.persist('actual-native-scheduling-application-ordered-release', restored=restored, released=released)

    def run(self):
        monitor = None;stop = threading.Event();failures = [];observations = []
        try:
            self.prepare();before = self.identities()
            keys = [n.prepared_keys() for n in self.endpoints]
            actors.require(len({v for record in keys for v in record.values()}) == 6,
                           'native prepared key collision')
            cluster = Cluster(self.endpoints, self.args)
            installed = [cluster.prepare(i) for i in range(3)]
            cluster.start(1);cluster.wrapper(1);cluster.import_images(1)
            for index in (0, 2):
                transfer_private(self.endpoints[1], self.endpoints[index], 'join-token')
                cluster.start(index);cluster.import_images(index)
            transfer_private(self.endpoints[1], self.target, 'admin-config');cluster.wrapper(0)
            self.ready()
            corpus = self.recovery()
            objects = fixtures(2)
            for obj in objects:
                if obj['kind'] in ('Deployment', 'DaemonSet'):
                    for container in obj['spec']['template']['spec']['containers']:
                        container['imagePullPolicy'] = 'Never'
                        if obj['kind'] == 'Deployment':
                            container['image'] = WORKLOAD['image'].rsplit(':', 1)[0] + '@' + WORKLOAD['digest']
            self.kubectl('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'List',
                                                            'items': objects}).encode(), json_output=False)
            for item, namespace in (('daemonset/kured', 'kured'), ('deployment/workload', NAMESPACE)):
                self.kubectl('rollout', 'status', item, '-n', namespace, '--timeout=1200s', json_output=False)
            initial = self.availability()
            actors.require(set(initial['node_names']) == {n.hostname for n in self.endpoints},
                           'native replicas are not initially spread')
            self.target.cluster_started = True
            self.persist('actual-native-cluster-and-ownership', installed=installed, initial=initial,
                         prepared_public_keys=keys, initialized=self.initialize())
            self.drain()
            hub_pid = self.hub.running();survivor_pids = [n.child.pid for n in self.endpoints[1:]]
            def watch():
                while not stop.is_set():
                    try:observations.append(self.availability())
                    except BaseException as error:failures.append(type(error).__name__ + ': ' + str(error));return
                    stop.wait(2)
            monitor = threading.Thread(target=watch, name='owned-native-survivor-HTTP');monitor.start()
            final = self.package_hop(corpus)
            stop.set();monitor.join(timeout=120)
            actors.require(not monitor.is_alive() and not failures and len(observations) >= 2,
                           'native survivor availability monitoring failed')
            self.persist('actual-native-survivor-HTTP-through-package-hop', observations=observations)
            self.accept_infrastructure(corpus, final, before, hub_pid, survivor_pids, keys)
            self.restore_and_release()
            self.result.update(accepted=True, actual_native_agent39_to41_controller_composition=True,
                               actual_packages_drain_recovery_and_release=True,
                               production_Ceph_Cilium_GPU_NAS_server_HA_and_later_hops_unqualified=True)
            (self.root / 'result.json').write_text(json.dumps(self.result, indent=2))
            return self.result
        finally:
            stop.set()
            if monitor is not None:monitor.join(timeout=120)
            try:self.cleanup()
            finally:
                if monitor is not None:
                    monitor.join(timeout=90)
                    actors.require(not monitor.is_alive(), 'owned native HTTP monitor remains')
                self.persist('owned-native-monitor-terminal', observations=observations, failures=failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'keys-dir', 'assets-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--revision', required=True)
    for name in ('qemu', 'qemu-img'):parser.add_argument('--' + name, required=True)
    fixture = Qualification(parser.parse_args())
    def interrupted(_number, _frame):raise InterruptedError('owned native controller cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):signal.signal(number, interrupted)
    print(json.dumps(fixture.run()), flush=True)


if __name__ == '__main__':
    main()
