// Native sqlite3 5.1.7 recovery for the reviewed Node20 demo; never start the app.
const fs = require('node:fs');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const sqlite = require('sqlite3');
const {pipeline} = require('node:stream/promises');
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const quote = name => '"' + name.replaceAll('"', '""') + '"';
const all = (db, sql) => new Promise((resolve, reject) => db.all(sql, (e, rows) => e ? reject(e) : resolve(rows)));
const exec = (db, sql) => new Promise((resolve, reject) => db.exec(sql, e => e ? reject(e) : resolve()));
const close = db => new Promise((resolve, reject) => db.close(e => e ? reject(e) : resolve()));
const open = (path, mode) => new Promise((resolve, reject) => {
  const db = new sqlite.Database(path, mode, e => e ? reject(e) : resolve(db));
});
function scalar(name) {
  return 'typeof(' + name + ')||\':\'||CASE typeof(' + name + ') ' +
    "WHEN 'integer' THEN CAST(" + name + " AS TEXT) WHEN 'real' THEN printf('%!.26g'," + name + ') ' +
    'ELSE hex(CAST(' + name + ' AS BLOB)) END';
}
async function snapshot(db) {
  const schema = await all(db, 'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name,tbl_name');
  const tables = await all(db, "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name");
  const tableInfo = await all(db, 'PRAGMA table_list');
  const contents = []; let rows = 0;
  for (const {name} of tables) {
    const columns = await all(db, 'PRAGMA table_xinfo(' + quote(name) + ')');
    const info = tableInfo.find(row => row.schema === 'main' && row.name === name); assert(info);
    const alias = ['rowid','oid','_rowid_'].find(key => !columns.some(row => row.name.toLowerCase() === key));
    const names = columns.map(row => row.name); if (info.wr === 0 && alias) names.unshift(alias);
    const projection = names.map((column, i) => scalar(quote(column)) + ' AS ' + quote('v' + i)).join(',');
    const records = (await all(db, 'SELECT ' + projection + ' FROM ' + quote(name)))
      .map(row => hash(JSON.stringify(Object.values(row)))).sort();
    rows += records.length; contents.push([name, columns, records]);
  }
  const metadata = [];
  for (const key of ['user_version','application_id','encoding']) metadata.push([key, await all(db, 'PRAGMA ' + key)]);
  return {tables: tables.length, rows, schema_sha256: hash(JSON.stringify(schema)),
    data_sha256: hash(JSON.stringify(contents)), metadata_sha256: hash(JSON.stringify(metadata)),
    sqlite_version: (await all(db, 'SELECT sqlite_version() AS v'))[0].v};
}
async function backup(db, destination) {
  const copy = db.backup(destination);
  try {
    await new Promise((resolve, reject) => copy.step(-1, (e, completed) => e ? reject(e) : completed ? resolve() : reject(new Error('incomplete native backup'))));
  } finally {
    await new Promise((resolve, reject) => copy.finish(e => e ? reject(e) : resolve()));
  }
}
async function holdWriter(source) {
  const db = await open(source, sqlite.OPEN_READWRITE);
  let locked = false, timer, keepAlive, onData, onEnd, onSignal;
  try {
    db.configure('busyTimeout', 1000);
    await exec(db, 'BEGIN IMMEDIATE'); locked = true;
    const state = await snapshot(db);
    await new Promise((resolve, reject) => {
      let armed = false, sequence = 0, pending = '';
      const acknowledge = () => process.stdout.write(JSON.stringify({held: true, armed, sequence, pid: process.pid, snapshot: state}) + '\n');
      const renew = () => {clearTimeout(timer); if (!armed) timer = setTimeout(() => reject(new Error('writer lease heartbeat lost')), 30000);};
      onEnd = () => {if (!armed) resolve();};
      onSignal = () => {if (!armed) resolve();};
      onData = chunk => {
        try {
          pending += chunk.toString('utf8'); assert(pending.length <= 4096);
          while (pending.includes('\n')) {
            const index = pending.indexOf('\n'); const value = JSON.parse(pending.slice(0, index)); pending = pending.slice(index + 1);
            assert.deepEqual(Object.keys(value).sort(), ['command','sequence']);
            assert.equal(value.sequence, sequence + 1); sequence = value.sequence;
            assert(['ping','arm','release'].includes(value.command));
            if (value.command === 'release') {resolve(); return;}
            if (value.command === 'arm') {
              // Once rollout is published, transport loss must never resume an obsolete writer.
              armed = true; if (!keepAlive) keepAlive = setInterval(() => {}, 1000);
            }
            renew(); acknowledge();
          }
        } catch (error) {if (!armed) reject(error);}
      };
      process.stdin.on('data', onData); process.stdin.on('end', onEnd); process.stdin.on('error', onEnd);
      process.on('SIGTERM', onSignal); process.on('SIGINT', onSignal);
      renew(); acknowledge(); process.stdin.resume();
    });
  } finally {
    clearTimeout(timer); clearInterval(keepAlive);
    if (onData) process.stdin.removeListener('data', onData);
    if (onEnd) {process.stdin.removeListener('end', onEnd); process.stdin.removeListener('error', onEnd);}
    process.stdin.pause();
    if (onSignal) {process.removeListener('SIGTERM', onSignal); process.removeListener('SIGINT', onSignal);}
    try {if (locked) await exec(db, 'ROLLBACK');} finally {await close(db);}
  }
  process.stdout.write(JSON.stringify({held: false, released: true}) + '\n');
}
async function main() {
  process.umask(0o077);
  assert.equal(process.version, 'v20.20.2'); assert.equal(require('sqlite3/package.json').version, '5.1.7');
  const [mode, source, directory, expected] = process.argv.slice(process.argv[1] === __filename ? 2 : 1);
  assert(['capture','restore','hold-writer'].includes(mode));
  assert(fs.lstatSync(source).isFile() && !fs.lstatSync(source).isSymbolicLink());
  assert(fs.lstatSync(directory).isDirectory() && !fs.lstatSync(directory).isSymbolicLink());
  assert.equal(fs.realpathSync(source), source); assert.equal(fs.realpathSync(directory), directory);
  if (mode === 'hold-writer') {await holdWriter(source); return;}
  const scratch = fs.mkdtempSync(directory + '/.sqlite-recovery-103-'); fs.chmodSync(scratch, 0o700);
  const destination = scratch + '/database.sqlite'; let db, copy;
  try {
    db = await open(source, sqlite.OPEN_READONLY); await exec(db, 'BEGIN'); const before = await snapshot(db);
    await backup(db, destination); assert.deepEqual(await snapshot(db), before);
    await exec(db, 'ROLLBACK'); await close(db); db = null; fs.chmodSync(destination, 0o600);
    copy = await open(destination, sqlite.OPEN_READWRITE);
    assert.equal((await all(copy, 'PRAGMA journal_mode=DELETE'))[0].journal_mode, 'delete');
    assert.deepEqual(await all(copy, 'PRAGMA integrity_check'), [{integrity_check: 'ok'}]);
    assert.equal((await all(copy, 'PRAGMA foreign_key_check')).length, 0);
    const after = await snapshot(copy); assert.deepEqual(after, before); await close(copy); copy = null;
    assert(!fs.existsSync(destination + '-wal') && !fs.existsSync(destination + '-shm'));
    if (mode === 'restore') {
      assert.deepEqual(after, JSON.parse(expected));
      process.stdout.write(JSON.stringify({accepted: true, snapshot: after, integrity_valid: true, foreign_keys_valid: true, native_backup_restored: true}));
    } else {
      const bytes = fs.readFileSync(destination); const header = {format: 1, bytes: bytes.length, sha256: hash(bytes), snapshot: after};
      const line = JSON.stringify(header); process.stdout.write(line + '\n');
      await pipeline(fs.createReadStream(destination), process.stdout, {end: false});
      process.stdout.write(JSON.stringify({commit: hash(line)}) + '\n');
    }
  } finally {
    try {if (copy) await close(copy); if (db) {try {await exec(db, 'ROLLBACK');} finally {await close(db);}}}
    finally {fs.rmSync(scratch, {recursive: true}); assert(!fs.existsSync(scratch));}
  }
}
if (require.main === module || ['capture','restore','hold-writer'].includes(process.argv[1])) main().catch(() => {
  process.stderr.write('Native sqlite3 recovery failed; no production records emitted\n'); process.exitCode = 1;
});
module.exports = {snapshot, scalar, backup};
