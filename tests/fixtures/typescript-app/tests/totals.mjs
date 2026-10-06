import { test } from 'node:test';
import assert from 'node:assert/strict';
import { total } from '../.test-build/totals.js';
test('empty invoice', () => assert.equal(total([]), 0));
test('sum and adjustment', () => {assert.equal(total([2,3]),5);assert.equal(total([10,-3]),7);});
