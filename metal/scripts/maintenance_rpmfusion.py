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
CODEC_OWNER = 'homelab-maintenance-103-d879ac6d-cd70-4925-a63d-fbd301d5ca3a'
CODEC_KEYS = {
    41: '5cd35342c292578d1a80ecf6c36c4f5a073cf9a1bbb858683882f071c0a529df',
    43: '3d02eeded1380cdd081bc544d082e3e9e0debf09ad0e88c410bebd05ddeb2f58',
    44: '2072ad5c9796d77baff2ff5eb7fe0dfd93f92f6719108c1ee137a73508cdb188',
}


def recovery_profile(kind):
    require(kind in ('rpmfusion', 'openh264'), 'unreviewed download recovery kind')
    if kind == 'rpmfusion':
        return dict(owner=OWNER, pending=PENDING, boot=BOOT, failure=FAILURE,
                    invocation=INVOCATION, source=39, target=41)
    return dict(owner=CODEC_OWNER,
                pending='62b4c27c0658f427f3677026b79a682da1d8891f30369701048e8a42a4f81bf2',
                boot='eb1ea7bc-b7cf-4def-8318-9edcc4f28f6b',
                failure='799d86b2b3435d65ca02bc96a76644c93c16ee77ca1edfa8d0e9dcb692b57ed8',
                invocation='5b965a8893c84396996f59022af34fb7', source=41, target=43)


def configure_openh264(directory, release, native):
    require(release in CODEC_KEYS, 'unreviewed OpenH264 release')
    private_directory(directory)
    key = directory / ('fedora' + str(release) + '.asc'); safe(key)
    info = key.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
            info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600 and
            hashlib.sha256(key.read_bytes()).hexdigest() == CODEC_KEYS[release],
            'retained Fedora OpenH264 signing key differs')
    native('rpmkeys', '--import', str(key))
    content = ('[maintenance-openh264]\nname=Issue 103 signed Fedora OpenH264 ' + str(release) +
               '\nbaseurl=https://codecs.fedoraproject.org/openh264/' + str(release) + '/x86_64/\n' +
               'enabled=1\ngpgcheck=1\nsslverify=1\nskip_if_unavailable=0\ngpgkey=file://' + str(key) +
               '\nincludepkgs=*openh264*\nexclude=*.i686\n')
    path = directory / 'openh264.repo'; safe(path)
    if not path.exists():exclusive_file(path, content.encode(), 0o600)
    require(path.read_bytes() == content.encode(), 'retained OpenH264 repository differs')
    return {'release': release, 'repos_sha256': hashlib.sha256(content.encode()).hexdigest(),
            'key_sha256': CODEC_KEYS[release], 'gpgcheck': True}


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


def failed_download(owner, state, native, directory, kind='rpmfusion'):
    profile = recovery_profile(kind)
    require(owner['owner'] == profile['owner'] and owner['node'] == 'arcanine' and
            owner['node_uid'] == '88aa2572-09df-40b9-8a00-960e9682917c' and
            owner['source'] == profile['source'] and owner['target'] == profile['target'], 'download repair owner differs')
    require(state['completed'] == ['cordon', 'drain', 'prepare_source'] and
            state['pending']['sha256'] == profile['pending'] and state['pending']['sequence'] == 7 and
            state['pending']['step'] == 'download_release', 'download repair intent differs')
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == profile['boot'] and
            native('rpm', '-E', '%fedora') == str(profile['source']), 'download repair source boot differs')
    require(not os.path.lexists('/system-update') and
            not list(Path('/var/lib/dnf/system-upgrade' if profile['source'] == 39 else
                          '/usr/lib/sysimage/libdnf5/offline').rglob('*.rpm')),
            'offline work exists; do not retry download')
    unit = profile['owner'] + '-download-release.service'
    observed = status(native, unit)
    expected = {'LoadState': 'loaded', 'ActiveState': 'failed', 'Result': 'exit-code',
                'ExecMainStatus': '1', 'MainPID': '0', 'ControlPID': '0', 'InvocationID': profile['invocation']}
    require(all(observed.get(k) == v for k, v in expected.items()), 'original failed unit differs')
    command = (('/usr/bin/dnf' if profile['source'] == 39 else '/usr/bin/dnf5') + ' --setopt=reposdir=' + str(directory) +
               ' --setopt=gpgcheck=True --setopt=localpkg_gpgcheck=True -y system-upgrade download --releasever=' + str(profile['target']))
    require('argv[]=' + command + ' ;' in observed['ExecStart'], 'download unit command differs')
    failure = native('journalctl', '--no-pager', '-u', unit, '-n', '30', '-o', 'cat')
    require(hashlib.sha256(failure.encode()).hexdigest() == profile['failure'], 'unreviewed download failure')
    return {'pending': state['pending'], 'boot': profile['boot'], 'status': observed, 'failure_log': failure,
            'installed_sha256': installed(native)}


def repair(journal, native, evidence, kind='rpmfusion'):
    """Retry only a proven pre-transaction failure; uncertain dispatch remains observe-only."""
    profile = recovery_profile(kind)
    root = journal.hold.state
    directory = root / ('fedora-repositories-' + str(profile['target']) + '-' + profile['owner'])
    before_path = root / (kind + '-download-before-' + profile['owner'] + '.json')
    dispatch_path = root / (kind + '-download-dispatch-' + profile['owner'] + '.json')
    with journal.hold.serialized():
        owner = journal.owners(idle=True)['global']
        require(owner['owner'] == profile['owner'], 'foreign signed repository recovery owner')
        if dispatch_path.exists():
            private_json(dispatch_path)
            return {'observe_only': True, 'dispatch_sha256': hashed(private_json(dispatch_path))}
        state = journal.read()
        before = failed_download(owner, state, native, directory, kind)
        if not before_path.exists():
            exclusive_file(before_path, canonical(before), 0o600)
        require(private_json(before_path) == before, 'original download failure evidence changed')
        coverage = (configure if kind == 'rpmfusion' else configure_openh264)(directory, profile['target'], native)
        require(installed(native) == before['installed_sha256'], 'repository preparation changed packages')
        value = evidence()
        require(journal.read() == state and failed_download(owner, state, native, directory, kind) == before,
                'failed download changed during preparation')
        journal.owners(idle=True)
        require(evidence() == value, 'download retry prerequisites changed')
        record = {'version': 1, 'before_sha256': hashed(before), 'pending': state['pending'],
                  'repositories': repository_hashes(directory), 'coverage': coverage, 'prerequisites': value}
        exclusive_file(dispatch_path, canonical(record), 0o600)
        native('systemctl', 'start', profile['owner'] + '-download-release.service')
    return {'dispatched_recovery': True, 'original_pending_preserved': True, 'dispatch_sha256': hashed(record)}


def repository_hashes(directory):
    result = {}
    private_directory(directory)
    names = {'maintenance.repo', 'nvidia.repo', 'rpmfusion.repo'}
    if (directory / 'openh264.repo').exists():names.add('openh264.repo')
    require({p.name for p in directory.glob('*.repo')} == names, 'unexpected private repository')
    for name in sorted(names):
        path = directory / name
        safe(path)
        info = path.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600, 'unsafe private repository')
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def accepted(journal, native):
    kind = 'openh264' if journal.token == CODEC_OWNER else 'rpmfusion'
    profile = recovery_profile(kind)
    path = journal.hold.state / (kind + '-download-dispatch-' + journal.token + '.json')
    if not path.exists():
        return None
    record = private_json(path)
    before = private_json(journal.hold.state / (kind + '-download-before-' + journal.token + '.json'))
    require(journal.token == profile['owner'] and record['before_sha256'] == hashed(before) and
            record['pending'] == journal.read()['pending'], 'download recovery chain differs')
    directory = journal.hold.state / ('fedora-repositories-' + str(profile['target']) + '-' + profile['owner'])
    require(repository_hashes(directory) == record['repositories'] and
            installed(native) == before['installed_sha256'], 'download recovery inputs changed')
    current = status(native, profile['owner'] + '-download-release.service')
    require(current['InvocationID'] != profile['invocation'] and len(current['InvocationID']) == 32,
            'download retry invocation absent')
    return {'before_sha256': hashed(before), 'dispatch_sha256': hashed(record),
            'invocation_id': current['InvocationID'], 'original_failed_download_retained': True}
