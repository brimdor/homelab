import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';

const require = createRequire('/app/package.json');
const postgres = require('postgres');
const sql = postgres(process.env.DATABASE_URL, { max: 1, connect_timeout: 10, prepare: false });

function runOriginal(task) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['/app/node_modules/tsx/dist/cli.mjs', `/app/src/cli/${task}-once.ts`], {
      cwd: '/app', stdio: ['ignore', 'pipe', 'pipe'], timeout: 60_000, killSignal: 'SIGKILL',
    });
    let output = '';
    child.stdout.on('data', (chunk) => {
      output += chunk.toString();
      if (output.length > 65_536) child.kill('SIGKILL');
    });
    child.stderr.resume();
    child.on('error', reject);
    child.on('close', (code) => {
      try {
        assert.equal(code, 0);
        const results = output.trim().split('\n').map((line) => JSON.parse(line));
        const result = results.find((item) => item.event === `${task}.completed`);
        assert.ok(result);
        if (task === 'triage') {
          assert.equal(result.completed, 0);
          assert.equal(result.needsAttention, 0);
          assert.ok(['QUEUE_EMPTY', 'OWNER_PAUSED'].includes(result.stopReason));
        } else {
          for (const key of ['selected', 'deleted', 'failed', 'deletedBytes']) assert.equal(result[key], 0);
        }
        resolve(result);
      } catch { reject(new Error('original command did not prove empty successful execution')); }
    });
  });
}

try {
  await sql.begin(async (guard) => {
    await guard`SET LOCAL lock_timeout = '5s'`;
    await guard`SET LOCAL statement_timeout = '5s'`;
    // SHARE blocks incoming queue/data writes while both unchanged commands execute.
    await guard`LOCK TABLE feedback_records, feedback_leases, feedback_units, attachments IN SHARE MODE`;
    const [counts] = await guard`
      SELECT
        (SELECT count(*)::int FROM feedback_records WHERE state = 'QUEUED') AS queued,
        (SELECT count(*)::int FROM feedback_leases WHERE released_at IS NULL) AS leased,
        (SELECT count(*)::int FROM triage_batches WHERE state = 'RUNNING') AS running,
        (SELECT count(*)::int FROM feedback_records fr
         WHERE fr.state = 'TRIAGED' AND fr.raw_deleted_at IS NULL
           AND fr.raw_delete_after <= now() + interval '10 minutes'
           AND NOT EXISTS (SELECT 1 FROM feedback_units fu
                           WHERE fu.feedback_record_id = fr.id AND fu.state <> 'TERMINAL')) AS retention
    `;
    assert.ok(Object.values(counts).every((value) => value === 0), 'actionable work requires ordinary scheduled execution');
    const task = process.env.MAINTENANCE_TASK ?? 'all';
    assert.ok(['all', 'triage', 'retention'].includes(task));
    const triage = task === 'retention' ? null : await runOriginal('triage');
    const retention = task === 'triage' ? null : await runOriginal('retention');
    await guard`SELECT 1`;
    console.log(JSON.stringify({ event: 'maintenance.empty-jobs.completed', triage, retention }));
  });
} catch {
  console.error(JSON.stringify({ event: 'maintenance.empty-jobs.failed' }));
  process.exitCode = 1;
} finally {
  await sql.end({ timeout: 5 });
}
