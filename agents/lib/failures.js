// Failure backlog (Bobby, Oct 1, 2026): every rejected idea, killed launch and failed asset pack is
// logged with an audited reason, shown to the idea agents as "failed before — don't repeat", and
// Autopilot refuses any new idea that repeats one. Pure helpers + one loader. No AI tokens.
import { db, kvGet, kvSet } from './db.js';
import { ruleBreak } from './smartscore.js';
import { truncate } from './text.js';
import { daysAgoIso } from './time.js';

export const KV_KEY = 'failure_log';
export const AUTO_PREFIX = 'auto: '; // ideas.feedback written by Autopilot (not Bobby) starts with this
const STOP = new Set('a an and the for of to in on with your you my our kit pack set guide bundle template templates toolkit printable digital download free pro ultimate complete simple easy best new mini starter edition by from at as is are this that how'.split(' '));

export const words = (t = '') => [...new Set(String(t).toLowerCase().normalize('NFKC').replace(/[^a-z0-9 ]+/g, ' ').split(/\s+/)
  .map((w) => w.replace(/s$/, '')).filter((w) => w.length > 2 && !STOP.has(w)))];

// Jaccard overlap of meaningful title words. Two ideas "repeat" at ≥0.5 with 2+ shared words.
export function overlap(a, b) {
  const A = new Set(words(a)), B = new Set(words(b));
  const shared = [...A].filter((w) => B.has(w));
  const union = new Set([...A, ...B]).size;
  return { score: union ? shared.length / union : 0, shared };
}

export function repeatOf(idea, failures = []) {
  let best = null;
  for (const f of failures) {
    const o = overlap(idea.title, f.title);
    if (o.shared.length >= 2 && o.score >= 0.5 && (!best || o.score > best.score)) best = { ...f, score: Math.round(o.score * 100) / 100 };
  }
  return best;
}

// Audit: turn a raw failure into a reason category the agents can learn from.
export function audit(f) {
  const note = (f.note || '').trim();
  const rule = f.kind === 'idea' ? ruleBreak(f) : null;
  let category, why;
  if (rule) { category = 'broke a hard rule'; why = rule; }
  else if (f.kind === 'launch') { category = 'did not sell'; why = note || 'kill rule: under the sales goal by day 14'; }
  else if (f.kind === 'pack') { category = 'failed quality'; why = note || 'too few images passed QA'; }
  else if (note && !note.startsWith(AUTO_PREFIX)) { category = 'rejected by Bobby'; why = note; }
  else if (note.startsWith(AUTO_PREFIX)) { category = 'repeat of a failure'; why = note.slice(AUTO_PREFIX.length); }
  else { category = 'rejected, no reason given'; why = 'Bobby rejected it without a note'; }
  return { ...f, category, why: truncate(why, 200) };
}

// Short prompt block every idea agent reads (via playbook().text()).
export function failureText(items = []) {
  if (!items.length) return '';
  const lines = items.slice(0, 25).map((f) => `- "${truncate(f.title, 70)}" (${f.category}: ${truncate(f.why, 90)})`);
  return `These failed or were rejected. Do NOT propose them again or anything close to them; learn the reason.\n${lines.join('\n')}`;
}

export async function loadFailures(days = 180) {
  const since = daysAgoIso(days);
  const safe = (p) => p.catch(() => []);
  const [ideas, launches, packs, notes] = await Promise.all([
    safe(db.select('ideas', { status: 'eq.rejected', decided_at: `gte.${since}`, select: 'id,title,summary,steps,business,feedback,decided_at,created_by', order: 'decided_at.desc', limit: 500 })),
    safe(db.select('launches', { status: 'eq.killed', killed_at: `gte.${since}`, select: 'id,idea_id,title,note,killed_at', order: 'killed_at.desc', limit: 200 })),
    safe(db.select('asset_packs', { status: 'in.(rejected,killed)', created_at: `gte.${since}`, select: 'id,title,feedback,created_at', order: 'created_at.desc', limit: 200 })),
    safe(db.select('feedback', { kind: 'eq.idea_rejected', created_at: `gte.${since}`, select: 'ref_id,text', limit: 1000 })),
  ]);
  const noteFor = Object.fromEntries(notes.map((n) => [n.ref_id, n.text]));
  const items = [
    ...ideas.filter((i) => i.created_by !== 'bobby').map((i) => ({ kind: 'idea', id: i.id, title: i.title, summary: i.summary, steps: i.steps, business: i.business, at: i.decided_at, note: noteFor[i.id] || i.feedback || '' })),
    ...launches.map((l) => ({ kind: 'launch', id: l.id, title: l.title, at: l.killed_at, note: l.note || '' })),
    ...packs.map((p) => ({ kind: 'pack', id: p.id, title: p.title, at: p.created_at, note: p.feedback || '' })),
  ].map(audit).sort((a, b) => String(b.at).localeCompare(String(a.at)));
  return items.map(({ summary, steps, ...rest }) => rest);
}

// Rebuild the backlog in kv at most once an hour (Autopilot calls this every run).
export async function refreshFailures({ force = false } = {}) {
  const prev = await kvGet(KV_KEY, null).catch(() => null);
  if (!force && prev?.at && Date.now() - new Date(prev.at).getTime() < 3600000) return prev;
  const items = await loadFailures();
  const counts = {};
  for (const f of items) counts[f.category] = (counts[f.category] || 0) + 1;
  const log = { at: new Date().toISOString(), counts, items: items.slice(0, 300), text: failureText(items) };
  await kvSet(KV_KEY, log);
  return log;
}
