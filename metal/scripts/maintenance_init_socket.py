"""Issue 103: permit PID 1 to inspect inherited uevent socket metadata."""

import hashlib
import json
from pathlib import Path


OWNER = 'homelab-maintenance-103-ff28f905-dd10-4857-affb-a06f56240ca6'
BOOT = '0e8373c7-598e-421e-880e-ff28131c82ca'
POLICY = b'(allow init_t kernel_t (netlink_kobject_uevent_socket (getattr)))\n'
MODULE = 'homelab_init_socket'
PROBE_HASHES = {'c4006ab1dea3412879f28df680dd9b9e6fe27eee00c5afcee00262fe542265c9',
                'a6edc0b5726cd8e240989deeb1055962ef3a5ad6120b73b8e9f26eef0e0bf2e3'}
HISTORICAL = ('audit: type=1400 audit(1793137096.898:4): avc:  denied  { getattr } for  '
              'pid=1 comm="systemd" path="socket:[3054]" dev="sockfs" ino=3054 '
              'scontext=system_u:system_r:init_t:s0 tcontext=system_u:system_r:kernel_t:s0 '
              'tclass=netlink_kobject_uevent_socket permissive=0')


def kernel_records(native):
    records = [json.loads(line) for line in native('journalctl', '-k', '-b', '-o', 'json', '--no-pager').splitlines()]
    return [r['MESSAGE'] for r in records if 'avc:' in r.get('MESSAGE', '') and 'denied' in r['MESSAGE']]


def allowed():
    import selinux
    import setools
    policy = setools.SELinuxPolicy('/sys/fs/selinux/policy')
    rules = list(setools.TERuleQuery(policy, ruletype=['allow'], source='init_t', target='kernel_t',
        tclass=['netlink_kobject_uevent_socket']).results())
    if len(rules) != 1 or set(rules[0].perms) != {'getattr'}: return False
    tclass = selinux.string_to_security_class('netlink_kobject_uevent_socket')
    permission = selinux.string_to_av_perm(tclass, 'getattr')
    decision = selinux.av_decision()
    result = selinux.security_compute_av_raw('system_u:system_r:init_t:s0',
        'system_u:system_r:kernel_t:s0', tclass, permission, decision)
    return result == 0 and permission > 0 and decision.allowed & permission == permission


def diagnostic_audits_resolved(records, boot):
    """Keep the two failed verification probes; never excuse another denial."""
    return (boot == BOOT and len(records) == 2 and
            {r.get('record_sha256') for r in records} == PROBE_HASHES and
            not any((Path('/proc') / str(pid)).exists() for pid in (8771, 8891)))


def verify(native, record):
    assert record['owner'] == OWNER and record['boot'] == BOOT
    assert record['policy_sha256'] == hashlib.sha256(POLICY).hexdigest()
    assert native('getenforce') == 'Enforcing' and allowed()
    assert kernel_records(native) == [HISTORICAL], 'new kernel AVC remains unresolved'
    assert ['400', MODULE, 'cil'] in [line.split() for line in native('semodule', '-lfull').splitlines()]
    return dict(record, accepted=True, loaded_policy_sha256=hashlib.sha256(Path('/sys/fs/selinux/policy').read_bytes()).hexdigest())


def execute(journal, native, identity, recovery):
    import maintenance_actor_hold as actors
    from maintenance_node_drain import private_json
    with journal.hold.serialized():
        owner = journal.owners(idle=True)['global']
        assert owner['owner'] == OWNER and owner['node'] == 'pikachu'
        assert owner['source'] == owner['target'] == 44
        assert identity() == {'machine': '0a7daf8b33244d9d85f46223c3582da9',
                              'root_uuid': '76e53a95-725a-4430-9d7b-a8db413f3997'}
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
        state = journal.read()
        assert not state['pending'] and state['completed'] == ['cordon', 'drain', 'security_default',
            'trusted_reconnect', 'verify_infrastructure', 'restore_scheduling']
        assert recovery['identity'] == identity() and recovery['source_release'] == 44
        assert recovery['sha256'] == '87f5fbda4231a41df2ab42c344c6e0c6c8d5069aeca111e2a1c9070a343b662e'
        root = journal.hold.state
        path = root / (MODULE + '.cil')
        intent = root / ('init-socket-policy-' + OWNER + '.json')
        accepted = root / ('init-socket-policy-accepted-' + OWNER + '.json')
        for item in (path, intent, accepted): actors.safe(item)
        if intent.exists():
            record = private_json(intent, security_receipt=True)
            assert path.read_bytes() == POLICY, 'uncertain policy install; observe, never replay'
        else:
            assert not path.exists() and not accepted.exists() and not allowed()
            assert not any(MODULE in line.split() for line in native('semodule', '-lfull').splitlines())
            assert native('rpm', '-q', 'selinux-policy-targeted', '--qf', '%{VERSION}-%{RELEASE}') == '44.11-1.fc44'
            assert native('getenforce') == 'Enforcing' and kernel_records(native) == [HISTORICAL]
            record = {'owner': OWNER, 'boot': BOOT, 'identity': identity(),
                'policy_sha256': hashlib.sha256(POLICY).hexdigest(), 'recovery_sha256': recovery['sha256'],
                'historical_avc_sha256': hashlib.sha256(HISTORICAL.encode()).hexdigest(),
                'before_policy_sha256': hashlib.sha256(Path('/sys/fs/selinux/policy').read_bytes()).hexdigest()}
            actors.exclusive_file(path, POLICY, 0o600)
            actors.exclusive_file(intent, json.dumps(record, sort_keys=True).encode(), 0o600)
            native('semodule', '-i', str(path))
        result = verify(native, record)
        if not accepted.exists(): actors.exclusive_file(accepted, json.dumps(result, sort_keys=True).encode(), 0o600)
        assert private_json(accepted, security_receipt=True) == result
        return result
