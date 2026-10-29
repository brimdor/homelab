"""Fresh reads through a private, GET-only kubectl Unix-socket proxy.

Mutations and exec retain the normal kubectl path. No API credentials leave
kubectl, and no read is cached between ownership or drain checks.
"""

import http.client
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import tempfile
import time
from urllib.parse import quote, urlencode

from maintenance_coordination import Kubectl, require


RESOURCES = {
    'node': ('/api/v1', 'nodes'), 'pod': ('/api/v1', 'pods'),
    'replicationcontroller': ('/api/v1', 'replicationcontrollers'),
    'daemonset': ('/apis/apps/v1', 'daemonsets'),
    'deployment': ('/apis/apps/v1', 'deployments'),
    'replicaset': ('/apis/apps/v1', 'replicasets'),
    'statefulset': ('/apis/apps/v1', 'statefulsets'),
    'job': ('/apis/batch/v1', 'jobs'),
}


class Connection(http.client.HTTPConnection):
    def __init__(self, directory):
        super().__init__('localhost', timeout=30)
        self.directory = directory

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        # Relative bind/connect avoids macOS's short sockaddr_un path limit.
        # This controller is single-threaded; restore cwd before returning.
        original = os.open('.', os.O_RDONLY)
        try:
            os.chdir(self.directory)
            self.sock.connect('api.sock')
        finally:
            os.fchdir(original)
            os.close(original)


class Reader(Kubectl):
    def __init__(self, executable):
        super().__init__(executable)
        runtime = Path(os.environ['XDG_RUNTIME_DIR'])
        require(runtime.is_absolute() and runtime.is_dir() and
                stat.S_IMODE(runtime.stat().st_mode) == 0o700 and
                not any(p.is_symlink() for p in (runtime, *runtime.parents)), 'private runtime required')
        self.temporary = tempfile.TemporaryDirectory(prefix='kube-reader-', dir=runtime)
        self.directory = Path(self.temporary.name)
        self.process = None
        self.connection = None
        try:
            self.process = subprocess.Popen([executable, 'proxy', '--unix-socket=api.sock',
                '--reject-methods=^(POST|PUT|PATCH|DELETE|CONNECT|HEAD|OPTIONS)$'],
                cwd=self.directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            started = time.monotonic()
            self.connection = Connection(self.directory)
            while True:
                require(self.process.poll() is None and time.monotonic() - started < 30,
                        'private kubectl reader did not start')
                if (self.directory / 'api.sock').exists():
                    try:
                        self.connection.connect()
                        break
                    except ConnectionRefusedError:
                        # bind creates the pathname before the proxy starts listening.
                        self.connection.close()
                time.sleep(0.1)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.connection is not None:
            self.connection.close()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
        self.temporary.cleanup()

    def call(self, *args, data=None):
        if args[0] != 'get' or len(args) < 2 or args[1].startswith('-'):
            return super().call(*args, data=data)
        names = args[1].split(',')
        selected = [name[:-1] if name.endswith('s') else name for name in names]
        if any(name not in RESOURCES for name in selected):
            return super().call(*args, data=data)
        if len(selected) > 1:
            return {'kind': 'List', 'items': [item for name in names
                    for item in self.call('get', name, *args[2:])['items']]}
        require(data is None, 'GET body is not allowed')
        resource = selected[0]
        tail = list(args[2:]); namespace = None; name = None; query = {}
        if tail and not tail[0].startswith('-'):
            name = tail.pop(0)
        while tail:
            flag = tail.pop(0)
            if flag == '-n':
                namespace = tail.pop(0)
            elif flag == '--field-selector':
                query['fieldSelector'] = tail.pop(0)
            elif flag == '-o':
                require(tail.pop(0) == 'json', 'reader requires JSON')
            else:
                require(flag == '-A', 'unsupported reader argument')
        prefix, plural = RESOURCES[resource]
        path = prefix
        if namespace:
            require(resource != 'node', 'Node cannot have a namespace')
            path += '/namespaces/' + quote(namespace, safe='')
        path += '/' + plural
        if name:
            path += '/' + quote(name, safe='')
        if query:
            path += '?' + urlencode(query)
        self.connection.request('GET', path)
        response = self.connection.getresponse()
        raw = response.read()
        require(response.status == 200, 'fresh Kubernetes read failed HTTP ' + str(response.status))
        value = json.loads(raw)
        # Typed API lists omit per-item TypeMeta; kubectl normally supplies it.
        if value.get('kind', '').endswith('List'):
            for item in value['items']:
                for key, expected in (('apiVersion', value['apiVersion']), ('kind', value['kind'][:-4])):
                    require(key not in item or item[key] == expected, 'list item type differs')
                    item[key] = expected
        return value
