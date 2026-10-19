import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../patches/login.js', import.meta.url), 'utf8');
const canary = fs.readFileSync(new URL('../../podwave-canary/patches/login.js', import.meta.url), 'utf8');
assert.equal(source, canary);

for (const mode of ['missing', 'invalid', 'success', 'database-error']) {
  const logs = [];
  const inserts = [];
  const password = 'synthetic-password-never-log';
  const session = 'synthetic-session-never-log';
  const context = vm.createContext({
    console: { log: (...v) => logs.push(v), error: (...v) => logs.push(v) },
    Date
  });
  const db = {
    prepare(sql) {
      if (mode === 'database-error') throw new Error('Synthetic database failure');
      return {
        get: () => ({ id: 'user-id', name: 'Synthetic user', username: 'synthetic', is_admin: 1, password_hash: 'hash' }),
        run: (...values) => inserts.push({ sql, values })
      };
    }
  };
  const exports = {
    './index-wpIsICWW.js': { j: (body, options = {}) => ({ body, ...options }) },
    bcryptjs: { default: { compareSync: (actual, hash) => actual === password && hash === 'hash' && mode !== 'invalid' } },
    crypto: { randomUUID: () => session },
    './index2-CdX4GARg.js': { g: () => db }
  };
  const module = new vm.SourceTextModule(source, { context });
  await module.link(specifier => {
    const values = exports[specifier] || {};
    return new vm.SyntheticModule(Object.keys(values), function () {
      for (const [key, value] of Object.entries(values)) this.setExport(key, value);
    }, { context });
  });
  await module.evaluate();
  const result = await module.namespace.POST({ request: {
    json: async () => mode === 'missing' ? { username: 'synthetic' } : { username: 'synthetic', password }
  } });
  const serialized = JSON.stringify(logs);
  assert(!serialized.includes(password), `${mode}: password was logged`);
  assert(!serialized.includes(session), `${mode}: session was logged`);
  if (mode === 'success') {
    assert.equal(result.body.userId, 'user-id');
    assert.equal(result.body.isAdmin, true);
    assert.equal(result.headers['Set-Cookie'], `podwave_session=${session}; HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=2592000`);
    assert.equal(inserts.length, 1);
    assert.equal(inserts[0].sql, 'INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)');
    assert.equal(inserts[0].values[0], session);
    assert.equal(inserts[0].values[1], 'user-id');
    assert(Number.isFinite(Date.parse(inserts[0].values[2])));
  } else {
    assert.equal(result.status, { missing: 400, invalid: 401, 'database-error': 500 }[mode]);
    assert.equal(result.body.error, { missing: 'Missing fields', invalid: 'Invalid credentials', 'database-error': 'Server error' }[mode]);
    assert.equal(inserts.length, 0);
    assert.equal(result.headers, undefined);
  }
}
console.log('PASS: four authentication contracts; no submitted credential/session logging');
