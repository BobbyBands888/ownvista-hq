// Smart Score — daily 11:30pm ET. Answers "are the agents getting smarter?" from logged results.
// No AI tokens. Reads only; its one write is kv smart_score (+ the first-run starting point).
import { db, kvGet, kvSet } from './lib/db.js';
import { buildScore, WEEKS } from './lib/smartscore.js';
import { refreshFailures } from './lib/failures.js';
import { daysAgoIso, etDate } from './lib/time.js';

// PostgREST returns at most 1000 rows per call: page through.
async function all(table, query) {
  const out = [];
  for (let offset = 0; offset < 20000; offset += 1000) {
    const rows = await db.select(table, { ...query, limit: 1000, offset: offset || undefined });
    out.push(...rows);
    if (rows.length < 1000) break;
  }
  return out;
}

const safe = (p) => p.catch(() => []);

export async function run(ctx) {
  const since = daysAgoIso(WEEKS * 7 + 7);
  const [ideas, drafts, productLogs, packs, launches, ledger, rules, feedback] = await Promise.all([
    safe(all('ideas', { created_at: `gte.${since}`, select: 'id,kind,business,title,summary,steps,status,feedback,created_by,created_at,decided_at', order: 'created_at.asc' })),
    safe(all('drafts', { sent_at: `gte.${since}`, select: 'sent_at,edit_distance', order: 'sent_at.asc' })),
    safe(all('activity', { kind: 'eq.launch', at: `gte.${since}`, or: '(message.ilike.*missed the bar*,message.ilike.*passed the quality bar*)', select: 'at,message,ref_id', order: 'at.asc' })),
    safe(all('asset_packs', { created_at: `gte.${since}`, select: 'created_at,published_at,images_made,items', order: 'created_at.asc' })),
    safe(all('launches', { launched_at: `gte.${since}`, select: 'launched_at', order: 'launched_at.asc' })),
    safe(all('ledger', { day: `gte.${since.slice(0, 10)}`, select: 'day,revenue,source', order: 'day.asc' })),
    safe(all('playbook_rules', { created_at: `gte.${since}`, select: 'created_at,origin', order: 'created_at.asc' })),
    safe(all('feedback', { created_at: `gte.${since}`, select: 'created_at', order: 'created_at.asc' })),
  ]);
  const score = buildScore({ ideas, drafts, productLogs, packs, launches, ledger, rules, feedback });
  // Freeze the starting point the first time this runs, so later weeks are judged against it.
  let start = await kvGet('smart_score_start', null);
  if (!start) {
    start = { day: etDate(), week: score.this_week, metrics: Object.fromEntries(score.metrics.map((m) => [m.id, m.weeks.slice(0, -1).filter((w) => w.v != null).slice(-1)[0] || null])) };
    await kvSet('smart_score_start', start);
  }
  const fail = await refreshFailures({ force: true }).catch(() => null);
  await kvSet('smart_score', { ...score, start, failure_counts: fail?.counts || {} });
  return score.verdict;
}
