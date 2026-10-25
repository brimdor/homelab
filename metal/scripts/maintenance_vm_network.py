"""Own one loopback QEMU Ethernet hub; never touch host or physical interfaces."""

import os
from pathlib import Path
import signal
import stat
import subprocess

import maintenance_actor_hold as actors


def arguments(qemu, ports):
    actors.require(isinstance(qemu, str) and Path(qemu).is_absolute(), 'absolute installed QEMU required')
    actors.require(isinstance(ports, (list, tuple)) and len(ports) == 3 and
                   all(type(port) is int and 1 <= port <= 65535 for port in ports) and
                   len(set(ports)) == 3, 'three distinct loopback ports required')
    argv = [qemu, '-no-user-config', '-nodefaults', '-machine', 'none', '-accel', 'tcg',
            '-display', 'none', '-monitor', 'none', '-serial', 'none', '-m', '32']
    for index, port in enumerate(ports):
        argv += ['-netdev', 'socket,id=s' + str(index) + ',listen=127.0.0.1:' + str(port),
                 '-netdev', 'hubport,id=h' + str(index) + ',hubid=0,netdev=s' + str(index)]
    return argv


class Hub:
    def __init__(self, qemu, ports, log):
        self.argv = arguments(qemu, ports)
        self.ports = tuple(ports)
        self.log, self.child = Path(log), None
        actors.safe(self.log)
        directory = self.log.parent.stat()
        actors.require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.geteuid() and
                       stat.S_IMODE(directory.st_mode) == 0o700, 'private owned network log directory required')

    def start(self):
        actors.require(self.child is None, 'network process already started; never overwrite ownership')
        descriptor = os.open(self.log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as output:
            self.child = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL, stdout=output,
                                          stderr=subprocess.STDOUT, start_new_session=True)
        return self.child.pid

    def running(self):
        actors.require(self.child is not None and self.child.poll() is None,
                       'owned network process exited or never started')
        return self.child.pid

    def stop(self):
        if self.child is None:
            return
        if self.child.poll() is None:
            try:os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:pass
            try:self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:os.killpg(self.child.pid, signal.SIGKILL)
                except ProcessLookupError:pass
                self.child.wait()
        actors.require(self.child.poll() is not None, 'owned network process was not reaped')
