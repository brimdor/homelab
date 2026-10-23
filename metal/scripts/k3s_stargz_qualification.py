#!/usr/bin/env python3
"""Qualify the declared stargz runtime through the existing isolated HA matrix."""

import json
import re
import tomllib

import k3s_qualification as ha


FLAG = '--k3s-arg=--snapshotter=stargz@server:*;agent:*'


def require_runtime(config, plugins, containers):
    images = config.get('plugins', {}).get('io.containerd.cri.v1.images', {})
    if (config.get('version') != 3 or images.get('snapshotter') != 'stargz' or
            images.get('disable_snapshot_annotations') is not False):
        raise RuntimeError('native CRI stargz configuration differs')
    matches = [line.split() for line in plugins.splitlines()
               if line.split()[:2] == ['io.containerd.snapshotter.v1', 'stargz']]
    if (len(matches) != 1 or len(matches[0]) != 4 or
            matches[0][2] not in {'linux/arm64', 'linux/arm64/v8'} or matches[0][3] != 'ok'):
        raise RuntimeError('native stargz snapshotter is not healthy for the fixture platform')
    if not containers or any(not re.fullmatch('[a-f0-9]{64}', identifier) or
                             item.get('ID') != identifier or item.get('Snapshotter') != 'stargz' or
                             not isinstance(item.get('SnapshotKey'), str) or not item['SnapshotKey']
                             for identifier, item in containers.items()):
        raise RuntimeError('running workload does not use native stargz snapshots')
    return {'config_version': 3, 'snapshotter': 'stargz', 'plugin_status': 'ok',
            'running_container_ids': sorted(containers),
            'snapshot_keys': {identifier: item['SnapshotKey'] for identifier, item in containers.items()}}


class Qualification(ha.Qualification):
    def command(self, command, **kwargs):
        if command[:3] == [self.args.k3d, 'cluster', 'create']:
            if command[3] != self.args.name or any('snapshotter' in arg for arg in command):
                raise RuntimeError('owned stargz cluster creation contract differs')
            command = [*command, FLAG]
        return super().command(command, **kwargs)

    def checkpoint(self, version, phase):
        super().checkpoint(version, phase)
        pods = self.kubectl('get', 'pods', '-A')['items']
        evidence = {}
        for node in self.versions:
            self.inspect(node)
            # The baseline container ships the standalone ctr entry point.
            prefix = ['docker', 'exec', node, '/bin/ctr',
                      '--address=/run/k3s/containerd/containerd.sock', '--namespace=k8s.io']
            client_version = self.command(['docker', 'exec', node, '/bin/ctr', '--version']).decode().strip()
            if not client_version.startswith('ctr '):
                raise RuntimeError('native ctr client identity differs')
            config = tomllib.loads(self.command(['docker', 'exec', node, 'cat',
                                                '/var/lib/rancher/k3s/agent/etc/containerd/config.toml']).decode())
            plugins = self.command([*prefix, 'plugins', 'list']).decode()
            self.stages[-1].setdefault('stargz_runtime_observed', {})[node] = {
                'ctr_client_version': client_version,
                'plugin_rows': [line for line in plugins.splitlines()
                                if line.split()[:2] == ['io.containerd.snapshotter.v1', 'stargz']]}
            self.persist()
            identifiers = set()
            for pod in pods:
                if pod['spec'].get('nodeName') != node or pod['metadata'].get('deletionTimestamp'):
                    continue
                status = pod.get('status', {})
                for container in [*status.get('containerStatuses', []), *status.get('initContainerStatuses', [])]:
                    if container.get('ready') is True and set(container.get('state', {})) == {'running'}:
                        identifier = container.get('containerID', '')
                        if not re.fullmatch('containerd://[a-f0-9]{64}', identifier):
                            raise RuntimeError('running fixture container identity is invalid')
                        identifiers.add(identifier.removeprefix('containerd://'))
            containers = {identifier: json.loads(self.command([*prefix, 'containers', 'info', identifier]))
                          for identifier in sorted(identifiers)}
            evidence[node] = require_runtime(config, plugins, containers)
            evidence[node]['ctr_client_version'] = client_version
        self.stages[-1]['stargz_runtime'] = evidence
        self.persist()

    def run(self):
        result = super().run()
        if len(result['stages']) != 13 or any(set(stage.get('stargz_runtime', {})) != set(self.versions)
                                             for stage in result['stages']):
            raise RuntimeError('stargz runtime matrix is incomplete')
        result.update(stargz_runtime_matrix_accepted=True, estargz_remote_lazy_fetch_unqualified=True)
        return result
