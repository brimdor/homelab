"""Reconstruct the reviewed Radarr logs schema inside a disposable fixture only."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import urllib.parse


SCHEMA_SHA256 = '211496206ef721f00c5b06e53c61a43123903028c70fff42f6b08871bf9218c1'
TABLES = ('Logs', 'UpdateHistory', 'VersionInfo', 'sqlite_sequence')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def typed(value):
    if value is None: return ['null']
    if isinstance(value, int): return ['integer', str(value)]
    if isinstance(value, float): return ['real', struct.pack('>d', value).hex()]
    if isinstance(value, str): return ['text', value]
    if isinstance(value, bytes): return ['blob', value.hex()]
    raise RuntimeError('unreviewed SQLite value type')


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def schema(database):
    rows = database.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name,tbl_name').fetchall()
    if digest([[typed(v) for v in row] for row in rows]) != SCHEMA_SHA256:
        raise RuntimeError('unreviewed Radarr logs schema')
    return rows


def scan(database, table):
    sql = 'SELECT rowid,* FROM ' + quote(table) + ' NOT INDEXED'
    plan = database.execute('EXPLAIN QUERY PLAN ' + sql).fetchall()
    if len(plan) != 1 or not plan[0][3].startswith('SCAN ') or 'USING' in plan[0][3]:
        raise RuntimeError('source row scan uses an unreviewed access path')
    return database.execute(sql)


def fingerprint(database):
    rows = schema(database)
    metadata = [(p, database.execute('PRAGMA ' + p).fetchone())
                for p in ('user_version', 'application_id', 'encoding')]
    tables = []
    for table in TABLES:
        columns = database.execute('PRAGMA table_xinfo(' + quote(table) + ')').fetchall()
        if any(c[6] != 0 or c[1].lower() in ('rowid', 'oid', '_rowid_') for c in columns):
            raise RuntimeError('unreviewed generated column or shadowed rowid')
        hashes = sorted(bytes.fromhex(digest([typed(v) for v in row])) for row in scan(database, table))
        tables.append({'table': table, 'rows': len(hashes),
                       'typed_rows_with_rowid_sha256': hashlib.sha256(b''.join(hashes)).hexdigest(),
                       'columns_sha256': digest([[typed(v) for v in row] for row in columns])})
    return {'schema_sha256': digest([[typed(v) for v in row] for row in rows]),
            'metadata_sha256': digest([[p, [typed(v) for v in values]] for p, values in metadata]),
            'tables': tables, 'rows': sum(t['rows'] for t in tables)}


def reconstruct(root):
    """Caller owns and removes root; source is root/copy/logs.db, output root/rebuilt.db."""
    root = Path(root)
    source, target = root / 'copy/logs.db', root / 'rebuilt.db'
    if (not root.is_absolute() or any(p.is_symlink() for p in (source, *source.parents)) or
            not source.is_file() or target.exists() or target.is_symlink() or
            source.stat().st_dev != root.stat().st_dev):
        raise RuntimeError('unsafe disposable reconstruction paths')
    uri = 'file:' + urllib.parse.quote(str(source)) + '?mode=ro'
    original = sqlite3.connect(uri, uri=True, timeout=0)
    output = None
    try:
        original.execute('BEGIN')
        before = fingerprint(original)
        definition = schema(original)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        output = sqlite3.connect(target, timeout=0)
        output.execute('PRAGMA temp_store=MEMORY')
        encoding = original.execute('PRAGMA encoding').fetchone()[0]
        if encoding not in ('UTF-8', 'UTF-16le', 'UTF-16be'):
            raise RuntimeError('unreviewed database encoding')
        output.execute("PRAGMA encoding='" + encoding + "'")
        output.execute('BEGIN')
        for kind, name, _table, sql in definition:
            if kind == 'table' and name != 'sqlite_sequence':
                output.execute(sql)
        for table in TABLES:
            if table == 'sqlite_sequence':
                output.execute('DELETE FROM sqlite_sequence')
            columns = [c[1] for c in original.execute('PRAGMA table_xinfo(' + quote(table) + ')')]
            names = ['rowid', *columns]
            sql = ('INSERT INTO ' + quote(table) + '(' + ','.join(map(quote, names)) + ') VALUES(' +
                   ','.join('?' for _ in names) + ')')
            # Bound VALUES forces individual inserts; never copy raw corrupt btree pages.
            output.executemany(sql, scan(original, table))
        for kind, _name, _table, sql in definition:
            if kind == 'index':
                output.execute(sql)
        for name in ('user_version', 'application_id'):
            output.execute('PRAGMA ' + name + '=' + str(original.execute('PRAGMA ' + name).fetchone()[0]))
        output.commit()
        if output.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or output.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('reconstructed logs integrity or foreign keys failed')
        after = fingerprint(output)
        if before != after:
            raise RuntimeError('reconstructed logs schema, metadata or readable typed rows changed')
        return {'sqlite_version': sqlite3.sqlite_version, 'source': before, 'output': after,
                'output_integrity_ok': True, 'output_foreign_key_rows': 0,
                'complete_typed_readable_rows_with_rowids_equal': True,
                'accepted_recovery': False, 'historical_completeness_unknown': True}
    finally:
        if output is not None:
            output.close()
        original.close()
