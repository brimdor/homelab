// Consistent native SQLite snapshot and protected-copy verification; never start the app.
const fs = require('node:fs');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {DatabaseSync, backup} = require('node:sqlite');
const {pipeline} = require('node:stream/promises');
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const canonical = data => JSON.stringify(data);
const quote = name => '"' + name.replaceAll('"', '""') + '"';
let stage = 'source_contract';
async function fileHash(path) {
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(path)) digest.update(chunk);
  return digest.digest('hex');
}
function confirmTransfer(expected) {
  return new Promise((resolve, reject) => {
    let text = '';
    const finish = error => {
      clearTimeout(timer); process.stdin.removeListener('data', onData);
      process.stdin.removeListener('end', onEnd); process.stdin.removeListener('error', finish); process.stdin.destroy();
      error ? reject(error) : resolve();
    };
    const onEnd = () => finish(new Error('transfer acknowledgement missing'));
    const onData = chunk => {
      text += chunk.toString('ascii');
      if (text.length > 65 || (text.includes('\n') && text !== expected + '\n')) finish(new Error('invalid transfer acknowledgement'));
      else if (text === expected + '\n') finish();
    };
    const timer = setTimeout(onEnd, 30000);
    process.stdin.on('data', onData); process.stdin.once('end', onEnd); process.stdin.once('error', finish); process.stdin.resume();
  });
}
function value(v) {
  if (v === null) return ['null'];
  if (typeof v === 'bigint') return ['integer', String(v)];
  if (typeof v === 'number') {const b = Buffer.alloc(8); b.writeDoubleBE(v); return ['real', b.toString('hex')];}
  if (typeof v === 'string') return ['text', v];
  if (ArrayBuffer.isView(v)) return ['blob', Buffer.from(v.buffer, v.byteOffset, v.byteLength).toString('hex')];
  throw new Error('unsupported SQLite value');
}
function query(db, sql) {const s = db.prepare(sql); s.setReadBigInts(true); s.setReturnArrays(true); return s;}
function snapshot(db) {
  const schema = query(db, 'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name,tbl_name').all();
  const tables = query(db, "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").all();
  const contents = []; let rows = 0;
  for (const [name] of tables) {
    const columns = query(db, 'PRAGMA table_xinfo(' + quote(name) + ')').all();
    const info = query(db, 'PRAGMA table_list').all().find(row => row[0] === 'main' && row[1] === name);
    assert(info);
    const alias = ['rowid','oid','_rowid_'].find(key => !columns.some(row => row[1].toLowerCase() === key));
    const prefix = info[4] === 0n && alias ? quote(alias) + ',' : '';
    const table = query(db, 'SELECT ' + prefix + '* FROM ' + quote(name));
    const records = [];
    for (const row of table.iterate()) records.push(hash(canonical(row.map(value))));
    records.sort(); rows += records.length;
    contents.push([name, columns.map(row => row.map(value)), records]);
  }
  const metadata = ['user_version', 'application_id', 'encoding'].map(p => [p, query(db, 'PRAGMA ' + p).get().map(value)]);
  return {tables: tables.length, rows, schema_sha256: hash(canonical(schema.map(row => row.map(value)))),
    data_sha256: hash(canonical(contents)), metadata_sha256: hash(canonical(metadata)),
    sqlite_version: db.prepare('SELECT sqlite_version() AS v').get().v};
}
function check(db) {
  assert.deepEqual(query(db, 'PRAGMA integrity_check').all(), [['ok']]);
  assert.equal(query(db, 'PRAGMA foreign_key_check').all().length, 0);
}
function protectedFile(path) {const s = fs.lstatSync(path); assert(s.isFile() && !s.isSymbolicLink()); return s;}
async function main() {
  process.umask(0o077);
  const [mode, source, directory, expected] = process.argv.slice(process.argv[1] === __filename ? 2 : 1);
  assert(['capture','restore'].includes(mode));
  assert(fs.lstatSync(directory).isDirectory() && !fs.lstatSync(directory).isSymbolicLink());
  protectedFile(source); assert.equal(fs.realpathSync(source), source); assert.equal(fs.realpathSync(directory), directory);
  const scratch = fs.mkdtempSync(directory + '/.sqlite-recovery-103-'); fs.chmodSync(scratch,0o700);
  const destination = scratch + '/database.sqlite'; let db;
  try {
    stage = 'source_snapshot';
    db = new DatabaseSync(source,{readOnly:true, timeout:10000, allowExtension:false});
    db.exec('BEGIN'); const before = snapshot(db);
    stage = 'online_backup';
    await backup(db,destination); assert.deepEqual(snapshot(db),before); db.exec('ROLLBACK'); db.close(); db=null;
    fs.chmodSync(destination,0o600);
    // Convert only the owned backup to a standalone rollback-journal file.
    stage = 'normalize_copy';
    const copy = new DatabaseSync(destination,{timeout:10000,allowExtension:false});
    try {assert.equal(copy.prepare('PRAGMA journal_mode=DELETE').get().journal_mode,'delete');} finally {copy.close();}
    assert(!fs.existsSync(destination+'-wal') && !fs.existsSync(destination+'-shm'));
    const restored = new DatabaseSync(destination,{readOnly:true,timeout:10000,allowExtension:false});
    stage = 'verify_copy';
    let after;
    try {check(restored); after=snapshot(restored);} finally {restored.close();}
    assert.deepEqual(after,before);
    if (mode==='restore') {
      stage = 'compare_restore';
      assert.deepEqual(after,JSON.parse(expected));
      process.stdout.write(canonical({accepted:true, snapshot:after, integrity_valid:true, foreign_keys_valid:true, native_backup_restored:true}));
    } else {
      stage = 'hash_copy';
      const header={format:1,bytes:fs.statSync(destination).size,sha256:await fileHash(destination),snapshot:after};
      const line=canonical(header); process.stdout.write(line+'\n');
      stage = 'stream_payload';
      await pipeline(fs.createReadStream(destination),process.stdout,{end:false});
      process.stdout.write(canonical({commit:hash(line)})+'\n');
      // Keep exec alive until the protected receiver has verified every byte and the final commit.
      if (expected === 'acknowledged') {stage = 'transfer_acknowledgement'; await confirmTransfer(hash(line));}
    }
  } finally {
    try {if (db) {try {db.exec('ROLLBACK');} finally {db.close();}}}
    finally {fs.rmSync(scratch,{recursive:true}); assert(!fs.existsSync(scratch));}
  }
}
if (require.main===module || ['capture','restore'].includes(process.argv[1])) main().catch(error=>{
  const type = ['Error','AssertionError','TypeError','RangeError'].includes(error.name) ? error.name : 'Unknown';
  const code = ['ERR_ASSERTION','ERR_STREAM_PREMATURE_CLOSE','SQLITE_BUSY','SQLITE_CORRUPT','SQLITE_FULL','SQLITE_IOERR','SQLITE_READONLY','EPIPE','ENOSPC'].includes(error.code) ? error.code : 'UNKNOWN';
  process.stderr.write(`SQLite recovery failed; stage=${stage}; type=${type}; code=${code}; no production records emitted\n`);process.exitCode=1;
});
module.exports={value,snapshot,check,hash};
