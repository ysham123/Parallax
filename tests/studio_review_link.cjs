#!/usr/bin/env node
// Review handoff links: identifiers only, explicit workspace entry, no access by link alone.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'studio/node_modules/typescript'));
const source = fs.readFileSync(path.join(root, 'studio/src/review-link.ts'), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const loaded = { exports: {} };
new Function('module', 'exports', output)(loaded, loaded.exports);
const { parseReviewTarget, reviewLink, resolveReviewEntry } = loaded.exports;
let passed = 0;
const check = (name, fn) => { fn(); passed++; console.log('PASS ' + name); };
const ws = '11111111-1111-4111-8111-111111111111', other = '22222222-2222-4222-8222-222222222222';
const worker = '33333333-3333-4333-8333-333333333333', task = '44444444-4444-4444-8444-444444444444';
const target = { workspace: ws, worker, task };

check('A link carries only the three identifiers under /studio', () => {
  const link = reviewLink('https://studio.example', target);
  assert.equal(link, `https://studio.example/studio#review=${ws}.${worker}.${task}`);
  assert.doesNotMatch(link, /token|\?|%2F|\/private|\/Users/);
});
check('Links refuse non-identifier input and unusable origins', () => {
  assert.equal(reviewLink('https://studio.example', { ...target, task: '../etc' }), null);
  assert.equal(reviewLink('https://studio.example', { ...target, worker: 'Fixture Mac' }), null);
  assert.equal(reviewLink('javascript:alert(1)', target), null);
  assert.equal(reviewLink('not a url', target), null);
  assert.equal(reviewLink('https://studio.example/path?x=1', target), `https://studio.example/studio#review=${ws}.${worker}.${task}`);
});
check('Parsing round-trips a link and normalizes case', () => {
  assert.deepEqual(parseReviewTarget(`#review=${ws.toUpperCase()}.${worker}.${task}`), target);
  assert.deepEqual(parseReviewTarget(new URL(reviewLink('https://a.example', target)).hash), target);
});
check('Malformed, partial or extra-segment links are ignored', () => {
  for (const hash of ['', '#task=' + task, `#review=${ws}.${worker}`, `#review=${ws}.${worker}.${task}.${task}`, `#review=${ws}.${worker}.not-a-uuid`, `#review=${ws}/${worker}/${task}`]) {
    assert.equal(parseReviewTarget(hash), null, hash);
  }
});
check('Another workspace waits for the account workspace list, then asks before switching', () => {
  assert.deepEqual(resolveReviewEntry(target, other, null, null), { kind: 'checking' });
  const space = { id: ws, name: 'Team', kind: 'team', role: 'reviewer' };
  assert.deepEqual(resolveReviewEntry(target, other, [space], []), { kind: 'switch', space });
});
check('A workspace outside the account list is unavailable without revealing anything', () => {
  assert.deepEqual(resolveReviewEntry(target, other, [{ id: other, name: 'Mine', kind: 'personal', role: 'owner' }], []), { kind: 'unavailable', reason: 'workspace' });
});
check('In the right workspace, only an authorized listed machine opens the task', () => {
  assert.deepEqual(resolveReviewEntry(target, ws, null, null), { kind: 'checking' });
  assert.deepEqual(resolveReviewEntry(target, ws, null, [{ id: worker }]), { kind: 'open', worker, task });
  assert.deepEqual(resolveReviewEntry(target, ws, null, [{ id: other }]), { kind: 'unavailable', reason: 'machine' });
  assert.deepEqual(resolveReviewEntry(target, ws, null, []), { kind: 'unavailable', reason: 'machine' });
});
console.log(`${passed} review link checks passed`);
