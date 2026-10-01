// The Ownvista economy: every agent has a budget and a P&L, and budget follows money earned.
//
// HARD LINE: the economy only moves EFFORT (daily token shares, image cap, minutes per run, on/off for
// non-essential agents). It never changes what an agent may do. Sending, spending, accounts, publishing and
// real-money trading stay exactly where they are: in sendgate / spend / Stripe launch / no code at all.
//
// Money terms used everywhere:
//   revenue      = real money in the ledger (Stripe offers, itch.io, Villa Cinema, manual lines)
//   burn         = real monthly bills Bobby already pays (kv economy_burn; new spend budget is $0)
//   shadow cost  = what an agent's usage WOULD cost on paid tiers + Bobby's time. Cash cost is $0 on free
//                  tiers, so shadow cost is how we compare agents fairly. It is never billed.
import { db, kvGet } from './db.js';
import { etDate, addDays, daysAgoIso } from './time.js';

// ---------- Lanes ----------
// Revenue lanes own agents. Overhead lanes earn nothing directly and are kept lean.
export const LANES = {
  offers: { name: 'Launcher offers', agents: ['launcher', 'builder'], earns: true },
  assets: { name: 'itch.io asset packs', agents: ['asset_studio'], earns: true },
  villa: { name: 'Villa Cinema', agents: ['villa_outreach', 'villa_studio'], earns: true },
  email: { name: 'Inbox + Bobby\'s businesses', agents: ['operator'], earns: true },
  growth: { name: 'Research & ideas (overhead)', agents: ['researcher', 'strategist', 'scout', 'analyst', 'judge', 'learner', 'economist', 'architect'], earns: false },
};

// Paper Trader is outside the economy: it can never earn real money, so it keeps a fixed allowance.
export const OUTSIDE = ['paper_trader'];

// These keep running no matter what: Bobby's inbox, learning, revenue tracking (Launcher syncs sales and
// kills losers), Villa replies/payments, and the economy itself.
export const PROTECTED = ['operator', 'learner', 'launcher', 'villa_outreach', 'economist', 'architect', 'paper_trader'];

// Today's daily token shares are the base. The economy multiplies them by the lane factor.
export const BASE_TOKENS = {
  operator: 60000, villa_outreach: 40000, villa_studio: 150000, researcher: 150000, strategist: 15000, scout: 15000,
  analyst: 20000, builder: 20000, judge: 10000, learner: 20000, launcher: 30000, asset_studio: 20000,
  economist: 6000, architect: 15000, paper_trader: 30000,
};
export const BASE_IMAGES = 100;

export const DEFAULT_RULES = {
  // Shadow prices (USD). Groq paid tier is ~$0.08–0.60 per million tokens; we use a blended $0.40.
  usd_per_million_tokens: 0.4,
  usd_per_image: 0.001,
  usd_per_action_minute: 0.008,
  bobby_usd_per_hour: 40,
  bobby_minutes_per_approval: 5,
  grace_days: 14, // no cuts in the first two weeks of the economy
  floor: 0.25, // a non-earning lane never drops below a quarter of its base budget
  cut: 0.75, // weekly cut for a non-earning lane after the grace period
  shutdown_weeks: 6, // weeks at the floor before non-essential agents in that lane are switched off
  focus_factor: 1.5,
  max_factor: 2,
};

export function laneOf(agent, crew = []) {
  for (const [id, l] of Object.entries(LANES)) if (l.agents.includes(agent)) return id;
  const spec = crew.find((c) => c.id === agent);
  return spec?.lane && LANES[spec.lane] ? spec.lane : OUTSIDE.includes(agent) ? 'outside' : 'growth';
}

// Which lane does a ledger row belong to?
export function ledgerLane(row) {
  if (row.source === 'itchio') return 'assets';
  if (row.line === 'villa-cinema') return 'villa';
  if (row.source === 'stripe' && row.line === 'experiment') return 'offers';
  if (row.line === 'experiment') return 'offers';
  return 'email'; // manual lines: nashville-buys, followup, ma-real-estate, clearance
}

// ---------- Pure math (tested) ----------

// Agent P&L over a window. usage: { [agent]: { tokens, images, minutes, approvals } }, laneRevenue: { [lane]: usd }
export function computePnl({ usage, laneRevenue, crew = [], rules = DEFAULT_RULES }) {
  const r = { ...DEFAULT_RULES, ...rules };
  const agents = Object.keys(usage);
  const laneTokens = {};
  for (const a of agents) {
    const lane = laneOf(a, crew);
    laneTokens[lane] = (laneTokens[lane] || 0) + (usage[a].tokens || 0);
  }
  const out = {};
  for (const a of agents) {
    const u = usage[a];
    const lane = laneOf(a, crew);
    const members = agents.filter((x) => laneOf(x, crew) === lane);
    // Lane revenue is split by token share (equal split when nobody used tokens).
    const share = laneTokens[lane] ? (u.tokens || 0) / laneTokens[lane] : 1 / Math.max(1, members.length);
    const revenue = lane === 'growth' || lane === 'outside' ? 0 : round2((laneRevenue[lane] || 0) * share);
    const shadow = round2(
      ((u.tokens || 0) / 1e6) * r.usd_per_million_tokens
      + (u.images || 0) * r.usd_per_image
      + (u.minutes || 0) * r.usd_per_action_minute
      + ((u.approvals || 0) * r.bobby_minutes_per_approval / 60) * r.bobby_usd_per_hour,
    );
    out[a] = { agent: a, lane, revenue, shadow_cost: shadow, net: round2(revenue - shadow), ...u };
  }
  return out;
}

// Lane closest to its first paying customer (used while total revenue is $0).
// signals: { [lane]: { live_offers, published_packs, can_send, replies_14d } }
export function pickFocus(signals) {
  const score = (s = {}) => (s.live_offers || 0) * 3 + (s.published_packs || 0) * 2 + (s.can_send ? 3 : 0) + Math.min(3, s.replies_14d || 0);
  let best = null, bestScore = 0;
  for (const lane of ['offers', 'assets', 'villa']) {
    const sc = score(signals[lane]);
    if (sc > bestScore) { best = lane; bestScore = sc; }
  }
  return best;
}

// One weekly step of survival pressure. Pure: returns the new lane state.
// prev: { [lane]: { factor, zero_weeks } }, revenue30: { [lane]: usd }, daysOld: age of the economy in days.
export function survivalStep({ prev = {}, revenue30, focus, daysOld, rules = DEFAULT_RULES }) {
  const r = { ...DEFAULT_RULES, ...rules };
  const total = Object.values(revenue30).reduce((n, x) => n + Math.max(0, x), 0);
  const next = {};
  for (const lane of Object.keys(LANES)) {
    const p = { factor: 1, zero_weeks: 0, ...(prev[lane] || {}) };
    const rev = revenue30[lane] || 0;
    if (lane === 'growth') {
      // Overhead: full strength while hunting the first dollar, trimmed once lanes earn on their own.
      next[lane] = { factor: total > 0 ? 0.75 : 1, zero_weeks: 0, state: 'overhead' };
    } else if (rev > 0) {
      next[lane] = { factor: Math.min(r.max_factor, 1 + rev / Math.max(total, 1)), zero_weeks: 0, state: 'earning' };
    } else if (lane === 'email') {
      // Bobby's inbox is never cut: it serves the businesses he runs by hand.
      next[lane] = { factor: 1, zero_weeks: 0, state: 'protected' };
    } else if (lane === focus) {
      next[lane] = { factor: r.focus_factor, zero_weeks: p.zero_weeks + 1, state: 'focus' };
    } else if (daysOld < r.grace_days) {
      next[lane] = { factor: p.factor, zero_weeks: p.zero_weeks + 1, state: 'grace' };
    } else {
      const factor = Math.max(r.floor, round2(Math.min(1, p.factor) * r.cut));
      const zero = p.zero_weeks + 1;
      // Never shut a lane down while the whole company is at $0: there's nowhere better to move the effort.
      const shut = factor <= r.floor && zero >= r.shutdown_weeks && total > 0;
      next[lane] = { factor, zero_weeks: zero, state: shut ? 'shut down' : 'cut back' };
    }
  }
  return next;
}

// Budgets that follow the lane factors. Protected agents never drop below their base.
export function allocate({ laneState, crew = [], rules = DEFAULT_RULES }) {
  const tokens = {}, minutesFactor = {};
  const all = [...Object.keys(BASE_TOKENS), ...crew.filter((c) => ['probation', 'active'].includes(c.status)).map((c) => c.id)];
  for (const a of all) {
    const lane = laneOf(a, crew);
    const spec = crew.find((c) => c.id === a);
    const base = spec ? Number(spec.token_budget) || 6000 : BASE_TOKENS[a];
    let f = lane === 'outside' ? 1 : laneState[lane]?.factor ?? 1;
    if (spec?.status === 'probation') f = Math.min(f, 1); // probation budgets never grow
    if (PROTECTED.includes(a)) f = Math.max(1, f);
    tokens[a] = Math.round(base * f);
    minutesFactor[a] = Math.min(1.5, Math.max(0.5, f));
  }
  const images = Math.round(BASE_IMAGES * Math.max(rules.floor ?? DEFAULT_RULES.floor, laneState.assets?.factor ?? 1));
  const off = [];
  for (const [lane, st] of Object.entries(laneState)) {
    if (st.state !== 'shut down') continue;
    for (const a of LANES[lane].agents) if (!PROTECTED.includes(a)) off.push(a);
  }
  return { tokens, minutesFactor, images, off };
}

export function runway({ revenue30, burn = [] }) {
  const monthlyBurn = round2(burn.reduce((n, b) => n + (Number(b.usd_month) || 0), 0));
  const rev = round2(Object.values(revenue30).reduce((n, x) => n + x, 0));
  return { revenue_30d: rev, burn_month: monthlyBurn, net_month: round2(rev - monthlyBurn), covers: monthlyBurn > 0 ? rev / monthlyBurn : null };
}

export const round2 = (n) => Math.round(Number(n || 0) * 100) / 100;

// ---------- Loading real numbers ----------

export async function loadRules() {
  return { ...DEFAULT_RULES, ...(await kvGet('economy_rules', {})) };
}

export async function loadCrewSafe() {
  try { return await db.select('crew_specs', { order: 'created_at.asc' }); } catch { return []; }
}

// Usage per agent since `fromDay` (ET date, inclusive) to `toDay` (inclusive).
export async function usageBetween(fromDay, toDay) {
  const [llm, runs, approvals] = await Promise.all([
    db.select('llm_usage', { day: [`gte.${fromDay}`, `lte.${toDay}`], select: 'agent,tokens_in,tokens_out', limit: 5000 }),
    db.select('agent_runs', { started_at: [`gte.${fromDay}T04:00:00Z`, `lt.${addDays(toDay, 1)}T04:00:00Z`], select: 'agent,started_at,finished_at', limit: 5000 }),
    db.select('approvals', { created_at: [`gte.${fromDay}T04:00:00Z`, `lt.${addDays(toDay, 1)}T04:00:00Z`], select: 'created_by', limit: 2000 }),
  ]);
  const u = {};
  const get = (a) => (u[a] ||= { tokens: 0, images: 0, minutes: 0, approvals: 0 });
  for (const r of llm) get(r.agent).tokens += (r.tokens_in || 0) + (r.tokens_out || 0);
  for (const r of runs) {
    if (!r.finished_at) continue;
    get(r.agent).minutes += Math.max(0, (Date.parse(r.finished_at) - Date.parse(r.started_at)) / 60000);
  }
  for (const r of approvals) if (r.created_by) get(r.created_by).approvals += 1;
  for (const a of Object.values(u)) a.minutes = round2(a.minutes);
  // Images: the Cloudflare counter (kv) only keeps the current day; it is all Asset Studio work.
  const cf = await kvGet('cf_images', {});
  if (cf.day && cf.day >= fromDay && cf.day <= toDay) get('asset_studio').images += cf.count || 0;
  return u;
}

export async function revenueSince(fromDay) {
  const rows = await db.select('ledger', { day: `gte.${fromDay}`, select: 'line,source,revenue', limit: 5000 });
  const out = Object.fromEntries(Object.keys(LANES).map((l) => [l, 0]));
  for (const r of rows) out[ledgerLane(r)] = round2(out[ledgerLane(r)] + Number(r.revenue || 0));
  return out;
}

export async function focusSignals() {
  const [offers, packs, vcOn, vcPaused, footer, replies] = await Promise.all([
    db.count('launches', { status: 'eq.live' }).catch(() => 0),
    db.count('asset_packs', { status: 'eq.published' }).catch(() => 0),
    kvGet('vc_enabled', false),
    kvGet('vc_paused', false),
    kvGet('vc_footer_address', ''),
    db.count('vc_messages', { direction: 'eq.in', created_at: `gte.${daysAgoIso(14)}` }).catch(() => 0),
  ]);
  return {
    offers: { live_offers: offers },
    assets: { published_packs: packs },
    villa: { can_send: vcOn === true && vcPaused !== true && Boolean(footer), replies_14d: replies },
  };
}

export { etDate, addDays };
