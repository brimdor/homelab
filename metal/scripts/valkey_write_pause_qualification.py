"""Exercise finite native write exclusion only in a verified synthetic namespace."""

import base64
import json

import etcd_recovery as common


PROGRAM = r'''
import json,select,socket,subprocess,sys,time

class Client:
    def __init__(self, port):
        self.socket=socket.create_connection(('127.0.0.1',port),timeout=5)
        self.socket.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.stream=self.socket.makefile('rb')
    def send(self,*args): self.socket.sendall(values.request(*args))
    def read(self): return values.response(self.stream)
    def call(self,*args): self.send(*args);return self.read()
    def close(self): self.stream.close();self.socket.close()

def call(port,*args):
    client=Client(port)
    try:return client.call(*args)
    finally:client.close()

def pause(milliseconds):
    started=time.monotonic()
    for port in range(17000,17006):
        assert call(port,'CLIENT','PAUSE',milliseconds,'WRITE')==b'OK'
    return started+milliseconds/1000

def probes():
    clients=[]
    try:
        for port in range(17000,17006):
            client=Client(port);clients.append(client);client.send('EVAL','return 1',0)
        assert not select.select([c.socket for c in clients],[],[],0.2)[0]
        return clients
    except BaseException:
        for client in clients:client.close()
        raise

clients=[];owner=None
try:
    assert call(17000,'SET',expiry_key,'synthetic-expiry','PX',400)==b'OK'
    deadline=pause(8000)
    clients=probes()
    for port in range(17000,17006):
        assert call(port,'PING')==b'PONG'
        assert call(port,'EVAL_RO','return 1',0)==1
        assert call(port,'SAVE')==b'OK'
    time.sleep(0.8)
    assert time.monotonic()<deadline
    assert call(17000,'GET',expiry_key)==b'synthetic-expiry'
    for port in range(17000,17006):assert call(port,'CLIENT','UNPAUSE')==b'OK'
    for client in clients:assert client.read()==1;client.close()
    clients=[]
    assert call(17000,'GET',expiry_key) is None
    owner_code=resp_boot+'''


OWNER = r'''
import socket,time
for port in range(17000,17006):
    with socket.create_connection(('127.0.0.1',port),timeout=5) as connection:
        connection.sendall(values.request('CLIENT','PAUSE',2500,'WRITE'))
        with connection.makefile('rb') as stream:assert values.response(stream)==b'OK'
print('FINITE-LEASE-READY',flush=True)
time.sleep(3600)
'''


FINISH = r'''
    owner=subprocess.Popen([sys.executable,'-I','-B','-c',owner_code],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert select.select([owner.stdout],[],[],5)[0]
    assert owner.stdout.readline()==b'FINITE-LEASE-READY\n'
    clients=probes();started=time.monotonic()
    owner.kill();owner.communicate(timeout=5)
    assert owner.returncode==-9
    for client in clients:assert client.read()==1;client.close()
    clients=[]
    elapsed=time.monotonic()-started
    assert 0.2<elapsed<5
    for port in range(17000,17006):assert call(port,'PING')==b'PONG'
    result={'accepted':True,'nodes':6,'write_flagged_noop_blocked':True,
        'reads_and_native_save_during_pause':True,'expiry_excluded_until_unpause':True,
        'explicit_unpause':True,'actual_owner_sigkill':True,'finite_lease_resumed':True,
        'resumption_seconds':elapsed}
finally:
    cleanup_errors=[]
    for port in range(17000,17006):
        try:call(port,'CLIENT','UNPAUSE')
        except Exception:cleanup_errors.append(port)
    for client in clients:client.close()
    if owner:
        if owner.poll() is None:owner.kill()
        owner.communicate(timeout=5)
    if cleanup_errors:raise RuntimeError('synthetic pause cleanup did not reach every owned node')
print(json.dumps(result))
'''


def qualify(namespace, observer, expiry_key):
    encoded = base64.b64encode(observer).decode()
    boot = ('import base64,sys,types;values=types.ModuleType("valkey_data_fingerprint");'
            'exec(base64.b64decode(' + repr(encoded) + '),values.__dict__);')
    program = (boot + '\nresp_boot=' + repr(boot) + '\nexpiry_key=' + repr(expiry_key) + '\n' +
               PROGRAM + repr(OWNER) + FINISH)
    wrapper = ('import json,traceback\ntry:\n exec(compile(' + repr(program) + ',"<synthetic-pause>","exec"))\n'
               'except Exception as error:\n print(json.dumps({"accepted":False,"failure_class":type(error).__name__,\n'
               ' "frames":[{"function":f.name,"line":f.lineno} for f in traceback.extract_tb(error.__traceback__)]}))\n')
    result = common.command([*namespace, 'python3', '-I', '-B', '-c', wrapper])
    value = json.loads(result.stdout)
    if result.stderr or value.get('accepted') is not True:
        raise RuntimeError('native synthetic write-pause qualification failed: ' + json.dumps(value))
    return value
