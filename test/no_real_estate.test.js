import { test } from 'node:test';
import assert from 'node:assert/strict';
import { realEstateRisk } from '../agents/lib/guard.js';
import { skipReason, HARD_MAX_PER_DAY } from '../agents/lib/autopilot.js';
import { checkCopy } from '../agents/lib/guard.js';
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

test('autopilot cap is 3 a day', () => assert.equal(HARD_MAX_PER_DAY, 3));

test('more real-estate phrasings are caught', () => {
  for (const t of ['House flipping profit calculator', 'Home staging checklist', 'Rental arbitrage starter kit', 'Investment property analyzer'])
    assert.ok(realEstateRisk(t), t);
});

test('made-up offers are blocked', () => {
  for (const t of ['Reply for a discount code for early adopters.', "Let me know if you'd like a preview link.", 'Just reply and I will send a quick sample.', '30-day money-back guarantee'])
    assert.ok(checkCopy(t).some((p) => /does not exist/.test(p)), t);
  assert.equal(checkCopy('Reply "Buy" and I will send the purchase link.').length, 0);
});

test('only Nashville Buys gets the Nashville Buys signature', () => {
  assert.match(signoff('nashville-buys'), /Nashville Buys/);
  assert.doesNotMatch(signoff('venture-lab'), /Nashville Buys/);
  assert.doesNotMatch(signoff(undefined), /Nashville Buys/);
});
