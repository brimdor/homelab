#!/usr/bin/env python3
"""Verify exact modern-key images in the empty, owned ARM64 Docker VM."""

import base64
import binascii
import hashlib
import json
import os
import re
import stat
import struct

import cilium_qualification as common
import rook_native_candidate as candidate


ANONYMOUS_CONFIG = {'auths': {'https://index.docker.io/v1/': {}, 'quay.io': {}}}


def require_anonymous_config(value):
    if value != ANONYMOUS_CONFIG:
        raise RuntimeError('native image client configuration is not the exact anonymous profile')


def default_key_metadata(raw):
    """Inspect a new disposable key in RAM; never return its value or a hash."""
    try:
        if not isinstance(raw, bytes) or len(raw) > 128:
            raise ValueError
        decoded = base64.b64decode(raw.strip(), validate=True)
        if len(decoded) != 44:
            raise ValueError
        kind, seconds, nanoseconds, length = struct.unpack('<HIIH', decoded[:12])
        if kind != 2 or seconds == 0 or nanoseconds >= 1_000_000_000 or length != 32:
            raise ValueError
    except (ValueError, binascii.Error, struct.error):
        raise RuntimeError('default-generated key is not the required native modern format') from None
    return {'type': 2, 'secret_bytes': 32, 'encoded_bytes': 44, 'key_value_retained': False}


def require_version(raw, version, rook=False):
    prefix = rb'rook: v' if rook else rb'ceph version '
    if (not isinstance(raw, bytes) or len(raw) > 1024 or
            not re.fullmatch(prefix + re.escape(version.encode()) + rb'(?:[ \t]+[^\r\n]*)?\r?\n?', raw)):
        raise RuntimeError('pinned native image version differs')


def require_image(value, reference):
    if (value.get('Os') != 'linux' or value.get('Architecture') != 'arm64' or
            not {reference, reference.removeprefix('docker.io/')}.intersection(value.get('RepoDigests', [])) or
            not re.fullmatch(r'sha256:[a-f0-9]{64}', value.get('Id', '')) or
            value.get('Config', {}).get('Volumes')):
        raise RuntimeError('pinned native image identity differs')


def require_container(value, name, image_id, entrypoint, arguments):
    config, host = value['Config'], value['HostConfig']
    if (value.get('Name') != '/' + name or value.get('Image') != image_id or
            config.get('Entrypoint') != [entrypoint] or config.get('Cmd') != list(arguments) or
            host.get('NetworkMode') != 'none' or host.get('Privileged') is not False or
            host.get('ReadonlyRootfs') is not True or host.get('CapAdd') or
            host.get('CapDrop') != ['ALL'] or
            host.get('SecurityOpt') != ['no-new-privileges'] or
            host.get('LogConfig', {}).get('Type') != 'none' or
            host.get('Memory') != 512 * 1024**2 or host.get('NanoCpus') != 1_000_000_000 or
            host.get('PidsLimit') != 64 or host.get('Binds') or host.get('Mounts') or
            host.get('Devices') or host.get('DeviceRequests') or host.get('PortBindings') or
            host.get('PidMode') or host.get('IpcMode') != 'private' or
            host.get('Tmpfs') != {'/tmp': 'rw,noexec,nosuid,size=16m,mode=1777'} or
            value.get('Mounts')):
        raise RuntimeError('native image execution isolation differs')


class Qualification(common.Qualification):
    def __init__(self, args):
        private_config = args.work_dir / 'i'
        config_file = private_config / 'config.json'
        if (os.environ.get('DOCKER_CONFIG') != str(private_config) or
                not private_config.is_dir() or private_config.is_symlink() or
                sorted(p.name for p in private_config.iterdir()) != ['config.json'] or
                config_file.is_symlink() or not config_file.is_file() or
                config_file.stat().st_uid != os.getuid() or
                stat.S_IMODE(config_file.stat().st_mode) != 0o600):
            raise RuntimeError('native image qualification requires its exact private Docker configuration')
        require_anonymous_config(json.loads(config_file.read_text()))
        super().__init__(args)
        self.anonymous_config = config_file
        for key in ('DOCKER_CONTEXT', 'DOCKER_AUTH_CONFIG', 'DOCKER_CERT_PATH',
                    'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CUSTOM_HEADERS'):
            self.env.pop(key, None)
        self.active_container = None

    def command(self, arguments, *, data=None, private=True):
        # Version/key output may contain secrets on failure; keep all raw output in RAM.
        if arguments and arguments[0] == 'docker':
            if self.anonymous_config.is_symlink():
                raise RuntimeError('native image client configuration became a link')
            require_anonymous_config(json.loads(self.anonymous_config.read_text()))
        return super().command(arguments, data=data, private=True)

    def execute(self, image, image_id, entrypoint, *arguments):
        name = self.args.name + '-image-check'
        self.active_container = name
        identifier = None
        try:
            identifier = self.command([
                'docker', 'create', '--name=' + name, '--pull=never', '--network=none',
                '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--log-driver=none', '--pids-limit=64', '--memory=512m', '--cpus=1',
                '--ipc=private', '--tmpfs=/tmp:rw,noexec,nosuid,size=16m,mode=1777',
                '--entrypoint=' + entrypoint, image, *arguments]).decode().strip()
            if not re.fullmatch(r'[a-f0-9]{64}', identifier):
                raise RuntimeError('native image container identity missing')
            value = json.loads(self.command(['docker', 'inspect', identifier]))[0]
            if value['Id'] != identifier:
                raise RuntimeError('native image container identity changed')
            require_container(value, name, image_id, entrypoint, arguments)
            raw = self.command(['docker', 'start', '--attach', identifier])
            final = json.loads(self.command(['docker', 'inspect', identifier]))[0]
            require_container(final, name, image_id, entrypoint, arguments)
            if (final['Id'] != identifier or final['State']['Running'] or
                    final['State']['ExitCode'] != 0 or final['State']['OOMKilled']):
                raise RuntimeError('native image process did not exit successfully')
            return raw
        finally:
            if identifier and re.fullmatch(r'[a-f0-9]{64}', identifier):
                self.command(['docker', 'rm', '--force', identifier])
            if self.command(['docker', 'ps', '-aq', '--filter=name=^/' + name + '$']).strip():
                raise RuntimeError('owned native image container remains')
            self.active_container = None

    def run(self):
        info = json.loads(self.command(['docker', 'info', '--format={{json .}}']))
        if (info.get('Name') != self.args.docker_server or info.get('OSType') != 'linux' or
                info.get('Architecture') != 'aarch64' or self.command(['docker', 'ps', '-aq']).strip()):
            raise RuntimeError('native image fixture is not the exact empty ARM64 daemon')
        results = []
        images = [('rook-' + version,
                   'docker.io/rook/ceph@sha256:' + values['image_sha256'], version)
                  for version, values in candidate.OPERATORS.items()]
        images.append(('ceph', candidate.CEPH_IMAGE, None))
        for label, image, version in images:
            print(json.dumps({'native_image_stage': label}), flush=True)
            self.command(['docker', 'pull', image])
            metadata = json.loads(self.command(['docker', 'image', 'inspect', image]))[0]
            require_image(metadata, image)
            if version:
                require_version(self.execute(image, metadata['Id'], '/usr/local/bin/rook', 'version'),
                                version, rook=True)
            require_version(self.execute(image, metadata['Id'], '/usr/bin/ceph', '--version'), '20.2.4')
            key = default_key_metadata(self.execute(
                image, metadata['Id'], '/usr/bin/ceph-authtool', '--gen-print-key'))
            results.append({'image': image, 'image_id': metadata['Id'], 'label': label,
                            'rook_version': version, 'ceph_version': '20.2.4', 'default_key': key})
        if self.command(['docker', 'ps', '-aq']).strip():
            raise RuntimeError('native image qualification left a container')
        return {'accepted': True, 'images': results, 'containers_absent': True,
                'raw_key_output_persisted': False, 'production_writes': 0,
                'controllers_or_storage_daemons_executed': False,
                'whole_vm_image_cleanup_required': True,
                'result_sha256': hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()}
