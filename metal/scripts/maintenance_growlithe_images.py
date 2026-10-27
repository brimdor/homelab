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
    'IMAGE': '10.0.20.11:32309/nibble:issue-26-audit-canary',
    'ALIAS': '10.0.20.11:32309/nibble@sha256:bd302668a32803da79db8dc178cf93b0c05cd6f48766acca0bf5075cddd53d46',
    'DIGEST': 'sha256:bd302668a32803da79db8dc178cf93b0c05cd6f48766acca0bf5075cddd53d46',
    'CONFIG': 'sha256:c5041e29afd7b0b6ac5e6adb59d5abb063358af0ea59688071721ecb7d0325d7',
    'BLOB_COUNT': 14,
    'TARGET_HOST': 'charmander',
    'TARGET_MACHINE': '58d682ccab5a4269acedc3cdf53e46dc',
    'TARGET_ROOT': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2',
    'RECOVERY': '/var/lib/homelab-recovery/maintenance-103/growlithe-nibble-canary-bd302668',
    'ARTIFACT': 'maintenance103-growlithe-nibble-canary-bd302668.tar',
}

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
    return stream(args, '10.0.20.18', bindings(NIBBLE) + SOURCE_PROGRAM,
                  bindings(NIBBLE) + CAPACITY + RECEIVE_PROGRAM, '10.0.20.11')


def register_nibble(args):
    return remote(args, bindings(NIBBLE) + CAPACITY + REGISTER_PROGRAM, '10.0.20.11')
