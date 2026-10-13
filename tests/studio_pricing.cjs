#!/usr/bin/env node
// Pricing is published only from a valid build-time setting; anything else shows nothing.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'studio/node_modules/typescript'));
const source = fs.readFileSync(path.join(root, 'studio/src/pricing.ts'), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const loaded = { exports: {} };
new Function('module', 'exports', output)(loaded, loaded.exports);
const { parsePricing } = loaded.exports;
let passed = 0;
const check = (name, fn) => { fn(); passed++; console.log('PASS ' + name); };
const good = { freeTasks: 5, monthly: '$29', yearly: '$249', checkoutUrl: 'https://buy.polar.sh/abc', founding: 'First 50 buyers: $149 for the first year' };
check('No setting publishes no pricing', () => {
  for (const raw of [undefined, null, '', '   ', 'not json', '[]', '{}']) assert.equal(parsePricing(raw), null);
});
check('A valid setting is accepted from JSON text', () => {
  assert.deepEqual(parsePricing(JSON.stringify(good)), good);
  const { yearly, founding, ...minimal } = good;
  assert.deepEqual(parsePricing(minimal), minimal);
});
check('Malformed prices, insecure checkout and odd allowances are refused', () => {
  for (const change of [{ monthly: '29' }, { monthly: '$29/mo' }, { yearly: 'cheap' }, { checkoutUrl: 'http://buy.example/x' },
    { checkoutUrl: 'javascript:alert(1)' }, { freeTasks: 0 }, { freeTasks: 2.5 }, { founding: 'x'.repeat(161) }]) {
    assert.equal(parsePricing({ ...good, ...change }), null, JSON.stringify(change));
  }
});
console.log(`${passed} pricing checks passed`);
