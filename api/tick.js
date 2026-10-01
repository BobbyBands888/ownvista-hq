// Continuous shift (Vercel Cron, every 5 minutes — vercel.json "crons"). Runs the agents that should never stop:
//   autopilot (every 15 min), then the most overdue of: researcher (5 min), product_scout (60 min),
//   dropship_scout (90 min), architect gap check (30 min). One heavy agent per tick keeps each call under the time limit.
// Safe to hit from outside: if CRON_SECRET is set Vercel signs the call; either way a database lock and the
// intervals below mean extra calls do nothing, and every LLM call still obeys the daily token caps.
// Intervals can be tuned without a deploy: kv tick_rules = { "researcher": 5, ... } (minutes; 0 = off).
import { db, kvGet, kvSet } from '../agents/lib/db.js';
import { runAgent } from '../agents/runner.js';
import { loadCrew } from '../agents/router.js';
import { resetUsageCache } from '../agents/lib/llm.js';
import { clearBriefCache } from '../agents/lib/briefs.js';

// Nashville Buys runs on Supabase's Free plan (since Oct 1, 2026), which pauses a project after 7 days without API
// activity. One read a day keeps it awake. The publishable key is public by design (it ships in the site's own code).
const KEEP_AWAKE = [{
  name: 'nashville-buys',
  url: 'https://xyxtwzsesvjowzyjaeyx.supabase.co/rest/v1/public_listings?select=id&limit=1',
  key: 'sb_publishable_RY7ufGi_jwQUqmfhs-4GRA_BnG1cjKe',
}];
async function keepAwake() {
  const last = await kvGet('keep_awake', {}).catch(() => ({}));
  const out = { ...last };
  for (const p of KEEP_AWAKE) {
    if (last[p.name]?.at && Date.now() - Date.parse(last[p.name].at) < 20 * 3600000) continue;
    try {
      const res = await fetch(p.url, { headers: { apikey: p.key }, signal: AbortSignal.timeout(15000) });
      out[p.name] = { at: new Date().toISOString(), status: res.status };
    } catch (e) {
      out[p.name] = { at: new Date().toISOString(), status: 0, error: String(e.message).slice(0, 120) };
    }
  }
  await kvSet('keep_awake', out).catch(() => {});
  return out;
}

export const INTERVALS = { autopilot: 15, researcher: 5, product_scout: 60, dropship_scout: 90, architect: 30 };
const LIGHT = ['autopilot'];
const BUDGET_MS = 270000;

const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });

// Pure: which agents run this tick, given minutes since each last ran.
export function pickAgents(sinceMin, intervals = INTERVALS) {
  const due = Object.entries(intervals)
    .filter(([, every]) => every > 0)
    .map(([id, every]) => ({ id, every, ratio: (sinceMin[id] ?? Infinity) / every }))
    .filter((a) => a.ratio >= 0.9);
  const light = due.filter((a) => LIGHT.includes(a.id)).map((a) => a.id);
  const heavy = due.filter((a) => !LIGHT.includes(a.id)).sort((a, b) => b.ratio - a.ratio)[0];
  return [...light, ...(heavy ? [heavy.id] : [])];
}

export async function GET(request) {
  const secret = process.env.CRON_SECRET;
  if (secret && request.headers.get('authorization') !== `Bearer ${secret}`) return json({ error: 'unauthorized' }, 401);
  if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_ROLE_KEY) return json({ skipped: 'Supabase env missing on Vercel' });
  if (!process.env.GROQ_API_KEY && (process.env.LLM_PROVIDER || 'groq') === 'groq') return json({ skipped: 'GROQ_API_KEY missing on Vercel' });

  const start = Date.now();
  const lock = await kvGet('tick_lock', null).catch(() => null);
  if (lock?.until && lock.until > start) return json({ skipped: 'another tick is running' });
  await kvSet('tick_lock', { until: start + BUDGET_MS + 20000, at: new Date(start).toISOString() });

  const results = {};
  resetUsageCache();
  clearBriefCache();
  const awake = await keepAwake().catch(() => null);
  try {
    const intervals = { ...INTERVALS, ...(await kvGet('tick_rules', {})) };
    const since = {};
    for (const id of Object.keys(intervals)) {
      const last = await db.one('agent_runs', { agent: `eq.${id}`, status: 'in.(ok,capped,error)', order: 'started_at.desc', select: 'started_at' }).catch(() => null);
      since[id] = last ? (start - Date.parse(last.started_at)) / 60000 : Infinity;
    }
    await loadCrew();
    for (const id of pickAgents(since, intervals)) {
      const left = start + BUDGET_MS - Date.now();
      if (left < 40000) { results[id] = 'deferred'; continue; }
      results[id] = await runAgent(id, { jobId: null, trigger: 'tick', jobDeadline: start + BUDGET_MS, budgetMin: Math.floor(left / 60000) || 1 });
    }
  } finally {
    await kvSet('tick_lock', { until: 0, at: new Date().toISOString(), last: results }).catch(() => {});
  }
  return json({ ok: true, ms: Date.now() - start, results, awake });
}
