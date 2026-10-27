"""Read-only acceptance for Cyndaquil's reviewed Samsung PM871 SSD."""

import json
import pathlib
import socket
import stat
import subprocess

ERROR_ATTRIBUTES = {
    5: 'Reallocated_Sector_Ct', 171: 'Program_Fail_Count_Chip',
    172: 'Erase_Fail_Count_Chip', 178: 'Used_Rsvd_Blk_Cnt_Chip',
    184: 'End-to-End_Error', 187: 'Uncorrectable_Error_Cnt', 199: 'CRC_Error_Count',
}


def validate_smart(smart):
    assert smart['model_name'] == 'SAMSUNG MZ7LN512HCHP-000L1', 'SSD model changed'
    assert smart['firmware_version'] == 'EMT04L0Q', 'SSD firmware changed'
    assert smart['serial_number'] == 'S1ZKNXAGB03370', 'SSD serial changed'
    assert smart['user_capacity']['bytes'] == 512110190592 and smart['rotation_rate'] == 0
    assert smart['smart_status']['passed'] is True
    assert smart['ata_smart_error_log']['summary']['count'] == 0
    table = smart['ata_smart_attributes']['table']
    attrs = {a['id']: a for a in table}
    assert len(attrs) == len(table), 'duplicate SMART attribute'
    for a in table:
        assert not a['when_failed'], 'SMART attribute reports failure'
        if a['thresh'] > 0:
            assert min(a['value'], a['worst']) > a['thresh'], 'SMART threshold failure'
    for number, name in ERROR_ATTRIBUTES.items():
        assert number in attrs and attrs[number]['name'] == name, 'required SMART error attribute missing or changed'
        assert attrs[number]['raw']['value'] == 0, 'nonzero SMART error count'
    # This PM871 does not expose HDD attributes 197/198; never invent zero values.
    assert 197 not in attrs and 198 not in attrs, 'review changed SMART schema'
    return {
        'smart_passed': True, 'ata_error_count': 0,
        'failure_attribute_raw_values': {str(n): attrs[n]['raw']['value'] for n in ERROR_ATTRIBUTES},
        'unsupported_attributes': [197, 198],
        'wear_leveling_normalized': attrs[173]['value'],
        'historical_unexpected_power_losses': attrs[174]['raw']['value'],
        'unused_reserved_blocks': attrs[180]['raw']['value'],
        'self_test_performed_by_observer': False,
    }


def observe():
    def run(*args):
        return subprocess.check_output(args, text=True).strip()

    assert socket.gethostname() == 'cyndaquil'
    assert pathlib.Path('/etc/machine-id').read_text().strip() == '51140709f60f45c1bcd0edfa23dba2ef'
    assert run('findmnt', '-n', '-o', 'UUID', '/') == 'fc02c8c4-35c6-4efe-a88a-b03d7673c0c8'
    assert run('rpm', '-E', '%fedora') == '44' and run('getenforce') == 'Enforcing'
    smart = json.loads(run('smartctl', '-a', '-j', '/dev/sda'))
    result = validate_smart(smart)
    keys = pathlib.Path('/root/.ssh/authorized_keys')
    key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG8VfbH1Oawbqn1bg2QhmBI8z0Ql9q0qFZGieJfR1ABC buster@yoshi-to-cc'
    assert keys.read_text().splitlines().count(key) == 1
    assert keys.stat().st_uid == 0 and stat.S_IMODE(keys.stat().st_mode) == 0o600
    assert run('getsebool', 'virt_use_nfs') == 'virt_use_nfs --> on'
    assert not run('systemctl', '--failed', '--no-legend', '--plain')
    disks = json.loads(run('lsblk', '-b', '-J', '-o', 'NAME,TYPE,SIZE,FSTYPE,UUID,PARTUUID,MOUNTPOINTS'))
    disk = next(d for d in disks['blockdevices'] if d['name'] == 'sda')
    parts = {p['name']: p for p in disk['children']}
    assert disk['size'] == 512110190592 and set(parts) == {'sda1', 'sda2', 'sda3'}
    for name, partuuid in {
        'sda1': 'c32010c6-b680-4d44-9c1e-4e21384488b0',
        'sda2': '3286e8ce-0da8-4e56-bb7c-42a957e8ca2c',
        'sda3': '65459bd3-62d0-457c-8d50-d8629b78e787',
    }.items():
        assert parts[name]['partuuid'] == partuuid
    assert parts['sda1']['uuid'] == '8CAE-C52C'
    assert parts['sda2']['uuid'] == 'fc02c8c4-35c6-4efe-a88a-b03d7673c0c8' and parts['sda2']['size'] == 68719476736
    assert parts['sda3']['fstype'] == 'ceph_bluestore' and parts['sda3']['size'] == 442852442112
    result.update(boot=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  disk_serial=smart['serial_number'], temperature=smart.get('temperature'),
                  nfs_utils=run('rpm', '-q', 'nfs-utils'), virt_use_nfs='on',
                  yoshi_key_exact_once=True, authorized_keys_mode='0600', disks=disks)
    return result


if __name__ == '__main__':
    print(json.dumps(observe()))
