#!/usr/bin/env python3
"""Qualify bcrypt and the registry HTTP method policy against an isolated Linux mock."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import uuid


IMAGE = 'docker.io/library/nginx@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949'
LABEL = 'io.eaglepass.registry-auth-qualification-103'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def command(arguments, *, data=None, check=True):
    value = subprocess.run(arguments, input=data, capture_output=True)
    require(not check or value.returncode == 0, 'qualification command failed: ' + arguments[0])
    return value


def docker(*arguments, check=True):
    return command(['docker', *arguments], check=check)


def inspect(container):
    return json.loads(docker('inspect', container).stdout)[0]


def isolated(value, root, run_id):
    host = value['HostConfig']
    require(value['Config']['Image'] == IMAGE and value['Config']['User'] == '101:101' and
            value['Config']['Labels'].get(LABEL) == run_id and
            host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] and not host['Privileged'] and
            host['CapDrop'] == ['ALL'] and host['SecurityOpt'] == ['no-new-privileges:true'] and
            host['LogConfig']['Type'] == 'none' and not host.get('PortBindings') and
            not any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests')) and
            host.get('PidMode', '') == '' and host.get('IpcMode') == 'private' and
            host.get('PidsLimit') == 64 and host.get('Memory') == 134217728 and
            host.get('NanoCpus') == 500000000 and
            host.get('Tmpfs') == {'/tmp': 'rw,nosuid,nodev,uid=101,gid=101,mode=0700,size=16777216'},
            'container isolation changed')
    expected = {(str(root / 'config'), '/etc/nginx-auth', False),
                (str(root / 'users'), '/etc/nginx-auth-users', False)}
    mounts = value['Mounts']
    require(len(mounts) == 2 and all(m['Type'] == 'bind' and m['Mode'] == 'ro,Z' for m in mounts) and
            {(m['Source'], m['Destination'], m['RW']) for m in mounts} == expected, 'unowned mount')


CLIENT = r'''
import base64,json,sys,time,urllib.request,urllib.error,socket
value=json.load(sys.stdin);opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(method,path,credential=None):
 headers={'Host':'registry.eaglepass.io'}
 if credential is not None:headers['Authorization']='Basic '+base64.b64encode(('admin:'+credential).encode()).decode()
 request=urllib.request.Request('http://127.0.0.1:8080'+path,headers=headers,method=method)
 try:response=opener.open(request,timeout=5)
 except urllib.error.HTTPError as error:response=error
 with response:return response.status,response.headers.get('X-Maintenance-103-Mock-Upstream'),response.read(4096)
end=time.monotonic()+30
while True:
 try:
  if request('GET','/healthz')[0]==200:break
 except (urllib.error.URLError,socket.timeout):pass
 if time.monotonic()>=end:raise RuntimeError('isolated mock did not become ready')
 time.sleep(.1)
cases=[]
reads=['/v2/','/v2/nested/repo/manifests/stable','/v2/repo/blobs/sha256:abc','/v2/repo/referrers/sha256:abc','/v2/repo/tags/list']
for method in ('GET','HEAD'):
 for path in reads:
  status,mock,_=request(method,path);assert status==200 and mock=='true'
  cases.append({'method':method,'path':path,'anonymous':200})
protected=[('GET','/v2/_catalog'),('GET','/v2/repo/blobs/uploads/id'),('GET','/admin')]
protected += [(method,'/v2/repo/manifests/test')for method in ('POST','PUT','PATCH','DELETE')]
for method,path in protected:
 assert request(method,path)[0]==401
 assert request(method,path,value['password']+'wrong')[0]==401
 status,mock,_=request(method,path,value['password']);assert status==200 and mock=='true'
 cases.append({'method':method,'path':path,'anonymous':401,'wrong_password':401,'valid_bcrypt':200})
print(json.dumps({'accepted':True,'cases':cases,'credential_not_forwarded_to_mock':True}))
'''


def main(payload):
    result = {'accepted': False, 'protected_registry_contacted': False, 'NAS_accessed': False}
    root = container = attach = image_id = None
    before_images = set()
    try:
        require(os.geteuid() == 0 and socket.gethostname() == 'pikachu', 'wrong qualification host')
        require(Path('/etc/machine-id').read_text().strip() == '0a7daf8b33244d9d85f46223c3582da9' and
                command(['findmnt', '-n', '-o', 'UUID', '/']).stdout.strip() ==
                b'76e53a95-725a-4430-9d7b-a8db413f3997', 'host identity changed')
        require(command(['getenforce']).stdout.strip() == b'Enforcing', 'SELinux must remain enforcing')
        require(set(payload) == {'config', 'auth', 'password'} and
                bool(re.fullmatch(r'[A-Za-z0-9_-]{32,80}', payload['password'])) and
                bool(re.fullmatch(r'admin:\$2[aby]\$10\$[./A-Za-z0-9]{53}\n?', payload['auth'])),
                'synthetic credential contract changed')
        require(payload['config'].count('proxy_pass ') == 1 and
                'proxy_pass http://127.0.0.1:19080;' in payload['config'] and
                'listen 127.0.0.1:19080;' in payload['config'] and
                'if ($http_authorization != "") { return 502; }' in payload['config'], 'mock-only upstream required')
        run_id = uuid.uuid4().hex
        root = Path(tempfile.mkdtemp(prefix='maintenance103-registry-auth-', dir='/var/tmp'))
        root.chmod(0o700)
        for name, filename, text in (('config', 'nginx.conf', payload['config']), ('users', 'auth', payload['auth'])):
            directory = root / name
            directory.mkdir(mode=0o750)
            os.chown(directory, 0, 101)
            path = directory / filename
            path.write_text(text)
            os.chown(path, 0, 101)
            path.chmod(0o440)
        before_images = set(docker('image', 'ls', '--no-trunc', '-q').stdout.decode().splitlines())
        docker('pull', IMAGE)
        image_id = json.loads(docker('image', 'inspect', IMAGE).stdout)[0]['Id']
        container = docker('create', '--label', LABEL + '=' + run_id, '--log-driver=none',
            '--user', '101:101', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--pids-limit', '64', '--memory', '134217728',
            '--cpus', '0.5', '--tmpfs', '/tmp:rw,nosuid,nodev,uid=101,gid=101,mode=0700,size=16777216',
            '-v', str(root / 'config') + ':/etc/nginx-auth:ro,Z',
            '-v', str(root / 'users') + ':/etc/nginx-auth-users:ro,Z',
            '--entrypoint', '/usr/sbin/nginx', IMAGE, '-c', '/etc/nginx-auth/nginx.conf').stdout.decode().strip()
        isolated(inspect(container), root, run_id)
        attach = subprocess.Popen(['docker', 'start', '--attach', container], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        end = time.monotonic() + 30
        while not inspect(container)['State']['Running']:
            require(attach.poll() is None and time.monotonic() < end, 'isolated container did not start')
            time.sleep(.1)
        native = inspect(container)
        isolated(native, root, run_id)
        pid = native['State']['Pid']
        for kind in ('link', 'route'):
            values = json.loads(command(['nsenter', '--target', str(pid), '--net', 'ip', '-j', kind]).stdout)
            require(({v['ifname'] for v in values} == {'lo'} if kind == 'link' else not values), 'external network present')
        checked = command(['nsenter', '--target', str(pid), '--net', 'python3', '-B', '-c', CLIENT],
                          data=json.dumps({'password': payload['password']}).encode())
        result.update(json.loads(checked.stdout))
        result['config_sha256'] = hashlib.sha256(payload['config'].encode()).hexdigest()
        result['image'] = IMAGE
        require(command(['getenforce']).stdout.strip() == b'Enforcing', 'SELinux changed')
    except Exception as error:
        result.update(accepted=False, error=type(error).__name__ + ': ' + str(error))
    finally:
        if container:
            docker('rm', '-f', container)
            require(docker('inspect', container, check=False).returncode != 0, 'owned container remains')
        if attach:
            stdout, stderr = attach.communicate()
            result['owned_attach_reaped'] = attach.poll() is not None
            result['native_log_sha256'] = hashlib.sha256(stdout + stderr).hexdigest()
            result['native_log_bytes'] = len(stdout) + len(stderr)
        if root:
            shutil.rmtree(root)
        result['owned_scratch_absent'] = root is None or not root.exists()
        if image_id and image_id not in before_images and not docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            docker('image', 'rm', IMAGE)
            result['new_unused_image_reference_removed'] = docker('image', 'inspect', IMAGE, check=False).returncode != 0
        print(json.dumps(result))


if __name__ == '__main__':
    import sys
    main(json.load(sys.stdin))
