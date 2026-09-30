// Hunter — runs inside the Researcher. Turns demand-flavored items into scored signals
// across the six lanes. Evidence must be the item itself (its URL), never invented.
import { db } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt, untrusted } from '../lib/guard.js';
import { LANES } from '../lib/context.js';
import { truncate } from '../lib/text.js';

const TRADEMARK_RISK = /\b(nfl|nba|mlb|nhl|ncaa|disney|marvel|pixar|star wars|pokemon|nintendo|harry potter|barbie|taylor swift|nike|adidas|gucci|louis vuitton|coca-?cola|hello kitty|super bowl|olympics?)\b/i;

export async function hunt(ctx, candidates) {
  if (!candidates.length) return 0;
  const system = systemPrompt('the Hunter in the Venture Lab', `
Lanes: ${LANES.join(', ')}.
- reselling: clearance/arbitrage vs sold comps (Bobby shops Home Depot/Lowe's clearance in Greater Boston).
- pod: print-on-demand niches, seasonal events, search terms. No brands, teams, characters or lyrics.
- dropshipping: products with rising demand and room for margin.
- local-services: complaints and gaps in reviews and forums.
- b2b: people saying "I'd pay for" or "is there a tool that".
- digital: templates, guides, small software.
For each item that shows real demand, output one signal. Use ONLY numbers present in the item; put unknowns as null.
Score 0–100 = strength of evidence that people pay for this today.
JSON only: {"signals":[{"i":0,"lane":"b2b","title":"short name of the opportunity","evidence":"quote or fact from the item","metrics":{"price":null,"volume_hint":null},"score":0}]}`);
  const user = candidates.slice(0, 12).map((c, i) =>
    `[${i}] ${untrusted(c.source.name, `Title: ${c.title}\nURL: ${c.url}\n${c.snippet}\nSummary: ${c.judged.summary}`, 1200)}`).join('\n\n');
  const { json } = await chat({ ctx, tier: 'fast', system, json: true, maxTokens: 1500, temperature: 0.2, messages: [{ role: 'user', content: user }] });
  let n = 0;
  for (const s of json.signals || []) {
    const c = candidates[s.i];
    if (!c || !LANES.includes(s.lane)) continue;
    const trademark = TRADEMARK_RISK.test(`${s.title} ${s.evidence}`);
    await db.insertOne('signals', {
      lane: s.lane,
      title: truncate(String(s.title || c.title), 200),
      url: c.url,
      evidence: truncate(String(s.evidence || ''), 800),
      metrics: { ...(s.metrics || {}), ...(trademark ? { trademark_risk: true } : {}) },
      score: trademark ? Math.min(20, Number(s.score) || 0) : Math.max(0, Math.min(100, Number(s.score) || 0)),
      source: 'hunter',
    });
    n++;
  }
  return n;
}
