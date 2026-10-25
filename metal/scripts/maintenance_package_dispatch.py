"""Dispatch one reviewed package phase; an uncertain intent is never replayed."""

import os
from pathlib import Path
import re
import socket
import subprocess

import maintenance_actor_hold as actor
import maintenance_hop_journal as hops


def command(owner, step):
    source, target = owner['source'], owner['target']
    actor.require(type(source) is int and type(target) is int and
                  (source, target) in ((39, 41), (41, 43), (43, 44)), 'foreign package release hop')
    dnf = '/usr/bin/dnf' if source == 39 else '/usr/bin/dnf5'
    phases = {
        'prepare_source': [dnf, '-y', '--refresh', 'upgrade'],
        'download_release': [dnf, '-y', 'system-upgrade', 'download', '--releasever=' + str(target)],
        'offline_transaction': [dnf, '-y', 'system-upgrade' if source == 39 else 'offline', 'reboot'],
    }
    actor.require(step in phases, 'foreign package phase')
    actor.require(isinstance(owner['owner'], str) and re.fullmatch(
        r'homelab-maintenance-103-[0-9a-f-]{36}', owner['owner']), 'invalid package owner')
    unit = owner['owner'] + '-' + step.replace('_', '-')
    return ['/usr/bin/systemd-run', '--unit=' + unit, '--service-type=exec', '--remain-after-exit',
            '--expand-environment=no', '--property=Restart=no', '--working-directory=/',
            '--setenv=LANG=C.UTF-8', '--'] + phases[step]


def require_native(owner):
    release = Path('/etc/os-release').read_text().splitlines()
    actor.require(os.geteuid() == 0 and socket.gethostname() == owner['node'] and
                  'ID=fedora' in release and 'VERSION_ID=' + str(owner['source']) in release,
                  'package source host/release/root differs')


def dispatch(journal, step, reviewed_inputs_sha256, prerequisites_sha256, verify_prerequisites):
    before = journal.inspect()
    owner = before['owners']['global']
    argv = command(owner, step)
    actor.require(hops.digest(hops.canonical(argv)) == reviewed_inputs_sha256,
                  'package command differs from reviewed inputs')
    require_native(owner)
    pending = journal.begin(step, reviewed_inputs_sha256, prerequisites_sha256, verify_prerequisites)
    with journal.hold.serialized():
        actor.require(journal.read() == pending, 'package intent changed before dispatch')
        journal.owners(idle=True)
        require_native(owner)
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, cwd='/',
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}, check=False)
        actor.require(result.returncode == 0, 'package dispatch uncertain; observe pending intent, never retry')
        return {'queued': True, 'unit': owner['owner'] + '-' + step.replace('_', '-') + '.service',
                'intent': pending['pending'], 'accepted': False}
