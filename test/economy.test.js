// Economy + Architect guardrails. Runs before every job, so a crew member can only go live on a passing suite.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { computePnl, pickFocus, survivalStep, allocate, runway, ledgerLane, PROTECTED, BASE_TOKENS, LANES } from '../agents/lib/economy.js';
import { validateSpec, judgeCrew, scheduleEntry, BLOCKS, CLONABLE, LIMITS } from '../agents/lib/crew.js';

const ROOT = new URL('..', import.meta.url).pathname;
const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8');

const goodNew = { kind: 'new', name: 'Offer Polisher', lane: 'offers', mission: 'Reads live offers and drafts sharper sales copy variants for Bobby to review each day.', blocks: ['draft_asset', 'agent_task'], reads: ['launches'] };

test('A new crew member must stay on the menu', () => {
  const ok = validateSpec(goodNew);
  assert.equal(ok.ok, true, ok.problems.join('; '));
  assert.ok(ok.spec.token_budget <= LIMITS.probation_tokens);
  assert.equal(ok.spec.kill_metric.days, 14);

  for (const bad of ['send_email', 'stripe_launch', 'spend', 'publish_page', 'create_account', 'trade', 'shell']) {
    const r = validateSpec({ ...goodNew, blocks: [bad] });
    assert.equal(r.ok, false, `${bad} must be refused`);
  }
  for (const mission of ['Send cold emails to villa managers every morning.', 'Publish the best sales pages to the site.', 'Sign up for new ad accounts and buy traffic.', 'Trade options when signals are strong.']) {
    assert.equal(validateSpec({ ...goodNew, mission }).ok, false, mission);
  }
  assert.equal(validateSpec({ ...goodNew, token_budget: 999999 }).spec.token_budget, LIMITS.probation_tokens);
  assert.equal(validateSpec({ ...goodNew, lane: 'crypto' }).ok, false);
});

test('Only proven, non-sending agents can be cloned, and the crew has a ceiling', () => {
  for (const b of ['villa_outreach', 'operator', 'paper_trader', 'villa_studio', 'economist', 'architect']) {
    assert.equal(validateSpec({ kind: 'clone', base: b, name: 'X', lane: 'villa', mission: 'Second shift for a proven agent in an earning lane.' }).ok, false, b);
  }
  assert.ok(validateSpec({ kind: 'clone', base: 'launcher', name: 'Launcher 2', lane: 'offers', mission: 'Second shift for launcher in an earning lane.' }).ok);
  const full = Array.from({ length: LIMITS.max_crew }, (_, i) => ({ id: `x_c${i}xx`, status: 'probation' }));
  assert.equal(validateSpec(goodNew, { existing: full }).ok, false);
  assert.ok(!CLONABLE.some((c) => PROTECTED.includes(c) && c !== 'launcher'), 'only the launcher is both protected and clonable');
});

test('Probation: retire on day 14 unless it pays its way', () => {
  const spec = { ...validateSpec(goodNew).spec, status: 'probation', probation_ends: '2026-10-15' };
  assert.equal(judgeCrew(spec, { accepted: 0, revenue: 0 }, '2026-10-10').action, 'none');
  assert.equal(judgeCrew(spec, { accepted: 0, revenue: 0 }, '2026-10-15').action, 'retire');
  assert.equal(judgeCrew(spec, { accepted: 2, revenue: 0 }, '2026-10-15').action, 'keep');
  assert.equal(judgeCrew({ ...spec, kind: 'clone' }, { accepted: 9, revenue: 0 }, '2026-10-15').action, 'retire');
  assert.equal(judgeCrew({ ...spec, kind: 'clone' }, { accepted: 0, revenue: 4 }, '2026-10-15').action, 'keep');
  assert.equal(scheduleEntry(spec).type, 'daily');
});

test('Survival pressure: grow earners, boost the focus, cut losers, never shut down at $0', () => {
  const zero = { offers: 0, assets: 0, villa: 0, email: 0, growth: 0 };
  let s = survivalStep({ revenue30: zero, focus: 'offers', daysOld: 0 });
  assert.equal(s.offers.state, 'focus');
  assert.equal(s.villa.state, 'grace');
  assert.equal(s.email.state, 'protected');
  for (let w = 0; w < 20; w++) s = survivalStep({ prev: s, revenue30: zero, focus: 'offers', daysOld: 30 + w * 7 });
  assert.equal(s.villa.factor, 0.25, 'cut to the floor');
  assert.notEqual(s.villa.state, 'shut down', 'nothing shuts down while the company is at $0');
  s = survivalStep({ prev: s, revenue30: { ...zero, assets: 12 }, focus: null, daysOld: 200 });
  assert.equal(s.assets.state, 'earning');
  assert.ok(s.assets.factor > 1);
  assert.equal(s.villa.state, 'shut down');
  const plan = allocate({ laneState: s });
  assert.ok(plan.off.includes('villa_studio'));
  assert.ok(!plan.off.includes('villa_outreach'), 'protected agents never switch off');
  for (const p of PROTECTED) if (BASE_TOKENS[p]) assert.ok(plan.tokens[p] >= BASE_TOKENS[p], `${p} keeps its base`);
  assert.ok(plan.tokens.asset_studio > BASE_TOKENS.asset_studio, 'earning lane gets more');
});

test('P&L, focus and runway math', () => {
  const pnl = computePnl({
    usage: { launcher: { tokens: 3e5, images: 0, minutes: 10, approvals: 0 }, builder: { tokens: 1e5, images: 0, minutes: 0, approvals: 0 }, researcher: { tokens: 1e6, images: 0, minutes: 0, approvals: 3 } },
    laneRevenue: { offers: 49 },
  });
  assert.equal(pnl.launcher.revenue, 36.75);
  assert.equal(pnl.builder.revenue, 12.25);
  assert.equal(pnl.researcher.revenue, 0);
  assert.equal(pnl.researcher.shadow_cost, 10.4); // $0.40 tokens + 3 approvals × 5 min × $40/h
  assert.equal(pickFocus({ offers: { live_offers: 1 }, assets: { published_packs: 1 }, villa: { can_send: false } }), 'offers');
  assert.equal(pickFocus({}), null);
  assert.deepEqual(runway({ revenue30: { offers: 49 }, burn: [{ usd_month: 20 }, { usd_month: 5 }] }), { revenue_30d: 49, burn_month: 25, net_month: 24, covers: 1.96 });
  assert.equal(ledgerLane({ source: 'itchio', line: 'experiment' }), 'assets');
  assert.equal(ledgerLane({ source: 'stripe', line: 'villa-cinema' }), 'villa');
  assert.ok(Object.values(LANES).every((l) => !l.agents.includes('paper_trader')), 'paper trading never earns budget');
});

test('Economy, Architect and crew code cannot send, spend, publish or trade', () => {
  const files = ['agents/economist.js', 'agents/architect.js', 'agents/spawned.js', 'agents/lib/economy.js', 'agents/lib/crew.js'];
  const forbidden = /(sendgate|gmail\.js|zoho\.js|minimax|spend\.js|stripe(_launch)?\.js|cfimage|search\.js|robots\.js|trader\/|fetch\(|child_process|\beval\(|new Function)/;
  const code = (f) => src(f).split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n');
  for (const f of files) assert.doesNotMatch(code(f), forbidden, `${f} must not import senders, payments, images, the network or code execution`);
  // The runner can only start a crew member as an existing module or spawned.js.
  const run = src('agents/run.js');
  assert.match(run, /spec\.kind === 'clone' && MODULES\[spec\.base\]/);
  assert.match(run, /spec\.kind === 'new'\) return \{ load: \(\) => import\('\.\/spawned\.js'\)/);
  // Every block in spawned.js has a handler and nothing else does.
  const handlers = [...src('agents/spawned.js').matchAll(/^ {2}async (\w+)\(spec, a\)/gm)].map((m) => m[1]).sort();
  assert.deepEqual(handlers, Object.keys(BLOCKS).sort());
  // The economist only writes budgets: never send/spend kv keys.
  assert.doesNotMatch(src('agents/economist.js'), /vc_enabled|vc_paused|vc_countries|vc_price|spend_|launch_rules|STRIPE/);
});
