import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const values = readFileSync(join(root, 'apps/pointguide-canary/values.yaml'), 'utf8');
const block = values.match(/        corpus:\n[\s\S]*?          args:\n            - \|\n([\s\S]*?)          env:\n/);
assert.ok(block, 'Find the actual Canary corpus init shell, not a duplicated implementation');
const source = block[1].split('\n').map(line => line.replace(/^              /, '')).join('\n');

function git(cwd, ...args) {
  const result = spawnSync('git', ['-C', cwd, ...args], { encoding: 'utf8', env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' } });
  assert.equal(result.status, 0, `git ${args.join(' ')}: ${result.stderr}`);
  return result.stdout.trim();
}

function fixture(t) {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), 'pointguide-corpus-test-')));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const origin = join(dir, 'origin');
  const workspace = join(dir, 'workspace');
  const helper = join(dir, 'askpass');
  mkdirSync(origin);
  mkdirSync(workspace);
  git(origin, 'init', '--quiet');
  git(origin, 'config', 'user.name', 'Fixture');
  git(origin, 'config', 'user.email', 'fixture@example.invalid');
  writeFileSync(join(origin, 'corpus.txt'), 'immutable corpus\n');
  git(origin, 'add', '.');
  git(origin, 'commit', '--quiet', '-m', 'Fixture corpus');
  const commit = git(origin, 'rev-parse', 'HEAD');
  const url = `file://${origin}`;
  const script = source.replaceAll('/workspace', workspace)
    .replaceAll('/tmp/pointguide-askpass', helper)
    .replaceAll('https://github.com/PointCommunity/pointaudio.git', url);
  const run = (pin = commit) => spawnSync('/bin/sh', ['-ec', script], {
    encoding: 'utf8', timeout: 30000,
    env: { ...process.env, CORPUS_COMMIT: pin, GITHUB_TOKEN: 'fixture-not-a-secret', GIT_TERMINAL_PROMPT: '0', GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' },
  });
  const clone = () => git(workspace, 'clone', '--no-checkout', url, join(workspace, 'repository'));
  const cleanHelper = () => assert.equal(existsSync(helper), false, 'Authentication helper must be removed on every exit');
  const success = (result, expectedCommit = commit) => {
    assert.equal(result.status, 0, result.stderr);
    for (const name of ['web', 'worker']) {
      assert.equal(git(join(workspace, name), 'rev-parse', 'HEAD'), expectedCommit);
      assert.equal(git(join(workspace, name), 'status', '--porcelain'), '');
    }
    cleanHelper();
  };
  const failure = (result, reason) => {
    assert.notEqual(result.status, 0, 'Unsafe state must fail closed');
    assert.equal(result.signal, null, 'Failure must be deliberate, not a timeout');
    assert.match(result.stderr, reason, 'Reject for the intended unsafe condition');
    cleanHelper();
  };
  return { dir, origin, workspace, helper, commit, url, run, clone, cleanHelper, success, failure };
}

test('fresh initialization and repeated startup both succeed at the immutable pin', t => {
  const f = fixture(t);
  f.success(f.run());
  f.success(f.run());
});

test('startup resumes after clone completed but neither worktree exists', t => {
  const f = fixture(t);
  f.clone();
  f.success(f.run());
});

test('startup resumes after only the web worktree was created', t => {
  const f = fixture(t);
  f.clone();
  git(join(f.workspace, 'repository'), 'worktree', 'add', '--detach', join(f.workspace, 'web'), f.commit);
  f.success(f.run());
});

test('an unexpected repository origin is rejected without changing it', t => {
  const f = fixture(t);
  f.clone();
  const repo = join(f.workspace, 'repository');
  const other = `file://${join(f.dir, 'untrusted-origin')}`;
  git(repo, 'remote', 'set-url', 'origin', other);
  const result = f.run();
  assert.equal(git(repo, 'remote', 'get-url', 'origin'), other);
  f.failure(result, /Corpus initialization refused: unexpected repository origin/);
});

test('dirty worker changes are preserved and initialization fails closed', t => {
  const f = fixture(t);
  f.success(f.run());
  const path = join(f.workspace, 'worker', 'corpus.txt');
  writeFileSync(path, 'unpublished worker changes\n');
  const result = f.run();
  assert.equal(readFileSync(path, 'utf8'), 'unpublished worker changes\n');
  f.failure(result, /Corpus initialization refused: worktree has retained changes/);
});

test('a conflicting non-repository directory is preserved', t => {
  const f = fixture(t);
  const path = join(f.workspace, 'repository');
  mkdirSync(path);
  writeFileSync(join(path, 'keep.txt'), 'must survive\n');
  const result = f.run();
  assert.equal(readFileSync(join(path, 'keep.txt'), 'utf8'), 'must survive\n');
  f.failure(result, /Corpus initialization refused: repository state is not reusable/);
});

test('a missing pinned commit fails and removes the authentication helper', t => {
  const f = fixture(t);
  f.failure(f.run('0000000000000000000000000000000000000001'), /not our ref|couldn't find remote ref/);
});

test('a repository symlink is rejected without changing its target', t => {
  const f = fixture(t);
  symlinkSync(f.origin, join(f.workspace, 'repository'));
  const before = git(f.origin, 'status', '--porcelain');
  const result = f.run();
  assert.equal(git(f.origin, 'status', '--porcelain'), before);
  assert.equal(git(f.origin, 'rev-parse', 'HEAD'), f.commit);
  f.failure(result, /Corpus initialization refused: symbolic-link workspace path/);
});

test('a worktree symlink is rejected and its contents remain intact', t => {
  const f = fixture(t);
  f.clone();
  const external = join(f.dir, 'external');
  mkdirSync(external);
  writeFileSync(join(external, 'keep.txt'), 'outside workspace\n');
  symlinkSync(external, join(f.workspace, 'web'));
  const result = f.run();
  assert.equal(readFileSync(join(external, 'keep.txt'), 'utf8'), 'outside workspace\n');
  f.failure(result, /Corpus initialization refused: symbolic-link workspace path/);
});

test('a valid commit absent from the reusable clone is fetched before creating worktrees', t => {
  const f = fixture(t);
  f.clone();
  writeFileSync(join(f.origin, 'later.txt'), 'subsequent pinned corpus\n');
  git(f.origin, 'add', '.');
  git(f.origin, 'commit', '--quiet', '-m', 'Later corpus');
  const later = git(f.origin, 'rev-parse', 'HEAD');
  const absent = spawnSync('git', ['-C', join(f.workspace, 'repository'), 'cat-file', '-e', `${later}^{commit}`]);
  assert.notEqual(absent.status, 0, 'Prove the existing clone lacks the requested object');
  f.success(f.run(later), later);
});

test('a checkout belonging to another repository is rejected without modification', t => {
  const f = fixture(t);
  f.clone();
  const web = join(f.workspace, 'web');
  git(f.workspace, 'clone', f.url, web);
  const metadata = readFileSync(join(web, '.git', 'config'), 'utf8');
  const result = f.run();
  assert.equal(readFileSync(join(web, '.git', 'config'), 'utf8'), metadata);
  assert.equal(git(web, 'rev-parse', 'HEAD'), f.commit);
  f.failure(result, /Corpus initialization refused: unexpected worktree repository/);
});

test('corrupt worktree metadata fails closed with all files preserved', t => {
  const f = fixture(t);
  f.success(f.run());
  const web = join(f.workspace, 'web');
  const metadata = join(web, '.git');
  const corrupt = 'gitdir: /nonexistent-pointguide-fixture-metadata\n';
  writeFileSync(metadata, corrupt);
  const result = f.run();
  assert.equal(readFileSync(metadata, 'utf8'), corrupt);
  assert.equal(readFileSync(join(web, 'corpus.txt'), 'utf8'), 'immutable corpus\n');
  f.failure(result, /Corpus initialization refused: unexpected worktree root/);
});
