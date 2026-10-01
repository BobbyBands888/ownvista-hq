// Runs one agent with bookkeeping (agent_runs row, caps, errors). Shared by the hourly GitHub job
// (agents/run.js) and the continuous Vercel tick (api/tick.js).
import { db, kvGet } from './lib/db.js';
import { CapError } from './lib/llm.js';
import { SpendRefused } from './lib/spend.js';
import { startRun, finishRun, activity } from './lib/log.js';
import { scheduleFor } from './router.js';

export const MODULES = {
  villa_outreach: () => import('./villa/outreach.js'),
  operator: () => import('./operator.js'),
  villa_studio: () => import('./villa/studio.js'),
  researcher: () => import('./researcher.js'),
  strategist: () => import('./strategist.js'),
  scout: () => import('./scout.js'),
  analyst: () => import('./lab/analyst.js'),
  builder: () => import('./lab/builder.js'),
  judge: () => import('./lab/judge.js'),
  launcher: () => import('./lab/launcher.js'),
  asset_studio: () => import('./lab/asset_studio.js'),
  learner: () => import('./learner.js'),
  paper_trader: () => import('./trader/paper.js'),
  economist: () => import('./economist.js'),
  architect: () => import('./architect.js'),
  product_scout: () => import('./lab/product_scout.js'),
  dropship_scout: () => import('./lab/dropship_scout.js'),
  autopilot: () => import('./lab/autopilot_agent.js'),
  marketer: () => import('./lab/marketer.js'),
};

// Extra manual-only commands.
export const COMMANDS = {
  villa_test_email: { agent: 'villa_outreach', fn: 'testEmail' },
  villa_test_order: { agent: 'villa_studio', fn: 'createTestOrder' },
  villa_preflight: { agent: 'villa_outreach', fn: 'preflight' },
  trader_probe: { agent: 'paper_trader', fn: 'probe' },
};

// Station/World rows for agents added after the original SQL seed (no SQL block needed).
const NEW_ROWS = {
  product_scout: { name: 'Product Scout', description: 'Scans Etsy (official API), itch.io and Product Hunt for products people buy; digital ones go straight to the Launcher; print-on-demand designs and physical ones go to the Radar (scout only).', sort: 34 },
  dropship_scout: { name: 'Dropship Scout', description: 'Hunts trending physical products with margin, shipping time and saturation scored; results on the Radar page.', sort: 35 },
  autopilot: { name: 'Autopilot', description: 'Approves new ideas on Bobby\'s behalf (caps, IP and copy checks) so they build and go live without waiting.', sort: 36 },
  marketer: { name: 'Marketer', description: 'Writes draft-only marketing kits for live offers and itch.io packs: better listing, tags, Pinterest pins, Reddit drafts, search text. Bobby posts; it never does.', sort: 37 },
};
const ensured = new Set();
export async function ensureAgentRow(id) {
  if (!NEW_ROWS[id] || ensured.has(id)) return;
  ensured.add(id);
  const have = await db.one('agents', { id: `eq.${id}` }).catch(() => null);
  if (!have) await db.insert('agents', [{ id, ...NEW_ROWS[id], schedule: scheduleFor(id)?.label || null, enabled: true }], { onConflict: 'id', ignoreDuplicates: true }).catch(() => {});
}

// A crew member is data: a clone runs its base agent's module, a new one runs spawned.js. Nothing else.
export function moduleFor(agentId) {
  if (MODULES[agentId]) return { load: MODULES[agentId], spec: null };
  const spec = scheduleFor(agentId)?.spec;
  if (!spec) return null;
  if (spec.kind === 'clone' && MODULES[spec.base]) return { load: MODULES[spec.base], spec };
  if (spec.kind === 'new') return { load: () => import('./spawned.js'), spec };
  return null;
}

// jobDeadline: absolute ms the whole job must end by. budgetMin overrides the schedule's minutes.
export async function runAgent(id, { jobId, trigger, jobDeadline, budgetMin }) {
  const cmd = COMMANDS[id];
  const agentId = cmd ? cmd.agent : id;
  const m = moduleFor(agentId);
  if (!m) throw new Error(`Unknown agent ${id}`);
  await ensureAgentRow(agentId);
  const row = await db.one('agents', { id: `eq.${agentId}` });
  if (row && row.enabled === false && trigger !== 'manual') return 'skipped';
  // Minutes per run follow the economy (0.5x–1.5x of the base budget, never under 2 minutes).
  const factor = Number((await kvGet('economy_budgets', {}).catch(() => ({})))?.minutes?.[agentId]) || 1;
  const base = budgetMin ?? scheduleFor(agentId)?.budgetMin ?? 5;
  const budget = Math.max(budgetMin ? 1 : 2, Math.round(base * factor)) * 60000;
  const deadlineMs = trigger === 'manual' ? jobDeadline : Math.min(jobDeadline, Date.now() + budget);
  const ctx = await startRun(agentId, { jobId, trigger: cmd ? `manual:${id}` : trigger, deadlineMs });
  if (m.spec) ctx.spec = m.spec;
  try {
    const mod = await m.load();
    const fn = cmd ? mod[cmd.fn] : mod.run;
    const summary = await fn(ctx);
    await finishRun(ctx, 'ok', { summary: typeof summary === 'string' ? summary : undefined });
    return 'ok';
  } catch (e) {
    if (e instanceof CapError) {
      ctx.note(`stopped: ${e.message}`);
      await finishRun(ctx, 'capped');
      return 'capped';
    }
    if (e instanceof SpendRefused) {
      ctx.note(e.message);
      await finishRun(ctx, 'ok');
      return 'ok';
    }
    console.error(`[${id}]`, e);
    await finishRun(ctx, 'error', { error: `${e.message}\n${(e.stack || '').split('\n').slice(1, 6).join('\n')}` });
    await activity(agentId, 'error', e.message);
    return 'error';
  }
}
