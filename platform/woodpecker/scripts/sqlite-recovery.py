#!/usr/bin/env python3
"""Create and exercise a protected SQLite recovery point without exporting records."""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3


def connect_readonly(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.execute("PRAGMA query_only=ON")
    return connection


def inventory(connection):
    assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]
    counts = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        counts[table] = connection.execute("SELECT count(*) FROM " + quoted).fetchone()[0]
    assert "repos" in tables, "Unexpected database: repos table absent"
    trusted = connection.execute(
        "SELECT typeof(trusted), count(*) FROM repos GROUP BY typeof(trusted)"
    ).fetchall()
    numeric = connection.execute(
        "SELECT id, trusted FROM repos WHERE typeof(trusted) IN ('integer','real') ORDER BY id"
    ).fetchall()
    schema = connection.execute('PRAGMA table_info("repos")').fetchall()
    migration_tables = [table for table in tables if table in ("migration", "migrations")]
    migrations = {}
    for table in migration_tables:
        columns = [row[1] for row in connection.execute('PRAGMA table_info("' + table + '")')]
        if "id" in columns:
            migrations[table] = connection.execute('SELECT id FROM "' + table + '" ORDER BY id').fetchall()
    return {"table_counts": counts, "trusted_storage_types": trusted, "numeric_trusted": numeric,
            "repo_schema": schema, "migration_ids": migrations}


def snapshot(connection):
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]
    return {table: sorted(connection.execute(
        'SELECT * FROM "' + table.replace('"', '""') + '"'
    ).fetchall(), key=repr) for table in tables}


def normalize_trusted(connection):
    assert not connection.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='repos'"
    ).fetchall(), "Unexpected repository triggers"
    columns = [row[1] for row in connection.execute('PRAGMA table_info("repos")')]
    assert "trusted_conf" not in columns, "Ambiguous partial migration"
    before = snapshot(connection)
    expected = {table: list(rows) for table, rows in before.items()}
    updates = []
    keys = {"network", "volumes", "security"}
    for row in before["repos"]:
        value = row[columns.index("trusted")]
        parsed = json.loads(value) if isinstance(value, str) else value
        if isinstance(parsed, dict):
            assert set(parsed) == keys and all(type(x) is bool for x in parsed.values())
            continue
        # Preserve the exact Boolean mapping in upstream migration 017. This
        # changes serialization, not the stored legacy trust decision.
        assert type(parsed) is int and parsed in (0, 1), "Unexpected legacy trust representation"
        replacement = json.dumps({key: bool(parsed) for key in sorted(keys)}, separators=(",", ":"))
        identifier = row[columns.index("id")]
        updates.append((replacement, identifier, value))
        new_row = list(row)
        new_row[columns.index("trusted")] = replacement
        expected["repos"][expected["repos"].index(row)] = tuple(new_row)
    assert updates, "No legacy false trust found; refuse an unbound repair"
    expected["repos"].sort(key=repr)
    for replacement, identifier, value in updates:
        cursor = connection.execute(
            "UPDATE repos SET trusted=? WHERE id=? AND trusted=?", (replacement, identifier, value)
        )
        assert cursor.rowcount == 1, "Repository identity/value changed"
    assert snapshot(connection) == expected, "Unexpected database change"
    assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    return [identifier for _, identifier, _ in updates]


def repair(source, recovery_point, backup_sha, source_sha):
    assert source.is_file() and recovery_point.is_file()
    assert hashlib.sha256(recovery_point.read_bytes()).hexdigest() == backup_sha
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    assert not any(source.with_name(source.name + suffix).exists() for suffix in ("-wal", "-journal"))
    original_identity = (source.stat().st_uid, source.stat().st_gid, source.stat().st_ino)
    working = recovery_point.parent / "repair-work"
    working.mkdir(mode=0o700)
    try:
        with closing(connect_readonly(recovery_point)) as recovery:
            original = snapshot(recovery)
            with closing(sqlite3.connect(working / "restore.sqlite")) as restored:
                recovery.backup(restored)
                restored.execute("BEGIN EXCLUSIVE")
                simulated = normalize_trusted(restored)
                restored.commit()
            assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)) as live:
                try:
                    live.execute("BEGIN EXCLUSIVE")
                    assert snapshot(live) == original, "Live data differs from verified recovery point"
                    repaired = normalize_trusted(live)
                    assert repaired == simulated
                    live.commit()
                except BaseException:
                    live.rollback()
                    raise
            assert original_identity == (source.stat().st_uid, source.stat().st_gid, source.stat().st_ino)
            assert hashlib.sha256(recovery_point.read_bytes()).hexdigest() == backup_sha
        return {"repaired_repository_ids": repaired, "isolated_repair": "passed",
                "backup_sha256": backup_sha, "only_trusted_fields_changed": True,
                "legacy_trust_semantics_preserved": True}
    finally:
        shutil.rmtree(working)


def backup(source, destination, quiesced_copy=False):
    assert source.is_file(), "Expected existing SQLite database"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert not destination.exists(), "Never overwrite an existing recovery point"
    assert shutil.disk_usage(destination.parent).free > source.stat().st_size * 3
    os.umask(0o077)
    working = destination.parent / "recovery-work"
    raw_hashes = {}
    try:
        if quiesced_copy:
            # A read-only WAL database may need new shared-memory files. Recover
            # a separate copy; never create or modify those files on the source.
            raw = destination.parent / "raw-source"
            raw.mkdir(mode=0o700)
            working.mkdir(mode=0o700)
            for suffix in ("", "-wal", "-journal"):
                original_file = source.with_name(source.name + suffix)
                if not original_file.exists():
                    continue
                before = original_file.stat()
                archived = raw / original_file.name
                shutil.copyfile(original_file, archived)
                archived.chmod(0o600)
                with archived.open("rb") as stream:
                    os.fsync(stream.fileno())
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                after = original_file.stat()
                assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
                    after.st_ino, after.st_size, after.st_mtime_ns
                ), "Source changed during quiesced copy"
                with original_file.open("rb") as stream:
                    assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
                raw_hashes[original_file.name] = digest
                shutil.copyfile(archived, working / original_file.name)
            raw_directory = os.open(raw, os.O_RDONLY)
            try:
                os.fsync(raw_directory)
            finally:
                os.close(raw_directory)
            original = sqlite3.connect(working / source.name, timeout=30)
        else:
            original = connect_readonly(source)
        with closing(original), closing(sqlite3.connect(destination)) as copied:
            original.backup(copied)
    finally:
        if working.exists():
            shutil.rmtree(working)
    with closing(connect_readonly(destination)) as copied:
        expected = inventory(copied)
        restored_path = destination.with_suffix(".restore.sqlite")
        assert not restored_path.exists()
        try:
            with closing(sqlite3.connect(restored_path)) as restored:
                copied.backup(restored)
                assert inventory(restored) == expected, "Isolated restored inventory differs"
        finally:
            restored_path.unlink(missing_ok=True)
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    directory = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {"integrity": "ok", "isolated_restore": "passed", "sha256": digest,
            "quiesced_copy": quiesced_copy, "raw_source_hashes": raw_hashes,
            "bytes": destination.stat().st_size, **expected}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/source/woodpecker.sqlite"))
    parser.add_argument("--destination", type=Path,
                        default=Path("/recovery/trusted-20261019-offline-v2/pre-repair.sqlite"))
    parser.add_argument("--quiesced", action="store_true",
                        help="Copy all SQLite recovery files after proving every writer stopped")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--backup-sha")
    parser.add_argument("--source-sha")
    options = parser.parse_args()
    if options.repair:
        assert options.quiesced and options.backup_sha and options.source_sha
        result = repair(options.source, options.destination, options.backup_sha, options.source_sha)
    else:
        result = backup(options.source, options.destination, options.quiesced)
    print(json.dumps(result, sort_keys=True), flush=True)
