#!/usr/bin/env python3
"""Issue 103 passive root-disk timing capture; no workload or storage changes."""

import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request


RPM_URL = ('https://kojipkgs.fedoraproject.org/packages/bcc/0.35.0/5.fc44/'
           'data/signed/6d9f90a6/x86_64/libbpf-tools-0.35.0-5.fc44.x86_64.rpm')
RPM_SHA = 'ba1c23ca487bc3082209817dd9345806b183af491cab966ecb99e93d1874d8ad'
FINGERPRINT = '36F612DCF27F7D1A48A835E4DBFCF71C6D9F90A6'
DURATION = 1800


def require(value, message):
    if not value:
        raise RuntimeError(message)


def output(arguments):
    result = subprocess.run(arguments, capture_output=True)
    require(result.returncode == 0, 'native command failed: ' + arguments[0])
    return result.stdout.decode()


def parse_event(line):
    """COMM may contain spaces or be empty; queue -1 means unavailable."""
    fields = line.rsplit(None, 7)
    require(len(fields) == 8, 'unexpected biosnoop record shape')
    prefix, pid, disk, operation, sector, size, queue, latency = fields
    prefix = prefix.split(None, 1)
    require(bool(re.fullmatch(r'\d{2}:\d{2}:\d{2}\.\d{3}', prefix[0])), 'invalid event clock')
    datetime.datetime.strptime(prefix[0], '%H:%M:%S.%f')
    require(pid.isdecimal() and disk == 'sda' and bool(re.fullmatch('[A-Z]+', operation)),
            'invalid process, disk or operation')
    require(bool(re.fullmatch('-?[0-9]+', sector)) and size.isdecimal(), 'invalid event size or sector')
    queue, latency = float(queue), float(latency)
    require(math.isfinite(queue) and (queue >= 0 or queue == -1) and
            math.isfinite(latency) and latency >= 0, 'invalid event timing')
    return {'clock': prefix[0], 'comm': prefix[1] if len(prefix) == 2 else '',
            'pid': int(pid), 'operation': operation, 'bytes': int(size),
            'queue_ms': queue, 'service_ms': latency}


def lost_events(line):
    match = re.fullmatch(r'lost ([0-9]+) events on CPU #([0-9]+)', line.strip())
    return int(match[1]) if match else None


def identity():
    require(os.geteuid() == 0 and socket.gethostname() == 'bulbasaur', 'wrong native host')
    require(Path('/etc/machine-id').read_text().strip() == 'f61201c3e2ba4b8cbd31e09f77da2ad0',
            'machine identity changed')
    require(output(['findmnt', '-n', '-o', 'UUID', '/']).strip() ==
            '2c59d1d1-d2d8-420e-b3a5-d87eb0437823', 'root identity changed')
    require(output(['findmnt', '-n', '-o', 'SOURCE', '/']).strip() == '/dev/sda2', 'root source changed')
    require(Path('/sys/block/sda/dev').read_text().strip() == '8:0' and
            int(Path('/sys/block/sda/size').read_text()) * 512 == 512110190592, 'disk identity changed')
    require('VERSION_ID=44' in Path('/etc/os-release').read_text() and
            output(['getenforce']).strip() == 'Enforcing' and Path('/sys/kernel/btf/vmlinux').is_file(),
            'reviewed Fedora, SELinux or BTF prerequisite changed')
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def extract_tool(root):
    package = root / 'package.rpm'
    with urllib.request.urlopen(RPM_URL, timeout=60) as stream:
        require(stream.url.startswith('https://'), 'insecure package redirect')
        raw = stream.read(16777217)
    require(len(raw) == 2111675 and hashlib.sha256(raw).hexdigest() == RPM_SHA, 'package identity changed')
    package.write_bytes(raw)
    signature = output(['rpmkeys', '--checksig', '--verbose', str(package)])
    require(FINGERPRINT.lower() in signature.lower() and
            not any(word in signature.upper() for word in ('NOKEY', 'NOT OK', 'BAD')), 'signature failed')
    require(output(['rpm', '-qp', '--queryformat', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}', str(package)]) ==
            'libbpf-tools-0.35.0-5.fc44.x86_64', 'package NEVRA changed')
    require(output(['rpm', '-qp', '--queryformat', '%{FILEDIGESTALGO}', str(package)]) == '8',
            'package file digest is not SHA256')
    entries = [line.split('\t') for line in output(['rpm', '-qp', '--queryformat',
               '[%{FILENAMES}\t%{FILEDIGESTS}\n]', str(package)]).splitlines()]
    digests = [digest for name, digest in entries if name == '/usr/bin/bpf-biosnoop']
    require(len(digests) == 1 and bool(re.fullmatch('[0-9a-f]{64}', digests[0])), 'tool digest missing')
    binary = root / 'bpf-biosnoop'
    producer = None
    consumer = None
    try:
        producer = subprocess.Popen(['rpm2cpio', str(package)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        with binary.open('xb') as target:
            consumer = subprocess.Popen(['cpio', '--extract', '--to-stdout', '--quiet',
                                         './usr/bin/bpf-biosnoop'], stdin=producer.stdout,
                                        stdout=target, stderr=subprocess.DEVNULL)
            producer.stdout.close()
            require(consumer.wait() == 0 and producer.wait() == 0, 'exact tool extraction failed')
    finally:
        for child in (consumer, producer):
            if child is not None:
                if child.poll() is None:
                    child.terminate()
                child.wait()
    require(binary.is_file() and not binary.is_symlink() and binary.stat().st_uid == 0 and
            binary.stat().st_nlink == 1 and binary.read_bytes().startswith(b'\x7fELF') and
            hashlib.sha256(binary.read_bytes()).hexdigest() == digests[0], 'extracted tool differs')
    binary.chmod(0o700)
    return binary, digests[0]


def sample():
    pressure = {}
    for line in Path('/proc/pressure/io').read_text().splitlines():
        fields = line.split()
        pressure[fields[0]] = {key: float(value) for key, value in (p.split('=') for p in fields[1:])}
    return {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'disk_stat': [int(n) for n in Path('/sys/block/sda/stat').read_text().split()], 'io_pressure': pressure}


def capture(binary, result):
    require(shutil.which('stdbuf') is not None, 'line buffering prerequisite absent')
    arguments = ['stdbuf', '-oL', str(binary), '-Q', '-t', '-d', 'sda', str(DURATION)]
    env = dict(os.environ, TZ='UTC', LC_ALL='C')
    child = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    result['owned_pid'] = child.pid
    result['samples'] = [sample()]
    result.update(header_seen=False, events=0, lost_events=0, stderr_bytes=0, stderr_lines=0)
    stderr_hash = hashlib.sha256()
    aggregates = {}
    buffers = {'stdout': b'', 'stderr': b''}
    next_sample = time.monotonic() + 10
    started = time.monotonic()

    def record(kind, line):
        line = line.decode('utf-8', errors='strict').rstrip('\r')
        if kind == 'stderr':
            count = lost_events(line)
            result['stderr_lines'] += 1
            if count is None:
                result['unexpected_stderr_lines'] = result.get('unexpected_stderr_lines', 0) + 1
            else:
                result['lost_events'] += count
            return
        if not result['header_seen']:
            require(line.split() == ['TIMESTAMP', 'COMM', 'PID', 'DISK', 'T', 'SECTOR', 'BYTES', 'QUE(ms)', 'LAT(ms)'],
                    'unexpected biosnoop header')
            result['header_seen'] = True
            return
        event = parse_event(line)
        key = (event['clock'][:5], event['comm'], event['pid'], event['operation'])
        require(len(aggregates) < 100000 or key in aggregates, 'unexpected aggregate cardinality')
        value = aggregates.setdefault(key, {'events': 0, 'bytes': 0, 'max_queue_ms': None,
                                          'max_service_ms': 0, 'slow_queue_50ms': 0, 'slow_service_50ms': 0,
                                          'queue_unavailable': 0})
        result['events'] += 1
        value['events'] += 1
        value['bytes'] += event['bytes']
        value['max_service_ms'] = max(value['max_service_ms'], event['service_ms'])
        value['slow_service_50ms'] += event['service_ms'] >= 50
        if event['queue_ms'] == -1:
            value['queue_unavailable'] += 1
        else:
            value['max_queue_ms'] = max(value['max_queue_ms'] or 0, event['queue_ms'])
            value['slow_queue_50ms'] += event['queue_ms'] >= 50

    try:
        with selectors.DefaultSelector() as selector:
            for name in buffers:
                selector.register(getattr(child, name), selectors.EVENT_READ, name)
            while selector.get_map():
                for key, _ in selector.select(timeout=1):
                    raw = os.read(key.fileobj.fileno(), 65536)
                    if key.data == 'stderr':
                        stderr_hash.update(raw)
                        result['stderr_bytes'] += len(raw)
                    buffers[key.data] += raw
                    require(len(buffers[key.data]) <= 1048576, 'unbounded native output record')
                    while b'\n' in buffers[key.data]:
                        line, buffers[key.data] = buffers[key.data].split(b'\n', 1)
                        record(key.data, line)
                    if not raw:
                        if buffers[key.data]:
                            record(key.data, buffers[key.data])
                            buffers[key.data] = b''
                        selector.unregister(key.fileobj)
                if time.monotonic() >= next_sample:
                    result['samples'].append(sample())
                    next_sample = time.monotonic() + 10
            result['exit'] = child.wait()
        result['elapsed_seconds'] = time.monotonic() - started
        result['complete_measurement'] = (result['exit'] == 0 and result['header_seen'] and
            result['elapsed_seconds'] >= DURATION and not result['lost_events'] and
            not result.get('unexpected_stderr_lines'))
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait()
        child.stdout.close()
        child.stderr.close()
        result['owned_child_reaped'] = child.poll() is not None
        result['stderr_sha256'] = stderr_hash.hexdigest()
        result['aggregates'] = [dict(utc_minute=k[0], comm=k[1], pid=k[2], operation=k[3], **v)
                                for k, v in sorted(aggregates.items())]
        result['samples'].append(sample())


def main():
    def interrupted(signum, frame):
        raise InterruptedError('native capture interrupted by signal ' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    result = {'started': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'rpm_sha256': RPM_SHA, 'measurement_seconds': DURATION, 'complete_measurement': False,
              'limitations': ['Last merged BIO process attribution; requeues and partial completions limit timing.',
                              'Userspace UTC completion receipt time, not kernel issue time.',
                              'No synthetic load; quiet window does not resolve prior stalls.',
                              'No error count or hardware cause inferred from timing alone.']}
    root = None
    try:
        boot = identity()
        root = Path(tempfile.mkdtemp(prefix='maintenance103-bulbasaur-io-', dir='/var/tmp'))
        root.chmod(0o700)
        binary, digest = extract_tool(root)
        result['tool_sha256'] = digest
        result['boot_id'] = boot
        capture(binary, result)
        require(identity() == boot, 'native boot identity changed during measurement')
    except Exception as error:
        result['complete_measurement'] = False
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        if root is not None:
            result['owned_scratch_bytes'] = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
            shutil.rmtree(root)
        result['owned_scratch_absent'] = root is None or not root.exists()
        result['ended'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        print(json.dumps(result))


if __name__ == '__main__':
    main()
