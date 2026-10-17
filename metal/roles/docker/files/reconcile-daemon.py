#!/usr/bin/env python3
"""Reconcile the CLI-owned live-restore option without exporting daemon JSON."""

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile


ERROR = "Docker daemon reconciliation failed."
LOCK_NAME = ".homelab-daemon.lock"


class RepairError(Exception):
    """A public error that never contains daemon data or command diagnostics."""


@contextmanager
def bounded_read():
    def expired(signum, frame):
        raise RepairError(ERROR)

    previous = signal.signal(signal.SIGALRM, expired)
    timer = signal.setitimer(signal.ITIMER_REAL, 30)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *timer)
        signal.signal(signal.SIGALRM, previous)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_regular(path):
    with bounded_read():
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise RepairError(ERROR)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if identity(os.fstat(stream.fileno())) != identity(before):
                raise RepairError(ERROR)
            content = stream.read()
            if identity(os.fstat(stream.fileno())) != identity(before):
                raise RepairError(ERROR)
        if identity(path.lstat()) != identity(before):
            raise RepairError(ERROR)
        return before, content


def unchanged(path, before, content):
    current, current_content = read_regular(path)
    if identity(current) != identity(before) or current_content != content:
        raise RepairError(ERROR)


@contextmanager
def daemon_lock(path):
    fd = None
    try:
        with bounded_read():
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise RepairError(ERROR)
            fcntl.flock(fd, fcntl.LOCK_EX)
            if identity(path.lstat()) != identity(os.fstat(fd)):
                raise RepairError(ERROR)
        # Both repository-owned writers use this persistent lock. Snapshot checks
        # still detect stale data; this is not atomic CAS against writers that
        # ignore the advisory lock or replace its inode.
        yield
    except OSError:
        raise RepairError(ERROR) from None
    finally:
        if fd is not None:
            os.close(fd)


def private_file(path, kind, content):
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.{kind}-", dir=path.parent)
    created = os.fstat(fd)
    complete = False
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            os.fchmod(fd, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(fd)
        complete = True
        return name
    finally:
        try:
            if not complete:
                try:
                    current = os.lstat(name)
                    if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                        os.unlink(name)
                except FileNotFoundError:
                    pass
        finally:
            os.close(fd)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def command(argv):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                            check=False, timeout=30)
    if result.returncode != 0:
        raise RepairError(ERROR)
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RepairError(ERROR)
        result[key] = value
    return result


def invalid_constant(value):
    raise RepairError(ERROR)


def reconcile(config="/etc/docker/daemon.json", daemon="/usr/bin/dockerd"):
    candidate = None
    try:
        path = Path(os.path.abspath(config))  # Do not resolve away a symlink.
        result = {"changed": False, "validated": False, "reconciled": False, "backup_path": None}
        try:
            before, content = read_regular(path)
        except FileNotFoundError:
            return result
        settings = json.loads(content, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(settings, dict):
            raise RepairError(ERROR)
        effective = command(["systemctl", "show", "docker.service", "--property=ExecStart", "--value"])
        if effective.stderr:
            raise RepairError(ERROR)
        if not re.search(r"(?:^|\s)--live-restore(?:=[^;\s]+)?(?=\s|;|$)", effective.stdout.decode("utf-8")):
            return result
        with daemon_lock(path.parent / LOCK_NAME):
            unchanged(path, before, content)
            if "live-restore" not in settings:
                command([str(daemon), "--validate", "--config-file", str(path)])
                unchanged(path, before, content)
                result.update(validated=True, reconciled=True)
                return result

            # The effective systemd command owns this option; preserve every other key,
            # including NVIDIA runtimes and any registry configuration.
            del settings["live-restore"]
            candidate = private_file(path, "candidate", (json.dumps(settings, indent=2, allow_nan=False) + "\n").encode("utf-8"))
            command([str(daemon), "--validate", "--config-file", candidate])
            unchanged(path, before, content)
            backup = private_file(path, "backup", content)
            sync_directory(path.parent)
            unchanged(path, before, content)
            os.replace(candidate, path)
            candidate = None
            sync_directory(path.parent)
            result.update(changed=True, validated=True, reconciled=True, backup_path=backup)
            return result
    except Exception:
        raise RepairError(ERROR) from None
    finally:
        if candidate is not None:
            try:
                os.unlink(candidate)
            except FileNotFoundError:
                pass
            except OSError:
                raise RepairError(ERROR) from None


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RepairError(ERROR)


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--config", default="/etc/docker/daemon.json")
        parser.add_argument("--daemon", default="/usr/bin/dockerd")
        args = parser.parse_args(argv)
        print(json.dumps(reconcile(args.config, args.daemon)))
        return 0
    except (Exception, KeyboardInterrupt):
        sys.stderr.write(ERROR + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
