#!/usr/bin/env node
// Entry point for the hourly GitHub Actions job.
//   node agents/run.js                 → run every agent that is due (router)
//   node agents/run.js --agent=operator → run one agent now (manual dispatch)
//   node agents/run.js --plan          → print the plan (used to decide whether to install ffmpeg)
import { appendFileSync } from 'node:fs';
import { db } from './lib/db.js';
import { env } from './lib/env.js';
import { CapError } from './lib/llm.js';
import { SpendRefused } from './lib/spend.js';
import { startJob, finishJob, startRun, finishRun, activity } from './lib/log.js';
import { etDate } from './lib/time.js';
import { dueAgents, scheduleFor, AGENT_IDS } from './router.js';

const MODULES = {
  villa_outreach: () => import('./villa/outreach.js'),
  operator: () => import('./operator.js'),
  villa_studio: () => import('./villa/studio.js'),
  researcher: () => import('./researcher.js'),
  strategist: () => import('./strategist.js'),
  scout: () => import('./scout.js'),
  analyst: () => import('./lab/analyst.js'),
  builder: () => import('./lab/builder.js'),
  judge: () => import('./lab/judge.js'),
  learner: () => import('./learner.js'),
};

// Extra manual-only commands.
const COMMANDS = {
  villa_test_email: { agent: 'villa_outreach', fn: 'testEmail' },
  villa_test_order: { agent: 'villa_studio', fn: 'createTestOrder' },
  villa_preflight: { agent: 'villa_outreach', fn: 'preflight' },
};

const args = Object.fromEntries(process.argv.slice(2).map((a) => {
  const [k, v] = a.replace(/^--/, '').split('=');
  return [k, v ?? true];
}));

const JOB_START = Number(env('JOB_STARTED_AT', '0')) * 1000 || Date.now();
const JOB_DEADLINE = JOB_START + Number(env('JOB_BUDGET_MIN', '17')) * 60000;

async function studioHasWork() {
  const n = await db.count('vc_orders', { status: 'in.(photos_received,generating,qa,upgrading,stitching,approved)' });
  return n > 0;
}

async function plan() {
  const requested = args.agent && args.agent !== 'auto' ? String(args.agent) : null;
  if (requested) {
    const agents = requested === 'all' ? AGENT_IDS : [requested];
    const needsFfmpeg = agents.includes('villa_studio') || requested === 'all';
    return { agents, needsFfmpeg, trigger: 'manual', next: null };
  }
  const { due, next } = await dueAgents();
  const agents = [];
  for (const id of due) {
    if (scheduleFor(id).onlyIfWork && !(await studioHasWork())) continue;
    agents.push(id);
  }
  return { agents, needsFfmpeg: agents.includes('villa_studio'), trigger: 'schedule', next };
}

async function runAgent(id, { jobId, trigger }) {
  const cmd = COMMANDS[id];
  const agentId = cmd ? cmd.agent : id;
  if (!MODULES[agentId]) throw new Error(`Unknown agent ${id}`);
  const row = await db.one('agents', { id: `eq.${agentId}` });
  if (row && row.enabled === false && trigger !== 'manual') return 'skipped';
  const budget = (scheduleFor(agentId)?.budgetMin ?? 5) * 60000;
  const deadlineMs = trigger === 'manual' ? JOB_DEADLINE : Math.min(JOB_DEADLINE, Date.now() + budget);
  const ctx = await startRun(agentId, { jobId, trigger: cmd ? `manual:${id}` : trigger, deadlineMs });
  try {
    const mod = await MODULES[agentId]();
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

async function main() {
  const p = await plan();
  if (args.plan) {
    console.log(JSON.stringify({ agents: p.agents, needsFfmpeg: p.needsFfmpeg }));
    if (process.env.GITHUB_OUTPUT) {
      appendFileSync(process.env.GITHUB_OUTPUT, `needs_ffmpeg=${p.needsFfmpeg}\nagents=${p.agents.join(',')}\n`);
    }
    return;
  }

  const jobId = await startJob({ trigger: p.trigger, githubRunId: env('GITHUB_RUN_ID') });
  const results = {};
  for (const id of p.agents) {
    if (Date.now() > JOB_DEADLINE - 30000) { results[id] = 'deferred'; continue; }
    results[id] = await runAgent(id, { jobId, trigger: p.trigger });
    console.log(`${id}: ${results[id]}`);
  }

  // Next-run times for the World view.
  const { next } = p.next ? p : await dueAgents();
  await Promise.all(Object.entries(next).map(([id, t]) =>
    db.update('agents', { id: `eq.${id}` }, {
      next_run_at: t ? t.toISOString() : null,
      ...(scheduleFor(id)?.label ? { schedule: scheduleFor(id).label } : {}),
    }).catch(() => {})));

  const minutes = await finishJob(jobId, { startedAtMs: JOB_START, agents: p.agents });
  await addMinutesToday(minutes);

  const failed = Object.values(results).includes('error');
  if (failed && p.trigger === 'manual') process.exitCode = 1;
}

async function addMinutesToday(minutes) {
  const day = etDate();
  const row = await db.one('metrics_daily', { day: `eq.${day}` });
  if (row) await db.update('metrics_daily', { day: `eq.${day}` }, { actions_minutes: (row.actions_minutes || 0) + minutes });
  else await db.insert('metrics_daily', [{ day, actions_minutes: minutes }], { onConflict: 'day', merge: true });
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
