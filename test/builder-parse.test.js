import test from 'node:test';
import assert from 'node:assert/strict';
import { assetList, assetBody } from '../agents/lab/builder.js';

test('builder accepts common asset shapes', () => {
  assert.equal(assetList({ assets: [{ kind: 'a', body: 'x' }] }).length, 1);
  assert.equal(assetList({ assets: { landing_page: '<h1>x</h1>', step_plan: { title: 't', content: 'y' } } }).length, 2);
  assert.equal(assetList({}).length, 0);
  assert.equal(assetList(null).length, 0);
  assert.equal(assetBody({ content: 'hi' }), 'hi');
  assert.equal(assetBody({ html: '<p>x</p>' }), '<p>x</p>');
  assert.equal(assetBody({ title: 'no body' }), '');
});
