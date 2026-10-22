"""Read complete typed values through loopback RESP2; emit only fingerprints."""

import hashlib
import json
import socket
import sys
import traceback


READ = """
local t=redis.call('TYPE',KEYS[1]).ok
local v
if t=='string' then v=redis.call('GET',KEYS[1])
elseif t=='hash' then v=redis.call('HGETALL',KEYS[1])
elseif t=='list' then v=redis.call('LRANGE',KEYS[1],0,-1)
elseif t=='set' then v=redis.call('SMEMBERS',KEYS[1])
elseif t=='zset' then v=redis.call('ZRANGE',KEYS[1],0,-1,'WITHSCORES')
else return redis.error_reply('unqualified value type') end
return {t,redis.call('PEXPIRETIME',KEYS[1]),v}
"""


def request(*parts):
    parts = [p if isinstance(p, bytes) else str(p).encode() for p in parts]
    return b'*' + str(len(parts)).encode() + b'\r\n' + b''.join(
        b'$' + str(len(p)).encode() + b'\r\n' + p + b'\r\n' for p in parts)


def response(stream, depth=0):
    line = stream.readline(65537)
    if depth > 8 or not line.endswith(b'\r\n') or len(line) > 65536:
        raise RuntimeError('invalid private RESP framing')
    kind, raw = line[:1], line[1:-2]
    if kind == b'+':
        return raw
    if kind == b'-':
        raise RuntimeError('private Valkey response refused; raw output withheld')
    if kind not in (b':', b'$', b'*'):
        raise RuntimeError('unexpected private RESP type')
    try:
        size = int(raw)
    except ValueError:
        raise RuntimeError('invalid private RESP length') from None
    if kind == b':':
        return size
    if size == -1:
        return None
    if size < 0 or size > (536870912 if kind == b'$' else 10000000):
        raise RuntimeError('invalid private RESP allocation')
    if kind == b'*':
        return [response(stream, depth + 1) for _ in range(size)]
    data = stream.read(size)
    if len(data) != size or stream.read(2) != b'\r\n':
        raise RuntimeError('truncated private RESP value')
    return data


def canonical(value):
    if isinstance(value, bytes):
        return b'b' + str(len(value)).encode() + b':' + value
    if isinstance(value, int):
        return b'i' + str(value).encode() + b';'
    if isinstance(value, (list, tuple)):
        return b'a' + str(len(value)).encode() + b':' + b''.join(map(canonical, value))
    raise RuntimeError('unsupported private value representation')


def typed(value):
    if not isinstance(value, list) or len(value) != 3:
        raise RuntimeError('incomplete typed value')
    kind, expiry, data = value
    if type(expiry) is not int or expiry < -1:
        raise RuntimeError('value expired during complete comparison')
    if kind == b'string':
        if not isinstance(data, bytes):
            raise RuntimeError('invalid string value')
    elif kind in (b'hash', b'list', b'set', b'zset'):
        if not isinstance(data, list) or not all(isinstance(p, bytes) for p in data):
            raise RuntimeError('invalid aggregate value')
        if kind in (b'hash', b'zset') and len(data) % 2:
            raise RuntimeError('incomplete field or score pair')
        if kind == b'hash':
            data = sorted(zip(data[::2], data[1::2]))
        elif kind == b'set':
            data = sorted(data)
    else:
        raise RuntimeError('unqualified value type')
    return [kind, expiry, data]


def fingerprint(port, replica=False):
    # Only called inside the independently verified disconnected network namespace.
    with socket.create_connection(('127.0.0.1', port), timeout=30) as connection:
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with connection.makefile('rb') as stream:
            def call(*args):
                connection.sendall(request(*args))
                return response(stream)
            if replica and call('READONLY') != b'OK':
                raise RuntimeError('replica read mode refused')
            keys, cursor = set(), b'0'
            while True:
                cursor, batch = call('SCAN', cursor, 'COUNT', 1000)
                if not isinstance(cursor, bytes) or not isinstance(batch, list) or not all(isinstance(k, bytes) for k in batch):
                    raise RuntimeError('invalid complete key inventory')
                keys.update(batch)
                if cursor == b'0':
                    break
            if call('DBSIZE') != len(keys):
                raise RuntimeError('key inventory changed')
            digest, types, expires = hashlib.sha256(), {}, 0
            ordered = sorted(keys)
            for offset in range(0, len(ordered), 100):
                batch = ordered[offset:offset + 100]
                connection.sendall(b''.join(request('EVAL_RO', READ, 1, key) for key in batch))
                for key in batch:
                    value = typed(response(stream))
                    digest.update(canonical([key, value]))
                    name = value[0].decode('ascii')
                    types[name] = types.get(name, 0) + 1
                    expires += value[1] != -1
            if call('DBSIZE') != len(keys):
                raise RuntimeError('key count changed during complete value comparison')
    return {'keys': len(keys), 'types': types, 'expiring_keys': expires, 'sha256': digest.hexdigest()}


if __name__ == '__main__':
    try:
        print(json.dumps(fingerprint(int(sys.argv[1]), len(sys.argv) == 3 and sys.argv[2] == 'replica')))
    except Exception as error:
        print(json.dumps({'observer_failed': type(error).__name__,
                          'frames': [{'function': f.name, 'line': f.lineno}
                                     for f in traceback.extract_tb(error.__traceback__)]}))
