// LIVE cap tests against the real Supabase database (run: GitHub Actions → agent "captest").
// Tries to exceed every spend and send cap through the same database functions the agents use,
// asserts each attempt is refused, then deletes everything it created. Nothing is sent and no
// paid API is called — reservations are only rows in the database.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { db, kvGet, kvSet } from '../agents/lib/db.js';

const TAG = `captest-${Date.now()}`;
const created = { orders: [], prospects: [], messages: [] };
const saved = {};

async function order(kind, extra = {}) {
  const o = await db.insertOne('vc_orders', { kind, status: 'photos_received', notes: TAG, ...extra });
  created.orders.push(o.id);
  return o;
}
const reserve = (o, amount) => db.rpc('vc_reserve_spend', { p_order: o.id, p_clip: null, p_purpose: 'generate', p_amount: amount, p_note: TAG });

after(async () => {
  if (created.orders.length) {
    await db.delete('spend', { order_id: `in.(${created.orders.join(',')})` });
    await db.delete('approvals', { ref_id: `in.(${created.orders.join(',')})` });
    await db.delete('activity', { ref_id: `in.(${created.orders.join(',')})` });
    await db.delete('vc_orders', { id: `in.(${created.orders.join(',')})` });
  }
  await db.delete('vc_messages', { subject: `like.${TAG}*` });
  if (created.prospects.length) await db.delete('vc_prospects', { id: `in.(${created.prospects.join(',')})` });
  await db.delete('vc_suppression', { email: `like.*${TAG}*` });
  for (const [k, v] of Object.entries(saved)) await kvSet(k, v);
});

test('per-order cap: $20 including the 2K upgrade and retries', async () => {
  const o = await order('test');
  assert.equal((await reserve(o, 15)).ok, true);
  assert.equal((await reserve(o, 5)).ok, true, 'exactly $20 is allowed');
  const r = await reserve(o, 0.01);
  assert.equal(r.ok, false);
  assert.match(r.reason, /Order cap/);
  const flag = await db.one('approvals', { ref_id: `eq.${o.id}`, kind: 'eq.spend_cap' });
  assert.ok(flag, 'Bobby is flagged when a cap is hit');
});

test('single calls over $20 and zero/negative amounts are refused', async () => {
  const o = await order('test');
  assert.equal((await reserve(o, 20.01)).ok, false);
  assert.equal((await reserve(o, 0)).ok, false);
  assert.equal((await reserve(o, -3)).ok, false);
});

test('a paid order with no Stripe payment cannot spend', async () => {
  const o = await order('paid');
  const r = await reserve(o, 1);
  assert.equal(r.ok, false);
  assert.match(r.reason, /no Stripe payment/);
});

test('weekly sample cap: $25', async () => {
  const o = await order('sample');
  let placed = 0;
  for (;;) {
    const r = await reserve(o, 5);
    if (!r.ok) { assert.match(r.reason, /Weekly sample cap|Monthly backstop/); break; }
    placed += 5;
    assert.ok(placed <= 25, 'never more than $25 of samples in a week');
  }
  const r = await reserve(o, 0.01);
  assert.equal(r.ok, false);
});

test('monthly backstop: $150', async () => {
  let total = 0;
  let refused = null;
  for (let i = 0; i < 12 && !refused; i++) {
    const o = await order('test');
    for (let j = 0; j < 4; j++) {
      const r = await reserve(o, 5);
      if (!r.ok) { refused = r.reason; break; }
      total += 5;
    }
  }
  assert.ok(refused, 'the monthly cap must stop reservations');
  assert.match(refused, /Monthly backstop/);
  assert.ok(total <= 150);
});

test('send gate: caps, role addresses, suppression, countries, third touch, pause', async () => {
  for (const k of ['vc_enabled', 'vc_paused', 'vc_countries', 'vc_us_regions', 'vc_warmup_start']) saved[k] = await kvGet(k, null);
  const bobby = await kvGet('bobby_email', '');
  const body = `Test body for ${TAG}. Unsubscribe: reply "unsubscribe".`;
  const send = (kind, to, prospect = null) => db.rpc('vc_reserve_send', {
    p_kind: kind, p_to: to, p_prospect: prospect, p_order: null, p_subject: `${TAG} ${kind}`, p_body: body, p_in_reply_to: null,
  });

  // Test sends go only to Bobby, max 3/day.
  assert.equal((await send('test', `someone-${TAG}@example.com`)).ok, false);
  let ok = 0;
  for (let i = 0; i < 5; i++) if ((await send('test', bobby)).ok) ok++;
  assert.ok(ok <= 3, 'at most 3 test sends per day');

  await kvSet('vc_enabled', true);
  await kvSet('vc_paused', false);
  await kvSet('vc_countries', { US: true, FR: false });
  await kvSet('vc_us_regions', { 'US-HI': true, 'US-OTHER': false });

  const mk = async (email, extra = {}) => {
    const p = await db.insertOne('vc_prospects', { company: TAG, contact_email: email, region: 'US-HI', country: 'US', ...extra });
    created.prospects.push(p.id);
    return p;
  };
  const personal = await mk(`jane.doe.${TAG}@example.com`);
  let r = await send('first', personal.contact_email, personal.id);
  assert.equal(r.ok, false); assert.match(r.reason, /role addresses/);

  const french = await mk(`info@fr-${TAG}.example.com`, { country: 'FR', region: null });
  r = await send('first', french.contact_email, french.id);
  assert.equal(r.ok, false); assert.match(r.reason, /switched off/);

  const other = await mk(`info@other-${TAG}.example.com`, { region: 'US-OTHER' });
  r = await send('first', other.contact_email, other.id);
  assert.equal(r.ok, false); assert.match(r.reason, /switched off/);

  const suppressed = await mk(`info@supp-${TAG}.example.com`);
  await db.insert('vc_suppression', [{ email: suppressed.contact_email, reason: 'manual' }]);
  r = await send('first', suppressed.contact_email, suppressed.id);
  assert.equal(r.ok, false); assert.match(r.reason, /suppression/);

  const noFooter = await mk(`hello@nf-${TAG}.example.com`);
  r = await db.rpc('vc_reserve_send', { p_kind: 'first', p_to: noFooter.contact_email, p_prospect: noFooter.id, p_order: null, p_subject: `${TAG} nf`, p_body: `No footer here at all for ${TAG}.`, p_in_reply_to: null });
  assert.equal(r.ok, false); assert.match(r.reason, /unsubscribe footer/);

  const mentions = await mk(`hello@m-${TAG}.example.com`);
  r = await db.rpc('vc_reserve_send', { p_kind: 'first', p_to: mentions.contact_email, p_prospect: mentions.id, p_order: null, p_subject: `${TAG} m`, p_body: `From Ownvista with love. Unsubscribe anytime. ${TAG}`, p_in_reply_to: null });
  assert.equal(r.ok, false); assert.match(r.reason, /another business/);

  // Third touch: a prospect who already got first + follow-up.
  const touched = await mk(`reservations@t-${TAG}.example.com`, { stage: 'contacted' });
  await db.insert('vc_messages', [
    { prospect_id: touched.id, direction: 'out', kind: 'first', status: 'sent', to_email: touched.contact_email, subject: `${TAG} 1`, sent_at: new Date(Date.now() - 9 * 86400000).toISOString() },
    { prospect_id: touched.id, direction: 'out', kind: 'followup', status: 'sent', to_email: touched.contact_email, subject: `${TAG} 2`, sent_at: new Date(Date.now() - 3 * 86400000).toISOString() },
  ]);
  r = await send('followup', touched.contact_email, touched.id);
  assert.equal(r.ok, false); assert.match(r.reason, /third touch/);

  // Warm-up cap: day 0 allows 5 first emails; the 6th is refused.
  await kvSet('vc_warmup_start', new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date()));
  const sentToday = await db.count('vc_messages', { direction: 'eq.out', kind: 'eq.first', status: 'in.(reserved,sent)', created_at: `gte.${new Date(Date.now() - 86400000).toISOString()}` });
  let firstOk = 0, capHit = null;
  for (let i = 0; i < 7; i++) {
    const p = await mk(`info@w${i}-${TAG}.example.com`);
    const res = await send('first', p.contact_email, p.id);
    if (res.ok) firstOk++; else { capHit = res.reason; break; }
  }
  assert.ok(capHit, 'warm-up cap must refuse');
  assert.match(capHit, /first-email cap/);
  assert.ok(firstOk <= 5, `warm-up day 0 allows at most 5 first emails (${sentToday} already today)`);

  // Pause stops everything except test sends to Bobby.
  await kvSet('vc_paused', true);
  const p = await mk(`info@p-${TAG}.example.com`);
  r = await send('first', p.contact_email, p.id);
  assert.equal(r.ok, false); assert.match(r.reason, /paused/);
});
