// Scout — Mon + Thu 8am ET. Up to 3 new business opportunities scored 0–100
// (time to revenue 30, fit 25, cost 20, Bobby's hours 15, evidence 10). Each must cite real
// source links from collected knowledge/signals; #1 gets a full launch kit.
import { db } from './lib/db.js';
import { chat } from './lib/llm.js';
import { systemPrompt, untrusted, realEstateRisk } from './lib/guard.js';
import { playbook } from './lib/context.js';
import { similarTitle, truncate } from './lib/text.js';
import { daysAgoIso } from './lib/time.js';

const MAX = { time_to_revenue: 30, fit: 25, cost: 20, hours: 15, evidence: 10 };

export function scoreOf(b = {}) {
  let total = 0;
  const clean = {};
  for (const [k, max] of Object.entries(MAX)) {
    clean[k] = Math.max(0, Math.min(max, Math.round(Number(b[k]) || 0)));
    total += clean[k];
  }
  return { total, breakdown: clean };
}

export async function run(ctx) {
  const pb = await playbook();
  const [knowledge, signals, rejected, recent] = await Promise.all([
    db.select('knowledge', { created_at: `gte.${daysAgoIso(14)}`, order: 'usefulness.desc', limit: 40 }),
    db.select('signals', { created_at: `gte.${daysAgoIso(14)}`, order: 'score.desc', limit: 25 }),
    db.select('ideas', { kind: 'in.(business,venture)', status: 'eq.rejected', order: 'decided_at.desc', limit: 15 }),
    db.select('ideas', { kind: 'eq.business', created_at: `gte.${daysAgoIso(45)}`, select: 'title', limit: 100 }),
  ]);
  const evidence = [
    ...knowledge.map((k) => ({ url: k.url, text: `${k.title}: ${k.summary}` })),
    ...signals.filter((s) => s.url).map((s) => ({ url: s.url, text: `[${s.lane} signal ${s.score}] ${s.title}: ${s.evidence}` })),
  ];
  if (evidence.length < 3) return 'not enough evidence collected yet — skipped';
  const allowedUrls = new Set(evidence.map((e) => e.url));

  const system = systemPrompt('the Scout', `
${pb.text(['scout', 'lab', 'businesses', 'guardrails'])}

Find up to 3 NEW business opportunities for Bobby (not the existing businesses).
Hard requirements: nothing to do with real estate, housing, mortgages or Bobby's real estate license; start for $0–200, no new licenses, no phone calls, workable by one person by email and the web.
Every opportunity must cite at least one source URL copied exactly from the evidence list. No other links.
Score each: time_to_revenue (0–30), fit (0–25), cost (0–20, cheaper = higher), hours (0–15, fewer of Bobby's hours = higher), evidence (0–10).
Do not repeat rejected ideas.
JSON only: {"opportunities":[{"title":"","summary":"","why_bobby":"","startup_cost_usd":0,"needs_license":false,"needs_calls":false,
"scores":{"time_to_revenue":0,"fit":0,"cost":0,"hours":0,"evidence":0},"steps":["..."],"source_urls":["..."]}]}`);

  const user = [
    `Evidence:\n${evidence.map((e) => untrusted(e.url, e.text, 400)).join('\n')}`,
    `Rejected before:\n${rejected.map((r) => `- ${r.title}${r.feedback ? ` — "${truncate(r.feedback, 150)}"` : ''}`).join('\n') || '(none)'}`,
  ].join('\n\n');

  const { json } = await chat({ ctx, tier: 'smart', system, json: true, maxTokens: 2600, messages: [{ role: 'user', content: user }] });

  const kept = [];
  for (const o of (json.opportunities || []).slice(0, 3)) {
    const urls = (o.source_urls || []).filter((u) => allowedUrls.has(u));
    const cost = Number(o.startup_cost_usd);
    if (!o.title || !urls.length || o.needs_license || o.needs_calls || !(cost >= 0 && cost <= 200)) continue;
    if (recent.some((r) => similarTitle(r.title, o.title))) continue;
    if (realEstateRisk(`${o.title}\n${o.summary}\n${(o.steps || []).join('\n')}`)) continue; // Bobby's rule: no real estate
    const { total, breakdown } = scoreOf(o.scores);
    kept.push({ ...o, urls, total, breakdown, cost });
  }
  kept.sort((a, b) => b.total - a.total);

  let first = null;
  for (const o of kept) {
    const row = await db.insertOne('ideas', {
      kind: 'business', business: 'venture-lab', title: truncate(o.title, 200),
      summary: `${o.summary}\n\nWhy Bobby: ${o.why_bobby || ''}\nStartup cost: $${o.cost}`.trim(),
      steps: (o.steps || []).slice(0, 8), score: o.total, score_breakdown: o.breakdown,
      source_urls: o.urls, created_by: 'scout',
    });
    first ||= { row, o };
  }

  if (first && !ctx.outOfTime(90000)) {
    const kit = await chat({
      ctx, tier: 'smart', maxTokens: 2600,
      system: systemPrompt('the Scout writing a launch kit', `${pb.text(['lab', 'guardrails'])}
Write a complete launch kit in markdown: positioning (1 paragraph), the offer, target customer, pricing hypothesis with math, a 14-day plan by day,
the first $0–25 experiment with a pass metric and a kill metric set in advance, copy for a one-page landing page, and 3 outreach email drafts.
Everything must be doable by email and the web; no calls, no accounts created by agents (list any accounts Bobby would need, with cost).`),
      messages: [{ role: 'user', content: `Opportunity: ${first.o.title}\n${first.o.summary}\nSteps: ${(first.o.steps || []).join('; ')}\nSources: ${first.o.urls.join(', ')}` }],
    });
    await db.update('ideas', { id: `eq.${first.row.id}` }, { launch_kit: kit.text });
  }
  ctx.log('scout', `Scouted ${kept.length} opportunit${kept.length === 1 ? 'y' : 'ies'}${first ? `; top: "${first.o.title}" (${first.o.total}/100)` : ''}`);
  return `opportunities ${kept.length}${first ? `, top ${first.o.total}/100 with launch kit` : ''}`;
}
