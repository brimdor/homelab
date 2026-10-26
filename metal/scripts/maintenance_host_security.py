"""Native final-release host work under the existing production owner and hold."""

import hashlib
import json
import os
import tempfile
import time
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
    if operation in ('security-firmware', 'observe-security-firmware', 'security-firmware-reboot'):
        return firmware(operation, journal, native, identity, recovery)
    if operation == 'security-enforce':
        return enforce(journal, native, identity, recovery)
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


def facts(native, since=None):
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
        timestamp = re.search(r'\bmsg=audit\((\d+(?:\.\d+)?):', line)
        assert timestamp, 'audit event timestamp missing'
        if since is not None and float(timestamp.group(1)) < since:
            continue
        fields = {key: re.search(r'\b' + key + r'=("[^"]*"|[^ ]+)', line)
                  for key in ('type', 'comm', 'scontext', 'tcontext', 'tclass', 'permissive')}
        record = {key: match.group(1).strip('"') for key, match in fields.items() if match}
        access = re.search(r'avc:\s+denied\s+\{([^}]*)\}', line)
        if access:
            record['denied'] = access.group(1).split()
        record['timestamp'] = float(timestamp.group(1))
        record['record_sha256'] = hashlib.sha256(line.encode()).hexdigest()
        records.append(record)
    assert all(re.fullmatch(r'NOTE - using logs in /var/log/audit/audit\.log(?:\.[0-9]+)?', line)
               for line in audit.stderr.splitlines()), 'native audit diagnostics require review'
    assert audit.returncode == 0 or (not records and not audit.stdout.strip()), 'audit evidence unavailable'
    assert Path('/var/log/audit/audit.log').stat().st_size > 0, 'audit log unavailable'
    audit_state = dict(line.split(None, 1) for line in native('auditctl', '-s').splitlines())
    assert audit_state.get('enabled') in ('1', '2') and audit_state.get('lost') == '0', 'audit collection disabled or events lost'
    return {'boot': boot, 'mode': native('getenforce'),
            'kernel': native('uname', '-r'), 'autorelabel': Path('/.autorelabel').exists(),
            'kernel_overrides': sorted({'selinux=0', 'enforcing=0'}.intersection(Path('/proc/cmdline').read_text().split())),
            'k3s_context': process.read_text().strip().rstrip(chr(0)) if process.exists() else None,
            'k3s_binary_context': os.getxattr('/usr/local/bin/k3s', 'security.selinux').decode().rstrip(chr(0)),
            'containerd_selinux': runtime.get('enable_selinux'),
            'audit_records': records, 'audit_record_count': len(records),
            'failed_units': native('systemctl', '--failed', '--no-legend', '--plain')}


def observers():
    """Actual host-agent domains and process start times; never infer from Pod phase."""
    names = {'node_exporter', 'nfd-worker', 'alloy'}
    boot = int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines()
                    if line.startswith('btime ')))
    result = {}
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            name = (process / 'comm').read_text().strip()
            if name not in names:
                continue
            stat = (process / 'stat').read_text().rsplit(')', 1)[1].split()
            context = (process / 'attr/current').read_text().strip().rstrip(chr(0))
            assert name not in result, 'overlapping host-agent processes'
            assert context.split(':')[2] == 'spc_t', 'host-agent GitOps correction not active'
            result[name] = {'pid': int(process.name), 'context': context,
                            'started': boot + int(stat[19]) / os.sysconf('SC_CLK_TCK')}
        except FileNotFoundError:
            continue
    assert set(result) == names, 'host-agent process coverage incomplete'
    return result


def replace(path, content):
    import maintenance_actor_hold as hold
    hold.safe(path)
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


def enforce(journal, native, identity, recovery):
    """Persist enforcement and reboot once after actual corrected-agent acceptance."""
    import maintenance_actor_hold as hold
    token = journal.token
    root = journal.hold.state
    intent = root / ('host-enforce-' + token + '.json')
    with journal.hold.serialized():
        journal.owners(idle=True)
        assert not intent.exists(), 'enforcement intent exists; observe, never replay'
        relabel_intent = json.loads((root / ('host-relabel-' + token + '.json')).read_bytes())
        assert relabel_intent['owner'] == token and relabel_intent['identity'] == identity()
        agents = observers()
        since = max(v['started'] for v in agents.values())
        assert time.time() - since >= 90, 'corrected agents have not completed their actual collection interval'
        observed = facts(native, since)
        assert observed['mode'] == 'Permissive' and not observed['autorelabel'] and not observed['failed_units']
        assert observed['boot'] != relabel_intent['boot'] and observed['containerd_selinux'] is True
        assert observed['k3s_context'].split(':')[2] == 'container_runtime_t'
        assert observed['k3s_binary_context'].split(':')[2] == 'container_runtime_exec_t'
        assert observed['audit_record_count'] == 0, 'actual corrected runtime still produces SELinux denials'
        native('rpm', '-V', '--noghost', 'k3s-selinux', 'container-selinux')
        native('rpm', '-q', 'microcode_ctl')
        config = Path('/etc/selinux/config')
        assert config.read_text().splitlines().count('SELINUX=permissive') == 1
        guard = Path('/etc/systemd/system/k3s.service.d/90-maintenance103-relabel.conf')
        hold.safe(guard)
        assert guard.read_bytes() == b'[Unit]\nConditionPathExists=!/.autorelabel\n'
        assert 'selinux: true' in Path('/etc/rancher/k3s/config.yaml').read_text().splitlines()
        record = {'owner': token, 'identity': identity(), 'boot': observed['boot'],
                  'recovery_sha256': recovery['sha256'], 'agents': agents, 'audit_since': since,
                  'before_selinux_config': config.read_text(),
                  'k3s_configuration_sha256': hashlib.sha256(Path('/etc/rancher/k3s/config.yaml').read_bytes()).hexdigest(),
                  'accepted_permissive_evidence': observed}
        hold.exclusive_file(intent, json.dumps(record, sort_keys=True).encode(), 0o600)
        replace(config, config.read_text().replace('SELINUX=permissive', 'SELINUX=enforcing'))
        native('restorecon', '/etc/selinux/config')
        native('grubby', '--update-kernel=ALL', '--remove-args=selinux enforcing')
        assert not any(word in native('grubby', '--info=ALL') for word in ('selinux=0', 'enforcing=0'))
        guard.unlink(); hold.fsync_directory(guard.parent)
        native('systemctl', 'daemon-reload')
        native('setenforce', '1')
        assert native('getenforce') == 'Enforcing' and Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
        assert not native('systemctl', '--failed', '--no-legend', '--plain')
        journal.owners(idle=True)
        reboot = root / ('host-enforce-reboot-' + token + '.json')
        hold.exclusive_file(reboot, json.dumps({'intent_sha256': hashlib.sha256(intent.read_bytes()).hexdigest(),
                            'boot': observed['boot']}, sort_keys=True).encode(), 0o600)
        native('systemd-run', '--unit=' + token + '-selinux-enforce', '--on-active=5s',
               '--property=Restart=no', '/usr/bin/systemctl', 'reboot')
    return {'enforcement_reboot_dispatched': True, 'owner_retained': True, 'node_stays_cordoned': True,
            'permissive_denials_after_correction': observed['audit_record_count']}


def acceptance(journal, native, identity):
    root = journal.hold.state
    token = journal.token
    record = json.loads((root / ('host-enforce-' + token + '.json')).read_bytes())
    assert record['owner'] == token and record['identity'] == identity()
    reboot = json.loads((root / ('host-enforce-reboot-' + token + '.json')).read_bytes())
    assert reboot['intent_sha256'] == hashlib.sha256((root / ('host-enforce-' + token + '.json')).read_bytes()).hexdigest()
    observed = facts(native)
    assert observed['boot'] != reboot['boot'], 'persistent enforcement boot not yet proven'
    assert observed['mode'] == 'Enforcing' and not observed['kernel_overrides'] and not observed['autorelabel']
    assert not observed['failed_units'] and observed['audit_record_count'] == 0, 'host security findings remain'
    assert observed['containerd_selinux'] is True and observed['k3s_context'].split(':')[2] == 'container_runtime_t'
    assert observed['k3s_binary_context'].split(':')[2] == 'container_runtime_exec_t'
    assert hashlib.sha256(Path('/etc/rancher/k3s/config.yaml').read_bytes()).hexdigest() == record['k3s_configuration_sha256']
    native('rpm', '-V', '--noghost', 'k3s-selinux', 'container-selinux')
    native('rpm', '-q', 'microcode_ctl')
    observed['host_observers'] = observers()
    observed['microcode_revision'] = Path('/sys/devices/system/cpu/cpu0/microcode/version').read_text().strip()
    firmware_boot = json.loads((root / ('host-firmware-reboot-' + token + '.json')).read_bytes())
    assert firmware_boot['owner'] == token and firmware_boot['identity'] == identity() and firmware_boot['boot'] != observed['boot']
    assert int(observed['microcode_revision'], 16) >= 0xf0, 'new microcode has not actually loaded'
    assert early_intel_revision(Path('/boot/initramfs-' + FIRMWARE_KERNEL + '.img')) == 0xf0
    assert not any(p.read_text().strip().startswith('Vulnerable') for p in Path('/sys/devices/system/cpu/vulnerabilities').iterdir()), 'CPU security finding remains'
    return observed


FIRMWARE_CONFIG = 'early_microcode="yes"\n'
FIRMWARE_SHA256 = '15e96637a89012390e2c254effad092fc9535912b709ffa316069fc5606efb65'
FIRMWARE_KERNEL = '7.2.11-200.fc44.x86_64'


def early_intel_revision(path):
    """Read the real uncompressed early newc archive and checksum Intel updates."""
    import struct
    with path.open('rb') as source:
        offset = 0
        for _ in range(100):
            source.seek(offset); header = source.read(110)
            assert header[:6] in (b'070701', b'070702'), 'early microcode CPIO missing'
            size, namesize = int(header[54:62], 16), int(header[94:102], 16)
            assert 0 < namesize < 4096 and size < 16 * 1024 * 1024
            name = source.read(namesize).rstrip(bytes([0])).decode()
            start = (offset + 110 + namesize + 3) & ~3
            offset = (start + size + 3) & ~3
            if name == 'TRAILER!!!': break
            if name != 'kernel/x86/microcode/GenuineIntel.bin': continue
            source.seek(start); data = source.read(size); revisions = []; position = 0
            while position < len(data):
                fields = struct.unpack_from('<12I', data, position)
                length = fields[8] or 2048
                assert fields[0] == 1 and length >= 48 and length % 4 == 0 and position + length <= len(data)
                block = data[position:position + length]
                assert sum(struct.unpack('<' + str(length // 4) + 'I', block)) & 0xffffffff == 0
                if fields[3] == 0x506e3: revisions.append(fields[1])
                position += length
            assert revisions, 'target CPU update absent from early archive'
            return max(revisions)
    raise AssertionError('Intel early microcode payload absent')


def firmware(operation, journal, native, identity, recovery):
    """Build a candidate first; verify it before replacing the boot image once."""
    import maintenance_actor_hold as hold
    import shlex
    token = journal.token; root = journal.hold.state
    intent = root / ('host-firmware-' + token + '.json')
    accepted = root / ('host-firmware-accepted-' + token + '.json')
    install = root / ('host-firmware-reboot-' + token + '.json')
    unit = token + '-host-firmware.service'
    image = Path('/boot/initramfs-' + FIRMWARE_KERNEL + '.img')
    candidate = Path('/boot/.maintenance103-' + token + '.img')
    assert native('uname', '-r') == FIRMWARE_KERNEL and native('getenforce') == 'Enforcing'
    if operation == 'observe-security-firmware':
        record = json.loads(intent.read_bytes())
        assert record['owner'] == token and record['identity'] == identity()
        fields = dict(line.split('=', 1) for line in native('systemctl', 'show', unit,
            '-p', 'LoadState', '-p', 'ActiveState', '-p', 'Result', '-p', 'ExecMainStatus',
            '-p', 'MainPID', '-p', 'ControlPID').splitlines())
        assert fields['LoadState'] == 'loaded', 'uncertain firmware dispatch; never replay'
        result = {'unit': unit, 'status': fields, 'accepted': False}
        if fields['MainPID'] == fields['ControlPID'] == '0':
            assert fields['ActiveState'] == 'active' and fields['Result'] == 'success' and fields['ExecMainStatus'] == '0', native('journalctl', '-u', unit, '-n', '20', '--no-pager', '-o', 'cat')
            assert early_intel_revision(candidate) == 0xf0
            native('rpm', '-q', 'smartmontools'); native('rpm', '-V', '--noghost', 'microcode_ctl')
            result.update(accepted=True, candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                          target_microcode='0xf0', boot=record['boot'], identity=identity(), owner=token)
            if not accepted.exists():hold.exclusive_file(accepted, json.dumps(result, sort_keys=True).encode(), 0o600)
        return result
    with journal.hold.serialized():
        journal.owners(idle=True)
        for path in (image, candidate, intent, accepted, install):hold.safe(path)
        if operation == 'security-firmware-reboot':
            assert not install.exists(), 'firmware installation intent exists; observe boot, never replay'
            record = json.loads(intent.read_bytes()); proof = json.loads(accepted.read_bytes())
            assert record['owner'] == proof['owner'] == token and record['identity'] == proof['identity'] == identity()
            assert proof['accepted'] is True and hashlib.sha256(candidate.read_bytes()).hexdigest() == proof['candidate_sha256']
            assert early_intel_revision(candidate) == 0xf0
            assert hashlib.sha256(image.read_bytes()).hexdigest() == record['before_image_sha256']
            assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == record['boot']
            hold.exclusive_file(install, json.dumps({'owner': token, 'identity': identity(), 'boot': record['boot'],
                'candidate_sha256': proof['candidate_sha256'], 'before_image_sha256': record['before_image_sha256']}, sort_keys=True).encode(), 0o600)
            os.chmod(candidate, image.stat().st_mode & 0o777); os.chown(candidate, 0, 0)
            with candidate.open('rb') as descriptor:os.fsync(descriptor.fileno())
            os.replace(candidate, image); hold.fsync_directory(image.parent)
            native('restorecon', str(image))
            assert hashlib.sha256(image.read_bytes()).hexdigest() == proof['candidate_sha256']
            native('systemd-run', '--unit=' + token + '-firmware-reboot', '--on-active=5s',
                   '--property=Restart=no', '/usr/bin/systemctl', 'reboot')
            return {'firmware_reboot_dispatched': True, 'node_stays_cordoned': True, 'owner_retained': True}
        assert operation == 'security-firmware' and not intent.exists() and not candidate.exists()
        assert Path('/sys/devices/system/cpu/cpu0/microcode/version').read_text().strip() == '0xec'
        firmware_path = Path('/usr/lib/firmware/intel-ucode/06-5e-03')
        assert hashlib.sha256(firmware_path.read_bytes()).hexdigest() == FIRMWARE_SHA256
        native('rpm', '-V', '--noghost', 'microcode_ctl')
        config = Path('/etc/dracut.conf.d/90-homelab-microcode.conf'); hold.safe(config)
        assert not config.exists(), 'existing early-microcode configuration requires review'
        original = root / ('host-firmware-original-' + token + '.img')
        before = hashlib.sha256(image.read_bytes()).hexdigest()
        script = root / ('host-firmware-' + token + '.sh')
        repos = root / ('fedora-repositories-44-' + token)
        assert (repos / 'maintenance.repo').is_file()
        commands = [['/usr/bin/dnf5', '--setopt=reposdir=' + str(repos), '--setopt=gpgcheck=True',
                    '--setopt=localpkg_gpgcheck=True', '--assumeyes', 'install', 'smartmontools'],
                    ['/usr/bin/dracut', '--early-microcode', '--kver', FIRMWARE_KERNEL, str(candidate)]]
        content = '#!/bin/bash\nset -euo pipefail\n' + '\n'.join(shlex.join(c) for c in commands) + '\n'
        record = {'owner': token, 'identity': identity(), 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'before_image_sha256': before, 'recovery_sha256': recovery['sha256'],
                  'firmware_sha256': FIRMWARE_SHA256, 'script_sha256': hashlib.sha256(content.encode()).hexdigest()}
        hold.exclusive_file(original, image.read_bytes(), 0o600)
        assert hashlib.sha256(original.read_bytes()).hexdigest() == before
        hold.exclusive_file(intent, json.dumps(record, sort_keys=True).encode(), 0o600)
        hold.exclusive_file(config, FIRMWARE_CONFIG.encode(), 0o644)
        native('restorecon', str(config))
        hold.exclusive_file(script, content.encode(), 0o700)
        native('systemd-run', '--unit=' + unit, '--property=Type=exec', '--property=RemainAfterExit=yes',
               '--property=Restart=no', '--setenv=LANG=C.UTF-8', '/bin/bash', str(script))
        return {'firmware_build_dispatched': True, 'boot_image_unchanged': True, 'owner_retained': True}
