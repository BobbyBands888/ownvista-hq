#!/usr/bin/env node
// Entry point for the hourly GitHub Actions job.
//   node agents/run.js                 → run every agent that is due (router)
//   node agents/run.js --agent=operator → run one agent now (manual dispatch)
//   node agents/run.js --plan          → print the plan (used to decide whether to install ffmpeg / Python)
import { appendFileSync } from 'node:fs';
import { db } from './lib/db.js';
import { env } from './lib/env.js';
import { startJob, finishJob } from './lib/log.js';
import { etDate } from './lib/time.js';
import { dueAgents, scheduleFor, loadCrew, AGENT_IDS } from './router.js';
import { runAgent as runOne } from './runner.js';

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
    await loadCrew();
    const agents = requested === 'all' ? AGENT_IDS : [requested];
    const needsFfmpeg = agents.includes('villa_studio') || agents.includes('asset_studio') || requested === 'all';
    const books = agents.includes('book_studio') ? await import('./lab/book_studio.js') : null;
    const needsPython = !!books;
    const needsToddler = needsPython && await books.needsToddler().catch(() => false);
    return { agents, needsFfmpeg, needsPython, needsToddler, trigger: 'manual', next: null };
  }
  const { due, next } = await dueAgents();
  const agents = [];
  for (const id of due) {
    if (scheduleFor(id).onlyIfWork && !(await studioHasWork())) continue;
    agents.push(id);
  }
  // ffmpeg is installed only when Villa Studio has an order or the Asset Studio can still make images today.
  const assetWork = agents.includes('asset_studio') && await (await import('./lab/asset_studio.js')).hasWork().catch(() => false);
  // Python (reportlab, pypdf) is installed only when the Book Studio has a book to build.
  const books = agents.includes('book_studio') ? await import('./lab/book_studio.js') : null;
  const needsPython = !!books && await books.hasWork().catch(() => false);
  const needsToddler = needsPython && await books.needsToddler().catch(() => false);
  return { agents, needsFfmpeg: agents.includes('villa_studio') || assetWork, needsPython, needsToddler, trigger: 'schedule', next };
}

const runAgent = (id, opts) => runOne(id, { ...opts, jobDeadline: JOB_DEADLINE });

async function main() {
  const p = await plan();
  if (args.plan) {
    console.log(JSON.stringify({ agents: p.agents, needsFfmpeg: p.needsFfmpeg, needsPython: p.needsPython }));
    if (process.env.GITHUB_OUTPUT) {
      appendFileSync(process.env.GITHUB_OUTPUT, `needs_ffmpeg=${p.needsFfmpeg}\nneeds_python=${!!p.needsPython}\nneeds_toddler=${!!p.needsToddler}\nagents=${p.agents.join(',')}\n`);
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
