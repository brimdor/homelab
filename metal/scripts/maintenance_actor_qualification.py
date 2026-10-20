#!/usr/bin/env python3
"""Qualify persistent actor holds in the owned offline Fedora44 AMD64 fixture."""

import argparse
import json
import os
from pathlib import Path
import signal

import fedora_target_qualification as fedora


TOKEN = 'homelab-maintenance-103-11111111-1111-4111-8111-111111111111'
REVISION = 'a' * 40


class Qualification(fedora.Qualification):
    def guest(self, body):
        source = Path(__file__).with_name('maintenance_actor_hold.py').read_text()
        header = """import json,pathlib,subprocess,types,time
assert subprocess.check_output(['hostname']).strip()==b'qualification-fedora44'
assert 'VERSION_ID=44' in pathlib.Path('/etc/os-release').read_text()
m=types.ModuleType('maintenance_actor_hold');exec(SOURCE,m.__dict__)
token=TOKEN
def identity():
 return {'machine':pathlib.Path('/etc/machine-id').read_text().strip(),
         'root_uuid':subprocess.check_output(['findmnt','-n','-o','UUID','/']).decode().strip()}
def timer(name):
 return subprocess.check_output(['systemctl','show',name,'-p','UnitFileState','-p','ActiveState']).decode()
def counter():
 p=m.STATE/'fixture-executed';return p.stat().st_mtime_ns if p.exists() else None
owner=m.Hold(m.Systemd(),identity,lambda value:value==token)
""".replace('SOURCE', repr(source)).replace('TOKEN', repr(TOKEN))
        return json.loads(self.command(self.ssh + ['sudo python3 -'], data=(header + body).encode()))

    def environment(self):
        return {**os.environ, 'ANSIBLE_CONFIG': str(Path('metal/maintenance/ansible.cfg').resolve()),
                'ANSIBLE_COLLECTIONS_PATH': str(self.args.collection_dir),
                'ANSIBLE_HOST_KEY_CHECKING': 'True', 'ANSIBLE_LOCAL_TEMP': str(self.root / 'ansible-tmp'),
                'ANSIBLE_SSH_ARGS': '-o ControlMaster=no -o ControlPersist=no'}

    def play(self, path, expected=0):
        return self.command([str(self.args.ansible_playbook), '-i', str(self.root / 'inventory.yml'),
                             str(path), '--limit', 'fixture'], env=self.environment(), expected=expected)

    def run(self):
        primitive = super().run()
        before = self.identity()
        setup = self.guest("""
assert not owner.marker.exists()
unitroot=m.UNITS
for name in m.SERVICES[:-1]:
 p=unitroot/name;assert not p.exists()
 p.write_text('[Unit]\\nDescription=Synthetic automatic updater for maintenance103 qualification\\n'
              '[Service]\\nType=oneshot\\nExecStart=/usr/bin/touch /var/lib/homelab-maintenance/fixture-executed\\n')
p=unitroot/'dnf-automatic.timer';assert not p.exists()
p.write_text('[Unit]\\nDescription=Synthetic automatic timer\\n[Timer]\\nOnActiveSec=2s\\n'
             'Unit=dnf-automatic.service\\n[Install]\\nWantedBy=timers.target\\n')
subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
subprocess.run(['systemctl','enable','--now','dnf-automatic.timer'],check=True,capture_output=True)
timers={n:timer(n)for n in ('dnf-automatic.timer','dnf5-automatic.timer')}
held=owner.acquire(token,identity(),REVISION)
assert timers=={n:timer(n)for n in timers}
original=counter()
for service in m.SERVICES:
 subprocess.run(['systemctl','start',service],check=True,capture_output=True)
 assert counter()==original
owner.systemd.idle(owner.marker)
old=int(subprocess.check_output(['systemctl','show','dnf-automatic.timer','-p','LastTriggerUSecMonotonic','--value']).strip()or b'0')
subprocess.run(['systemctl','restart','dnf-automatic.timer'],check=True,capture_output=True)
deadline=time.monotonic()+180
while True:
 value=int(subprocess.check_output(['systemctl','show','dnf-automatic.timer','-p','LastTriggerUSecMonotonic','--value']).strip()or b'0')
 if value>old:break
 if time.monotonic()>deadline:raise RuntimeError('owned two-second timer did not trigger')
 time.sleep(.25)
owner.systemd.idle(owner.marker);assert counter()==original
baseline={'counter':original,'timers':{n:timer(n)for n in timers},'journal':owner.marker.read_text()}
(m.STATE/'fixture.json').write_text(json.dumps(baseline))
print(json.dumps({'held':held,'timers_before_after_equal':True,'manual_and_timer_starts_excluded':True,
                  'native_dnf5_service_excluded':True,'counter_unchanged':True,'timer_triggered':True}))
""".replace('REVISION', repr(REVISION)))
        guard = self.root / 'guard.yml'
        guard.write_text('- hosts: fixture\n  gather_facts: false\n  become: true\n  tasks:\n'
                         '    - ansible.builtin.import_tasks: ' +
                         str(Path('metal/tasks/maintenance-guard.yml').resolve()) + '\n')
        refusal = self.play(guard, expected=2)
        if b'Maintenance ownership exists' not in refusal:
            raise RuntimeError('legacy entry guard did not produce the reviewed refusal')
        reboot = self.root / 'actor-reboot.yml'
        reboot.write_text('- hosts: fixture\n  gather_facts: false\n  become: true\n  tasks:\n'
                          '    - ansible.builtin.reboot:\n        reboot_timeout: 1200\n'
                          '        connect_timeout: 10\n        post_reboot_delay: 0\n')
        self.play(reboot)
        after = self.identity()
        if before['boot'] == after['boot'] or any(before[k] != after[k] for k in ('machine', 'root_uuid', 'architecture', 'kernel')):
            raise RuntimeError('actor hold reboot changed host identity or did not reboot')
        resumed = self.guest("""
baseline=json.loads((m.STATE/'fixture.json').read_text())
assert owner.marker.read_text()==baseline['journal']
held=owner.resume(token)
assert counter()==baseline['counter']
assert {n:timer(n)for n in baseline['timers']}==baseline['timers']
for service in m.SERVICES:
 subprocess.run(['systemctl','start',service],check=True,capture_output=True)
assert counter()==baseline['counter']
try:owner.release(token,lambda _v:False)
except RuntimeError as error:assert 'release gates' in str(error)
else:raise RuntimeError('failed release was accepted')
assert owner.marker.read_text()==baseline['journal']
owner.release(token,lambda _v:True)
subprocess.run(['systemctl','start','dnf-automatic.service'],check=True,capture_output=True)
assert counter()!=baseline['counter'] and not owner.marker.exists()
assert {n:timer(n)for n in baseline['timers']}==baseline['timers']
print(json.dumps({'resumed':held,'reboot_persistent':True,'failed_release_retained':True,
                  'native_dnf5_service_still_excluded_while_held':True,
                  'explicit_fixture_release_restored_synthetic_service':True,
                  'timer_enablement_and_activity_preserved':True,'guards_remain_installed':True}))
""")
        self.play(guard)
        return {'automatic_actor_qualification': True, 'primitive': primitive, 'setup': setup,
                'after_reboot': resumed, 'before': before, 'after': after,
                'legacy_entry_guard_refused_while_held_and_passed_after_release': True,
                'global_owner_callback_synthetic': True, 'dnf4_services_synthetic': True,
                'full_controller_and_release_transactions_unqualified': True, 'production_changes': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir', 'automatic-rpm'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    args = parser.parse_args()
    qualification = Qualification(args)

    def cancel(_number, _frame):
        raise RuntimeError('owned actor qualification cancelled')

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'actor-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
