// Crew made by the Architect. A crew member is DATA (a row in crew_specs), never new code:
//   kind 'clone' → runs an existing, proven agent module under its own name and budget
//   kind 'new'   → runs agents/spawned.js, which can only use the building blocks below
// The Architect cannot add a block, a module or a permission; validateSpec() rejects anything off-menu.
import { db, kvGet, kvSet } from './db.js';
import { etDate, addDays } from './time.js';
import { truncate } from './text.js';
import { LANES } from './economy.js';

// Proven agents the Architect may clone when their paying lane is bottlenecked.
// (No Villa senders, no Operator, no trader: their limits live in the database or must stay single.)
export const CLONABLE = ['builder', 'launcher', 'asset_studio', 'researcher', 'analyst'];

// The only things a new crew member can do. Every one writes a PROPOSAL row that an existing,
// guarded pipeline (or Bobby) acts on. None sends, spends, publishes, signs up or trades.
export const BLOCKS = {
  propose_idea: { label: 'Propose a growth idea (goes to Ideas for approval)', perRun: 1, perWeek: 3 },
  agent_task: { label: 'Create a writing task for the Operator', perRun: 2, perWeek: 6 },
  research_query: { label: 'Suggest a research search (paused until search is approved)', perRun: 2, perWeek: 4 },
  draft_asset: { label: 'Draft copy for a launched/approved idea; Bobby reviews it in Needs you (never published by itself)', perRun: 1, perWeek: 3 },
  note_to_bobby: { label: 'One short note in Needs you', perRun: 1, perWeek: 1 },
};

// What a new crew member may read (summaries only).
export const READS = ['ledger', 'launches', 'asset_packs', 'knowledge', 'ideas', 'activity', 'signals', 'villa_counts'];

export const ASSET_KINDS = ['sales_copy_variant', 'outreach_draft', 'seo_article', 'listing_copy', 'faq', 'social_post'];

export const LIMITS = {
  max_crew: 4, // probation + active, all kinds
  max_clones_per_base: 2,
  probation_days: 14,
  probation_tokens: 8000, // per day
  min_tokens: 2000,
  allowed_hours: [8, 10, 12, 14, 16, 18, 20],
};

const ID_RE = /^x_[a-z0-9_]{3,30}$/;

export function slugId(name, taken = []) {
  const base = `x_${String(name).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 24) || 'crew'}`;
  if (!taken.includes(base)) return base;
  for (let i = 2; ; i++) if (!taken.includes(`${base}_${i}`)) return `${base}_${i}`;
}

// Validate and normalize a proposed spec. Returns { ok, spec, problems }.
export function validateSpec(raw, { existing = [] } = {}) {
  const problems = [];
  const live = existing.filter((c) => ['probation', 'active'].includes(c.status));
  const kind = raw.kind === 'clone' ? 'clone' : raw.kind === 'new' ? 'new' : null;
  if (!kind) problems.push('kind must be clone or new');
  const name = truncate(String(raw.name || '').trim(), 60);
  if (!name) problems.push('missing name');
  const id = raw.id || slugId(name || raw.base || 'crew', existing.map((c) => c.id));
  if (!ID_RE.test(id)) problems.push(`bad id ${id}`);
  if (existing.some((c) => c.id === id)) problems.push('id already used');
  const lane = LANES[raw.lane] ? raw.lane : null;
  if (!lane) problems.push('unknown lane');
  if (live.length >= LIMITS.max_crew) problems.push(`crew is full (${LIMITS.max_crew})`);

  let base = null, blocks = [], reads = [];
  if (kind === 'clone') {
    base = CLONABLE.includes(raw.base) ? raw.base : null;
    if (!base) problems.push(`${raw.base} cannot be cloned`);
    if (live.filter((c) => c.base === raw.base).length >= LIMITS.max_clones_per_base) problems.push(`already ${LIMITS.max_clones_per_base} clones of ${raw.base}`);
  } else if (kind === 'new') {
    const askedBlocks = Array.isArray(raw.blocks) ? raw.blocks : [];
    const off = askedBlocks.filter((b) => !BLOCKS[b]);
    if (off.length) problems.push(`off-menu blocks: ${off.join(', ')}`);
    blocks = [...new Set(askedBlocks.filter((b) => BLOCKS[b]))];
    if (!blocks.length) problems.push('needs at least one block');
    reads = [...new Set((Array.isArray(raw.reads) ? raw.reads : []).filter((r) => READS.includes(r)))].slice(0, 5);
  }
  const mission = truncate(String(raw.mission || '').trim(), 600);
  if (mission.length < 20) problems.push('mission too short');
  if (/\b(send|email (them|prospects|leads)|post (it|to)|publish|sign ?up|create (an )?account|pay|purchase|buy|charge|trade|wire|transfer)\b/i.test(mission)) {
    problems.push('mission asks for an action no crew member can take');
  }
  const hour = LIMITS.allowed_hours.includes(Number(raw.hour)) ? Number(raw.hour) : 12;
  const killMin = Math.min(5, Math.max(1, Math.round(Number(raw.kill_min) || 2)));
  const spec = {
    id, kind, base, name, lane, mission, blocks, reads,
    schedule: kind === 'clone' ? { type: 'hourly', hours: Array.from({ length: 24 }, (_, i) => i) } : { type: 'daily', hour },
    token_budget: Math.max(LIMITS.min_tokens, Math.min(LIMITS.probation_tokens, Math.round(Number(raw.token_budget) || LIMITS.probation_tokens))),
    expected_money: truncate(String(raw.expected_money || 'unknown').trim(), 200),
    kill_metric: { days: LIMITS.probation_days, min_accepted: killMin, text: kind === 'clone' ? `Retire on day ${LIMITS.probation_days} unless its lane brings in new revenue.` : `Retire on day ${LIMITS.probation_days} unless you approve at least ${killMin} of its ideas or drafts.` },
    why: truncate(String(raw.why || '').trim(), 600),
  };
  return { ok: problems.length === 0, spec, problems };
}

// Router entry for a crew member.
export function scheduleEntry(spec) {
  const s = spec.schedule || {};
  if (s.type === 'hourly') return { id: spec.id, type: 'hourly', hours: s.hours || [], budgetMin: 4, label: 'Hourly (clone)' };
  return { id: spec.id, type: 'daily', hour: Number(s.hour) || 12, budgetMin: 3, label: `Daily ${((Number(s.hour) + 11) % 12) + 1}${Number(s.hour) < 12 ? 'am' : 'pm'} ET (crew)` };
}

// Deploy: one crew_specs row + one agents row (so it shows on the Station and can be switched off).
export async function deploy(spec, { createdBy = 'architect' } = {}) {
  const today = etDate();
  const row = {
    ...spec, status: 'probation', created_by: createdBy,
    probation_ends: addDays(today, spec.kill_metric.days), stats: {},
  };
  await db.insertOne('crew_specs', row);
  await db.insert('agents', [{
    id: spec.id, name: spec.name, description: truncate(spec.mission, 300),
    schedule: scheduleEntry(spec).label, sort: 50, enabled: true,
  }], { onConflict: 'id', merge: true });
  // Its token share starts at the probation budget (the economist resizes it daily).
  const caps = await kvGet('llm_caps', {});
  await kvSet('llm_caps', { ...caps, agents: { ...(caps.agents || {}), [spec.id]: spec.token_budget } });
  return row;
}

export async function retire(spec, reason) {
  await db.update('crew_specs', { id: `eq.${spec.id}` }, { status: 'retired', retired_at: new Date().toISOString(), retire_reason: truncate(reason, 500) });
  await db.update('agents', { id: `eq.${spec.id}` }, { enabled: false });
  const caps = await kvGet('llm_caps', {});
  // 1 token, not 0: a 0 cap means "no cap" in llm.js. (It's also switched off in the agents table.)
  await kvSet('llm_caps', { ...caps, agents: { ...(caps.agents || {}), [spec.id]: 1 } });
}

// How a crew member is doing: real revenue in its lane during probation + its outputs that were accepted.
export async function crewStats(spec) {
  const since = `${spec.created_at || new Date().toISOString()}`;
  const [ideas, tasks, approvals, assets, sources] = await Promise.all([
    db.select('ideas', { created_by: `eq.${spec.id}`, select: 'status' }),
    db.select('tasks', { created_by: `eq.${spec.id}`, select: 'status' }),
    db.select('approvals', { created_by: `eq.${spec.id}`, select: 'status' }),
    db.select('assets', { created_by: `eq.${spec.id}`, select: 'id' }),
    db.select('sources', { added_by: `eq.${spec.id}`, select: 'status' }).catch(() => []),
  ]);
  // Only Bobby's yes counts (an approved idea or an approved draft/note). Tasks the Operator finishes don't:
  // agents grading agents would let a crew member pass by keeping another agent busy.
  const accepted = ideas.filter((i) => ['approved', 'launched'].includes(i.status)).length
    + approvals.filter((a) => a.status === 'approved').length;
  const outputs = ideas.length + tasks.length + approvals.length + assets.length + sources.length;
  let revenue = 0;
  if (spec.kind === 'clone') {
    const rows = await db.select('ledger', { created_at: `gte.${since}`, select: 'line,source,revenue', limit: 2000 });
    const { ledgerLane } = await import('./economy.js');
    revenue = rows.filter((r) => ledgerLane(r) === spec.lane).reduce((n, r) => n + Number(r.revenue || 0), 0);
  }
  return { accepted, outputs, revenue: Math.round(revenue * 100) / 100 };
}

// Pure: keep or retire at the end of probation?
export function judgeCrew(spec, stats, today = etDate()) {
  if (spec.status !== 'probation') return { action: 'none' };
  if (today < spec.probation_ends) return { action: 'none' };
  const min = spec.kill_metric?.min_accepted ?? 2;
  if (stats.revenue > 0 || (spec.kind === 'new' && stats.accepted >= min)) {
    return { action: 'keep', reason: stats.revenue > 0 ? `$${stats.revenue} in its lane during probation` : `${stats.accepted} outputs approved or used` };
  }
  return { action: 'retire', reason: `Kill metric missed: ${spec.kind === 'clone' ? 'no new revenue in its lane' : `${stats.accepted} of ${min} outputs accepted`} after ${spec.kill_metric?.days ?? 14} days.` };
}

// Daily: refresh stats on every live crew member, close probation (keep/retire).
export async function reviewCrew(ctx) {
  let crew;
  try { crew = await db.select('crew_specs', { status: 'in.(probation,active)' }); } catch { return ''; }
  const out = [];
  for (const spec of crew) {
    const stats = await crewStats(spec);
    await db.update('crew_specs', { id: `eq.${spec.id}` }, { stats: { ...stats, at: new Date().toISOString() } });
    const verdict = judgeCrew(spec, stats);
    if (verdict.action === 'keep') {
      await db.update('crew_specs', { id: `eq.${spec.id}` }, { status: 'active' });
      ctx.log('economy', `${spec.name} passed probation (${verdict.reason}) and stays on the crew`, { table: 'crew_specs', id: spec.id });
      out.push(`kept ${spec.name}`);
    } else if (verdict.action === 'retire') {
      await retire(spec, verdict.reason);
      ctx.log('economy', `Retired ${spec.name}: ${verdict.reason}`, { table: 'crew_specs', id: spec.id });
      out.push(`retired ${spec.name}`);
    }
  }
  return out.join(', ');
}
