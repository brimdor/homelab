#!/usr/bin/env python3
"""Bridge one QEMU guestfwd connection only to the owned loopback repository."""

import os
import select
import socket
import sys


def bridge(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise RuntimeError('invalid owned repository port')
    with socket.create_connection(('127.0.0.1', port), timeout=30) as connection:
        connection.settimeout(None)
        sources = [sys.stdin.fileno(), connection.fileno()]
        while sources:
            ready, _, _ = select.select(sources, [], [])
            for descriptor in ready:
                if descriptor == connection.fileno():
                    data = connection.recv(65536)
                    if not data:
                        return
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                else:
                    data = os.read(descriptor, 65536)
                    if not data:
                        sources.remove(descriptor)
                        connection.shutdown(socket.SHUT_WR)
                    else:
                        connection.sendall(data)


if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit('exact owned repository port required')
    bridge(int(sys.argv[1]))
