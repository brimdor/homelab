#!/usr/bin/env python3
"""Qualify actual package dispatch/resume in an owned disconnected Fedora VM."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import time

import fedora_release_upgrade_qualification as upgrade


MODULES = ('maintenance_coordination', 'maintenance_actor_hold', 'maintenance_hop_journal',
           'maintenance_package_dispatch', 'test_maintenance_coordination', 'test_maintenance_actor_hold')
CONTEXT = '''import types,sys
for name,source in bundle.items():
 module=types.ModuleType(name);module.__file__='/ram/'+name+'.py';sys.modules[name]=module
 exec(compile(source,module.__file__,'exec'),module.__dict__)
actors=sys.modules['maintenance_actor_hold'];hops=sys.modules['maintenance_hop_journal']
package=sys.modules['maintenance_package_dispatch'];API=sys.modules['test_maintenance_coordination'].API
Systemd=sys.modules['test_maintenance_actor_hold'].Systemd
root=pathlib.Path('/var/lib/qualification-package-dispatch')
def identity():
 return {'machine':pathlib.Path('/etc/machine-id').read_text().strip(),
  'root_uuid':native('findmnt','-n','-o','UUID','/').strip()}
def connect():
 value=json.loads((root/'context.json').read_bytes());api=API()
 for key in ('ds','nodes','pods'):setattr(api,key,value['api'][key])
 owner=value['owner'];controller=api.controller()
 hold=actors.Hold(Systemd(),identity,lambda token:controller.resume(token)==owner,root/'state',root/'units')
 return value,hops.Journal(controller,hold,owner['owner'])
def unit_state(owner,step):
 unit=owner['owner']+'-'+step.replace('_','-')+'.service'
 fields=('LoadState','ActiveState','SubState','Result','ExecMainCode','ExecMainStatus','InvocationID','NRestarts')
 raw=native('systemctl','show',unit,*('--property='+field for field in fields))
 result=dict(line.split('=',1)for line in raw.splitlines())
 assert set(result)==set(fields)
 return result
def prerequisites(value,step):
 assert pathlib.Path('/sys/fs/selinux/enforce').read_text().strip()=='1'
 config=pathlib.Path('/etc/dnf/dnf.conf').read_bytes()
 assert b'gpgcheck=True' in config and b'localpkg_gpgcheck=True' in config
 for timer in ('dnf-automatic.timer','dnf5-automatic.timer'):
  result=subprocess.run(['systemctl','is-enabled',timer],capture_output=True)
  assert result.returncode==1 and result.stdout.strip()==b'masked'
 if step in ('download_release','offline_transaction'):
  native('rpm','-q','--whatprovides','dnf-plugin-system-upgrade')
 return {'identity':identity(),'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
  'release':int(native('rpm','-E','%fedora').strip()),'config_sha256':hashlib.sha256(config).hexdigest(),
  'owner':value['owner'],'phase':step,'enforcing':True,'native_timer_masks':True}
'''


def service_complete(fields):
    required = {'LoadState', 'ActiveState', 'SubState', 'Result', 'ExecMainCode',
                'ExecMainStatus', 'InvocationID', 'NRestarts'}
    if (set(fields) != required or fields['LoadState'] != 'loaded' or fields['NRestarts'] != '0' or
            not re.fullmatch('[0-9a-f]{32}', fields['InvocationID']) or fields['InvocationID'] == '0' * 32 or
            fields['ActiveState'] not in ('active', 'activating', 'deactivating', 'inactive', 'failed')):
        raise RuntimeError('native package unit identity/restart evidence refused')
    complete = (fields['ActiveState'] == 'active' and fields['SubState'] == 'exited' and
                fields['Result'] == 'success' and fields['ExecMainCode'] == '1' and
                fields['ExecMainStatus'] == '0')
    if (fields['ActiveState'] in ('failed', 'inactive') or
            fields['ActiveState'] == 'active' and fields['SubState'] == 'exited' and not complete):
        raise RuntimeError('native package unit failed: ' + json.dumps(fields, sort_keys=True))
    return complete


class Qualification(upgrade.Qualification):
    def __init__(self, args):
        if not re.fullmatch('[0-9a-f]{40}', args.revision):
            raise RuntimeError('exact published revision required')
        super().__init__(args)

    def package_guest(self, body, expected=0):
        bundle = {name: Path(__file__).with_name(name + '.py').read_text() for name in MODULES}
        script = upgrade.GUEST + 'bundle=' + repr(bundle) + '\n' + CONTEXT + body
        output = self.command(self.ssh + ['sudo python3 -B -'], data=script.encode(), expected=expected)
        return json.loads(output) if expected == 0 else output

    def initialize(self):
        return self.package_guest('revision=' + repr(self.args.revision) + '\n' + '''
root.mkdir(mode=0o700);(root/'units').mkdir(mode=0o700)
api=API();hostname=socket.gethostname()
api.nodes[0]['metadata']['name']=hostname;api.pods[0]['spec']['nodeName']=hostname
controller=api.controller();owner=controller.acquire(hostname,39,41,revision)
hold=actors.Hold(Systemd(),identity,lambda token:controller.resume(token)==owner,root/'state',root/'units')
hold.acquire(owner['owner'],identity(),revision)
journal=hops.Journal(controller,hold,owner['owner']);journal.initialize()
value={'owner':owner,'api':{key:getattr(api,key)for key in ('ds','nodes','pods')}}
path=root/'context.json';path.write_bytes(hops.canonical(value));path.chmod(0o600)
for step in ('cordon','drain'):
 evidence={'synthetic_api_actor_and_scheduling_only':True,'step':step}
 checksum=hops.digest(hops.canonical(evidence))
 state=journal.begin(step,checksum,checksum,lambda *_:True)
 journal.accept(state['pending']['sha256'],checksum,lambda *_:True)
print(json.dumps({'journal':journal.inspect(),'synthetic_api_actor_and_scheduling_only':True}))
''')

    def dispatch(self, step, lose_response=False):
        result = self.package_guest('step=' + repr(step) + '\nlose=' + repr(lose_response) + '\n' + '''
value,journal=connect();gates=prerequisites(value,step);digest=hops.digest(hops.canonical(gates))
inputs=hops.digest(hops.canonical(package.command(value['owner'],step)))
result=package.dispatch(journal,step,inputs,digest,
 lambda selected,checksum:selected==step and checksum==digest and prerequisites(value,step)==gates)
if lose:os._exit(73)
print(json.dumps(result))
''', expected=73 if lose_response else 0)
        return result

    def refuse_replay(self, step):
        return self.package_guest('step=' + repr(step) + '\n' + '''
value,journal=connect();before=journal.inspect();unit=unit_state(value['owner'],step)
assert before['pending']['step']==step
try:
 package.dispatch(journal,step,hops.digest(hops.canonical(package.command(value['owner'],step))),
  '0'*64,lambda *_:False)
except RuntimeError as error:
 assert str(error)=='pending or out-of-order hop; observe, never replay'
else:raise RuntimeError('native pending package operation was replayed')
assert journal.inspect()==before
assert unit_state(value['owner'],step)['InvocationID']==unit['InvocationID']
print(json.dumps({'pending':before,'unit':unit,'redispatch_refused':True}))
''')

    def wait_unit(self, step):
        invocation = None
        while True:
            observation = self.package_guest('step=' + repr(step) + '\n' + '''
value,journal=connect();assert journal.inspect()['pending']['step']==step
fields=unit_state(value['owner'],step)
failure=None
if fields['ActiveState'] in ('failed','inactive'):
 failure=native('journalctl','--no-pager','-o','cat','-n','80','-u',
  value['owner']['owner']+'-'+step.replace('_','-')+'.service')[-16000:]
print(json.dumps({'unit':fields,'failure_journal':failure}))
''')
            fields = observation['unit']
            if observation['failure_journal'] is not None:
                self.persist('native-package-unit-failure', phase=step, observation=observation)
            if invocation is None:
                invocation = fields['InvocationID']
            if fields['InvocationID'] != invocation:
                raise RuntimeError('native package unit invocation changed')
            if service_complete(fields):
                return fields
            time.sleep(5)

    def history(self):
        return self.guest('''
output=native('/usr/bin/dnf-3','history','info','last')
import re
ids=re.findall(r'^Transaction ID\\s*:\\s*(\\d+)\\s*$',output,re.M)
assert len(ids)==1
print(json.dumps({'id':int(ids[0]),'native_history_sha256':hashlib.sha256(output.encode()).hexdigest()}))
''')

    def prepare_plugin(self):
        before = self.history()
        self.command(self.ssh + ['sudo /usr/bin/dnf -y install dnf-plugin-system-upgrade'])
        after = self.history()
        if after['id'] not in (before['id'], before['id'] + 1):
            raise RuntimeError('plugin preparation changed native history ambiguously')
        provider = self.guest('''
provider=native('rpm','-q','--whatprovides','dnf-plugin-system-upgrade').strip()
assert provider and len(provider.splitlines())==1
assert not native('rpm','-V',provider)
print(json.dumps({'installed_provider':provider,'native_rpm_verification_clean':True}))
''')
        changed = after['id'] != before['id']
        self.persist('separate-native-plugin-preparation', history_before=before, history_after=after,
                     provider=provider, new_transaction=changed,
                     signatures=self.signatures() if changed else None,
                     no_op_provenance='verified pinned cloud image' if not changed else None)

    def accept(self, step, receipt, release, unit=None):
        checksum = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return self.package_guest('step=' + repr(step) + '\nchecksum=' + repr(checksum) +
                                  '\nrelease=' + repr(release) + '\nunit=' + repr(unit) + '\n' + '''
value,journal=connect();pending=journal.inspect()['pending'];assert pending['step']==step
before=identity()
def observed(selected,receipt):
 assert selected==step and receipt==checksum and identity()==before
 assert native('rpm','-E','%fedora').strip()==str(release)
 assert pathlib.Path('/sys/fs/selinux/enforce').read_text().strip()=='1'
 if unit is not None:assert unit_state(value['owner'],step)==unit
 return True
print(json.dumps(journal.accept(pending['sha256'],checksum,observed)))
''')

    def run(self):
        self.prepare();self.wait_ready()
        configured = self.configure()
        corpus = self.corpus(create=True)
        initial = self.state(39, corpus)
        self.persist('initial-native-fedora39', result=initial, configured=configured)
        self.repositories(39)
        self.persist('synthetic-owner-and-journal-initialized', result=self.initialize())
        before_history = self.history()
        self.dispatch('prepare_source', lose_response=True)
        self.persist('actual-controller-exit73-after-package-dispatch', result=self.refuse_replay('prepare_source'))
        unit = self.wait_unit('prepare_source')
        history = self.history()
        if history['id'] != before_history['id'] + 1:
            raise RuntimeError('source preparation did not produce exactly one new native DNF transaction')
        receipt = {'unit': unit, 'history_before': before_history, 'history_after': history,
                   'state': self.state(39, corpus), 'signatures': self.signatures()}
        self.persist('native-source-transaction-accepted', receipt=receipt,
                     journal=self.accept('prepare_source', receipt, 39, unit))
        self.checkpoint('release39')
        updated_source = self.state(39, corpus)
        if any(updated_source['identity'][key] != initial['identity'][key]
               for key in ('machine', 'root_uuid', 'architecture')):
            raise RuntimeError('source39 checkpoint changed stable VM identity')
        self.persist('native-updated-source-reboot', result=updated_source)
        self.prepare_plugin()
        history = self.history()
        self.repositories(41)
        self.dispatch('download_release')
        unit = self.wait_unit('download_release')
        unchanged = self.history()
        if unchanged['id'] != history['id']:
            raise RuntimeError('release download changed installed-package history')
        receipt = {'unit': unit, 'history': unchanged, 'state': self.state(39, corpus),
                   'signatures': self.signatures()}
        self.persist('native-download-accepted', receipt=receipt,
                     journal=self.accept('download_release', receipt, 39, unit))
        before = self.identity()
        try:
            self.dispatch('offline_transaction')
        except RuntimeError as error:
            output = (self.root / (str(self.number) + '.log')).read_bytes()
            if not upgrade.reboot_probe_disconnect(error, self.number, output):
                raise
            self.persist('offline-dispatch-response-lost', command=self.number,
                         output_sha256=hashlib.sha256(output).hexdigest())
        while True:
            try:
                self.wait_ready()
                current = self.guest('''
print(json.dumps({'release':int(native('rpm','-E','%fedora').strip()),
 'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'offline_pending':pathlib.Path('/system-update').is_symlink()}))
''')
                if current['boot'] == before['boot']:
                    fields = self.package_guest('''
value,journal=connect();assert journal.inspect()['pending']['step']=='offline_transaction'
print(json.dumps(unit_state(value['owner'],'offline_transaction')))
''')
                    service_complete(fields)
            except RuntimeError as error:
                output = (self.root / (str(self.number) + '.log')).read_bytes()
                if not upgrade.reboot_probe_disconnect(error, self.number, output):
                    raise
                self.persist('offline-read-only-probe-disconnected', command=self.number,
                             output_sha256=hashlib.sha256(output).hexdigest())
                time.sleep(5)
                continue
            if current['boot'] != before['boot'] and not current['offline_pending']:
                if current['release'] != 41:
                    raise RuntimeError('offline package transaction returned without Fedora41')
                break
            time.sleep(5)
        final = self.state(41, corpus)
        if any(final['identity'][key] != before[key] for key in ('machine', 'root_uuid', 'architecture')):
            raise RuntimeError('native package integration changed stable VM identity')
        history_after = self.history()
        if history_after['id'] != history['id'] + 1:
            raise RuntimeError('offline release did not produce exactly one new native DNF transaction')
        receipt = {'state': final, 'history': history_after, 'before': before,
                   'signatures': self.signatures(), 'transient_unit_not_required_after_reboot': True}
        journal = self.accept('offline_transaction', receipt, 41)
        if self.server.errors:
            raise RuntimeError('verified package repository transport reported a failure')
        self.persist('native-offline-transaction-accepted', receipt=receipt, journal=journal)
        self.result.update(accepted=True, actual_package_dispatch_and_exit_resume=True,
                           api_actor_and_scheduling_are_synthetic=True, source_supported_today=False,
                           production_or_full_combined_orchestration_acceptance=False)
        (self.root / 'upgrade-result.json').write_text(json.dumps(self.result, indent=2))
        return self.result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'keys-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())
    def cancel(_number, _frame):
        raise InterruptedError('owned package integration cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        print(json.dumps(qualification.run()), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
