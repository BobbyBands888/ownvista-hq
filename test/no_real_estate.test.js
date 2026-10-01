import { test } from 'node:test';
import assert from 'node:assert/strict';
import { realEstateRisk } from '../agents/lib/guard.js';
import { skipReason, HARD_PAUSE } from '../agents/lib/autopilot.js';
import { signoff } from '../agents/lib/context.js';

test('real-estate ideas from this morning are caught', () => {
  for (const t of ['Fraud‑Prevention Consulting for MA Real‑Estate Transactions', 'Massachusetts Mortgage‑Rate Insight Newsletter',
    'Integrate Closinglock fraud-defense into client onboarding', 'First-time homebuyer checklist', 'Open house sign-in sheet'])
    assert.ok(realEstateRisk(t), t);
});

test('game and villa products are not caught', () => {
  for (const t of ['Top‑Down Game Asset Pack Creation Blueprint', 'Indie Game Asset Marketing Playbook', 'AI villa walkthrough script pack'])
    assert.equal(realEstateRisk(t), null, t);
});

test('autopilot never approves real estate, even untagged', () => {
  const why = skipReason({ kind: 'business', business: 'venture-lab', title: 'Massachusetts Mortgage-Rate Insight Newsletter', score: 90 });
  assert.match(why, /real estate/);
  assert.match(skipReason({ kind: 'growth', business: 'nashville-buys', title: 'Blog post ideas' }), /stays with Bobby/);
});

test('autopilot is hard-paused', () => assert.equal(HARD_PAUSE, true));

test('only Nashville Buys gets the Nashville Buys signature', () => {
  assert.match(signoff('nashville-buys'), /Nashville Buys/);
  assert.doesNotMatch(signoff('venture-lab'), /Nashville Buys/);
  assert.doesNotMatch(signoff(undefined), /Nashville Buys/);
});
