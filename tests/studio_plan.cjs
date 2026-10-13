#!/usr/bin/env node
// Plan summary: honest usage wording, no promises beyond the recorded plan.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'studio/node_modules/typescript'));
const source = fs.readFileSync(path.join(root, 'studio/src/plan.ts'), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const loaded = { exports: {} };
new Function('module', 'exports', output)(loaded, loaded.exports);
const { planSummary } = loaded.exports;
let passed = 0;
const check = (name, fn) => { fn(); passed++; console.log('PASS ' + name); };
const resets = '2026-11-01T00:00:00+00:00';
check('Free plan shows usage, remaining tasks and what never counts', () => {
  const s = planSummary({ licensing: true, plan: 'free', used: 2, limit: 5, resets_at: resets });
  assert.equal(s.title, 'Free plan');
  assert.match(s.detail, /^2 tasks of 5 used this month; 3 left\. Resets /);
  assert.match(s.detail, /never count/);
  // The reset date is the UTC day the allowance renews, never the local day before.
  assert.match(s.detail, /Resets November 1\./);
  assert.match(planSummary({ licensing: true, plan: 'free', used: 1, limit: 5, resets_at: resets }).detail, /^1 task of 5/);
});
check('An exhausted free plan keeps existing tasks available', () => {
  const s = planSummary({ licensing: true, plan: 'free', used: 7, limit: 5, resets_at: resets });
  assert.match(s.detail, /All 5 free tasks are used/);
  assert.match(s.detail, /Existing tasks stay available/);
  assert.doesNotMatch(s.detail, /-\d/);
});
check('Pro and unlimited builds never show a limit', () => {
  assert.match(planSummary({ licensing: true, plan: 'pro', used: 12, limit: null, key_hint: '…1234' }).detail, /^Unlimited tasks\. License key …1234\. 12 tasks started/);
  assert.equal(planSummary({ licensing: false, plan: 'unlimited', used: 3, limit: null }).title, 'Unlimited');
});
check('An unreadable reset date falls back to plain wording', () => {
  assert.match(planSummary({ licensing: true, plan: 'free', used: 0, limit: 5, resets_at: 'nope' }).detail, /Resets next month/);
});
console.log(`${passed} plan checks passed`);
