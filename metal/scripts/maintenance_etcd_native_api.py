"""Read only cycle ownership through existing server credentials and a survivor."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from maintenance_actor_hold import require, safe
from maintenance_k3s_binary import record
from maintenance_k3s_contract import SHA256


ENDPOINTS = {'charmander': 'https://10.0.20.11:6443',
             'squirtle': 'https://10.0.20.12:6443',
             'bulbasaur': 'https://10.0.20.13:6443'}
RESOURCES = ('/apis/apps/v1/namespaces/kured/daemonsets/kured',
             '/api/v1/namespaces/kured/pods', '/api/v1/nodes')
REGISTRY_PODS = '/api/v1/namespaces/zot/pods'


class Reader:
    def __init__(self, node, endpoint, native, credential=Path('/etc/rancher/k3s/k3s.yaml'),
                 executable=Path('/usr/local/bin/k3s'), scratch_parent=Path('/var/tmp')):
        require(node in ENDPOINTS and endpoint in ENDPOINTS.values() and endpoint != ENDPOINTS[node],
                'owned server requires an original surviving HTTPS API endpoint')
        self.native, self.credential = native, Path(credential)
        self.executable, self.endpoint = Path(executable), endpoint
        self.original = self.credential_record()
        require(record(self.executable)['sha256'] == SHA256['v1.33.10+k3s1'],
                'native API reader requires the published SOURCE executable')
        safe(scratch_parent)
        self.scratch = Path(tempfile.mkdtemp(prefix='maintenance103-etcd-api-', dir=scratch_parent))
        self.scratch.chmod(0o700)
        try:
            value = self.query('config', 'view', '--minify', '-o', 'json')
            require(len(value['clusters']) == len(value['users']) == len(value['contexts']) == 1,
                    'native API trust context differs')
            cluster, user = value['clusters'][0]['cluster'], value['users'][0]['user']
            require(cluster.get('certificate-authority-data') and not cluster.get('insecure-skip-tls-verify') and
                    not cluster.get('proxy-url') and set(user) == {'client-certificate-data', 'client-key-data'} and
                    all(user.values()), 'native API requires existing verified CA and client certificate')
        except BaseException:
            self.close()
            raise

    def credential_record(self):
        safe(self.credential)
        descriptor = os.open(self.credential, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1 and
                    stat.S_IMODE(info.st_mode) == 0o600, 'unsafe original native kubeconfig')
            value = {'identity': [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns],
                     'sha256': hashlib.sha256(source.read()).hexdigest()}
            after = os.fstat(source.fileno())
            require(value['identity'] == [after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns],
                    'native kubeconfig changed during observation')
        return value

    def query(self, *args):
        require(args == ('config', 'view', '--minify', '-o', 'json') or
                len(args) == 3 and args[:2] == ('get', '--raw') and args[2] in (*RESOURCES, REGISTRY_PODS),
                'native cycle API permits only original ownership reads')
        require(self.credential_record() == self.original, 'original native kubeconfig changed')
        value = json.loads(self.native(str(self.executable), 'kubectl', '--kubeconfig=' + str(self.credential),
            '--cache-dir=' + str(self.scratch / 'cache'), '--request-timeout=30s', '--server=' + self.endpoint, *args))
        require(self.credential_record() == self.original, 'original native kubeconfig changed')
        return value

    def snapshot(self):
        values = [self.query('get', '--raw', path) for path in RESOURCES]
        return values[0], values[1]['items'], values[2]['items']

    def close(self):
        safe(self.scratch)
        shutil.rmtree(self.scratch)
        require(not self.scratch.exists(), 'owned native API cache cleanup failed')
