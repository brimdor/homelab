"""Retain signed multimedia coverage without changing Arcanine's NVIDIA provider."""

import hashlib
import os
from pathlib import Path
import stat

from maintenance_actor_hold import exclusive_file, require, safe
from maintenance_hop_journal import canonical, private_directory
from maintenance_node_drain import hashed, private_json


OWNER = 'homelab-maintenance-103-62c5a6b2-a570-4a28-9dcb-6e14c705f40d'
PENDING = '380a6eeab52c79d82ddb599e52548e625932f2bcaf96cc48740e754aa3e429eb'
BOOT = 'ed2b710a-42e0-4653-9fb2-6d0f450c4841'
FAILURE = '8c7dfcd7b48f7f6d859de7a5b12a0adb2b2d40fa7a2ccb057c116198c7605222'
INVOCATION = 'b57d949613414e5f9df2000f34ebb75c'
KEYS = {
    'free': '10fc0a3e1a0307e8088357a31a9c5e4e3d9f9e0b01db2b03b5790d949a47f3b3',
    'nonfree': '7ac65a8dfeced70c8c335862b5f0696d57abac378deda34c4af78cd2220e3de6',
}


def configure(directory, release, native, key_directory=Path('/etc/pki/rpm-gpg')):
    require(release in (41, 43, 44), 'unreviewed RPM Fusion release')
    private_directory(directory)
    content = ''
    for component, suffix in (('free', ''), ('free', '-updates-released'), ('nonfree', '')):
        key = key_directory / ('RPM-GPG-KEY-rpmfusion-' + component + '-fedora-2020')
        safe(key)
        info = key.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                info.st_nlink == 1 and not info.st_mode & 0o022 and
                hashlib.sha256(key.read_bytes()).hexdigest() == KEYS[component],
                'installed RPM Fusion trust anchor differs')
        native('rpmkeys', '--import', str(key))
        identifier = component + '-fedora' + suffix + '-' + str(release)
        content += ('[maintenance-rpmfusion-' + identifier + ']\nname=Issue 103 signed RPM Fusion ' +
                    identifier + '\nmetalink=https://mirrors.rpmfusion.org/metalink?repo=' +
                    identifier + '&arch=x86_64&protocol=https\nenabled=1\ngpgcheck=1\n' +
                    'sslverify=1\nskip_if_unavailable=0\ngpgkey=file://' + str(key) +
                    '\nexclude=*.i686\n')
        if component == 'nonfree':
            content += 'includepkgs=rpmfusion-nonfree-release\n'
    path = directory / 'rpmfusion.repo'
    safe(path)
    if not path.exists():
        exclusive_file(path, content.encode(), 0o600)
    require(path.read_bytes() == content.encode(), 'retained RPM Fusion repository differs')
    return {'release': release, 'repos_sha256': hashlib.sha256(content.encode()).hexdigest(),
            'existing_trust_sha256': KEYS, 'nonfree_driver_packages_excluded': True}


def status(native, unit):
    fields = ('LoadState', 'ActiveState', 'Result', 'ExecMainStatus', 'MainPID', 'ControlPID',
              'InvocationID', 'ExecStart')
    return dict(line.split('=', 1) for line in native(
        'systemctl', 'show', unit, *[arg for field in fields for arg in ('-p', field)]).splitlines())


def installed(native):
    rows = native('rpm', '-qa', '--qf', '%{NAME} %{EPOCHNUM} %{VERSION} %{RELEASE} %{ARCH}\n')
    return hashed(sorted(row for row in rows.splitlines() if not row.startswith('gpg-pubkey ')))


def failed_download(owner, state, native, directory):
    require(owner['owner'] == OWNER and owner['node'] == 'arcanine' and
            owner['node_uid'] == '88aa2572-09df-40b9-8a00-960e9682917c' and
            owner['source'] == 39 and owner['target'] == 41, 'download repair owner differs')
    require(state['completed'] == ['cordon', 'drain', 'prepare_source'] and
            state['pending']['sha256'] == PENDING and state['pending']['sequence'] == 7 and
            state['pending']['step'] == 'download_release', 'download repair intent differs')
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT and
            native('rpm', '-E', '%fedora') == '39', 'download repair source boot differs')
    require(not os.path.lexists('/system-update') and
            not list(Path('/var/lib/dnf/system-upgrade').rglob('*.rpm')),
            'offline work exists; do not retry download')
    unit = OWNER + '-download-release.service'
    observed = status(native, unit)
    expected = {'LoadState': 'loaded', 'ActiveState': 'failed', 'Result': 'exit-code',
                'ExecMainStatus': '1', 'MainPID': '0', 'ControlPID': '0', 'InvocationID': INVOCATION}
    require(all(observed.get(k) == v for k, v in expected.items()), 'original failed unit differs')
    command = ('/usr/bin/dnf --setopt=reposdir=' + str(directory) +
               ' --setopt=gpgcheck=True --setopt=localpkg_gpgcheck=True -y system-upgrade download --releasever=41')
    require('argv[]=' + command + ' ;' in observed['ExecStart'], 'download unit command differs')
    failure = native('journalctl', '--no-pager', '-u', unit, '-n', '30', '-o', 'cat')
    require(hashlib.sha256(failure.encode()).hexdigest() == FAILURE, 'unreviewed download failure')
    return {'pending': state['pending'], 'boot': BOOT, 'status': observed, 'failure_log': failure,
            'installed_sha256': installed(native)}


def repair(journal, native, evidence):
    """Retry only a proven pre-transaction failure; uncertain dispatch remains observe-only."""
    root = journal.hold.state
    directory = root / ('fedora-repositories-41-' + OWNER)
    before_path = root / ('rpmfusion-download-before-' + OWNER + '.json')
    dispatch_path = root / ('rpmfusion-download-dispatch-' + OWNER + '.json')
    with journal.hold.serialized():
        owner = journal.owners(idle=True)['global']
        require(owner['owner'] == OWNER, 'foreign RPM Fusion recovery owner')
        if dispatch_path.exists():
            private_json(dispatch_path)
            return {'observe_only': True, 'dispatch_sha256': hashed(private_json(dispatch_path))}
        state = journal.read()
        before = failed_download(owner, state, native, directory)
        if not before_path.exists():
            exclusive_file(before_path, canonical(before), 0o600)
        require(private_json(before_path) == before, 'original download failure evidence changed')
        coverage = configure(directory, 41, native)
        require(installed(native) == before['installed_sha256'], 'repository preparation changed packages')
        value = evidence()
        require(journal.read() == state and failed_download(owner, state, native, directory) == before,
                'failed download changed during preparation')
        journal.owners(idle=True)
        require(evidence() == value, 'download retry prerequisites changed')
        record = {'version': 1, 'before_sha256': hashed(before), 'pending': state['pending'],
                  'repositories': repository_hashes(directory), 'coverage': coverage, 'prerequisites': value}
        exclusive_file(dispatch_path, canonical(record), 0o600)
        native('systemctl', 'start', OWNER + '-download-release.service')
    return {'dispatched_recovery': True, 'original_pending_preserved': True, 'dispatch_sha256': hashed(record)}


def repository_hashes(directory):
    result = {}
    private_directory(directory)
    for name in ('maintenance.repo', 'nvidia.repo', 'rpmfusion.repo'):
        path = directory / name
        safe(path)
        info = path.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600, 'unsafe private repository')
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def accepted(journal, native):
    path = journal.hold.state / ('rpmfusion-download-dispatch-' + journal.token + '.json')
    if not path.exists():
        return None
    record = private_json(path)
    before = private_json(journal.hold.state / ('rpmfusion-download-before-' + journal.token + '.json'))
    require(journal.token == OWNER and record['before_sha256'] == hashed(before) and
            record['pending'] == journal.read()['pending'], 'download recovery chain differs')
    directory = journal.hold.state / ('fedora-repositories-41-' + OWNER)
    require(repository_hashes(directory) == record['repositories'] and
            installed(native) == before['installed_sha256'], 'download recovery inputs changed')
    current = status(native, OWNER + '-download-release.service')
    require(current['InvocationID'] != INVOCATION and len(current['InvocationID']) == 32,
            'download retry invocation absent')
    return {'before_sha256': hashed(before), 'dispatch_sha256': hashed(record),
            'invocation_id': current['InvocationID'], 'original_failed_download_retained': True}
