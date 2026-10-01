// "Are the agents getting smarter?" scoreboard (Bobby, Oct 1, 2026).
// Pure math over rows the system already logs. No AI tokens, no writes except the kv result.
// Each metric is bucketed by ET week (Mon–Sun). A metric only gets a verdict once both the latest
// full week and the weeks before it have enough data (MIN_N), so a quiet week can't fake a trend.
import { checkCopy, realEstateRisk } from './guard.js';
import { ipRisk } from './autopilot.js';
import { et, addDays } from './time.js';
import { repeatOf } from './failures.js';

export const WEEKS = 8;
export const MIN_N = 5;

export const weekOf = (ts) => {
  const d = et(new Date(ts));
  return addDays(d.date, -((d.weekday + 6) % 7));
};

// Why an agent's idea breaks Bobby's hard rules (null = clean). Same code checks Autopilot uses.
export function ruleBreak(idea) {
  const text = [idea.title, idea.summary, ...(Array.isArray(idea.steps) ? idea.steps : [])].filter(Boolean).join('\n');
  const re = realEstateRisk(text);
  if (re) return `real estate ("${re}")`;
  const ip = ipRisk(text);
  if (ip) return `brand/IP ("${ip}")`;
  const copy = checkCopy(text, { business: idea.business });
  return copy.length ? copy[0] : null;
}

const isAuto = (i) => String(i.feedback || '').startsWith('auto: ');
const pct = (a, b) => (b ? Math.round((a / b) * 1000) / 10 : null);
const avg = (xs) => (xs.length ? Math.round((xs.reduce((s, x) => s + x, 0) / xs.length) * 1000) / 1000 : null);

// The metrics. better: 'down' or 'up' is the direction that means smarter. n = sample size behind the value.
export const METRICS = [
  { id: 'idea_reject', label: 'Ideas you reject', unit: '%', better: 'down', what: 'Of agent ideas decided that week, the share that ended up rejected.' },
  { id: 'idea_repeat', label: 'Ideas repeating a past failure', unit: '%', better: 'down', what: 'Agent ideas that match an idea already rejected before it was proposed. Learning from failures should push this to 0.' },
  { id: 'idea_rulebreak', label: 'Ideas that break your rules', unit: '%', better: 'down', what: 'Agent ideas that trip the real-estate, brand/IP or copy checks. Learning your rules should push this to 0.' },
  { id: 'email_edited', label: 'Emails you had to edit', unit: '%', better: 'down', what: 'Drafts you sent with a real edit (5%+ changed).' },
  { id: 'email_edit_size', label: 'Average edit size', unit: '', better: 'down', what: 'How much of each sent draft you changed (0 = nothing, 1 = everything).' },
  { id: 'product_first_pass', label: 'Products passing quality on try 1', unit: '%', better: 'up', what: 'Launcher products that passed the quality bar with no rewrite.' },
  { id: 'image_pass', label: 'Images passing QA', unit: '%', better: 'up', what: 'Asset Studio images that passed QA, out of all images made.' },
  { id: 'launches', label: 'New launches', unit: '', better: 'info', what: 'Offers and itch packs that went live that week.' },
  { id: 'revenue', label: 'Agent revenue', unit: '$', better: 'up', what: 'Real money from Stripe/itch (ledger, not manual entries).' },
  { id: 'lessons', label: 'Lessons learned', unit: '', better: 'info', what: 'New Playbook rules + feedback items the Learner had to work with.' },
];

// rows: { ideas, drafts, productLogs, packs, launches, ledger, rules, feedback }. now: Date.
export function buildScore(rows, now = new Date()) {
  const thisWeek = weekOf(now);
  const weeks = Array.from({ length: WEEKS }, (_, i) => addDays(thisWeek, -7 * (WEEKS - 1 - i)));
  const cell = () => Object.fromEntries(weeks.map((w) => [w, []]));
  const put = (b, ts, v) => { const w = ts && weekOf(ts); if (w && b[w]) b[w].push(v); };

  const ideasDecided = cell(), ideasNew = cell(), ideasRepeat = cell(), breaks = [];
  const agentIdeas = (rows.ideas || []).filter((i) => i.created_by !== 'bobby');
  const rejectedBefore = agentIdeas.filter((i) => i.status === 'rejected' && i.decided_at && !isAuto(i));
  for (const i of agentIdeas) {
    const why = ruleBreak(i);
    put(ideasNew, i.created_at, why ? 1 : 0);
    if (why && weekOf(i.created_at) >= weeks[0]) breaks.push({ week: weekOf(i.created_at), title: i.title, why });
    const earlier = rejectedBefore.filter((r) => r.id !== i.id && new Date(r.decided_at) < new Date(i.created_at));
    put(ideasRepeat, i.created_at, isAuto(i) || repeatOf(i, earlier) ? 1 : 0);
    // Autopilot's own repeat rejections are not Bobby's decisions, so they stay out of "ideas you reject".
    if (i.status !== 'proposed' && !isAuto(i)) put(ideasDecided, i.decided_at || i.created_at, i.status === 'rejected' ? 1 : 0);
  }

  const edited = cell(), editSize = cell();
  for (const d of rows.drafts || []) {
    if (!d.sent_at || d.edit_distance == null) continue;
    put(edited, d.sent_at, d.edit_distance >= 0.05 ? 1 : 0);
    put(editSize, d.sent_at, Number(d.edit_distance));
  }

  // Product quality bar: a finish with no earlier "missed the bar" for the same idea = first-try pass.
  const firstPass = cell();
  const missed = new Set();
  for (const l of [...(rows.productLogs || [])].sort((a, b) => new Date(a.at) - new Date(b.at))) {
    if (/missed the bar/i.test(l.message)) missed.add(l.ref_id);
    else if (/passed the quality bar/i.test(l.message)) put(firstPass, l.at, missed.has(l.ref_id) ? 0 : 1);
  }

  const images = Object.fromEntries(weeks.map((w) => [w, { made: 0, done: 0 }]));
  for (const p of rows.packs || []) {
    const w = weekOf(p.created_at);
    if (!images[w]) continue;
    images[w].made += Number(p.images_made || 0);
    images[w].done += (p.items || []).filter((x) => x.done).length;
  }

  const launches = cell();
  for (const l of rows.launches || []) put(launches, l.launched_at, 1);
  for (const p of rows.packs || []) put(launches, p.published_at, 1);

  const revenue = cell();
  for (const r of rows.ledger || []) if (r.source !== 'manual' && Number(r.revenue) > 0) put(revenue, `${r.day}T12:00:00Z`, Number(r.revenue));

  const lessons = cell();
  for (const r of rows.rules || []) if (r.origin !== 'manual') put(lessons, r.created_at, 1);
  for (const f of rows.feedback || []) put(lessons, f.created_at, 1);

  const sum = (xs) => xs.reduce((s, x) => s + x, 0);
  const table = {
    idea_reject: (w) => ({ v: pct(sum(ideasDecided[w]), ideasDecided[w].length), n: ideasDecided[w].length }),
    idea_repeat: (w) => ({ v: pct(sum(ideasRepeat[w]), ideasRepeat[w].length), n: ideasRepeat[w].length }),
    idea_rulebreak: (w) => ({ v: pct(sum(ideasNew[w]), ideasNew[w].length), n: ideasNew[w].length }),
    email_edited: (w) => ({ v: pct(sum(edited[w]), edited[w].length), n: edited[w].length }),
    email_edit_size: (w) => ({ v: avg(editSize[w]), n: editSize[w].length }),
    product_first_pass: (w) => ({ v: pct(sum(firstPass[w]), firstPass[w].length), n: firstPass[w].length }),
    image_pass: (w) => ({ v: pct(images[w].done, images[w].made), n: images[w].made }),
    launches: (w) => ({ v: launches[w].length, n: launches[w].length }),
    revenue: (w) => ({ v: Math.round(sum(revenue[w]) * 100) / 100, n: revenue[w].length }),
    lessons: (w) => ({ v: lessons[w].length, n: lessons[w].length }),
  };

  const lastFull = weeks[weeks.length - 2];
  const metrics = METRICS.map((m) => {
    const byWeek = weeks.map((w) => ({ week: w, ...table[m.id](w) }));
    return { ...m, weeks: byWeek, trend: trendOf(m, byWeek.slice(0, -1)) };
  });
  const judged = metrics.filter((m) => ['better', 'worse', 'flat'].includes(m.trend.verdict));
  const better = judged.filter((m) => m.trend.verdict === 'better').length;
  const worse = judged.filter((m) => m.trend.verdict === 'worse').length;
  const verdict = !judged.length
    ? 'Not enough data yet to say. Each metric needs 5+ data points in a week and in the weeks before it.'
    : better > worse
      ? `Smarter: ${better} of ${judged.length} measurable metrics improved, ${worse} got worse.`
      : worse > better
        ? `Not smarter: ${worse} of ${judged.length} measurable metrics got worse, ${better} improved.`
        : `No clear change: ${better} better, ${worse} worse, ${judged.length - better - worse} flat.`;

  return { at: now.toISOString(), this_week: thisWeek, last_full_week: lastFull, weeks, metrics, verdict, rule_breaks: breaks.slice(-15) };
}

// Latest full week vs the average of the weeks before it (both need MIN_N data points).
export function trendOf(m, full) {
  if (m.better === 'info') return { verdict: 'info' };
  const last = full[full.length - 1];
  const prior = full.slice(0, -1).filter((w) => w.v != null && w.n >= (m.id === 'revenue' ? 1 : MIN_N));
  if (m.id === 'revenue') {
    const before = prior.length ? prior.reduce((s, w) => s + w.v, 0) / prior.length : 0;
    if (!last.v && !before) return { verdict: 'none', note: 'No agent revenue yet' };
    return compare(m, last.v, before);
  }
  if (last.v == null || last.n < MIN_N) return { verdict: 'none', note: `Last week had ${last.n} data point${last.n === 1 ? '' : 's'} (need ${MIN_N})` };
  if (!prior.length) return { verdict: 'none', note: 'No earlier week with enough data to compare' };
  return compare(m, last.v, prior.reduce((s, w) => s + w.v, 0) / prior.length);
}

function compare(m, now, before) {
  const delta = Math.round((now - before) * 1000) / 1000;
  const scale = m.unit === '%' ? 5 : m.id === 'email_edit_size' ? 0.03 : 0.01; // ignore noise-sized moves
  if (Math.abs(delta) < scale) return { verdict: 'flat', now, before: Math.round(before * 1000) / 1000, delta };
  const up = delta > 0;
  return { verdict: (m.better === 'up') === up ? 'better' : 'worse', now, before: Math.round(before * 1000) / 1000, delta };
}
