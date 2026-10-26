"""Native final-release host work under the existing production owner and hold."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
import urllib.request


POLICY = ('https://github.com/k3s-io/k3s-selinux/releases/download/v1.6.latest.1/k3s-selinux-1.6-1.el9.noarch.rpm',
          '1115a1223b0db998c7977c879f2a3a6f07a0c63240f68f6e3b665a7ae27c38f7')
SIGNING_FINGERPRINT = 'c8cff216455126e9b9c918be925ea29ae257814a'


def execute(operation, journal, native, identity, recovery):
    actors = journal.hold
    owner = journal.owners()['global']
    root = actors.state
    assert owner['source'] == 43 and owner['target'] == 44
    assert native('rpm', '-E', '%fedora') == '44'
    assert recovery['source_release'] == 44 and recovery['identity'] == identity()
    state = journal.inspect()
    assert not state['pending'] and state['completed'] == [
        'cordon', 'drain', 'prepare_source', 'download_release', 'offline_transaction',
        'trusted_reconnect', 'verify_infrastructure']
    token = owner['owner']
    unit = token + '-host-policy.service'
    intent = root / ('host-policy-' + token + '.json')
    if operation == 'observe-security-policy':
        record = json.loads(intent.read_bytes())
        assert record['owner'] == token and record['identity'] == identity()
        raw = native('systemctl', 'show', unit, '-p', 'LoadState', '-p', 'ActiveState',
                     '-p', 'Result', '-p', 'ExecMainStatus', '-p', 'MainPID', '-p', 'ControlPID')
        fields = dict(line.split('=', 1) for line in raw.splitlines())
        assert fields['LoadState'] == 'loaded', 'uncertain policy dispatch; never replay'
        result = {'unit': unit, 'status': fields, 'accepted': False}
        if fields['MainPID'] == fields['ControlPID'] == '0':
            assert fields['ActiveState'] == 'active' and fields['Result'] == 'success' and fields['ExecMainStatus'] == '0', native('journalctl', '-u', unit, '-n', '20', '--no-pager', '-o', 'cat')
            assert native('rpm', '-q', 'k3s-selinux', '--qf', '%{VERSION}-%{RELEASE}.%{ARCH}') == '1.6-1.el9.noarch'
            native('rpm', '-q', 'microcode_ctl')
            native('rpm', '-V', '--noghost', 'k3s-selinux', 'container-selinux')
            assert any(line.split()[:2] == ['200', 'k3s'] for line in native('semodule', '--list=full').splitlines())
            result['accepted'] = True
            path = root / ('host-policy-accepted-' + token + '.json')
            if not path.exists():
                import maintenance_actor_hold as hold
                hold.exclusive_file(path, json.dumps(result, sort_keys=True).encode(), 0o600)
        return result
    if operation == 'security-relabel':
        return relabel(journal, native, identity, recovery)
    assert operation == 'security-policy'
    assert not intent.exists(), 'policy intent exists; observe, never replay'
    import maintenance_actor_hold as hold
    with actors.serialized():
        journal.owners(idle=True)
        assets = root / ('host-security-assets-' + token)
        assets.mkdir(mode=0o700, exist_ok=True)
        for name, (url, digest) in (('policy.rpm', POLICY),):
            path = assets / name
            if not path.exists():
                with urllib.request.urlopen(url, timeout=60) as response:
                    content = response.read(16 * 1024 * 1024 + 1)
                assert hashlib.sha256(content).hexdigest() == digest, 'vendor artifact changed'
                hold.exclusive_file(path, content, 0o600)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        signature = native('rpmkeys', '--checksig', '--verbose', str(assets / 'policy.rpm'))
        assert ('key fingerprint: ' + SIGNING_FINGERPRINT + ': ok') in signature.lower() and not any(word in signature for word in ('NOKEY', 'NOT OK', 'BAD'))
        repos = root / ('fedora-repositories-44-' + token)
        assert (repos / 'maintenance.repo').is_file()
        command = ['systemd-run', '--unit=' + unit, '--property=Type=exec',
                   '--property=RemainAfterExit=yes', '--property=Restart=no', '--setenv=LANG=C.UTF-8',
                   '/usr/bin/dnf5', '--setopt=reposdir=' + str(repos), '--setopt=gpgcheck=True',
                   '--setopt=localpkg_gpgcheck=True', '--assumeyes', 'install',
                   str(assets / 'policy.rpm'), 'microcode_ctl']
        record = {'owner': token, 'identity': identity(), 'command': command,
                  'recovery_sha256': recovery['sha256']}
        hold.exclusive_file(intent, json.dumps(record, sort_keys=True).encode(), 0o600)
        native(*command)
    return {'dispatched': True, 'unit': unit, 'intent_sha256': hashlib.sha256(intent.read_bytes()).hexdigest()}


def relabel(journal, native, identity, recovery):
    """One vendor permissive relabel reboot; preserve all volume data and history."""
    import maintenance_actor_hold as hold
    token = journal.token
    root = journal.hold.state
    intent = root / ('host-relabel-' + token + '.json')
    with journal.hold.serialized():
        journal.owners(idle=True)
        assert not intent.exists(), 'relabel intent exists; observe boot, never replay'
        accepted = json.loads((root / ('host-policy-accepted-' + token + '.json')).read_bytes())
        assert accepted['accepted'] is True and native('getenforce') == 'Disabled'
        expected = {
            '/usr/lib/systemd/system-generators/selinux-autorelabel-generator.sh': '6f899df4b3b60e5fe39e85591e70bade030ec25eeac5e826fd44aa4d34095f43',
            '/usr/lib/systemd/system/selinux-autorelabel.target': 'c340133060c163caf9e22f0624306bd528768e89b3d5faf7285f23d2bada9485',
            '/usr/lib/systemd/system/selinux-autorelabel.service': '9b39bc7e3fb46bc916b23933ad742f11e58401b14755d3a5c991ce5718669586',
            '/usr/libexec/selinux/selinux-autorelabel': '7510982b425be80a45d4186a57ad1b99471a2a7f58a9e311d7ecc6f056d0f154',
            '/etc/fstab': 'b03fa47b7c80bdf71de0b1ff8201da20e194af73d23f6fa74c5c13fc82ad374f',
        }
        for name, digest in expected.items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, 'native relabel contract changed'
        assert not list(Path('/etc/rancher/k3s/config.yaml.d').glob('*')), 'review configuration overrides first'
        # Native early relabel target starts before K3s; fstab has only root and EFI.
        mounts = json.loads(native('findmnt', '--json', '-o', 'TARGET,SOURCE,FSTYPE'))
        def check_mounts(items):
            for item in items:
                assert item['fstype'] not in ('nfs', 'nfs4', 'ceph', 'fuse.ceph', 'cifs'), 'protected data mount present'
                assert not str(item['source']).startswith('/dev/rbd'), 'active RBD mount present'
                check_mounts(item.get('children', []))
        check_mounts(mounts['filesystems'])
        config = Path('/etc/selinux/config')
        k3s = Path('/etc/rancher/k3s/config.yaml')
        exclude = Path('/etc/selinux/fixfiles_exclude_dirs')
        guard = Path('/etc/systemd/system/k3s.service.d/90-maintenance103-relabel.conf')
        for path in (config, k3s, exclude, guard):
            hold.safe(path)
        assert hashlib.sha256(config.read_bytes()).hexdigest() == '8f7613640d263143e3563c8f1a919358712cc368ad854e6edca3bd75487e9b13'
        assert hashlib.sha256(k3s.read_bytes()).hexdigest() == 'bc77fad02ca8d4251895857d3f04cb4bd510ca6b8074febebc9310fa51d713e8'
        assert not exclude.exists() and not guard.exists(), 'unreviewed existing relabel exclusions or guard'
        record = {'owner': token, 'identity': identity(), 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'recovery_sha256': recovery['sha256'], 'native_contract': expected,
                  'before': {str(p): p.read_text() for p in (config, k3s)}, 'mounts': mounts}
        hold.exclusive_file(intent, json.dumps(record, sort_keys=True).encode(), 0o600)
        def replace(path, content):
            info = path.stat()
            descriptor, temporary = tempfile.mkstemp(prefix='.maintenance103-', dir=path.parent)
            try:
                with os.fdopen(descriptor, 'wb') as target:
                    os.fchmod(target.fileno(), info.st_mode & 0o777)
                    os.fchown(target.fileno(), info.st_uid, info.st_gid)
                    target.write(content.encode()); target.flush(); os.fsync(target.fileno())
                os.replace(temporary, path); hold.fsync_directory(path.parent)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
        replace(config, config.read_text().replace('SELINUX=disabled', 'SELINUX=permissive'))
        replace(k3s, k3s.read_text().rstrip() + '\nselinux: true\n')
        hold.exclusive_file(exclude, b'/mnt\n/media\n/var/lib/kubelet/pods\n/var/lib/kubelet/plugins\n/run\n', 0o644)
        guard.parent.mkdir(mode=0o755, exist_ok=True)
        hold.exclusive_file(guard, b'[Unit]\nConditionPathExists=!/.autorelabel\n', 0o644)
        native('grubby', '--update-kernel=ALL', '--remove-args=selinux enforcing', '--args=enforcing=0')
        boot_entries = native('grubby', '--info=ALL')
        assert 'selinux=0' not in boot_entries and 'enforcing=0' in boot_entries
        native('fixfiles', '-F', 'onboot')
        assert Path('/.autorelabel').read_text().strip() == '-F'
        native('systemctl', 'daemon-reload')
        journal.owners(idle=True)
        reboot = root / ('host-relabel-reboot-' + token + '.json')
        hold.exclusive_file(reboot, json.dumps({'intent_sha256': hashlib.sha256(intent.read_bytes()).hexdigest(),
                            'boot': record['boot']}, sort_keys=True).encode(), 0o600)
        native('systemd-run', '--unit=' + token + '-selinux-relabel', '--on-active=5s',
               '--property=Restart=no', '/usr/bin/systemctl', 'reboot')
    return {'relabel_reboot_dispatched': True, 'owner_retained': True, 'node_stays_cordoned': True}


def facts(native):
    """Project security evidence without returning raw audit records or configuration."""
    import re
    import subprocess
    import tomllib
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    pid = native('systemctl', 'show', 'k3s', '-p', 'MainPID', '--value')
    process = Path('/proc') / pid / 'attr/current'
    containerd = Path('/var/lib/rancher/k3s/agent/etc/containerd/config.toml')
    config = tomllib.loads(containerd.read_text())
    plugins = config.get('plugins', {})
    runtime = plugins.get('io.containerd.cri.v1.runtime', plugins.get('io.containerd.grpc.v1.cri', {}))
    audit = subprocess.run(['ausearch', '--input', '/var/log/audit', '-m', 'AVC,USER_AVC,SELINUX_ERR,USER_SELINUX_ERR',
                            '-ts', 'boot', '--raw'], capture_output=True, text=True)
    assert audit.returncode in (0, 1), 'native audit query failed'
    records = []
    for line in audit.stdout.splitlines():
        if not re.match(r'type=(?:AVC|USER_AVC|SELINUX_ERR|USER_SELINUX_ERR)\b', line):
            continue
        fields = {key: re.search(r'\b' + key + r'=("[^"]*"|[^ ]+)', line)
                  for key in ('type', 'comm', 'scontext', 'tcontext', 'tclass', 'permissive')}
        record = {key: match.group(1).strip('"') for key, match in fields.items() if match}
        access = re.search(r'avc:\s+denied\s+\{([^}]*)\}', line)
        if access:
            record['denied'] = access.group(1).split()
        record['record_sha256'] = hashlib.sha256(line.encode()).hexdigest()
        records.append(record)
    assert audit.returncode == 0 or (not records and audit.stdout.strip() == '<no matches>' and not audit.stderr.strip()), 'audit evidence unavailable'
    return {'boot': boot, 'mode': native('getenforce'),
            'kernel': native('uname', '-r'), 'autorelabel': Path('/.autorelabel').exists(),
            'kernel_overrides': sorted({'selinux=0', 'enforcing=0'}.intersection(Path('/proc/cmdline').read_text().split())),
            'k3s_context': process.read_text().strip() if process.exists() else None,
            'k3s_binary_context': os.getxattr('/usr/local/bin/k3s', 'security.selinux').decode().rstrip(chr(0)),
            'containerd_selinux': runtime.get('enable_selinux'),
            'audit_records': records, 'audit_record_count': len(records),
            'failed_units': native('systemctl', '--failed', '--no-legend', '--plain')}
