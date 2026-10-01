import { test } from 'node:test';
import assert from 'node:assert/strict';
import { et, etToUtc } from '../agents/lib/time.js';
import { SCHEDULE, isDue } from '../agents/router.js';
import { parseFeed } from '../agents/lib/feeds.js';
import { parseRobots, isAllowed } from '../agents/lib/robots.js';
import { editDistance, stripQuoted, extractEmails } from '../agents/lib/text.js';
import { buildRaw } from '../agents/lib/gmail.js';
import { plan, clipCost, upgradeCost, priceLine, formatUsd } from '../agents/lib/pricing.js';
import { VC_PRICE_USD } from '../agents/lib/env.js';
import { scoreOf } from '../agents/scout.js';
import { parseJson } from '../agents/lib/llm.js';

const S = (id) => SCHEDULE.find((s) => s.id === id);

test('New York time conversion handles DST', () => {
  assert.equal(etToUtc('2026-07-01', 7, 0).toISOString(), '2026-07-01T11:00:00.000Z');
  assert.equal(etToUtc('2026-12-01', 7, 0).toISOString(), '2026-12-01T12:00:00.000Z');
  assert.equal(et(new Date('2026-03-08T12:30:00Z')).hour, 8);
});

test('Operator and Builder run every hour, day and night', () => {
  for (const id of ['operator', 'builder']) {
    for (const h of [8, 10, 3]) assert.ok(isDue(S(id), new Date(`2026-10-01T${String(h).padStart(2, '0')}:07:00Z`), []), `${id} due ${h}:07 UTC`);
  }
});

test('Villa Outreach (emails strangers) still runs 6am–11pm ET only', () => {
  for (const id of ['villa_outreach']) {
    assert.ok(isDue(S(id), new Date('2026-10-01T10:07:00Z'), []), `${id} due 6:07am EDT`);
    assert.ok(isDue(S(id), new Date('2026-10-02T03:07:00Z'), []), `${id} due 11:07pm EDT`);
    assert.ok(!isDue(S(id), new Date('2026-10-01T08:07:00Z'), []), `${id} not due 4:07am EDT`);
  }
});

test('daily agents catch up after a dropped run, but not twice', () => {
  const s = S('strategist');
  const at = (iso) => new Date(iso);
  assert.ok(isDue(s, at('2026-10-01T11:07:00Z'), []), 'due at 7:07am');
  assert.ok(isDue(s, at('2026-10-01T13:07:00Z'), []), 'still due at 9:07 if 7 and 8 were dropped');
  assert.ok(!isDue(s, at('2026-10-01T13:07:00Z'), [{ status: 'ok', started_at: '2026-10-01T11:08:00Z' }]), 'not after success');
  assert.ok(!isDue(s, at('2026-10-01T10:07:00Z'), []), 'not before 7am');
  const errs = [{ status: 'error', started_at: '2026-10-01T12:08:00Z' }, { status: 'error', started_at: '2026-10-01T11:08:00Z' }];
  assert.ok(!isDue(s, at('2026-10-01T13:07:00Z'), errs), 'stops retrying after 2 errors');
});

test('Learner runs every hour; Scout Mon+Thu; Judge Sundays', () => {
  for (const h of ['03', '08', '15']) assert.ok(isDue(S('learner'), new Date(`2026-10-02T${h}:07:00Z`), []), `learner due ${h}:07 UTC`);
  assert.ok(isDue(S('scout'), new Date('2026-10-01T12:07:00Z'), []), 'Thu 8:07am');
  assert.ok(!isDue(S('scout'), new Date('2026-09-30T12:07:00Z'), []), 'Wed');
  assert.ok(isDue(S('judge'), new Date('2026-10-04T22:07:00Z'), []), 'Sun 6:07pm');
});

test('Researcher learns hourly, 24/7, once per hour', () => {
  const s = S('researcher');
  assert.ok(isDue(s, new Date('2026-10-01T07:07:00Z'), [{ status: 'ok', started_at: '2026-10-01T06:08:00Z' }]), '3am ET runs');
  assert.ok(isDue(s, new Date('2026-10-01T12:07:00Z'), [{ status: 'ok', started_at: '2026-10-01T11:08:00Z' }]));
  assert.ok(!isDue(s, new Date('2026-10-01T12:37:00Z'), [{ status: 'ok', started_at: '2026-10-01T12:08:00Z' }]), 'backup fire in the same hour does not rerun');
});

test('RSS and Atom parsing', () => {
  const rss = `<rss><channel><item><title><![CDATA[Nashville FSBO & more]]></title><link>https://a.example/1</link><description>&lt;p&gt;Hi&lt;/p&gt;</description><pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>`;
  const atom = `<feed><entry><title>Atom post</title><link rel="alternate" href="https://b.example/2"/><summary>Sum</summary><updated>2026-09-29T10:00:00Z</updated></entry></feed>`;
  assert.deepEqual(parseFeed(rss)[0].title, 'Nashville FSBO & more');
  assert.equal(parseFeed(rss)[0].snippet, 'Hi');
  assert.equal(parseFeed(atom)[0].url, 'https://b.example/2');
});

test('robots.txt: Google News RSS is disallowed, allowed paths pass', () => {
  const g = parseRobots('User-agent: *\nDisallow: /\nAllow: /$\nAllow: /topics/\n');
  assert.equal(isAllowed(g, '/rss/search?q=x'), false);
  assert.equal(isAllowed(g, '/topics/abc'), true);
  assert.equal(isAllowed(parseRobots('User-agent: *\nDisallow:'), '/feed/'), true);
  assert.equal(isAllowed(parseRobots('User-agent: *\nDisallow: /private\n'), '/private/x'), false);
});

test('text helpers', () => {
  assert.equal(editDistance('Hello there Bob', 'Hello there Bob'), 0);
  assert.ok(editDistance('Hello there Bob', 'Totally different words here') > 0.7);
  assert.equal(stripQuoted('Thanks!\n\nOn Tue, Sep 29, 2026 Jane wrote:\n> old'), 'Thanks!');
  assert.deepEqual(extractEmails('Write info@villa.com or Reservations@Villa.com.'), ['info@villa.com', 'reservations@villa.com']);
});

test('draft MIME threads the reply and never includes Bcc', () => {
  const raw = Buffer.from(buildRaw({ from: 'hello@nashvillebuys.com', to: 'a@b.com', subject: 'Re: Hi', body: 'Body', inReplyTo: '<m1@x>', references: '<m0@x>' }), 'base64url').toString();
  assert.match(raw, /In-Reply-To: <m1@x>/);
  assert.match(raw, /References: <m0@x> <m1@x>/);
  assert.doesNotMatch(raw, /Bcc:/i);
});

test('film plans fit the spend caps with room for retries', () => {
  const paid = plan('paid');
  const sample = plan('sample');
  assert.equal(clipCost(), 0.4);
  assert.equal(upgradeCost(), 0.5);
  assert.ok(paid.total <= 20 - 2 * 3 * clipCost(), `paid plan $${paid.total} leaves room for 6 retries`);
  assert.ok(sample.total * 1.5 <= 25, 'a sample with retries fits the weekly sample budget');
});

test('film price comes from VC_PRICE_USD (default $149)', () => {
  const saved = process.env.VC_PRICE_USD;
  try {
    delete process.env.VC_PRICE_USD;
    assert.equal(VC_PRICE_USD(), 149);
    assert.equal(priceLine(), '$149 per film, one-time');
    process.env.VC_PRICE_USD = '179';
    assert.equal(priceLine(), '$179 per film, one-time');
    process.env.VC_PRICE_USD = 'abc';
    assert.throws(() => VC_PRICE_USD(), /positive number/);
    assert.equal(formatUsd(149.5), '$149.50');
  } finally {
    if (saved === undefined) delete process.env.VC_PRICE_USD; else process.env.VC_PRICE_USD = saved;
  }
});

test('Villa reply and delivery templates use the configured price', async () => {
  const { readFileSync } = await import('node:fs');
  const outreach = readFileSync(new URL('../agents/villa/outreach.js', import.meta.url), 'utf8');
  const studio = readFileSync(new URL('../agents/villa/studio.js', import.meta.url), 'utf8');
  assert.match(outreach, /Price: \$\{priceLine\(\)\}/, 'reply prompt states the price');
  assert.match(outreach, /The film is \$\{priceLine\(\)\}\. You can order here/, 'payment-link next step');
  assert.match(outreach, /free sample first — no charge/, 'free sample offer kept');
  assert.match(studio, /full-length 2K film \(\$\{priceLine\(\)\}\)/, 'sample delivery upsell');
  assert.doesNotMatch(outreach + studio, /\$\d/, 'no hard-coded dollar amounts in Villa templates');
});

test('Scout score clamps to the formula', () => {
  const { total, breakdown } = scoreOf({ time_to_revenue: 99, fit: 20, cost: -5, hours: 15, evidence: 10 });
  assert.deepEqual(breakdown, { time_to_revenue: 30, fit: 20, cost: 0, hours: 15, evidence: 10 });
  assert.equal(total, 75);
});

test('JSON extraction from model output', () => {
  assert.deepEqual(parseJson('```json\n{"a":1}\n```'), { a: 1 });
  assert.deepEqual(parseJson('Sure! {"a":[1,2]} done'), { a: [1, 2] });
  assert.throws(() => parseJson('no json'), /valid JSON/);
});

test('Hourly agents run once per hour even if triggered twice', () => {
  const at = new Date('2026-10-01T14:37:00Z');
  assert.ok(!isDue(S('operator'), at, [{ status: 'ok', started_at: '2026-10-01T14:20:00Z' }]), 'already ran this hour');
  assert.ok(isDue(S('operator'), at, [{ status: 'ok', started_at: '2026-10-01T13:20:00Z' }]), 'ran last hour');
  assert.ok(isDue(S('operator'), at, [{ status: 'error', started_at: '2026-10-01T14:20:00Z' }]), 'retry after an error');
});
