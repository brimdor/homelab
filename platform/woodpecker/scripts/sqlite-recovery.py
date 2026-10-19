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


def backup(source, destination):
    assert source.is_file(), "Expected existing SQLite database"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert not destination.exists(), "Never overwrite an existing recovery point"
    assert shutil.disk_usage(destination.parent).free > source.stat().st_size * 3
    os.umask(0o077)
    with closing(connect_readonly(source)) as original, closing(sqlite3.connect(destination)) as copied:
        original.backup(copied)
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
            "bytes": destination.stat().st_size, **expected}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/source/woodpecker.sqlite"))
    parser.add_argument("--destination", type=Path,
                        default=Path("/recovery/trusted-20261019-offline/pre-repair.sqlite"))
    options = parser.parse_args()
    result = backup(options.source, options.destination)
    print(json.dumps(result, sort_keys=True), flush=True)
