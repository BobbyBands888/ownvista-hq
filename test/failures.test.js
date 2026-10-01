// Failure backlog: audited reasons, repeat detection, and the guarantees Bobby asked for.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { audit, repeatOf, overlap, failureText, AUTO_PREFIX } from '../agents/lib/failures.js';

const ROOT = new URL('..', import.meta.url).pathname;
const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8');

test('Every failure gets an audited reason', () => {
  assert.equal(audit({ kind: 'idea', title: 'FSBO seller kit', note: '' }).category, 'broke a hard rule');
  assert.equal(audit({ kind: 'idea', title: 'Pixel potion icons', note: 'too generic, 1000 of these on itch' }).category, 'rejected by Bobby');
  assert.equal(audit({ kind: 'idea', title: 'Pixel potion icons', note: '' }).category, 'rejected, no reason given');
  assert.equal(audit({ kind: 'launch', title: 'HVAC toolkit', note: '' }).category, 'did not sell');
  assert.equal(audit({ kind: 'pack', title: 'Sci-fi gadgets', note: 'Only 4/16 images passed QA.' }).category, 'failed quality');
  assert.equal(audit({ kind: 'idea', title: 'X', note: `${AUTO_PREFIX}repeats "Y"` }).category, 'repeat of a failure');
});

test('A reworded copy of a failed idea is caught; a different idea is not', () => {
  const failed = [audit({ kind: 'launch', title: 'HVAC Service Pricing Toolkit', note: '' })];
  assert.ok(repeatOf({ title: 'HVAC Pricing Toolkit for Service Techs' }, failed));
  assert.equal(repeatOf({ title: 'Fantasy potion icon pack' }, failed), null);
  assert.equal(repeatOf({ title: 'Plumbing estimate templates' }, failed), null);
  assert.ok(overlap('Pixel Potion Icons', 'Potion icons, pixel art').score >= 0.5);
});

test('Idea agents are told what failed and why', () => {
  const t = failureText([audit({ kind: 'launch', title: 'HVAC toolkit', note: '' })]);
  assert.match(t, /Do NOT propose/);
  assert.match(t, /HVAC toolkit.*did not sell/);
  assert.match(src('agents/lib/context.js'), /Failed before — don't repeat/);
  assert.match(src('agents/lab/product_scout.js'), /repeatOf\(p, failures\)/);
});

test('Autopilot rejects repeats with the reason logged, and never approves them', () => {
  const a = src('agents/lib/autopilot.js');
  assert.match(a, /repeatOf\(idea, failures\)/);
  assert.match(a, /kind: 'idea_repeat'/);
  // The repeat check runs before any approval and the loop continues past it.
  assert.ok(a.indexOf('repeatOf(idea, failures)') < a.indexOf("status: 'approved'"));
});
