#!/usr/bin/env python3
"""Reconcile the CLI-owned live-restore option without exporting daemon JSON."""

import argparse
from contextlib import contextmanager
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shlex
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


def unit_property(name):
    result = command(["systemctl", "show", "docker.service", f"--property={name}", "--value"])
    if result.stderr:
        raise RepairError(ERROR)
    return result.stdout.decode("utf-8")


def assignments(text):
    result = {}
    for token in shlex.split(text):
        name, separator, value = token.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or "\x00" in value:
            raise RepairError(ERROR)
        result[name] = value
    return result


def environment_file_assignments(text):
    """Parse one assignment per line, with only whole-value multiline quoting."""
    result = {}
    stream = io.StringIO(text)
    for line in stream:
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            continue
        name, separator, value = line.partition("=")
        name = name.strip(" \t\r\n")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or "\x00" in value:
            raise RepairError(ERROR)
        value = value.lstrip(" \t\r")
        if value.startswith(("'", '"')):
            quote, position = value[0], 1
            while True:
                if position >= len(value):
                    continuation = stream.readline()
                    if not continuation or "\x00" in continuation:
                        raise RepairError(ERROR)
                    value += continuation
                char = value[position]
                if quote == '"' and char == "\\":
                    # Only the escape forms shared with shlex are supported.
                    if position + 1 >= len(value) or value[position + 1] not in ('"', "\\"):
                        raise RepairError(ERROR)
                    position += 2
                    continue
                if char == quote:
                    if value[position + 1:].strip(" \t\r\n"):
                        raise RepairError(ERROR)
                    tokens = shlex.split(value[:position + 1])
                    if len(tokens) != 1:
                        raise RepairError(ERROR)
                    value = tokens[0]
                    break
                position += 1
        else:
            # Spaces remain part of this value, not another assignment. Shell
            # quoting/continuations inside an unquoted value are unsupported.
            if any(char in value for char in "'\"\\"):
                raise RepairError(ERROR)
            value = value.strip(" \t\r\n")
        result[name] = value
    return result


def owns_live_restore():
    effective = unit_property("ExecStart")
    snapshot = {"properties": {"ExecStart": effective}, "files": []}
    literal = re.search(r"(?:^|\s)--live-restore(?:=[^;\s]+)?(?=\s|;|$)", effective)
    reference = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
    references = list(reference.finditer(effective))
    if not literal:
        if "$" in reference.sub("", effective):
            raise RepairError(ERROR)
        for match in references:
            if ((match.start() and not effective[match.start() - 1].isspace())
                    or (match.end() < len(effective) and effective[match.end()] not in " \t\r\n;")):
                raise RepairError(ERROR)
        if not references:
            return False, snapshot

    properties = snapshot["properties"]
    for name in ("Environment", "EnvironmentFiles", "UnsetEnvironment"):
        properties[name] = unit_property(name)
    if properties["UnsetEnvironment"].strip():
        raise RepairError(ERROR)
    if literal:
        return True, snapshot
    environment = assignments(properties["Environment"])
    files = shlex.split(properties["EnvironmentFiles"])
    if len(files) % 2:
        raise RepairError(ERROR)
    for filename, optional in zip(files[::2], files[1::2]):
        if (not filename.startswith("/") or any(char in filename for char in "*?[]%$\x00")
                or optional not in ("(ignore_errors=yes)", "(ignore_errors=no)")):
            raise RepairError(ERROR)
        path = Path(filename)
        try:
            before, content = read_regular(path)
        except FileNotFoundError:
            if optional != "(ignore_errors=yes)":
                raise RepairError(ERROR) from None
            snapshot["files"].append((path, None, None))
            continue
        snapshot["files"].append((path, before, content))
        environment.update(environment_file_assignments(content.decode("utf-8")))

    owned = False
    for match in references:
        value = environment.get(match.group(1) or match.group(2), "")
        if any(char in value for char in "$`\x00"):
            raise RepairError(ERROR)
        # ${NAME} is one literal systemd argument; $NAME splits option words.
        tokens = [value] if match.group(1) else shlex.split(value)
        owned |= any(re.fullmatch(r"--live-restore(?:=[^\s]+)?", token) is not None for token in tokens)
    return owned, snapshot


def options_unchanged(snapshot):
    for name, value in snapshot["properties"].items():
        if unit_property(name) != value:
            raise RepairError(ERROR)
    for path, before, content in snapshot["files"]:
        if before is not None:
            unchanged(path, before, content)
        else:
            with bounded_read():
                try:
                    path.lstat()
                except FileNotFoundError:
                    continue
                raise RepairError(ERROR)


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
        owned, option_snapshot = owns_live_restore()
        if not owned:
            return result
        with daemon_lock(path.parent / LOCK_NAME):
            options_unchanged(option_snapshot)
            unchanged(path, before, content)
            if "live-restore" not in settings:
                command([str(daemon), "--validate", "--config-file", str(path)])
                options_unchanged(option_snapshot)
                unchanged(path, before, content)
                result.update(validated=True, reconciled=True)
                return result

            # The effective systemd command owns this option; preserve every other key,
            # including NVIDIA runtimes and any registry configuration.
            del settings["live-restore"]
            candidate = private_file(path, "candidate", (json.dumps(settings, indent=2, allow_nan=False) + "\n").encode("utf-8"))
            command([str(daemon), "--validate", "--config-file", candidate])
            options_unchanged(option_snapshot)
            unchanged(path, before, content)
            backup = private_file(path, "backup", content)
            sync_directory(path.parent)
            options_unchanged(option_snapshot)
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
