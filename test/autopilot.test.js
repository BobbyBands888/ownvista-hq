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
  assert.deepEqual(pickAgents({}), ['autopilot', 'product_scout']); // never run: everything overdue, ties keep order (researcher is off on the tick)
  assert.deepEqual(pickAgents({ autopilot: 3, researcher: 600, product_scout: 30, dropship_scout: 30, architect: 40 }), ['architect']);
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

test('Product Scout keywords stay out of real estate; POD goes to the Radar only', async () => {
  const { ETSY_KEYWORDS, POD_KEYWORDS } = await import('../agents/lab/product_scout.js');
  const { realEstateRisk } = await import('../agents/lib/guard.js');
  for (const w of [...ETSY_KEYWORDS, ...POD_KEYWORDS]) assert.equal(realEstateRisk(w), null, w);
  assert.ok(!ETSY_KEYWORDS.some((w) => /airbnb|rental|property/i.test(w)));
  assert.match(src('agents/lab/product_scout.js'), /lane: pod \? 'pod'/);
});

test('Marketer only drafts: it never sends, posts, publishes, spends or fetches pages itself', async () => {
  const forbidden = /(sendgate|gmail\.js|zoho\.js|minimax|spend\.js|stripe(_launch)?\.js|cfimage|createDraft|child_process|\bfetch\(|method:\s*'(POST|PUT|DELETE)')/;
  assert.doesNotMatch(src('agents/lab/marketer.js'), forbidden);
  const { vetKit, pickTargets } = await import('../agents/lab/marketer.js');
  const target = { price: 4, url: 'https://www.levelingclips.com/p/x' };
  const { kit, dropped } = vetKit({
    listing: { title: 'Potion Icons', short: 'Sixteen icons', tags: ['icons'], description: 'Get it at https://www.levelingclips.com/p/x', price_note: '$4' },
    pins: [{ title: 'Use coupon code SAVE10', description: 'x', board: 'b' }, { title: 'Fantasy icons', description: 'Join 500+ happy customers', board: 'b' }, { title: 'Potion art', description: 'Clean icons', board: 'Game art' }],
    reddit: [{ subreddit: 'r/gamedev', title: 'Tips', body: 'Only $9 today, see https://evil.example' }],
    seo: { title: 'Potion Icons', description: 'Sixteen potion icons for games' },
    hooks: ['Hop on a quick call with me', 'Sixteen potions, one style', 'Starter homes for first-time buyers'],
  }, target);
  assert.ok(kit.listing);
  assert.equal(kit.pins.length, 1);
  assert.equal(kit.reddit.length, 0);
  assert.deepEqual(kit.hooks, ['Sixteen potions, one style']);
  assert.ok(dropped.length >= 5);
  const now = Date.parse('2026-10-01T12:00:00Z');
  const targets = [{ key: 'a' }, { key: 'b' }, { key: 'c' }];
  const kits = { a: { made_at: '2026-09-30T12:00:00Z' }, b: { made_at: '2026-09-20T12:00:00Z' } };
  assert.deepEqual(pickTargets(targets, kits, { now, per_run: 2, refresh_days: 7 }).map((t) => t.key), ['c', 'b']);
});

test('Marketer never calls AI art hand-made and always discloses AI on asset packs', async () => {
  const { vetKit, pickTargets, KIT_VERSION } = await import('../agents/lab/marketer.js');
  const pack = { kind: 'asset_pack', price: 4, itch_url: 'https://ownvista.itch.io/p' };
  const { kit } = vetKit({
    listing: { title: 'Potion Icons', short: 'x', tags: [], description: 'Sixteen AI-generated potion icons.', price_note: '' },
    pins: [{ title: 'Hand-painted potions', description: 'x', board: 'b' }, { title: 'Potion icons', description: 'Painterly style', board: 'b' }],
    reddit: [{ subreddit: 'gamedev', title: 'Tip', body: 'Consistent icons help.' }, { subreddit: 'aigamedev', title: 'Tip', body: 'AI-generated set, consistent style.' }],
    hooks: ['Hand-drawn alchemy', 'Sixteen potions'],
  }, pack);
  assert.ok(kit.listing);
  assert.equal(kit.pins.length, 1);
  assert.deepEqual(kit.reddit.map((r) => r.subreddit), ['gamedev', 'aigamedev']);
  assert.match(kit.reddit[0].body, /AI-generated/);
  assert.deepEqual(kit.hooks, ['Sixteen potions']);
  assert.match(vetKit({ listing: { title: 'P', description: 'Sixteen potion icons.' } }, pack).kit.listing.description, /AI-generated/);
  const fresh = new Date().toISOString();
  assert.equal(pickTargets([{ key: 'a' }], { a: { made_at: fresh } }).length, 1, 'old-version kits are rewritten');
  assert.equal(pickTargets([{ key: 'a' }], { a: { made_at: fresh, v: KIT_VERSION } }).length, 0);
});

test('Product Scout only proposes written products when the evidence is a paid written product', async () => {
  const { WRITTEN } = await import('../agents/lab/product_scout.js');
  assert.ok(WRITTEN.test('[Etsy "budget planner"] Monthly Budget Planner Template — $6'));
  assert.ok(!WRITTEN.test('[itch.io] Modern Office asset pack: 200 sprites'));
  assert.ok(!WRITTEN.test('[itch.io] Cute & Cozy UI SFX'));
  assert.match(src('agents/lab/asset_studio.js'), /asset_pack_ideas/);
});

test('Marketer kits must state the real item count (Fantasy Potion: 14 shipped, not 16 planned)', async () => {
  const { vetKit, wrongCount } = await import('../agents/lab/marketer.js');
  assert.equal(wrongCount('Download a set of 16 painterly AI-generated potion icons.', 14), 16);
  assert.equal(wrongCount('14 potion icons, each at 512 px and 128 px.', 14), null);
  assert.equal(wrongCount('Transparent PNGs at 512px, 128 px icons too', 14), null);
  assert.equal(wrongCount('16 icons', undefined), null, 'no count known = no check');
  const target = { kind: 'asset_pack', price: 4, count: 14, itch_url: 'https://ownvista.itch.io/fantasy-potion-icons-pack' };
  const { kit, dropped } = vetKit({
    pins: [
      { title: 'Fantasy Potion Icons', description: 'Download a set of 16 painterly AI-generated potion icons.', board: 'Game Art' },
      { title: 'Potion Icons for RPGs', description: '14 painterly AI-generated potion icons for inventory screens.', board: 'Game Art' },
    ],
  }, target);
  assert.equal(kit.pins.length, 1);
  assert.match(kit.pins[0].description, /^14 /);
  assert.ok(dropped.some((d) => /says 16 items, the pack has 14/.test(d)));
});
