// Run bookkeeping: job_runs, agent_runs, activity.
import { db } from './db.js';

export async function startJob({ trigger, githubRunId }) {
  const row = await db.insertOne('job_runs', { trigger, github_run_id: githubRunId ?? null });
  return row.id;
}

export async function finishJob(jobId, { startedAtMs, agents }) {
  const minutes = Math.max(1, Math.ceil((Date.now() - startedAtMs) / 60000));
  await db.update('job_runs', { id: `eq.${jobId}` }, {
    finished_at: new Date().toISOString(), minutes, agents,
  });
  return minutes;
}

export async function activity(agent, kind, message, ref = {}) {
  try {
    await db.insertOne('activity', {
      agent, kind, message: String(message).slice(0, 2000),
      ref_table: ref.table ?? null, ref_id: ref.id != null ? String(ref.id) : null,
    });
  } catch (e) {
    console.error(`[activity] ${e.message}`);
  }
}

// A per-agent run context passed to every agent.
export async function startRun(agent, { jobId, trigger, deadlineMs }) {
  const row = await db.insertOne('agent_runs', { agent, job_id: jobId ?? null, trigger });
  const ctx = {
    agent,
    runId: row.id,
    trigger,
    llmCalls: 0,
    tokens: 0,
    notes: [],
    deadlineMs,
    timeLeftMs: () => deadlineMs - Date.now(),
    outOfTime: (reserveMs = 60000) => Date.now() > deadlineMs - reserveMs,
    log: (kind, message, ref) => activity(agent, kind, message, ref),
    note: (s) => ctx.notes.push(s),
  };
  return ctx;
}

export async function finishRun(ctx, status, { summary, error } = {}) {
  const text = summary ?? ctx.notes.join(' · ');
  await db.update('agent_runs', { id: `eq.${ctx.runId}` }, {
    status, finished_at: new Date().toISOString(),
    summary: text?.slice(0, 2000) || null, error: error?.slice(0, 4000) || null,
    llm_calls: ctx.llmCalls, tokens: ctx.tokens,
  });
  await db.update('agents', { id: `eq.${ctx.agent}` }, {
    last_run_at: new Date().toISOString(), last_status: status, last_summary: text?.slice(0, 500) || error?.slice(0, 500) || null,
  });
}
