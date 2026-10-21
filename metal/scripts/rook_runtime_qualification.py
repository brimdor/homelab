#!/usr/bin/env python3
"""Exercise fresh modern-only Rook storage inside the owned serial-bound VM."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time
import urllib.request

import yaml

import ceph_runtime_qualification as ceph_checks
from ceph_admission_qualification import command_objects
import cilium_qualification as common
import rook_disk_qualification as disks
import rook_image_qualification as images
import rook_native_candidate as candidate


MODES = {name: 'secure' for name in (
    'ms_cluster_mode', 'ms_service_mode', 'ms_client_mode',
    'ms_mon_cluster_mode', 'ms_mon_service_mode', 'ms_mon_client_mode')}
CORE_KEYS = ('admin', 'mon', 'mgr', 'osd', 'crashCollector', 'cephExporter')


def resources(name, disk_run, inventory):
    rows = candidate.resources(name, disk_run, inventory)
    # Rook disables this crashing Ceph 20.2.4 module; this profile cannot qualify it.
    rows[2]['spec']['mgr']['modules'] = [{'name': 'rook', 'enabled': False}]
    rows[2]['spec']['cephConfig']['global'].update(MODES)
    rows[1]['data']['config'] += ''.join(key + ' = secure\n' for key in MODES)
    return rows


def toolbox():
    script = '''set -euo pipefail
umask 077
while true; do
  printf '[%s]\\nkey = %s\\n' "$ROOK_CEPH_USERNAME" "$(cat /run/mon/secret.keyring)" > /etc/ceph/keyring.new
  mv /etc/ceph/keyring.new /etc/ceph/keyring
  endpoints=$(sed 's/[a-z0-9_-]\\+=//g' /run/rook/mon-endpoints)
  printf '[global]\\nmon_host = %s\\nlog_to_file = false\\n[client.admin]\\nkeyring = /etc/ceph/keyring\\n' "$endpoints" > /etc/ceph/ceph.conf.new
  mv /etc/ceph/ceph.conf.new /etc/ceph/ceph.conf
  sleep 10
done
'''
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': 'qualification-tools', 'namespace': candidate.NAMESPACE},
            'spec': {
                'automountServiceAccountToken': False, 'restartPolicy': 'Never',
                'securityContext': {'runAsNonRoot': True, 'runAsUser': 2016,
                                    'runAsGroup': 2016, 'fsGroup': 2016},
                'containers': [{
                    'name': 'tools', 'image': candidate.CEPH_IMAGE,
                    'command': ['/bin/bash', '-ec', script],
                    'readinessProbe': {'exec': {'command': ['sh', '-ec',
                                                           'test -s /etc/ceph/keyring && test -s /etc/ceph/ceph.conf']},
                                       'periodSeconds': 2},
                    'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                        'capabilities': {'drop': ['ALL']}},
                    'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'},
                                  'limits': {'memory': '512Mi'}},
                    'env': [{'name': 'ROOK_CEPH_USERNAME', 'valueFrom': {
                        'secretKeyRef': {'name': 'rook-ceph-mon', 'key': 'ceph-username'}}}],
                    'volumeMounts': [{'name': name, 'mountPath': path, 'readOnly': readonly}
                                     for name, path, readonly in (
                                         ('config', '/etc/ceph', False), ('work', '/work', False),
                                         ('tmp', '/tmp', False), ('key', '/run/mon', True),
                                         ('endpoints', '/run/rook', True))],
                }],
                'volumes': [
                    *({'name': name, 'emptyDir': {'medium': 'Memory', 'sizeLimit': size}}
                      for name, size in (('config', '1Mi'), ('work', '8Mi'), ('tmp', '16Mi'))),
                    {'name': 'key', 'secret': {'secretName': 'rook-ceph-mon', 'defaultMode': 0o440,
                                             'items': [{'key': 'ceph-secret', 'path': 'secret.keyring'}]}},
                    {'name': 'endpoints', 'configMap': {'name': 'rook-ceph-mon-endpoints',
                                                      'items': [{'key': 'data', 'path': 'mon-endpoints'}]}},
                ],
            }}


def require_generation(cluster, generation):
    statuses = cluster.get('status', {}).get('cephx', {})
    for name in CORE_KEYS:
        value = statuses.get(name, {})
        if (value.get('keyGeneration') != generation or
                not re.fullmatch(r'20\.2\.4-[0-9]+', value.get('keyCephVersion', '')) or
                value.get('keyType', '') not in ('', 'aes256k')):
            raise RuntimeError('native Rook key-generation status differs')


def require_mon_security(value):
    expected = {'name': 'aes256k', 'value': 2}
    if (value.get('auth_allowed_ciphers') != [expected] or
            value.get('auth_service_cipher') != expected or
            value.get('auth_preferred_cipher') != expected or len(value.get('mons', [])) != 3):
        raise RuntimeError('native monitor cipher policy differs')
    if any(not row.get('public_addrs', {}).get('addrvec') or
           any(address.get('type') != 'v2' for address in row['public_addrs']['addrvec'])
           for row in value['mons']):
        raise RuntimeError('native monitor still exposes a non-msgr2 address')


def require_osd_device(value, osd, fsid, device):
    matches = [row for row in value.values() if row.get('osd_id') == osd]
    if (len(value) != 1 or len(matches) != 1 or matches[0].get('device') != device or
            matches[0].get('ceph_fsid') != fsid or
            not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',
                             matches[0].get('osd_uuid', ''))):
        raise RuntimeError('native Rook OSD device or data identity differs')
    return matches[0]['osd_uuid']


def node_layout(inventory, names):
    selected = disks.guest_disks(inventory, names)
    return [{'suffix': suffix, 'filter': selector, 'device': device,
             'masked': [row['path'] for row in selected if row['path'] != device['path']]}
            for suffix, selector, device in zip(
                ('-server-0', '-agent-0', '-agent-1'), ('server:0', 'agent:0', 'agent:1'), selected)]


def require_node_device(raw, device):
    major, minor = map(int, device['maj:min'].split(':'))
    expected = [device['serial'], device['maj:min'],
                str(disks.DISK_BYTES // 512), f'{major:x}:{minor:x}']
    actual = raw.decode('ascii', errors='replace').splitlines()
    if actual != expected:
        error = RuntimeError('assigned node virtual-device binding differs')
        error.observation = {'expected': expected, 'returned_fields': len(actual),
                             'actual': [row if re.fullmatch(r'[a-zA-Z0-9:._-]{1,128}', row)
                                        else 'unclassified' for row in actual[:8]]}
        raise error
    return {'serial': actual[0], 'major_minor': actual[1], 'sectors': int(actual[2]),
            'device_number_hex': actual[3]}


def command_failure(arguments, code, raw):
    markers = [word for word in ('forbidden', 'unauthorized', 'permission denied', 'x509',
                                'certificate', 'unknown flag', 'not found', 'no such file',
                                'strict decoding', 'timed out', 'connection refused', 'invalid',
                                'denied', 'conflict', 'already exists', 'field is immutable',
                                'einval', 'unrecognized entity', 'unrecognized key')
               if word.encode() in raw.lower()]
    return {'executable': Path(arguments[0]).name, 'exit': code, 'markers': markers,
            'raw_output_retained': False}


def messenger_entities(monitors, manager):
    mons = [row.get('name', '') for row in monitors.get('mons', [])]
    mgrs = [manager.get('active_name', ''),
            *[row.get('name', '') for row in manager.get('standbys', [])]]
    if (len(mons) != 3 or len(set(mons)) != 3 or len(mgrs) != 2 or len(set(mgrs)) != 2 or
            any(not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,127}', name)
                for name in mons + mgrs)):
        raise RuntimeError('native messenger daemon inventory differs')
    return (['mon.' + name for name in sorted(mons)] +
            ['mgr.' + name for name in sorted(mgrs)] + ['osd.0', 'osd.1', 'osd.2'])


def require_disabled_orchestrator(modules, configuration):
    enabled = modules.get('enabled_modules')
    always = modules.get('always_on_modules')
    if (not isinstance(enabled, list) or
            any(not isinstance(name, str) for name in enabled) or
            not isinstance(always, list) or 'orchestrator' not in always or
            any(not isinstance(name, str) for name in always) or
            modules.get('force_disabled_modules') != [] or 'rook' in enabled + always or
            not isinstance(configuration, list) or any(
                re.fullmatch(r'mgr/orchestrator/(?:[a-z0-9-]+/)?orchestrator', row.get('name', '')) and
                row.get('value') != ''
                for row in configuration)):
        raise RuntimeError('native no-orchestrator safety contract differs')


def require_no_warnings(observations):
    if not observations or any(row['events'] for row in observations):
        raise RuntimeError('private fixture has unresolved warning events')


def storage_observation(status, osds, pools):
    value = ceph_checks.replica_health_diagnostic(status, pools)
    states = status.get('pgmap', {}).get('pgs_by_state', [])
    names = [row.get('state_name', '') for row in states]
    if (any(not isinstance(name, str) or not re.fullmatch(r'[a-z_+]{1,128}', name) for name in names) or
            len(osds) != 3 or {row.get('osd') for row in osds} != {0, 1, 2} or
            any(type(row.get(key)) is not int or row[key] not in (0, 1)
                for row in osds for key in ('up', 'in'))):
        raise RuntimeError('native storage diagnostic evidence shape differs')
    available = status.get('mgrmap', {}).get('available')
    value.update(pg_states=sorted(names), manager_available=available if type(available) is bool else None,
                 osds=[{key: row[key] for key in ('osd', 'up', 'in')} for row in osds])
    return value


def require_toolbox(value):
    expected = toolbox()['spec']
    mismatch = []

    def included(left, right, path='spec'):
        if isinstance(left, dict):
            if isinstance(right, dict):
                for key, item in left.items():
                    if key not in right:
                        mismatch.append(path + '.' + key)
                        return False
                    if not included(item, right[key], path + '.' + key):
                        return False
                return True
        elif isinstance(left, list):
            if isinstance(right, list) and len(left) == len(right):
                return all(included(a, b, path + '.' + str(number))
                           for number, (a, b) in enumerate(zip(left, right)))
        elif type(left) is type(right) and left == right:
            return True
        mismatch.append(path)
        return False

    spec = copy.deepcopy(value.get('spec', {}))
    # VolumeMount.readOnly is a nonpointer false-default field omitted by the API.
    for container in spec.get('containers', []):
        for mount in container.get('volumeMounts', []):
            mount.setdefault('readOnly', False)
    if (not included(expected, spec) or spec.get('hostNetwork') or spec.get('hostPID') or
            spec.get('hostIPC') or spec.get('initContainers') or
            spec['containers'][0]['securityContext'].get('privileged') or
            spec['containers'][0]['securityContext'].get('capabilities', {}).get('add')):
        error = RuntimeError('native toolbox isolation differs')
        error.observation = {'required_field_mismatch': mismatch[0] if mismatch else None}
        raise error


def require_pod_completion(pod, job_uids):
    metadata, spec, status = pod['metadata'], pod['spec'], pod['status']
    statuses = status.get('containerStatuses', [])
    init = status.get('initContainerStatuses', [])
    if (metadata.get('deletionTimestamp') or not statuses or
            {row['name'] for row in statuses} != {row['name'] for row in spec['containers']} or
            {row['name'] for row in init} != {row['name'] for row in spec.get('initContainers', [])}):
        raise RuntimeError('private fixture container evidence is incomplete')
    if status['phase'] == 'Succeeded':
        if (not any(row.get('kind') == 'Job' and row.get('uid') and row['uid'] in job_uids
                    for row in metadata.get('ownerReferences', [])) or
                spec.get('restartPolicy') not in ('Never', 'OnFailure') or
                any(row.get('state', {}).get('terminated', {}).get('exitCode') != 0
                    for row in statuses + init)):
            raise RuntimeError('private fixture completion is not proven')
    elif (status['phase'] != 'Running' or
          not any(row.get('type') == 'Ready' and row.get('status') == 'True'
                  for row in status.get('conditions', [])) or
          any(not row.get('ready') or not row.get('state', {}).get('running') for row in statuses) or
          any(row.get('state', {}).get('terminated', {}).get('exitCode') != 0 for row in init)):
        raise RuntimeError('private fixture pod is not ready')


class Qualification(images.Qualification):
    def __init__(self, args):
        super().__init__(args)
        self.stage = 'preflight'
        self.evidence = {'accepted': False, 'stages': [], 'warning_observations': [],
                         'scope': 'modern-rados-without-rook-orchestrator',
                         'rook_orchestrator_qualified': False}
        self.fsid = None
        self.osds = None
        self.resource_uids = None
        self.operator_uid = None
        self.last_failure = None

    def command(self, arguments, *, data=None, private=True):
        if arguments and arguments[0] == 'docker':
            if self.anonymous_config.is_symlink():
                raise RuntimeError('native image client configuration became a link')
            images.require_anonymous_config(json.loads(self.anonymous_config.read_text()))
        self.count += 1
        child = subprocess.Popen(arguments, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = child.communicate(data)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        if child.returncode:
            self.last_failure = {'command_number': self.count,
                                 **command_failure(arguments, child.returncode, stderr)}
            raise RuntimeError('private runtime command failed: ' + json.dumps(self.last_failure))
        return stdout

    def apply(self, rows):
        self.identity()
        raw = self.kubectl('apply', '--server-side', '--field-manager=rook-qualification',
                           '--validate=strict', '-f=-', '-o=json', json_output=False,
                           data=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': rows}).encode())
        admitted = command_objects(raw)
        if len(admitted) != len(rows) or any(
                actual.get('kind') != expected['kind'] or any(
                    actual.get('metadata', {}).get(key) != expected['metadata'].get(key)
                    for key in ('name', 'namespace')) for expected, actual in zip(rows, admitted)):
            raise RuntimeError('native apply response identities differ')
        return admitted

    def wait(self, *arguments):
        self.kubectl('wait', *arguments, '--timeout=1200s', json_output=False)

    def tools(self, *arguments, data=None):
        return self.kubectl('exec', '-n', candidate.NAMESPACE, '-i', 'qualification-tools',
                            '-c', 'tools', '--', *arguments, data=data, json_output=False)

    def ceph(self, *arguments):
        return json.loads(self.tools('ceph', *arguments, '-f', 'json'))

    def route(self, fixture):
        rows = json.loads(fixture.colima('ssh', '--', 'sudo', 'ip', '-j', 'route', 'show',
                                        'exact', '10.0.0.0/16'))
        if len(rows) != 1 or rows[0].get('type') != 'blackhole' or rows[0].get('dst') != '10.0.0.0/16':
            raise RuntimeError('owned VM production-network blackhole is absent')

    def create_storage_cluster(self, fixture, inventory):
        self.stage = 'private-three-node-cluster'
        layout = node_layout(inventory, fixture.names)
        if not self.command([self.args.k3d, 'version']).startswith(b'k3d version v5.9.0\n'):
            raise RuntimeError('reviewed k3d version differs')
        info = json.loads(self.command(['docker', 'info', '--format={{json .}}']))
        if (info.get('Name') != 'colima-q' or info.get('OSType') != 'linux' or
                info.get('Architecture') != 'aarch64' or self.command(['docker', 'ps', '-aq']).strip()):
            raise RuntimeError('storage consumer requires the exact empty private daemon')
        fixture.colima('ssh', '--', 'sudo', 'ip', 'route', 'add', 'blackhole', '10.0.0.0/16')
        self.route(fixture)
        if fixture.colima('ssh', '--', 'sh', '-ec', 'test -c /dev/null; stat -c %t:%T /dev/null').strip() != b'1:3':
            raise RuntimeError('owned VM null-device contract differs')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.creation_started = True
        arguments = [self.args.k3d, 'cluster', 'create', self.args.name, '--servers=1', '--agents=2',
                     '--image=' + common.K3S, '--api-port=127.0.0.1:' + str(port),
                     '--subnet=172.31.240.0/24', '--kubeconfig-update-default=false',
                     '--kubeconfig-switch-context=false',
                     '--volume=/run/udev:/run/udev:ro@server:*;agent:*',
                     '--k3s-arg=--cluster-cidr=172.20.0.0/16@server:*',
                     '--k3s-arg=--service-cidr=172.21.0.0/16@server:*']
        arguments.extend('--k3s-arg=--disable=' + name + '@server:*'
                         for name in ('traefik', 'servicelb', 'local-storage', 'metrics-server'))
        # Privileged k3d nodes share guest devices; hide the other two raw paths per node.
        arguments.extend('--volume=/dev/null:' + path + ':ro@' + row['filter']
                         for row in layout for path in row['masked'])
        self.command(arguments)
        raw = self.command([self.args.k3d, 'kubeconfig', 'get', self.args.name])
        with Path(self.env['KUBECONFIG']).open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(raw)
        self.identity()
        self.wait('node', '--all', '--for=condition=Ready')
        self.node_uids = {row['metadata']['name']: row['metadata']['uid']
                          for row in self.kubectl('get', 'nodes')['items']}
        bindings = {}
        for entry in layout:
            device = entry['device']
            node = 'k3d-' + self.args.name + entry['suffix']
            block = Path(device['path']).name
            raw = self.command(['docker', 'exec', node, 'sh', '-ec',
                                f'test -b /dev/{block}; printf \'%s\\n\' '
                                f'"$(cat /sys/class/block/{block}/serial)" '
                                f'"$(cat /sys/class/block/{block}/dev)" '
                                f'"$(cat /sys/class/block/{block}/size)" '
                                f'"$(stat -c %t:%T /dev/{block})"'])
            bindings[node] = require_node_device(raw, device)
            script = '; '.join('test -c ' + path + '; test ! -b ' + path for path in entry['masked'])
            masked = self.command(['docker', 'exec', node, 'sh', '-ec',
                                   script + '; stat -c %t:%T ' + ' '.join(entry['masked'])])
            if masked.splitlines() != [b'1:3', b'1:3']:
                raise RuntimeError('unassigned raw device is not masked in its owned node')
            mounts = json.loads(self.command(['docker', 'inspect', node]))[0]['Mounts']
            observed = {row['Destination']: (row['Type'], row['Source'], row['RW'])
                        for row in mounts if row['Destination'] in entry['masked'] + [device['path']]}
            if observed != {path: ('bind', '/dev/null', False) for path in entry['masked']}:
                raise RuntimeError('owned node device-mask mount identity differs')
            bindings[node]['other_raw_paths_masked'] = entry['masked']
            self.command(['docker', 'exec', node, 'test', '-d', '/run/udev'])
        server = 'k3d-' + self.args.name + '-server-0'
        resolver = common.inherited_resolver(self.command(['docker', 'exec', server, 'cat',
                                                          '/etc/resolv.conf']).decode())
        self.command(['docker', 'exec', server, 'nslookup', 'example.com.', resolver])
        config = self.kubectl('get', 'configmap', 'coredns', '-n', 'kube-system')
        before = config['data']['Corefile']
        if before.count('forward . /etc/resolv.conf') != 1:
            raise RuntimeError('private DNS forwarding contract differs')
        self.kubectl('patch', 'configmap', 'coredns', '-n', 'kube-system', '--type=json', '-p',
                     json.dumps([{'op': 'test', 'path': '/data/Corefile', 'value': before},
                                 {'op': 'replace', 'path': '/data/Corefile',
                                  'value': before.replace('forward . /etc/resolv.conf',
                                                          'forward . ' + resolver)}]))
        self.route(fixture)
        self.evidence.update(cluster_uid=self.cluster_uid, node_uids=self.node_uids,
                             production_route_blackholed=True, assigned_devices_verified=True,
                             node_device_bindings=bindings)

    def operator(self, version):
        self.stage = 'operator-' + version
        values = candidate.OPERATORS[version]
        with urllib.request.urlopen('https://charts.rook.io/release/' + values['package'], timeout=30) as response:
            raw = response.read()
        if hashlib.sha256(raw).hexdigest() != values['package_sha256']:
            raise RuntimeError('reviewed operator package differs')
        package = self.work / values['package']
        package.write_bytes(raw)
        settings = self.work / 'operator-values.yaml'
        settings.write_text(yaml.safe_dump(candidate.operator_values(version)))
        rendered = self.command(['helm', 'template', 'rook-native', str(package),
                                  '--namespace=' + candidate.NAMESPACE, '--kube-version=1.33.6',
                                  '--values=' + str(settings)])
        candidate.require_operator_render(version, rendered)
        rows = [row for row in yaml.safe_load_all(rendered) if row]
        self.apply(rows)
        crds = [row['metadata']['name'] for row in rows if row['kind'] == 'CustomResourceDefinition']
        self.wait('--for=condition=Established', *['crd/' + name for name in crds])
        self.kubectl('rollout', 'status', 'deployment/rook-ceph-operator', '-n', candidate.NAMESPACE,
                     '--timeout=1200s', json_output=False)
        deployment = self.kubectl('get', 'deployment', 'rook-ceph-operator', '-n', candidate.NAMESPACE)
        uid = deployment['metadata']['uid']
        if not uid or (self.operator_uid is not None and uid != self.operator_uid):
            raise RuntimeError('native operator deployment identity changed')
        self.operator_uid = uid
        expected = 'docker.io/rook/ceph:v' + version + '@sha256:' + values['image_sha256']
        if deployment['spec']['template']['spec']['containers'][0]['image'] != expected:
            raise RuntimeError('native operator image differs')

    def clients(self, recreate=False):
        self.stage = 'owned-toolbox'
        if recreate:
            self.kubectl('delete', 'pod', 'qualification-tools', '-n', candidate.NAMESPACE,
                         '--wait=true', '--timeout=180s', json_output=False)
        self.wait('--for=create', 'secret/rook-ceph-mon', '-n', candidate.NAMESPACE)
        self.wait('--for=create', 'configmap/rook-ceph-mon-endpoints', '-n', candidate.NAMESPACE)
        self.apply([toolbox()])
        self.wait('pod/qualification-tools', '-n', candidate.NAMESPACE, '--for=condition=Ready')

    def storage_ready(self):
        deadline = time.monotonic() + 1200
        polls = 0
        while True:
            status = self.ceph('status')
            self.fsid = self.fsid or status['fsid']
            osds = self.ceph('osd', 'dump')['osds']
            pools = self.ceph('osd', 'pool', 'ls', 'detail')
            observation = storage_observation(status, osds, pools)
            polls += 1
            self.evidence['last_storage_observation'] = observation
            self.evidence['storage_readiness_polls'] = polls
            if ceph_checks.replica_state(status, osds, {0, 1, 2}, self.fsid):
                return status, pools
            if time.monotonic() >= deadline:
                raise RuntimeError('native Rook storage did not converge to the required healthy state')
            time.sleep(2)

    def snapshot(self, fixture, identities, requested, generation, label):
        self.stage = label
        self.identity()
        if {row['metadata']['name']: row['metadata']['uid']
            for row in self.kubectl('get', 'nodes')['items']} != self.node_uids:
            raise RuntimeError('private node identities changed')
        self.route(fixture)
        self.wait('cephcluster/' + candidate.NAMESPACE, '-n', candidate.NAMESPACE,
                  '--for=jsonpath={.status.phase}=Ready')
        self.wait('cephcluster/' + candidate.NAMESPACE, '-n', candidate.NAMESPACE,
                  '--for=jsonpath={.status.ceph.health}=HEALTH_OK')
        self.wait('cephblockpool/qualification', '-n', candidate.NAMESPACE,
                  '--for=jsonpath={.status.phase}=Ready')
        cluster = self.kubectl('get', 'cephcluster', candidate.NAMESPACE, '-n', candidate.NAMESPACE)
        pool = self.kubectl('get', 'cephblockpool', 'qualification', '-n', candidate.NAMESPACE)
        candidate.require_admitted_profile(requested[2:], [cluster, pool])
        require_generation(cluster, generation)
        uids = (cluster['metadata']['uid'], pool['metadata']['uid'])
        if self.resource_uids is not None and uids != self.resource_uids:
            raise RuntimeError('Rook resource identities changed')
        self.resource_uids = uids
        status, pools = self.storage_ready()
        if len(status.get('quorum_names', [])) != 3:
            raise RuntimeError('native Rook monitor quorum differs')
        manager = self.ceph('mgr', 'dump')
        if len(manager.get('standbys', [])) != 1:
            raise RuntimeError('native Rook manager redundancy differs')
        if not pools or any(row.get('size') != 2 or row.get('min_size') != 2 for row in pools):
            raise RuntimeError('native Rook pool redundancy differs')
        monitors = self.ceph('mon', 'dump')
        require_mon_security(monitors)
        entities = messenger_entities(monitors, manager)
        for entity in entities:
            for key in MODES:
                if self.tools('ceph', 'config', 'show', entity, key).strip() != b'secure':
                    raise RuntimeError('native Rook messenger encryption differs')
        self.evidence['messenger_entities_verified'] = entities
        require_disabled_orchestrator(self.ceph('mgr', 'module', 'ls'), self.ceph('config', 'dump'))
        keys = self.ceph('auth', 'ls').get('auth_dump', [])
        if len(keys) < 8 or any(row['entity'].startswith('client.csi') for row in keys):
            raise RuntimeError('native Rook key inventory differs')
        for row in keys:
            images.default_key_metadata(row['key'].encode())
        current = {row['entity']: row['key'] for row in keys}
        pods = self.kubectl('get', 'pods', '-n', candidate.NAMESPACE)['items']
        tools = [row for row in pods if row['metadata']['name'] == 'qualification-tools']
        if len(tools) != 1:
            raise RuntimeError('native toolbox identity is ambiguous')
        require_toolbox(tools[0])
        allowed = {candidate.CEPH_IMAGE, *('docker.io/rook/ceph:v' + version + '@sha256:' +
                                         value['image_sha256']
                                         for version, value in candidate.OPERATORS.items())}
        for pod in pods:
            declared = {row['name']: row['image'] for row in pod['spec']['containers']}
            for row in pod.get('status', {}).get('containerStatuses', []):
                image = declared[row['name']]
                if image not in allowed or not row.get('imageID', '').endswith(image[image.index('@'):]):
                    raise RuntimeError('native Rook running image digest differs')
        osd_pods = [row for row in pods if row['metadata'].get('labels', {}).get('app') == 'rook-ceph-osd']
        selected = requested[2]['spec']['storage']['nodes']
        device_by_node = {row['name']: row['devices'][0]['name'] for row in selected}
        observed_osds = {}
        if len(osd_pods) != 3 or {row['spec']['nodeName'] for row in osd_pods} != set(device_by_node):
            raise RuntimeError('native Rook OSD pod count or assigned nodes differ')
        for pod in osd_pods:
            number = int(pod['metadata']['labels']['ceph-osd-id'])
            raw = self.kubectl('exec', '-n', candidate.NAMESPACE, pod['metadata']['name'],
                               '-c', 'osd', '--', 'ceph-volume', 'raw', 'list', '--format=json',
                               json_output=False)
            observed_osds[number] = require_osd_device(json.loads(raw), number, self.fsid,
                                                       device_by_node[pod['spec']['nodeName']])
        if set(observed_osds) != {0, 1, 2} or (self.osds is not None and observed_osds != self.osds):
            raise RuntimeError('native Rook OSD UUID identities changed')
        self.osds = observed_osds
        for identity in identities.values():
            if disks.backing_identity(Path(identity['path'])) != {
                    key: identity[key] for key in ('device', 'inode', 'bytes')}:
                raise RuntimeError('native Rook backing file identity changed')
        disks.qemu_observation(fixture.root, identities)
        for pod in pods:
            for container in pod['spec'].get('containers', []) + pod['spec'].get('initContainers', []):
                if 'mon-auth-emergency-allowed-ciphers' in json.dumps(container.get('args', [])):
                    raise RuntimeError('native Rook enabled emergency cipher arguments')
        for kind in ('deployments', 'daemonsets'):
            for row in self.kubectl('get', kind, '-n', candidate.NAMESPACE)['items']:
                status_row = row.get('status', {})
                desired = row['spec'].get('replicas', status_row.get('desiredNumberScheduled'))
                ready = status_row.get('readyReplicas', status_row.get('numberReady', 0))
                if (not desired or ready != desired or
                        status_row.get('observedGeneration', 0) < row['metadata']['generation']):
                    raise RuntimeError('native Rook controller is not ready')
                if kind == 'deployments' and (
                        status_row.get('updatedReplicas') != desired or
                        status_row.get('availableReplicas') != desired or status_row.get('unavailableReplicas', 0)):
                    raise RuntimeError('native Rook deployment rollout is incomplete')
                if kind == 'daemonsets' and (
                        status_row.get('updatedNumberScheduled') != desired or
                        status_row.get('numberAvailable') != desired or status_row.get('numberUnavailable', 0)):
                    raise RuntimeError('native Rook daemonset rollout is incomplete')
        jobs = self.kubectl('get', 'jobs', '-A')['items']
        job_uids = set()
        for job in jobs:
            if (job.get('status', {}).get('failed', 0) or job.get('status', {}).get('active', 0) or
                    job.get('status', {}).get('succeeded', 0) < job['spec'].get('completions', 1)):
                raise RuntimeError('private fixture job is failed or incomplete')
            if not job['metadata'].get('uid'):
                raise RuntimeError('private fixture job identity is absent')
            job_uids.add(job['metadata']['uid'])
        for pod in self.kubectl('get', 'pods', '-A')['items']:
            require_pod_completion(pod, job_uids)
        warnings = self.kubectl('get', 'events', '-A', '--field-selector=type=Warning')['items']
        self.evidence['warning_reasons'] = sorted({row.get('reason', '') for row in warnings})
        self.evidence['warning_observations'].append({'stage': label, 'events': [
            {'uid': row['metadata']['uid'], 'reason': row.get('reason'), 'count': row.get('count'),
             'first': row.get('firstTimestamp'), 'last': row.get('lastTimestamp'),
             'event_time': row.get('eventTime'), 'series': row.get('series'),
             'object': {key: row.get('involvedObject', {}).get(key)
                        for key in ('kind', 'namespace', 'name', 'uid')}} for row in warnings]})
        if self.kubectl('get', 'csidrivers')['items']:
            raise RuntimeError('native no-CSI fixture has a CSI driver')
        crds = self.kubectl('get', 'crds')['items']
        if any(row['spec']['group'] == 'csi.ceph.io' for row in crds):
            raise RuntimeError('native no-CSI fixture has CSI operator CRDs')
        self.evidence['stages'].append({'name': label, 'health': 'HEALTH_OK', 'generation': generation,
                                        'fsid': self.fsid, 'osd_uuids': dict(observed_osds),
                                        'resource_uids': list(uids), 'modern_key_count': len(keys),
                                        'all_pools_size_and_min_size': 2})
        return current

    def objects(self, write=False):
        used = set()
        for number in range(64):
            name = f'replica-{number:03d}'
            payload = hashlib.sha256(str(number).encode()).digest() * 512
            if write:
                self.tools('sh', '-ec', 'cat > /work/payload', data=payload)
                self.tools('rados', '-p', 'qualification', 'put', name, '/work/payload')
            self.tools('rados', '-p', 'qualification', 'get', name, '/work/readback')
            if self.tools('cat', '/work/readback') != payload:
                raise RuntimeError('native Rook object bytes differ')
            used.update(ceph_checks.replica_placement(self.ceph('osd', 'map', 'qualification', name),
                                                      name, {0, 1, 2}))
        if used != {0, 1, 2}:
            raise RuntimeError('native Rook object placement omits an OSD')
        self.evidence['stages'][-1].update(objects_verified=64, two_copy_placement_verified=True)

    def run(self, fixture, inventory, identities):
        """The tracked parent must destroy the entire VM on every outcome."""
        disks.require_config(yaml.safe_load((fixture.root / 'l/colima-q/lima.yaml').read_text()),
                             'qemu', 'storage')
        self.create_storage_cluster(fixture, inventory)
        requested = resources(self.args.name, fixture.names[0][:-2], inventory)
        self.apply(requested[:2])
        self.operator('1.20.9')
        self.apply(requested[2:])
        self.wait('cephcluster/' + candidate.NAMESPACE, '-n', candidate.NAMESPACE,
                  '--for=jsonpath={.status.phase}=Ready')
        self.clients()
        self.snapshot(fixture, identities, requested, 1, 'initial')
        self.objects(write=True)
        before = self.kubectl('get', 'pods', '-n', candidate.NAMESPACE,
                               '-l', 'app=rook-ceph-operator')['items']
        if len(before) != 1:
            raise RuntimeError('native operator pod identity is ambiguous')
        self.kubectl('rollout', 'restart', 'deployment/rook-ceph-operator', '-n', candidate.NAMESPACE,
                     json_output=False)
        self.kubectl('rollout', 'status', 'deployment/rook-ceph-operator', '-n', candidate.NAMESPACE,
                     '--timeout=1200s', json_output=False)
        after = self.kubectl('get', 'pods', '-n', candidate.NAMESPACE,
                              '-l', 'app=rook-ceph-operator')['items']
        if len(after) != 1 or after[0]['metadata']['uid'] == before[0]['metadata']['uid']:
            raise RuntimeError('native operator restart was not observed')
        previous_keys = self.snapshot(fixture, identities, requested, 1, 'operator-restart')
        self.objects()
        requested = copy.deepcopy(requested)
        requested[2]['spec']['security']['cephx']['daemon']['keyGeneration'] = 2
        self.apply([requested[2]])
        for name in CORE_KEYS:
            self.wait('cephcluster/' + candidate.NAMESPACE, '-n', candidate.NAMESPACE,
                      '--for=jsonpath={.status.cephx.' + name + '.keyGeneration}=2')
        self.clients(recreate=True)
        current_keys = self.snapshot(fixture, identities, requested, 2, 'daemon-generation-two')
        core = {name for name in previous_keys if name == 'client.admin' or
                name == 'mon.' or name.startswith(('mgr.', 'osd.'))}
        if len(core) < 7 or any(name not in current_keys or current_keys[name] == previous_keys[name]
                                for name in core):
            raise RuntimeError('native Rook core key change was not observed')
        del previous_keys, current_keys
        self.objects()
        self.operator('1.21.0')
        self.snapshot(fixture, identities, requested, 2, 'operator-1.21.0')
        self.objects()
        require_no_warnings(self.evidence['warning_observations'])
        self.evidence.update(accepted=True, production_writes=0, raw_key_output_retained=False,
                             physical_fault_domains_qualified=False, kernel_csi_qualified=False,
                             legacy_ticket_transition_qualified=False, whole_vm_cleanup_required=True)
        self.evidence['result_sha256'] = hashlib.sha256(json.dumps(self.evidence, sort_keys=True).encode()).hexdigest()
        return self.evidence
