// Economist — daily 11pm ET. Keeps the books and moves effort toward money.
//   1. P&L per agent for today (agent_pnl): lane revenue share − shadow cost (tokens, images, minutes, Bobby's time)
//   2. Runway meter: real revenue (30 days) vs Bobby's real monthly bills (kv economy_burn). New spend budget: $0.
//   3. Once a week: survival pressure per lane (earning lanes grow, the focus lane gets a boost,
//      non-earning lanes are cut back after the grace period, then non-essential agents are switched off)
//   4. Writes the budgets the other agents already obey: llm_caps.agents (tokens/day),
//      asset_rules.images_per_day, economy_budgets.minutes (per-run minutes)
//   5. Reviews the Architect's crew: keep or retire at the end of probation
// HARD LINE: budgets only. It never touches send rules, spend caps, keys, Stripe, or what any agent may do.
import { db, kvGet, kvSet } from './lib/db.js';
import { etDate, addDays } from './lib/time.js';
import {
  LANES, computePnl, pickFocus, survivalStep, allocate, runway, round2,
  loadRules, loadCrewSafe, usageBetween, revenueSince, focusSignals,
} from './lib/economy.js';
import { reviewCrew } from './lib/crew.js';

export async function run(ctx) {
  const ready = await db.select('agent_pnl', { select: 'day', limit: 1 }).then(() => true).catch(() => false);
  if (!ready) return 'waiting for the database update (run the Economy SQL block in Supabase)';

  const today = etDate();
  const from30 = addDays(today, -29);
  const rules = await loadRules();
  const crew = await loadCrewSafe();

  // 1. Today's P&L per agent.
  const [usageToday, revToday, usage30, rev30, burn, signals] = await Promise.all([
    usageBetween(today, today), revenueSince(today), usageBetween(from30, today), revenueSince(from30),
    kvGet('economy_burn', []), focusSignals(),
  ]);
  const pnl = computePnl({ usage: usageToday, laneRevenue: revToday, crew, rules });
  const rows = Object.values(pnl).map((p) => ({
    day: today, agent: p.agent, lane: p.lane, tokens: p.tokens, images: p.images, minutes: p.minutes,
    approvals: p.approvals, revenue: p.revenue, shadow_cost: p.shadow_cost, net: p.net,
  }));
  if (rows.length) await db.insert('agent_pnl', rows, { onConflict: 'day,agent', merge: true });

  // 2. Runway.
  const meter = runway({ revenue30: rev30, burn });
  const focus = Object.values(rev30).some((x) => x > 0) ? null : pickFocus(signals);

  // 3. Survival pressure, at most once every 7 days.
  const state = await kvGet('economy_state', {});
  const started = state.started || today;
  const daysOld = Math.round((Date.parse(today) - Date.parse(started)) / 86400000);
  let lanes = state.lanes || {};
  let adjusted = false;
  if (!state.adjusted_on || Date.parse(today) - Date.parse(state.adjusted_on) >= 7 * 86400000) {
    lanes = survivalStep({ prev: lanes, revenue30: rev30, focus, daysOld, rules });
    adjusted = true;
  } else if (focus !== (state.focus ?? null)) {
    // The focus can move mid-week (e.g. an offer just went live): boost the new one, return the old one to normal.
    lanes = { ...lanes };
    for (const [id, l] of Object.entries(lanes)) if (l.state === 'focus' && id !== focus) lanes[id] = { ...l, factor: 1, state: 'grace' };
    if (focus && lanes[focus]?.state !== 'earning') lanes[focus] = { ...(lanes[focus] || { zero_weeks: 0 }), factor: rules.focus_factor, state: 'focus' };
  }

  // 4. Budgets.
  const plan = allocate({ laneState: lanes, crew, rules });
  const caps = await kvGet('llm_caps', {});
  await kvSet('llm_caps', { ...caps, agents: { ...(caps.agents || {}), ...plan.tokens } });
  const assetRules = await kvGet('asset_rules', {});
  if (assetRules.images_per_day !== plan.images) await kvSet('asset_rules', { ...assetRules, images_per_day: plan.images });
  await kvSet('economy_budgets', { minutes: plan.minutesFactor, tokens: plan.tokens, images: plan.images, day: today });

  const switchedOff = [];
  for (const a of plan.off) {
    const row = await db.one('agents', { id: `eq.${a}` });
    if (row && row.enabled !== false) {
      await db.update('agents', { id: `eq.${a}` }, { enabled: false });
      ctx.log('economy', `Switched off ${row.name}: its lane earned nothing for ${lanes[laneOfAgent(a)]?.zero_weeks} weeks while another lane earns. Turn it back on from the Economy page.`, { table: 'agents', id: a });
      switchedOff.push(row.name);
    }
  }

  // 5. Crew probation.
  const crewNote = await reviewCrew(ctx);

  // Lane P&L, 30 days.
  const pnl30 = computePnl({ usage: usage30, laneRevenue: rev30, crew, rules });
  const lanePnl = {};
  for (const id of Object.keys(LANES)) {
    const members = Object.values(pnl30).filter((p) => p.lane === id);
    lanePnl[id] = {
      revenue: rev30[id] || 0,
      shadow_cost: round2(members.reduce((n, p) => n + p.shadow_cost, 0)),
      net: round2((rev30[id] || 0) - members.reduce((n, p) => n + p.shadow_cost, 0)),
      ...lanes[id],
    };
  }

  await kvSet('economy_state', { started, lanes, adjusted_on: adjusted ? today : state.adjusted_on, focus });
  await kvSet('economy_snapshot', {
    day: today, at: new Date().toISOString(), meter, focus, lanes: lanePnl,
    agents: Object.fromEntries(Object.values(pnl30).map((p) => [p.agent, { lane: p.lane, revenue: p.revenue, shadow_cost: p.shadow_cost, net: p.net, tokens: p.tokens }])),
  });

  const summary = [
    `revenue 30d $${meter.revenue_30d} vs burn $${meter.burn_month}/mo`,
    focus ? `focus: ${LANES[focus].name}` : 'earning lanes lead',
    adjusted ? 'weekly budgets reset' : null,
    switchedOff.length ? `switched off ${switchedOff.join(', ')}` : null,
    crewNote || null,
  ].filter(Boolean).join(' · ');
  ctx.log('economy', `Books closed: ${summary}`);
  return summary;
}

function laneOfAgent(a) {
  return Object.entries(LANES).find(([, l]) => l.agents.includes(a))?.[0];
}
