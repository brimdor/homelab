#!/usr/bin/env python3
"""Measure only existing Builder fsync calls in one owned tracefs instance."""

import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import time
import uuid

import builder_recovery as source


ROOT = Path('/sys/kernel/tracing')
EVENTS = tuple('sys_' + edge + '_' + call for call in ('fsync', 'fdatasync') for edge in ('enter', 'exit'))
LINE = re.compile(r'^\s*.+-(\d+)\s+\[\d+\]\s+\S+\s+(\d+)\.(\d{1,9}):\s+(sys_(enter|exit)_(fsync|fdatasync)):\s+(.*)$')


class Samples:
    def __init__(self, tids, descriptors):
        self.tids = tids
        self.descriptors = descriptors
        self.pending = {}
        self.completed = []
        self.edge_exits = 0
        self.seen_tids = set()

    def add(self, line):
        if not line.strip() or line.lstrip().startswith('#'):
            return
        match = LINE.fullmatch(line)
        if not match or int(match[1]) not in self.tids:
            raise RuntimeError('lost, foreign or unrecognized native trace event')
        tid = int(match[1])
        timestamp = int(match[2]) * 10**9 + int(match[3].ljust(9, '0'))
        edge, call, payload = match[5], match[6], match[7]
        if edge == 'enter':
            value = re.fullmatch(r'fd: 0x([0-9a-fA-F]+)', payload)
            if not value or tid in self.pending:
                raise RuntimeError('native syscall enter sequence differs')
            fd = int(value[1], 16)
            self.pending[tid] = (timestamp, call, self.descriptors.get(fd, {}).get('store', 'unattributed'))
            self.seen_tids.add(tid)
        else:
            if not re.fullmatch(r'0x[0-9a-fA-F]+', payload):
                raise RuntimeError('native syscall return format differs')
            previous = self.pending.pop(tid, None)
            if previous is None:
                if tid in self.seen_tids:
                    raise RuntimeError('unmatched internal native syscall exit')
                self.edge_exits += 1
                self.seen_tids.add(tid)
                return
            started, expected, store = previous
            if call != expected or timestamp < started:
                raise RuntimeError('native syscall pair or monotonic clock differs')
            self.completed.append({'call': call, 'store': store, 'duration_ns': timestamp - started,
                                   'successful': int(payload, 16) == 0})

    def result(self):
        groups = {}
        for value in self.completed:
            key = value['store'] + '/' + value['call']
            groups.setdefault(key, []).append(value)
        result = {}
        for key, values in groups.items():
            durations = sorted(v['duration_ns'] for v in values)
            result[key] = {'count': len(values), 'errors': sum(not v['successful'] for v in values),
                           'min_ns': durations[0], 'max_ns': durations[-1],
                           'p50_ns': durations[(len(durations) - 1) // 2],
                           'at_least_500ms': sum(v >= 500000000 for v in durations),
                           'at_least_5s': sum(v >= 5000000000 for v in durations)}
        return {'completed': len(self.completed), 'groups': result,
                'window_edge_exits': self.edge_exits, 'window_edge_pending': len(self.pending)}


def identity():
    value = source.source_identity('builder-canary')
    if value['process']['start_ticks'] != '98642':
        raise RuntimeError('original Builder process start changed')
    pid = value['process']['pid']
    process = Path('/proc') / str(pid)
    tids = {int(path.name) for path in (process / 'task').iterdir()}
    descriptors = {}
    expected = {'/' + store + '/' + name + suffix: store for store, name in source.DATABASES.items()
                for suffix in ('', '-wal', '-shm')}
    for path in (process / 'fd').iterdir():
        try:
            target = os.readlink(path)
        except FileNotFoundError:
            continue
        if target not in expected:
            continue
        store = expected[target]
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_dev != value['profile']['stores'][store]['device']:
            raise RuntimeError('Builder SQLite descriptor device changed')
        descriptors[int(path.name)] = {'store': store, 'device': metadata.st_dev, 'inode': metadata.st_ino}
    if {v['store'] for v in descriptors.values()} != {'data', 'recovery'}:
        raise RuntimeError('both original Builder SQLite descriptor sets required')
    return value, tids, descriptors


def global_controls():
    names = ('tracing_on', 'trace_clock', 'current_tracer', 'set_event_pid', 'buffer_size_kb', 'trace_options')
    return {name: (ROOT / name).read_text() for name in names} | {
        name: (ROOT / 'events/syscalls' / name / 'enable').read_text() for name in EVENTS}


def observe(seconds=180):
    if type(seconds) is not int or seconds <= 0:
        raise RuntimeError('positive explicit observation window required')
    before, tids, descriptors = identity()
    controls = global_controls()
    if not any(line.split(' - ', 1)[-1].startswith('tracefs ') and line.split()[4] == str(ROOT)
               for line in Path('/proc/self/mountinfo').read_text().splitlines()):
        raise RuntimeError('existing canonical tracefs mount required')
    instance = ROOT / 'instances' / ('homelab103-builder-' + uuid.uuid4().hex)
    instance.mkdir()
    reader = None
    started = None
    samples = Samples(tids, descriptors)
    result = {'accepted': False, 'instance': instance.name}
    def write(name, value):
        (instance / name).write_text(value + '\n')
    try:
        write('tracing_on', '0')
        if (instance / 'options/event-fork').read_text().strip() != '0':
            raise RuntimeError('shared event-fork option must already be disabled')
        write('trace_clock', 'mono')
        write('buffer_size_kb', '256')
        write('set_event_pid', ' '.join(str(tid) for tid in sorted(tids)))
        if '[mono]' not in (instance / 'trace_clock').read_text() or {
                int(v) for v in (instance / 'set_event_pid').read_text().split()} != tids:
            raise RuntimeError('owned trace clock or PID filter differs')
        for name in EVENTS:
            write('events/syscalls/' + name + '/enable', '1')
        reader = os.open(instance / 'trace_pipe', os.O_RDONLY | os.O_NONBLOCK)
        started = time.monotonic()
        write('tracing_on', '1')
        buffered = b''
        def drain():
            nonlocal buffered
            while True:
                try:
                    block = os.read(reader, 65536)
                except BlockingIOError:
                    return
                if not block:
                    return
                buffered += block
                while b'\n' in buffered:
                    line, buffered = buffered.split(b'\n', 1)
                    samples.add(line.decode())
        while time.monotonic() - started < seconds:
            if select.select([reader], [], [], max(0, min(.25, seconds - (time.monotonic() - started))))[0]:
                drain()
        write('tracing_on', '0')
        drain()
        if buffered.strip():
            raise RuntimeError('incomplete final native trace line')
        losses = {}
        for path in (instance / 'per_cpu').glob('cpu*/stats'):
            fields = dict(line.split(':', 1) for line in path.read_text().splitlines() if ':' in line)
            losses[path.parent.name] = {key: int(fields[key].strip()) for key in
                                       ('overrun', 'commit overrun', 'dropped events')}
        if not losses or any(v for row in losses.values() for v in row.values()):
            raise RuntimeError('owned trace buffer lost native events')
        if identity() != (before, tids, descriptors):
            raise RuntimeError('Builder source, threads or attributed descriptors changed')
        result.update(accepted=True, seconds=time.monotonic() - started, thread_count=len(tids),
                      source_unchanged=True, buffer_losses=losses, **samples.result())
    finally:
        cleanup_errors = []
        for name in ('tracing_on', *('events/syscalls/' + event + '/enable' for event in EVENTS)):
            try:
                write(name, '0')
            except OSError as error:
                cleanup_errors.append(type(error).__name__)
        if reader is not None:
            os.close(reader)
        try:
            instance.rmdir()
        except OSError as error:
            cleanup_errors.append(type(error).__name__)
        if cleanup_errors or instance.exists() or global_controls() != controls:
            raise RuntimeError('owned trace cleanup or unchanged global controls unproven: ' + ','.join(cleanup_errors))
        result.update(owned_instance_absent=True, global_controls_unchanged=True)
        print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    def cancel(_number, _frame):
        raise InterruptedError('owned Builder observation cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    observe()
