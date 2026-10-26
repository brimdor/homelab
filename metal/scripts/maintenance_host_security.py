"""Native final-release host work under the existing production owner and hold."""

import hashlib
import json
from pathlib import Path
import urllib.request


POLICY = ('https://rpm.rancher.io/k3s/latest/common/centos/9/noarch/k3s-selinux-1.6-1.el9.noarch.rpm',
          '1115a1223b0db998c7977c879f2a3a6f07a0c63240f68f6e3b665a7ae27c38f7')
KEY = ('https://rpm.rancher.io/public.key',
       'b2ebdeb8d9b1bb66696622da6d086c2376de772af3dd96cc3a6cb4ca5568d171')


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
    assert operation == 'security-policy'
    assert not intent.exists(), 'policy intent exists; observe, never replay'
    import maintenance_actor_hold as hold
    with actors.serialized():
        journal.owners(idle=True)
        assets = root / ('host-security-assets-' + token)
        assets.mkdir(mode=0o700, exist_ok=True)
        for name, (url, digest) in (('policy.rpm', POLICY), ('rancher-public.key', KEY)):
            path = assets / name
            if not path.exists():
                with urllib.request.urlopen(url, timeout=60) as response:
                    content = response.read(16 * 1024 * 1024 + 1)
                assert hashlib.sha256(content).hexdigest() == digest, 'vendor artifact changed'
                hold.exclusive_file(path, content, 0o600)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        native('rpmkeys', '--import', str(assets / 'rancher-public.key'))
        signature = native('rpmkeys', '--checksig', '--verbose', str(assets / 'policy.rpm'))
        assert 'e257814a' in signature.lower() and not any(word in signature for word in ('NOKEY', 'NOT OK', 'BAD'))
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
