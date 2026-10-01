// Autopilot, continuous tick and scouts: what goes live without Bobby, and what never can.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { skipReason, ipRisk, DEFAULTS } from '../agents/lib/autopilot.js';
import { pickAgents, INTERVALS } from '../api/tick.js';
import { isDue, SCHEDULE } from '../agents/router.js';

const src = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8').split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n');

test('Autopilot approves clean ideas and refuses brands, bad copy, licensed lines and low scores', () => {
  const ok = { kind: 'venture', business: 'venture-lab', title: 'HVAC estimate follow-up playbook', summary: 'Scripts and checklists', steps: [], score: 72 };
  assert.equal(skipReason(ok), null);
  assert.match(skipReason({ ...ok, title: 'Disney princess party planner' }), /protected brand/);
  assert.match(skipReason({ ...ok, summary: 'Give us a call to book' }), /phone/);
  assert.match(skipReason({ ...ok, business: 'ma-real-estate' }), /stays with Bobby/);
  assert.match(skipReason({ ...ok, business: 'villa-cinema' }), /stays with Bobby/);
  assert.match(skipReason({ ...ok, score: 30 }), /score 30/);
  assert.equal(skipReason({ kind: 'growth', business: 'followup', title: 'Seasonal follow-up email', score: 10 }), null);
  assert.equal(ipRisk('generic dog bowl'), null);
  assert.equal(ipRisk('Pokemon card sleeves'), 'Pokemon');
  assert.ok(DEFAULTS.max_per_day >= 1 && DEFAULTS.max_per_day <= 12);
});

test('Autopilot only changes idea status: it never sends, spends, publishes or fetches', () => {
  const forbidden = /(sendgate|gmail\.js|zoho\.js|minimax|spend\.js|stripe(_launch)?\.js|cfimage|fetch\(|child_process)/;
  for (const f of ['agents/lib/autopilot.js', 'agents/lab/autopilot_agent.js', 'agents/lib/radar.js']) assert.doesNotMatch(src(f), forbidden, f);
  assert.match(src('agents/lib/autopilot.js'), /status: 'approved', decided_at/);
});

test('Scouts read the web politely and never sell, send, spend or contact anyone', () => {
  const forbidden = /(sendgate|gmail\.js|zoho\.js|minimax|spend\.js|stripe(_launch)?\.js|cfimage|createDraft|child_process|method:\s*'(POST|PUT|DELETE)')/;
  for (const f of ['agents/lab/product_scout.js', 'agents/lab/dropship_scout.js', 'agents/lib/etsy.js']) assert.doesNotMatch(src(f), forbidden, f);
  // Etsy only through its official API; marketplace pages only through robots-checked feeds.
  assert.match(src('agents/lib/etsy.js'), /openapi\.etsy\.com\/v3\/application\/listings\/active/);
  for (const f of ['agents/lab/product_scout.js', 'agents/lab/dropship_scout.js']) assert.doesNotMatch(src(f), /\bfetch\(/, `${f} must use fetchFeed (robots.txt)`);
});

test('Tick runs autopilot plus one heavy agent, most overdue first', () => {
  assert.deepEqual(pickAgents({}), ['autopilot', 'researcher']); // never run: everything overdue, ties keep order
  assert.deepEqual(pickAgents({ autopilot: 3, researcher: 6, product_scout: 30, dropship_scout: 30, architect: 10 }), ['researcher']);
  assert.deepEqual(pickAgents({ autopilot: 20, researcher: 5, product_scout: 90, dropship_scout: 30, architect: 10 }), ['autopilot', 'product_scout']);
  assert.deepEqual(pickAgents({ autopilot: 1, researcher: 1, product_scout: 1, dropship_scout: 1, architect: 1 }), []);
  assert.deepEqual(pickAgents({}, { ...INTERVALS, researcher: 0, autopilot: 0 }).includes('researcher'), false);
});

test('Hourly job only runs research as a backup when the tick has been quiet', () => {
  const s = SCHEDULE.find((x) => x.id === 'researcher');
  const now = new Date('2026-10-01T15:07:00Z');
  assert.equal(isDue(s, now, [{ status: 'ok', started_at: '2026-10-01T15:02:00Z' }]), false);
  assert.equal(isDue(s, now, [{ status: 'ok', started_at: '2026-10-01T14:10:00Z' }]), true);
  assert.equal(isDue(s, now, []), true);
});
