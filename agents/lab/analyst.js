// Analyst — daily 9am ET. Turns the best recent signals into one-page business cases with
// real numbers and sources, scored with the Scout formula, each with a $0–25 experiment.
import { db } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt, untrusted } from '../lib/guard.js';
import { playbook } from '../lib/context.js';
import { truncate, similarTitle } from '../lib/text.js';
import { daysAgoIso } from '../lib/time.js';
import { scoreOf } from '../scout.js';

const TRADEMARK = /\b(nfl|nba|mlb|nhl|ncaa|disney|marvel|pixar|star wars|pokemon|nintendo|harry potter|barbie|taylor swift|nike|adidas|gucci|louis vuitton|coca-?cola|hello kitty|super bowl|olympics?)\b/i;

export async function run(ctx) {
  const pb = await playbook();
  const signals = await db.select('signals', {
    processed_at: 'is.null', created_at: `gte.${daysAgoIso(5)}`, score: 'gte.50', order: 'score.desc', limit: 2,
  });
  if (!signals.length) return 'no strong new signals';
  const recent = await db.select('ideas', { kind: 'eq.venture', created_at: `gte.${daysAgoIso(30)}`, select: 'title', limit: 200 });
  let made = 0;
  for (const s of signals) {
    if (ctx.outOfTime(90000)) break;
    await db.update('signals', { id: `eq.${s.id}` }, { processed_at: new Date().toISOString() });
    if (s.metrics?.trademark_risk || TRADEMARK.test(`${s.title} ${s.evidence}`)) continue;
    const related = await db.rpc('search_knowledge', { q: s.title.split(/\s+/).filter((w) => w.length > 3).slice(0, 6).join(' or '), lim: 5 }).catch(() => []);
    const allowed = new Set([s.url, ...related.map((k) => k.url)].filter(Boolean));

    const system = systemPrompt('the Analyst in the Venture Lab', `
${pb.text(['lab', 'guardrails', 'results'])}

Write a one-page business case for this signal. Use ONLY numbers that appear in the evidence, or clearly labeled assumptions (prefix "assumption:").
Unit economics: price, unit cost, fees, shipping, margin per sale, and how many sales it takes to make $1,000 profit.
Experiment: costs $0–25, runs 7–14 days, with a pass metric and a kill metric set now. List any accounts it would need (Etsy, eBay, Printify, Shopify, a supplier) — Bobby creates those himself.
Estimate Bobby's hours for the experiment and expected profit per hour of his time.
Check print-on-demand ideas for trademark conflicts (brands, teams, characters, lyrics) and say what you checked.
Score with the Scout formula: time_to_revenue 0–30, fit 0–25, cost 0–20, hours 0–15, evidence 0–10.
Sources: only URLs from the evidence.
JSON only: {"title":"","case":"markdown one-pager","economics":{"price":null,"unit_cost":null,"fees":null,"shipping":null,"margin_per_sale":null,"sales_to_1000_profit":null,"assumptions":[]},
"experiment":{"hypothesis":"","cost_usd":0,"days":14,"pass_metric":"","kill_metric":"","needs_accounts":[],"bobby_hours":0},
"expected_profit_per_hour":0,"trademark_check":"","scores":{"time_to_revenue":0,"fit":0,"cost":0,"hours":0,"evidence":0},"source_urls":[]}`);

    const user = [
      untrusted(s.url || 'signal', `Lane: ${s.lane}\nSignal: ${s.title}\nEvidence: ${s.evidence}\nMetrics: ${JSON.stringify(s.metrics || {})}`, 1500),
      related.length ? `Related knowledge:\n${related.map((k) => untrusted(k.url, `${k.title}: ${k.summary}`, 500)).join('\n')}` : '',
    ].join('\n\n');

    const { json } = await chat({ ctx, tier: 'smart', system, json: true, maxTokens: 2600, messages: [{ role: 'user', content: user }] });
    if (!json.title || recent.some((r) => similarTitle(r.title, json.title))) continue;
    if (TRADEMARK.test(`${json.title} ${json.case}`)) continue;
    const urls = (json.source_urls || []).filter((u) => allowed.has(u));
    if (!urls.length && s.url) urls.push(s.url);
    const exp = json.experiment || {};
    const cost = Math.max(0, Math.min(25, Number(exp.cost_usd) || 0));
    const { total, breakdown } = scoreOf(json.scores);
    await db.insertOne('ideas', {
      kind: 'venture', business: s.lane, title: truncate(json.title, 200),
      summary: `${json.case || ''}${json.trademark_check ? `\n\n**Trademark check:** ${json.trademark_check}` : ''}`,
      economics: json.economics || {},
      experiment: { ...exp, cost_usd: cost, days: Math.max(7, Math.min(14, Number(exp.days) || 14)), needs_accounts: exp.needs_accounts || [] },
      profit_per_hour: Number(json.expected_profit_per_hour) || 0,
      score: total, score_breakdown: breakdown, source_urls: urls, created_by: 'analyst',
    });
    made++;
  }
  if (made) ctx.log('analyst', `Wrote ${made} business case(s)`);
  return `business cases ${made}`;
}
