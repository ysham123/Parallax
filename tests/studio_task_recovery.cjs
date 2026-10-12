#!/usr/bin/env node
// Task recovery guidance: plain-language categories, honest budgets, no invented actions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'studio/node_modules/typescript'));
const source = fs.readFileSync(path.join(root, 'studio/src/task-recovery.ts'), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const loaded = { exports: {} };
new Function("module", "exports", output)(loaded, loaded.exports);
const { recoveryCategory, recoveryGuidance, budgetUsed } = loaded.exports;
let passed = 0;
const check = (name, fn) => { fn(); passed++; console.log('PASS ' + name); };

check('Unknown or missing categories fall back to the generic runtime guidance', () => {
  assert.equal(recoveryCategory(null), 'runtime');
  assert.equal(recoveryCategory('<script>'), 'runtime');
  assert.equal(recoveryCategory('failed_checks'), 'failed_checks');
});
check('Every category names a next step without promising a budget reset', () => {
  for (const category of ['environment', 'provider_permission', 'provider_quota', 'rejected_review', 'failed_checks', 'destination_conflict', 'interrupted', 'configuration', 'runtime']) {
    for (const resumable of [true, false]) for (const candidate of [true, false]) {
      const guidance = recoveryGuidance(category, { resumable, candidate });
      assert.ok(guidance.title && guidance.explanation && guidance.next, category);
      assert.doesNotMatch(guidance.next + guidance.explanation, /reset|refund|fresh budget/i, category);
    }
  }
});
check('Resume is suggested only when the task can actually resume', () => {
  for (const category of ['provider_permission', 'provider_quota', 'interrupted', 'runtime']) {
    assert.match(recoveryGuidance(category, { resumable: true, candidate: false }).next, /resume/i);
    assert.doesNotMatch(recoveryGuidance(category, { resumable: false, candidate: false }).next, /then resume|^Resume/i);
  }
  assert.match(recoveryGuidance('interrupted', { resumable: false, candidate: false }).next, /cannot resume/);
});
check('Saved-candidate revision is offered only when a candidate exists', () => {
  assert.match(recoveryGuidance('failed_checks', { resumable: false, candidate: true }).next, /revision of the saved candidate/);
  assert.doesNotMatch(recoveryGuidance('failed_checks', { resumable: false, candidate: false }).next, /revision/);
  assert.doesNotMatch(recoveryGuidance('destination_conflict', { resumable: false, candidate: true }).next, /revision/);
});
check('Budget text reports recorded usage, including overruns, and refuses invalid input', () => {
  assert.equal(budgetUsed(61, 45), '2 of 45 minutes used');
  assert.equal(budgetUsed(0, 1), '0 of 1 minute used');
  assert.equal(budgetUsed(3600, 45), '60 of 45 minutes used');
  for (const [seconds, minutes] of [[undefined, 45], [10, undefined], [NaN, 45], [-1, 45], [10, 0], ['10', 45]]) assert.equal(budgetUsed(seconds, minutes), null);
});
check('Provider quota is its own category and points to capacity, not settings', () => {
  assert.equal(recoveryCategory('provider_quota'), 'provider_quota');
  const guidance = recoveryGuidance('provider_quota', { resumable: true, candidate: false, machine: 'build-mac' });
  assert.match(guidance.next, /restore capacity/);
  assert.match(guidance.next, /another independent provider on build-mac/);
  assert.doesNotMatch(guidance.title + guidance.next, /limit or setting|Adjust the limits/);
});
check('Viewers without delivery permission are pointed to a developer instead of an action they cannot take', () => {
  const guidance = recoveryGuidance('failed_checks', { resumable: false, candidate: true, canAct: false });
  assert.match(guidance.next, /^A developer on this project can act: request a revision/);
  assert.doesNotMatch(recoveryGuidance('failed_checks', { resumable: false, candidate: true }).next, /A developer/);
});
console.log(`${passed} task recovery checks passed`);
