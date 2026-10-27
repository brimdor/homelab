"""Protect Cyndaquil's exact production frontend before its owned drain finishes."""

from maintenance_nibble_artifact import RECEIVE_PROGRAM, REGISTER_PROGRAM, SOURCE_PROGRAM, stream
from maintenance_production_node import remote


VALUES = {
    'IMAGE': '10.0.20.11:32309/sporecast-frontend:a3fe7c8',
    'ALIAS': '10.0.20.11:32309/sporecast-frontend@sha256:6993efa30e8c0298243706307e2026ace448e673e97d374e2d6fc498cdb12d62',
    'DIGEST': 'sha256:6993efa30e8c0298243706307e2026ace448e673e97d374e2d6fc498cdb12d62',
    'CONFIG': 'sha256:24e8dc7aa94fbbe7d9d832315341a69c708c0961f49fc639d078118e28e9ea28',
    'BLOB_COUNT': 12,
    'SOURCE_HOST': 'cyndaquil',
    'SOURCE_MACHINE': '51140709f60f45c1bcd0edfa23dba2ef',
    'SOURCE_ROOT': 'fc02c8c4-35c6-4efe-a88a-b03d7673c0c8',
    'TARGET_HOST': 'pikachu',
    'TARGET_MACHINE': '0a7daf8b33244d9d85f46223c3582da9',
    'TARGET_ROOT': '76e53a95-725a-4430-9d7b-a8db413f3997',
    'RECOVERY': '/var/lib/homelab-recovery/maintenance-103/cyndaquil-sporecast-frontend-6993efa3',
    'ARTIFACT': 'maintenance103-cyndaquil-sporecast-frontend-6993efa3.tar',
}


def bindings():
    return ''.join(key + '=' + repr(value) + '\n' for key, value in VALUES.items())


def preserve(args):
    # The production tag resolves to 6993efa3, not the canary's 1ed9d37a build.
    # Retain the complete original graph on the receiver's native root filesystem.
    capacity = '''
import shutil
usage=shutil.disk_usage('/var/lib')
assert usage.free-80*1024*1024>usage.total//5,'receiver needs free space after original archive/import'
'''
    return stream(args, '10.0.20.16', bindings() + SOURCE_PROGRAM,
                  bindings() + capacity + RECEIVE_PROGRAM, '10.0.20.14')


def register(args):
    return remote(args, bindings() + REGISTER_PROGRAM, '10.0.20.14')
