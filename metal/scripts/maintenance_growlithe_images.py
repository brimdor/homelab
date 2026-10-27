"""Preserve Growlithe's original HumbleAI image on an existing ARM64 emulator."""

import inspect

from maintenance_nibble_artifact import RECEIVE_PROGRAM, REGISTER_PROGRAM, SOURCE_PROGRAM, stream
from maintenance_production_node import remote


VALUES = {
    'IMAGE': '10.0.20.11:32309/humbleai:demo',
    'ALIAS': 'registry.eaglepass.io/humbleai@sha256:fcf08c14538753af9539a66d2c3551e07445c664970a392da4928b80cb9fe542',
    'DIGEST': 'sha256:fcf08c14538753af9539a66d2c3551e07445c664970a392da4928b80cb9fe542',
    'CONFIG': 'sha256:da30cfa6e21c5ff8a1291228bab6ab4b212145e36b2b1fcf0187f0d2b02f0802',
    'BLOB_COUNT': 13,
    'SOURCE_HOST': 'growlithe',
    'SOURCE_MACHINE': 'a26cbcc990c044dea41fbf4f957f453d',
    'SOURCE_ROOT': '710e2dca-691e-4123-a867-4994b9c6e612',
    'TARGET_HOST': 'cyndaquil',
    'TARGET_MACHINE': '51140709f60f45c1bcd0edfa23dba2ef',
    'TARGET_ROOT': 'fc02c8c4-35c6-4efe-a88a-b03d7673c0c8',
    'RECOVERY': '/var/lib/homelab-recovery/maintenance-103/growlithe-humbleai-demo-fcf08c14',
    'ARTIFACT': 'maintenance103-growlithe-humbleai-demo-fcf08c14.tar',
}

NIBBLE = {
    **VALUES,
    'IMAGE': '10.0.20.11:32309/nibble:issue-26-prod',
    'ALIAS': '10.0.20.11:32309/nibble@sha256:bd302668a32803da79db8dc178cf93b0c05cd6f48766acca0bf5075cddd53d46',
    'DIGEST': 'sha256:bd302668a32803da79db8dc178cf93b0c05cd6f48766acca0bf5075cddd53d46',
    'CONFIG': 'sha256:c5041e29afd7b0b6ac5e6adb59d5abb063358af0ea59688071721ecb7d0325d7',
    'BLOB_COUNT': 14,
    'SOURCE_HOST': 'totodile',
    'SOURCE_MACHINE': '0f1915a59a124d999d8d68b53f406af1',
    'SOURCE_ROOT': '489f1af8-5d55-4356-8d48-418fcb2069a2',
    'SOURCE_ARCHIVE': '/var/lib/homelab-recovery/maintenance-103/nibble-image-bd302668-local-export/image.tar',
    'SOURCE_ARCHIVE_SHA256': 'b8624e3e9dd33515ab42ad088ac7b4cf2ca5c45cff93d0168f4a3c90d0990c29',
    'SOURCE_ARCHIVE_BYTES': 288765440,
    'TARGET_HOST': 'charmander',
    'TARGET_MACHINE': '58d682ccab5a4269acedc3cdf53e46dc',
    'TARGET_ROOT': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2',
    'RECOVERY': '/var/lib/homelab-recovery/maintenance-103/growlithe-nibble-canary-bd302668-protected-copy',
    'ARTIFACT': 'maintenance103-growlithe-nibble-canary-bd302668-protected-copy.tar',
}

PROTECTED_NIBBLE_SOURCE = '''
import hashlib,json,os,pathlib,socket,stat,subprocess
assert os.geteuid()==0 and socket.gethostname()==SOURCE_HOST
assert pathlib.Path('/etc/machine-id').read_text().strip()==SOURCE_MACHINE
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==SOURCE_ROOT
archive=pathlib.Path(SOURCE_ARCHIVE)
assert not any(p.is_symlink()for p in(archive,*archive.parents))
assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',str(archive)],text=True).strip()==SOURCE_ROOT
info=archive.stat()
assert stat.S_ISREG(info.st_mode)and info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600 and info.st_size==SOURCE_ARCHIVE_BYTES
record=json.loads((archive.parent/'verified.json').read_bytes())
assert record['image']==IMAGE and record['digest']==DIGEST and record['archive_sha256']==SOURCE_ARCHIVE_SHA256 and record['archive_bytes']==SOURCE_ARCHIVE_BYTES
with archive.open('rb')as source:assert hashlib.file_digest(source,'sha256').hexdigest()==SOURCE_ARCHIVE_SHA256
after=archive.stat()
assert all(getattr(after,key)==getattr(info,key)for key in('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'))
os.execv('/bin/cat',['cat',str(archive)])
'''

CAPACITY = '''
import shutil
usage=shutil.disk_usage('/var/lib')
assert usage.free-2*1024**3>usage.total//5,'receiver needs archive and native import headroom'
'''


def handler_ready(text):
    lines = text.splitlines()
    return (lines[:1] == ['enabled'] and
            'interpreter /usr/bin/qemu-aarch64-static' in lines and
            any(line.startswith('flags: ') and 'F' in line[7:] for line in lines))


def bindings(values=VALUES):
    return ''.join(key + '=' + repr(value) + '\n' for key, value in values.items())


def receiver_guard():
    return 'import pathlib\n' + inspect.getsource(handler_ready) + '''
assert handler_ready(pathlib.Path('/proc/sys/fs/binfmt_misc/qemu-aarch64').read_text()),'existing ARM64 handler unavailable'
''' + CAPACITY


def preserve(args):
    # The original is ARM64; exporting the neighboring helper's AMD64 platform loses it.
    assert SOURCE_PROGRAM.count("'linux/amd64'") == 1
    source = SOURCE_PROGRAM.replace("'linux/amd64'", "'linux/arm64'")
    return stream(args, '10.0.20.18', bindings() + source,
                  bindings() + receiver_guard() + RECEIVE_PROGRAM, '10.0.20.16')


def register(args):
    return remote(args, bindings() + receiver_guard() + REGISTER_PROGRAM, '10.0.20.16')


def preserve_nibble(args):
    return stream(args, '10.0.20.17', bindings(NIBBLE) + PROTECTED_NIBBLE_SOURCE,
                  bindings(NIBBLE) + CAPACITY + RECEIVE_PROGRAM, '10.0.20.11')


def register_nibble(args):
    return remote(args, bindings(NIBBLE) + CAPACITY + REGISTER_PROGRAM, '10.0.20.11')
