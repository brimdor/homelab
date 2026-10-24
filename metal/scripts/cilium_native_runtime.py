#!/usr/bin/env python3
"""Exercise only the disconnected native Fedora fixture's Cilium datapath."""

import base64
import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import sys
import tempfile
import time
import tomllib
import traceback

from nfs_csi_native_runtime import native, kubectl, get, apply, domains


NODE = 'qualification-fedora44'
NAMESPACE = 'cilium-native-client'
ASSETS = Path('/var/tmp/qualification-cilium-assets')
K3S = '/usr/local/bin/k3s'
STATE = Path('/work/native-cilium-state.json')
EVIDENCE = {'accepted': False, 'stages': []}
SERVER = '''from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  body=b'qualification-cilium-complete-payload\\n'
  self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
'''
PAYLOAD = hashlib.sha256(b'qualification-cilium-complete-payload\n').hexdigest()


def persist(stage, **values):
    EVIDENCE['stages'].append({'stage': stage, 'at_ns': time.time_ns(), **values})
    Path('/work/native-cilium-evidence.json').write_text(json.dumps(EVIDENCE, indent=2))


def sha_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def ordinary_pod(name, image, command):
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {
        'name': name, 'namespace': NAMESPACE, 'labels': {'role': name}}, 'spec': {
            'automountServiceAccountToken': False,
            'securityContext': {'runAsUser': 1000, 'runAsGroup': 1000, 'runAsNonRoot': True,
                                'seccompProfile': {'type': 'RuntimeDefault'}},
            'containers': [{'name': name, 'image': image, 'imagePullPolicy': 'Never',
                            'command': ['python3', '-B', '-c', command],
                            'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                                'capabilities': {'drop': ['ALL']}},
                            'readinessProbe': {'tcpSocket': {'port': 8080}, 'periodSeconds': 2}}]
        }}


def agent_pod():
    pods = get('pods', '-n', 'kube-system', '-l', 'k8s-app=cilium')['items']
    assert len(pods) == 1 and not pods[0]['metadata'].get('deletionTimestamp')
    return pods[0]


def agent(*args):
    return kubectl('exec', '-n', 'kube-system', agent_pod()['metadata']['name'], '-c', 'cilium-agent', '--', *args)


def cni_identity(configuration, info):
    entries = [value['cni'] for value in tomllib.loads(configuration)['plugins'].values() if 'cni' in value]
    assert len(entries) <= 1
    settings, active = info['config']['cni'], info['cniconfig']
    assert not (settings.get('binDir') and settings.get('binDirs'))
    directories = settings.get('binDirs') or ([settings['binDir']] if settings.get('binDir') else [])
    assert isinstance(directories, list) and directories and all(isinstance(value, str) for value in directories)
    assert len(set(directories)) == len(directories) and all(Path(value).is_absolute() for value in directories)
    directory = Path(settings['confDir'])
    assert directory.is_absolute() and directory.is_dir()
    assert active['PluginDirs'] == directories and active['PluginConfDir'] == str(directory)
    assert settings['maxConfNum'] == active['PluginMaxConfNum'] == 1
    for condition in ('RuntimeReady', 'NetworkReady'):
        assert [row['status'] for row in info['status']['conditions'] if row['type'] == condition] == [True]
    if entries:
        explicit = entries[0]
        assert not ('bin_dir' in explicit and 'bin_dirs' in explicit)
        if 'bin_dir' in explicit or 'bin_dirs' in explicit:
            assert explicit.get('bin_dirs', [explicit['bin_dir']] if 'bin_dir' in explicit else []) == directories
        if 'conf_dir' in explicit:
            assert explicit['conf_dir'] == str(directory)
        if 'max_conf_num' in explicit:
            assert explicit['max_conf_num'] == 1
    files = sorted(path for path in directory.iterdir() if path.suffix in ('.conf', '.conflist', '.json'))
    assert len(files) == 1 and files[0].is_file()
    configuration = json.loads(files[0].read_bytes())
    plugins = configuration.get('plugins', [configuration])
    assert len(plugins) == 1 and plugins[0]['type'] == 'cilium-cni'
    loaded = [row['Config'] for row in active['Networks'] if row['IFName'] != 'lo']
    assert len(loaded) == 1 and json.loads(loaded[0]['Source']) == configuration
    assert [plugin['Network']['type'] for plugin in loaded[0]['Plugins']] == ['cilium-cni']
    binaries = [Path(value) / 'cilium-cni' for value in directories if (Path(value) / 'cilium-cni').is_file()]
    assert len(binaries) == 1 and os.access(binaries[0], os.X_OK)
    return {'containerd_conf_dir': str(directory), 'containerd_bin_dirs': directories,
            'native_cri_ready_and_loaded_config_verified': True, 'toml_cni_explicit': bool(entries),
            'active_configuration': str(files[0]), 'configuration_sha256': sha_file(files[0]),
            'binary': str(binaries[0]), 'binary_sha256': sha_file(binaries[0])}


def api_credentials(value):
    assert all(len(value[key]) == 1 for key in ('clusters', 'users', 'contexts'))
    cluster, user, context = (value[key][0] for key in ('clusters', 'users', 'contexts'))
    assert value['current-context'] == context['name']
    assert context['context']['cluster'] == cluster['name'] and context['context']['user'] == user['name']
    settings = cluster['cluster']
    assert set(settings) == {'server', 'certificate-authority-data'}
    assert settings['server'] == 'https://127.0.0.1:6443'
    assert set(user['user']) == {'client-certificate-data', 'client-key-data'}
    encoded = [settings['certificate-authority-data'], user['user']['client-certificate-data'],
               user['user']['client-key-data']]
    assert all(isinstance(item, str) and len(item) <= 65536 for item in encoded)
    return tuple(base64.b64decode(item, validate=True) for item in encoded)


def native_api_tls():
    value = json.loads(native(K3S, 'kubectl', 'config', 'view', '--raw', '--minify', '--flatten', '-o', 'json'))
    authority, certificate, key = api_credentials(value)
    context = ssl.create_default_context(cadata=authority.decode('ascii'))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    with tempfile.TemporaryDirectory(prefix='qualification-api-', dir='/run') as directory:
        paths = [Path(directory) / name for name in ('certificate.pem', 'key.pem')]
        for path, content in zip(paths, (certificate, key)):
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
                output.write(content)
        context.load_cert_chain(str(paths[0]), str(paths[1]))
    assert not Path(directory).exists()
    return context, {'server': 'https://127.0.0.1:6443', 'certificate_and_hostname_verified': True,
                     'temporary_keyfiles_removed': True, 'ca_sha256': hashlib.sha256(authority).hexdigest(),
                     'client_certificate_sha256': hashlib.sha256(certificate).hexdigest()}


def api_response(context, path):
    assert path in ('/readyz', '/api/v1/nodes/' + NODE + '/proxy/healthz')
    connection = http.client.HTTPSConnection('127.0.0.1', 6443, context=context, timeout=10)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        body = response.read(65537)
        assert len(body) <= 65536
        return response.status, body
    finally:
        connection.close()


def wait_api_ready(path='/readyz'):
    kubelet_path = '/api/v1/nodes/' + NODE + '/proxy/healthz'
    assert path in ('/readyz', kubelet_path)
    context, trust = native_api_tls()
    EVIDENCE.setdefault('api_readiness_tls', []).append(trust)
    started = time.monotonic()
    attempts = []
    EVIDENCE.setdefault('api_readiness', []).append(attempts)
    while True:
        try:
            status, body = api_response(context, path)
        except (ConnectionRefusedError, ConnectionResetError, http.client.RemoteDisconnected, TimeoutError) as error:
            attempts.append({'elapsed_seconds': time.monotonic() - started, 'transport': type(error).__name__})
        else:
            attempts.append({'path': path, 'elapsed_seconds': time.monotonic() - started, 'http_status': status,
                             'body_bytes': len(body), 'body_sha256': hashlib.sha256(body).hexdigest()})
            if status == 200:
                assert body.strip() == b'ok'
                attempts[-1]['ready'] = True
                return
            # Kubernetes explicitly defines HTTP status, not verbose text, as the machine contract.
            if status not in ((500, 502, 503) if path == kubelet_path else (500, 503)):
                raise RuntimeError('native API readiness HTTP status refused: ' + str(status))
        if time.monotonic() - started >= 900:
            raise RuntimeError('native API did not become ready within 900 seconds')
        time.sleep(1)


def components():
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
    wait_api_ready()
    for kind, name in (('daemonset', 'cilium'), ('daemonset', 'cilium-envoy'),
                       ('deployment', 'cilium-operator'), ('deployment', 'hubble-relay'),
                       ('deployment', 'coredns')):
        kubectl('rollout', 'status', kind + '/' + name, '-n', 'kube-system', '--timeout=900s')
    kubectl('wait', '--for=condition=Ready', 'node/' + NODE, '--timeout=900s')
    # API readiness and a retained Node condition do not prove the kubelet tunnel is usable after reboot.
    wait_api_ready('/api/v1/nodes/' + NODE + '/proxy/healthz')
    nodes = get('nodes')['items']
    assert len(nodes) == 1 and nodes[0]['metadata']['name'] == NODE
    status = json.loads(agent('cilium-dbg', 'status', '--output', 'json'))
    assert status['cilium']['state'] == 'Ok' and status['kubernetes']['state'] == 'Ok'
    assert str(status['kube-proxy-replacement']['mode']).lower() == 'true'
    assert status['hubble']['state'] == 'Ok'
    config = json.loads(agent('cilium-dbg', 'config', '--output', 'json'))
    all_domains = []
    for label in ('k8s-app=cilium', 'k8s-app=cilium-envoy', 'io.cilium/app=operator', 'k8s-app=hubble-relay', 'k8s-app=kube-dns'):
        pods = get('pods', '-n', 'kube-system', '-l', label)['items']
        assert len(pods) == 1
        all_domains.extend(domains(pods[0]))
    assert all(r['context'].split(':')[2] == 'spc_t' for r in all_domains
               if r['container'] in ('cilium-agent', 'cilium-envoy'))
    assert all(r['context'].split(':')[2] == 'container_t' for r in all_domains
               if r['container'] not in ('cilium-agent', 'cilium-envoy'))
    pid = int(native('systemctl', 'show', 'qualification-k3s.service', '--property=MainPID', '--value'))
    assert pid > 1 and Path('/proc/' + str(pid) + '/attr/current').read_text().split(':')[2] == 'container_runtime_t'
    runtime = Path('/var/lib/rancher/k3s/agent/etc/containerd/config.toml').read_text()
    assert re.search(r'^\s*enable_selinux\s*=\s*true\s*$', runtime, re.M)
    return {'node_uid': nodes[0]['metadata']['uid'], 'cluster_uid': get('namespace', 'kube-system')['metadata']['uid'],
            'agent_uid': agent_pod()['metadata']['uid'], 'domains': all_domains,
            'kube_proxy_replacement': True, 'hubble_ready': True,
            'native_cni': cni_identity(runtime, json.loads(native(K3S, 'crictl', 'info'))),
            'config_sha256': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()}


def setup(inputs):
    assert native('hostname').strip() == NODE.encode()
    assert native('uname', '-r').strip() == b'7.2.11-200.fc44.x86_64'
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1' and not Path('/work').exists()
    Path('/work').mkdir(mode=0o700)
    for name, expected in inputs['assets'].items():
        assert sha_file(ASSETS / name) == expected
    configuration = Path('/boot/config-7.2.11-200.fc44.x86_64').read_text()
    required = ('BPF', 'BPF_EVENTS', 'BPF_SYSCALL', 'NET_CLS_BPF', 'BPF_JIT', 'NET_CLS_ACT',
                'NET_SCH_INGRESS', 'DEBUG_INFO_BTF', 'CGROUPS', 'CGROUP_BPF', 'PERF_EVENTS', 'SCHEDSTATS')
    assert all(re.search(r'^CONFIG_' + name + r'=[ym]$', configuration, re.M) for name in required)
    runtime = Path('/var/lib/rancher/k3s')
    expected_dirs = {'data', 'agent', 'agent/containerd', 'agent/containerd/io.containerd.snapshotter.v1.overlayfs',
                     'agent/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots'}
    assert runtime.is_dir() and {str(p.relative_to(runtime)) for p in runtime.rglob('*')} == expected_dirs
    assert all(p.is_dir() and not p.is_symlink() for p in runtime.rglob('*')) and not Path(K3S).exists()
    shutil.move(str(ASSETS / 'k3s'), K3S)
    Path(K3S).chmod(0o755)
    native('chcon', '-u', 'system_u', '-r', 'object_r', '-t', 'container_runtime_exec_t', K3S)
    assert os.getxattr(K3S, 'security.selinux').decode().split(':')[2] == 'container_runtime_exec_t'
    assert b'v1.33.6+k3s1' in native(K3S, '--version')
    images = runtime / 'agent/images'
    images.mkdir(parents=True)
    shutil.move(str(ASSETS / 'airgap.tar.zst'), str(images / 'airgap.tar.zst'))
    for number in range(len(inputs['records'])):
        shutil.move(str(ASSETS / ('image-' + str(number) + '.tar')), str(images / ('image-' + str(number) + '.tar')))
    assert json.loads(native('ip', '-j', 'route', 'show', 'default')) == []
    route = Path('/etc/systemd/system/qualification-airgap-route.service')
    unit = Path('/etc/systemd/system/qualification-k3s.service')
    assert not route.exists() and not unit.exists()
    route.write_text('[Unit]\nBefore=qualification-k3s.service\n[Service]\nType=oneshot\nRemainAfterExit=yes\n'
                     'ExecStart=/usr/sbin/ip link add dummy0 type dummy\nExecStart=/usr/sbin/ip link set dummy0 up\n'
                     'ExecStart=/usr/sbin/ip addr add 203.0.113.254/31 dev dummy0\n'
                     'ExecStart=/usr/sbin/ip route add default via 203.0.113.255 dev dummy0 metric 1000\n')
    unit.write_text('[Unit]\nAfter=network-online.target qualification-airgap-route.service\n'
                    'Wants=network-online.target\nRequires=qualification-airgap-route.service\n[Service]\n'
                    'Type=notify\nKillMode=process\nDelegate=yes\nLimitNOFILE=1048576\nTasksMax=infinity\n'
                    'TimeoutStartSec=0\nExecStart=' + K3S + ' server --cluster-init --selinux '
                    '--write-kubeconfig-mode=600 --disable=traefik,servicelb,local-storage,metrics-server '
                    '--disable-helm-controller --disable-network-policy --disable-kube-proxy '
                    '--flannel-backend=none --prefer-bundled-bin\n[Install]\nWantedBy=multi-user.target\n')
    native('systemctl', 'daemon-reload')
    native('systemctl', 'enable', '--now', 'qualification-k3s.service')
    kubectl('wait', '--for=create', 'node/' + NODE, '--timeout=900s')
    for number, record in enumerate(inputs['records']):
        repository = record['image'].rsplit(':', 1)[0]
        native(K3S, 'ctr', 'images', 'import', '--local', '--digests', '--all-platforms', '--no-unpack',
               '--base-name', repository, str(images / ('image-' + str(number) + '.tar')))
        image = json.loads(native(K3S, 'crictl', 'inspecti', repository + '@' + record['digest']))
        assert repository + '@' + record['digest'] in image['status']['repoDigests']
    apply(*inputs['objects'])
    current = components()
    persist('native-cilium-components', **current)
    record = inputs['records'][-1]
    image = record['image'].rsplit(':', 1)[0] + '@' + record['digest']
    client = ordinary_pod('client', image, 'import time;time.sleep(86400)')
    del client['spec']['containers'][0]['readinessProbe']
    apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
        'name': NAMESPACE, 'labels': {'pod-security.kubernetes.io/enforce': 'restricted'}}},
        ordinary_pod('server', image, SERVER), client,
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'echo', 'namespace': NAMESPACE},
         'spec': {'selector': {'role': 'server'}, 'ports': [{'port': 8080, 'targetPort': 8080}]}})
    STATE.write_text(json.dumps({'node_uid': current['node_uid'], 'cluster_uid': current['cluster_uid'],
                                 'booleans_sha256': hashlib.sha256(native('getsebool', '-a')).hexdigest()}))


def traffic(address, path='/allowed'):
    program = '''import hashlib,json,urllib.request,urllib.error,socket
try:
 with urllib.request.urlopen(URL,timeout=3)as response:
  body=response.read();print(json.dumps({'status':response.status,'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)}))
except urllib.error.HTTPError as error:print(json.dumps({'status':error.code}))
except (OSError,urllib.error.URLError,socket.timeout)as error:print(json.dumps({'network_error':type(error).__name__}))
'''
    return json.loads(kubectl('exec', '-n', NAMESPACE, 'client', '--', 'python3', '-B', '-c',
                             'URL=' + repr('http://' + address + ':8080' + path) + '\n' + program))


def require_http(address, path, expected):
    deadline = time.monotonic() + 45
    while True:
        value = traffic(address, path)
        if value.get('status') == expected:
            if expected == 200:
                assert value.get('sha256') == PAYLOAD and value.get('bytes') == 38
            return value
        if time.monotonic() >= deadline:
            raise RuntimeError('native HTTP behavior differs: ' + json.dumps(value))
        time.sleep(1)


def matching_flows(records, *, since, denial=False, blocked_http=False):
    accepted = []
    for record in records:
        flow = record.get('flow', {})
        source, destination = flow.get('source', {}), flow.get('destination', {})
        if ({(source.get('namespace'), source.get('pod_name')),
             (destination.get('namespace'), destination.get('pod_name'))} != {
                (NAMESPACE, 'client'), (NAMESPACE, 'server')}):
            continue
        timestamp = datetime.datetime.fromisoformat(flow['time'].replace('Z', '+00:00')).timestamp()
        if timestamp < since:
            continue
        if denial and (flow.get('verdict') != 'DROPPED' or flow.get('drop_reason_desc') != 'POLICY_DENIED'):
            continue
        if blocked_http:
            http = flow.get('l7', {}).get('http', {})
            if http.get('code') != 403 or not http.get('url', '').endswith('/blocked'):
                continue
        accepted.append(flow)
    return accepted


def flow_evidence(started, **requirements):
    timestamp = datetime.datetime.fromtimestamp(started, datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
    deadline = time.monotonic() + 30
    while True:
        raw = agent('hubble', 'observe', '--since', timestamp, '--last', '250', '--output', 'json')
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        matches = matching_flows(records, since=started, **requirements)
        if matches:
            return {'matching_flows': len(matches), 'flow_sha256': hashlib.sha256(raw).hexdigest(),
                    'first_time': matches[0]['time'], 'last_time': matches[-1]['time']}
        if time.monotonic() >= deadline:
            raise RuntimeError('fresh matching native Hubble evidence missing')
        time.sleep(1)


def policy(name, role, direction):
    return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
            'metadata': {'name': name, 'namespace': NAMESPACE}, 'spec': {
                'podSelector': {'matchLabels': {'role': role}}, 'policyTypes': [direction], direction.lower(): []}}


def exercise(phase):
    for name in ('client', 'server'):
        kubectl('wait', '--for=condition=Ready', 'pod/' + name, '-n', NAMESPACE, '--timeout=900s')
    pods = {name: get('pod', name, '-n', NAMESPACE) for name in ('client', 'server')}
    contexts = {name: domains(pod) for name, pod in pods.items()}
    assert all(len(values) == 1 and values[0]['context'].split(':')[2] == 'container_t' for values in contexts.values())
    assert contexts['client'][0]['context'].split(':', 3)[3] != contexts['server'][0]['context'].split(':', 3)[3]
    service = get('service', 'echo', '-n', NAMESPACE)
    address = service['spec']['clusterIP']
    direct = pods['server']['status']['podIP']
    baseline = [require_http(target, '/allowed', 200) for target in (address, direct)]
    dns = json.loads(kubectl('exec', '-n', NAMESPACE, 'client', '--', 'python3', '-B', '-c',
                           "import socket,json;print(json.dumps(sorted({v[4][0]for v in socket.getaddrinfo('echo.cilium-native-client.svc.cluster.local',8080,socket.AF_INET)})))"))
    assert dns == [address]
    persist(phase + '-allow-dns-service', payloads=baseline, dns=dns, domains=contexts)
    for name, role, direction in (('ingress-deny', 'server', 'Ingress'), ('egress-deny', 'client', 'Egress')):
        apply(policy(name, role, direction))
        started = time.time()
        deadline = time.monotonic() + 45
        while 'network_error' not in traffic(address):
            if time.monotonic() >= deadline:
                raise RuntimeError('native policy failed to deny ' + direction)
            time.sleep(1)
        flows = flow_evidence(started, denial=True)
        persist(phase + '-' + name, **flows)
        kubectl('delete', 'networkpolicy', name, '-n', NAMESPACE, '--wait=true')
        require_http(address, '/allowed', 200)
    apply({'apiVersion': 'cilium.io/v2', 'kind': 'CiliumNetworkPolicy',
           'metadata': {'name': 'http-path', 'namespace': NAMESPACE}, 'spec': {
               'endpointSelector': {'matchLabels': {'role': 'server'}}, 'ingress': [{
                   'fromEndpoints': [{'matchLabels': {'role': 'client'}}], 'toPorts': [{
                       'ports': [{'port': '8080', 'protocol': 'TCP'}],
                       'rules': {'http': [{'method': 'GET', 'path': '^/allowed$'}]}}]}]}})
    started = time.time()
    allowed = require_http(address, '/allowed', 200)
    blocked = require_http(address, '/blocked', 403)
    flows = flow_evidence(started, blocked_http=True)
    persist(phase + '-l7', allowed=allowed, blocked=blocked, **flows)
    kubectl('delete', 'ciliumnetworkpolicy', 'http-path', '-n', NAMESPACE, '--wait=true')
    require_http(address, '/blocked', 200)
    for name, pod in pods.items():
        current = get('pod', name, '-n', NAMESPACE)
        assert current['metadata']['uid'] == pod['metadata']['uid']
        assert current['status']['containerStatuses'][0]['containerID'] == pod['status']['containerStatuses'][0]['containerID']
        assert current['status']['containerStatuses'][0]['restartCount'] == pod['status']['containerStatuses'][0]['restartCount']


def main(phase):
    assert os.geteuid() == 0 and native('hostname').strip() == NODE.encode()
    assert native('uname', '-r').strip() == b'7.2.11-200.fc44.x86_64'
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
    inputs = json.loads((ASSETS / 'input.json').read_bytes())
    if phase == 'initial':
        setup(inputs)
    else:
        assert phase == 'after-reboot' and STATE.is_file()
    current = components()
    state = json.loads(STATE.read_text())
    assert all(current[k] == state[k] for k in ('node_uid', 'cluster_uid'))
    persist(phase + '-native-components', **current)
    exercise(phase)
    if phase == 'initial':
        previous = agent_pod()['metadata']['uid']
        kubectl('delete', 'pod', agent_pod()['metadata']['name'], '-n', 'kube-system', '--wait=true')
        replaced = components()
        assert replaced['agent_uid'] != previous
        assert all(replaced[k] == current[k] for k in ('node_uid', 'cluster_uid'))
        exercise('agent-replacement')
        persist('agent-replacement-identities', **replaced)
    booleans = hashlib.sha256(native('getsebool', '-a')).hexdigest()
    assert booleans == state['booleans_sha256']
    assert not native('rpm', '-V', 'container-selinux', 'k3s-selinux')
    packages = native('rpm', '-q', 'container-selinux', 'k3s-selinux').decode().splitlines()
    EVIDENCE.update(accepted=True, node_uid=current['node_uid'], cluster_uid=current['cluster_uid'],
                    packages=packages, booleans_sha256=booleans, images=inputs['records'],
                    native_cni=current['native_cni'],
                    selinux_enforcing=True, fixture_only=True, production_and_multihost_unqualified=True)
    return EVIDENCE


if __name__ == '__main__':
    try:
        result = main(sys.argv[1])
    except BaseException as error:
        EVIDENCE.update(error=type(error).__name__ + ': ' + str(error))
        EVIDENCE['failure_location'] = [{'file': Path(frame.filename).name, 'line': frame.lineno,
                                         'function': frame.name}
                                        for frame in traceback.extract_tb(error.__traceback__)]
        result = EVIDENCE
    print(json.dumps(result), flush=True)
