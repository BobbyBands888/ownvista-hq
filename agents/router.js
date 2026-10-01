// Decides which agents are due this hour (America/New_York), with catch-up for
// delayed or dropped GitHub schedule runs.
import { db } from './lib/db.js';
import { et, etToUtc, addDays } from './lib/time.js';

const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);

// Order matters: runs top to bottom inside the single hourly job.
export const SCHEDULE = [
  { id: 'villa_outreach', type: 'hourly', hours: range(6, 23), budgetMin: 5 },
  { id: 'operator', type: 'hourly', hours: range(0, 23), budgetMin: 6, label: 'Hourly, 24/7' },
  { id: 'villa_studio', type: 'hourly', hours: range(0, 23), budgetMin: 12, onlyIfWork: true },
  { id: 'researcher', type: 'interval', everyHours: 3, budgetMin: 6 },
  { id: 'strategist', type: 'daily', hour: 7, budgetMin: 4 },
  { id: 'scout', type: 'weekly', days: [1, 4], hour: 8, budgetMin: 5 },
  { id: 'analyst', type: 'daily', hour: 9, budgetMin: 4 },
  { id: 'builder', type: 'hourly', hours: range(0, 23), budgetMin: 4, label: 'Hourly, 24/7 when work exists' },
  { id: 'launcher', type: 'hourly', hours: range(0, 23), budgetMin: 4, label: 'Hourly, 24/7' },
  { id: 'asset_studio', type: 'hourly', hours: range(0, 23), budgetMin: 8, label: 'Hourly, 24/7 (free daily image allowance)' },
  { id: 'judge', type: 'weekly', days: [0], hour: 18, budgetMin: 4 },
  { id: 'learner', type: 'hourly', hours: range(0, 23), budgetMin: 5, label: 'Hourly, 24/7 (grades the day at 11pm ET)' },
];

export const AGENT_IDS = SCHEDULE.map((s) => s.id);

const GRACE_MS = 12 * 3600 * 1000;

// Most recent scheduled slot at or before `now` for daily/weekly agents.
function lastSlot(s, now) {
  for (let back = 0; back <= 7; back++) {
    const day = addDays(et(now).date, -back);
    const slot = etToUtc(day, s.hour, 0);
    const weekday = et(slot).weekday;
    if (slot <= now && (s.type === 'daily' || s.days.includes(weekday))) return slot;
  }
  return null;
}

function nextSlot(s, now, lastOk) {
  const n = et(now);
  if (s.type === 'hourly') {
    for (let i = 1; i <= 48; i++) {
      const t = new Date(now.getTime() + i * 3600000);
      if (s.hours.includes(et(t).hour)) return etToUtc(et(t).date, et(t).hour, 7);
    }
  }
  if (s.type === 'interval') {
    return new Date(Math.max(now.getTime(), (lastOk?.getTime() ?? now.getTime()) + s.everyHours * 3600000));
  }
  for (let fwd = 0; fwd <= 8; fwd++) {
    const day = addDays(n.date, fwd);
    const slot = etToUtc(day, s.hour, 7);
    const weekday = et(slot).weekday;
    if (slot > now && (s.type === 'daily' || s.days.includes(weekday))) return slot;
  }
  return null;
}

async function recentRuns(agent) {
  return db.select('agent_runs', {
    agent: `eq.${agent}`, select: 'status,started_at', order: 'started_at.desc', limit: 20,
  });
}

// Pure decision: is agent `s` due at `now`, given its recent runs (newest first)?
export function isDue(s, now, runs) {
  const okRuns = runs.filter((r) => r.status === 'ok' || r.status === 'capped');
  const lastOk = okRuns[0] ? new Date(okRuns[0].started_at) : null;
  if (s.type === 'hourly') {
    // Two triggers in the same hour (GitHub's schedule + the Supabase backup) must not run an agent twice.
    if (lastOk) { const a = et(lastOk), b = et(now); if (a.date === b.date && a.hour === b.hour) return false; }
    return s.hours.includes(et(now).hour);
  }
  if (s.type === 'interval') return !lastOk || now - lastOk >= s.everyHours * 3600000 - 20 * 60000;
  const slot = lastSlot(s, now);
  if (!slot || now - slot >= GRACE_MS) return false;
  const since = runs.filter((r) => new Date(r.started_at) >= slot);
  const done = since.some((r) => r.status === 'ok' || r.status === 'capped');
  const errors = since.filter((r) => r.status === 'error').length;
  return !done && errors < 2;
}

export async function dueAgents(now = new Date()) {
  const due = [];
  const next = {};
  for (const s of SCHEDULE) {
    const runs = await recentRuns(s.id);
    if (isDue(s, now, runs)) due.push(s.id);
    const lastOk = runs.find((r) => r.status === 'ok' || r.status === 'capped');
    next[s.id] = nextSlot(s, now, lastOk ? new Date(lastOk.started_at) : null);
  }
  return { due, next };
}

export { lastSlot, nextSlot };

export function scheduleFor(id) {
  return SCHEDULE.find((s) => s.id === id);
}
