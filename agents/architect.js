// Architect — checks hourly, full review Sundays 7pm ET. Shapes the crew around money.
//   Hourly: if the Researcher queued a gap no agent covers, design one crew member for it (max one a day).
//   1. Retires crew members that cost more than they bring (no accepted outputs or revenue for 4 weeks)
//   2. Clones a PROVEN agent where a paying lane is bottlenecked (its runs keep hitting caps, or work piles up)
//   3. Designs one brand-new kind of crew member aimed at the lane closest to money
// Both deploy automatically (Bobby's decision, Sep 30) on Claude's CEO terms:
//   - a crew member is data, not code: clones run an existing agent module; new ones run agents/spawned.js,
//     which can only write proposals (ideas, tasks, paused searches, draft copy, one note a week)
//   - validateSpec() rejects anything off-menu; the full guardrail test suite runs before every job
//   - probation: small token budget, 14-day kill metric, card on the Economy page with a Stop button
//   - anything needing money, an account, a key, or emailing a new audience still waits for Bobby
import { db, kvGet, kvSet } from './lib/db.js';
import { chat } from './lib/llm.js';
import { systemPrompt, untrusted } from './lib/guard.js';
import { truncate } from './lib/text.js';
import { daysAgoIso, etDate, et } from './lib/time.js';
import { LANES } from './lib/economy.js';
import { CLONABLE, BLOCKS, READS, LIMITS, validateSpec, deploy, retire, crewStats, slugId } from './lib/crew.js';

export async function run(ctx) {
  let crew;
  try { crew = await db.select('crew_specs', { order: 'created_at.asc' }); } catch { return 'waiting for the database update (run the Economy SQL block in Supabase)'; }
  const snap = await kvGet('economy_snapshot', null);
  if (!snap) return 'waiting for the Economist\'s first books';
  const now = new Date();
  // Full review once per Sunday evening (7pm or the first run after it).
  const weekly = isWeeklySlot(now) && (await kvGet('architect_weekly_on', null)) !== etDate(now);
  if (weekly) await kvSet('architect_weekly_on', etDate(now));
  const queue = await kvGet('architect_queue', []);
  const lastNew = crew.filter((c) => c.kind === 'new').map((c) => c.created_at).sort().pop() || null;
  if (!weekly && !shouldDesign({ weekly, queueLen: queue.length, lastDesignAt: lastNew, now })) {
    return queue.length ? `${queue.length} gap(s) queued; next design after the daily limit` : 'no new gaps';
  }
  const out = [];
  if (!weekly) {
    const live = crew.filter((c) => ['probation', 'active'].includes(c.status));
    if (live.length >= LIMITS.max_crew) return `${queue.length} gap(s) queued, but the crew is full (${LIMITS.max_crew})`;
    const made = await design(ctx, snap, crew, queue);
    await kvSet('architect_queue', []);
    return made || `looked at ${queue.length} gap(s); none worth a crew member`;
  }

  // 1. Retire active crew that stopped paying their way.
  for (const spec of crew.filter((c) => c.status === 'active')) {
    const stats = await crewStats(spec);
    const weekly = [...(spec.stats?.weekly || []), { day: etDate(), accepted: stats.accepted, revenue: stats.revenue }].slice(-5);
    await db.update('crew_specs', { id: `eq.${spec.id}` }, { stats: { ...spec.stats, ...stats, weekly } });
    const old = weekly[0];
    if (weekly.length >= 5 && stats.accepted === old.accepted && stats.revenue === old.revenue) {
      await retire(spec, 'No accepted outputs and no revenue for 4 weeks.');
      ctx.log('architect', `Retired ${spec.name}: nothing accepted and no revenue for 4 weeks`, { table: 'crew_specs', id: spec.id });
      out.push(`retired ${spec.name}`);
    }
  }
  crew = await db.select('crew_specs', { order: 'created_at.asc' });

  // 2. Clone a proven agent where a paying lane is bottlenecked.
  const earning = Object.entries(snap.lanes || {}).filter(([, l]) => l.revenue > 0).map(([id]) => id);
  for (const lane of earning) {
    const base = await bottleneck(lane);
    if (!base) continue;
    const name = `${base.id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())} #${crew.filter((c) => c.base === base.id).length + 2}`;
    const { ok, spec, problems } = validateSpec({
      kind: 'clone', base: base.id, name, lane,
      mission: `Second shift for ${base.id}: ${LANES[lane].name} is earning and ${base.why}. Same code, same guardrails, own budget.`,
      expected_money: `More throughput in a lane that made $${snap.lanes[lane].revenue} in 30 days`,
      id: slugId(`${base.id}_clone`, crew.map((c) => c.id)),
    }, { existing: crew });
    if (!ok) { ctx.note(`clone of ${base.id} skipped: ${problems.join('; ')}`); continue; }
    await deploy(spec);
    ctx.log('architect', `Cloned ${base.id} as "${spec.name}" (${base.why}). Probation 14 days, ${spec.token_budget} tokens/day.`, { table: 'crew_specs', id: spec.id });
    out.push(`cloned ${base.id}`);
    crew.push({ ...spec, status: 'probation' });
    break; // one clone a week
  }

  // 3. Design one new kind of crew member.
  const live = crew.filter((c) => ['probation', 'active'].includes(c.status));
  if (live.length < LIMITS.max_crew && !ctx.outOfTime(90000)) {
    const made = await design(ctx, snap, crew, queue);
    await kvSet('architect_queue', []);
    if (made) out.push(made);
  } else if (live.length >= LIMITS.max_crew) out.push('crew is full');

  return out.join(' · ') || 'no changes this week';
}

// Is this earning lane's proven agent the bottleneck? Returns { id, why } or null.
async function bottleneck(lane) {
  for (const id of LANES[lane].agents.filter((a) => CLONABLE.includes(a))) {
    const capped = await db.count('agent_runs', { agent: `eq.${id}`, status: 'eq.capped', started_at: `gte.${daysAgoIso(7)}` });
    if (capped >= 3) return { id, why: `${id} hit its limits ${capped} times this week` };
    if (id === 'launcher') {
      const waiting = await db.count('launches', { status: 'in.(draft,waiting_key)' }).catch(() => 0);
      if (waiting >= 3) return { id, why: `${waiting} offers are waiting to launch` };
    }
    if (id === 'builder') {
      const waiting = await db.count('ideas', { status: 'eq.approved', assets_built_at: 'is.null' });
      if (waiting >= 3) return { id, why: `${waiting} approved ideas are waiting for assets` };
    }
  }
  return null;
}

async function design(ctx, snap, crew, queue = []) {
  const agents = await db.select('agents', { select: 'id,name,description,enabled', order: 'sort' });
  const retired = crew.filter((c) => c.status === 'retired').slice(-6);
  const menu = Object.entries(BLOCKS).map(([k, v]) => `- ${k}: ${v.label} (max ${v.perWeek}/week)`).join('\n');
  const system = systemPrompt('the Architect', `
You design ONE new crew member for Ownvista HQ, or none if nothing would clearly help.
The company must earn to stay alive. Revenue is ${snap.meter?.revenue_30d ? `$${snap.meter.revenue_30d} in 30 days` : '$0 so far'}.
${snap.focus ? `Focus lane (closest to the first paying customer): ${snap.focus} — ${LANES[snap.focus].name}.` : 'Earning lanes lead; help the one with the best return.'}
A crew member can ONLY use these building blocks (every output is a proposal someone else acts on):
${menu}
It may read: ${READS.join(', ')}.
It can never send email, post, publish, pay, sign up, create accounts, use keys or trade. Do not design around that.
Do not duplicate an existing agent's job. Learn from retired crew and why they failed.
It keeps its job only if, within 14 days, its outputs get approved/used or its lane earns money.
JSON only: {"create":true|false,"why":"one paragraph: the bottleneck to money it removes",
 "spec":{"kind":"new","name":"2-4 words","lane":"${Object.keys(LANES).join('|')}","mission":"what it does each run, concretely",
 "blocks":["..."],"reads":["..."],"hour":12,"token_budget":6000,"expected_money":"plain words, honest","kill_min":2}}`);
  const user = [
    `Lanes (30 days): ${JSON.stringify(snap.lanes)}`,
    `Existing agents:\n${agents.map((a) => `- ${a.name}${a.enabled === false ? ' (off)' : ''}: ${truncate(a.description || '', 160)}`).join('\n')}`,
    `Retired crew:\n${retired.map((c) => `- ${c.name}: ${truncate(c.mission, 120)} — ${c.retire_reason || ''}`).join('\n') || '(none)'}`,
    `Gaps the Researcher found that no agent covers (prefer designing for the strongest one):\n${queue.map((q) => untrusted(q.url || 'researcher gap', `${q.title}: ${q.why}\nSuggested mission: ${q.mission}`, 700)).join('\n') || '(none)'}`,
  ].join('\n\n');
  const { json } = await chat({ ctx, tier: 'smart', json: true, maxTokens: 1400, system, messages: [{ role: 'user', content: user }] });
  if (!json.create || !json.spec) { ctx.note(`no new crew: ${truncate(json.why || 'nothing clearly useful', 200)}`); return null; }
  const { ok, spec, problems } = validateSpec({ ...json.spec, kind: 'new', why: json.why }, { existing: crew });
  if (!ok) {
    ctx.log('architect', `Rejected its own design "${truncate(json.spec.name || '', 60)}": ${problems.join('; ')}`);
    return null;
  }
  await deploy(spec);
  ctx.log('architect', `New crew member "${spec.name}" on probation: ${truncate(spec.mission, 200)} Budget ${spec.token_budget} tokens/day. ${spec.kill_metric.text}`, { table: 'crew_specs', id: spec.id });
  return `designed ${spec.name}`;
}

// Sunday from 7pm ET = the full weekly review window.
export function isWeeklySlot(now = new Date()) {
  const t = et(now);
  return t.weekday === 0 && t.hour >= 19;
}

// Between weekly reviews, design only for queued gaps, at most one new crew member per 24 hours.
export function shouldDesign({ weekly, queueLen, lastDesignAt, now = new Date() }) {
  if (weekly) return true;
  if (!queueLen) return false;
  return !lastDesignAt || now - new Date(lastDesignAt) >= 24 * 3600000;
}
