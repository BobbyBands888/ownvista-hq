// Dropship Scout — every ~90 min on the Vercel tick. Hunts physical products worth dropshipping and scores
// margin, shipping time and saturation. Results go to the Radar page (kv product_radar).
// Selling them needs a store, a supplier account and payment details — none of which agents may create — so this
// agent finds and ranks; it never lists, buys or contacts suppliers. When the radar holds strong candidates it leaves
// Bobby one note every 14 days at most.
import { db, kvGet, kvSet } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt, untrusted } from '../lib/guard.js';
import { fetchFeed } from '../lib/feeds.js';
import { webSearch } from '../lib/search.js';
import { ipRisk } from '../lib/autopilot.js';
import { addToRadar, radar } from '../lib/radar.js';
import { truncate } from '../lib/text.js';
import { daysAgoIso } from '../lib/time.js';

export const FEEDS = ['https://trends.google.com/trending/rss?geo=US'];
export const QUERIES = [
  'trending products to sell online this month', 'viral kitchen gadget sold out', 'best selling home organization products',
  'trending pet products', 'trending car accessories', 'trending fitness gear at home', 'garden tool trending',
  'trending phone accessories', 'baby product trend parents buying', 'tiktok made me buy it product list',
];

export async function run(ctx) {
  const evidence = [];
  const notes = [];
  for (const url of [...FEEDS, ...((await kvGet('dropship_feeds', [])) || [])].slice(0, 5)) {
    try {
      const { items } = await fetchFeed({ url });
      for (const it of items.slice(0, 20)) evidence.push({ url: it.url, text: `[${new URL(url).hostname}] ${it.title}: ${truncate(it.snippet, 160)}` });
    } catch (e) { notes.push(`${new URL(url).hostname}: ${truncate(e.message, 60)}`); }
  }
  // Web search only when Bobby has turned search on (Tavily free plan, daily cap in kv).
  const i = Number(await kvGet('dropship_query_i', 0)) || 0;
  const r = await webSearch(QUERIES[i % QUERIES.length], { purpose: 'discovery', maxResults: 8 }).catch((e) => ({ results: [], error: e.message }));
  if (!r.disabled) await kvSet('dropship_query_i', i + 1);
  for (const x of r.results || []) evidence.push({ url: x.url, text: `[search] ${x.title}: ${truncate(x.snippet, 220)}` });
  if (r.disabled) notes.push('web search off');

  const [knowledge, signals] = await Promise.all([
    db.select('knowledge', { created_at: `gte.${daysAgoIso(7)}`, lane: 'in.(dropshipping,reselling,pod)', order: 'usefulness.desc', limit: 15, select: 'url,title,summary' }).catch(() => []),
    db.select('signals', { created_at: `gte.${daysAgoIso(10)}`, lane: 'in.(dropshipping,reselling,pod)', order: 'score.desc', limit: 10 }).catch(() => []),
  ]);
  for (const k of knowledge) evidence.push({ url: k.url, text: `[research] ${k.title}: ${truncate(k.summary, 200)}` });
  for (const s of signals.filter((x) => x.url)) evidence.push({ url: s.url, text: `[signal] ${s.title}: ${truncate(s.evidence || '', 200)}` });
  if (evidence.length < 5) return `not enough evidence yet (${evidence.length})${notes.length ? ` · ${notes.join(' · ')}` : ''}`;

  const allowed = new Set(evidence.map((e) => e.url));
  const have = (await radar()).slice(0, 40).map((x) => x.title);
  const system = systemPrompt('the Dropship Scout', `
From the evidence, pick up to 5 PHYSICAL products a one-person online store could dropship profitably.
Generic products only: no brands, licensed characters, knock-offs, supplements, medical/safety claims, weapons, batteries
shipped alone, cosmetics, kids' car seats or anything regulated.
For each estimate honestly (say so in "why" when it's a guess): sell_price and est_cost in USD (product + shipping),
margin_pct, shipping_days from a typical supplier, saturation 1 (few sellers) to 5 (everyone sells it),
score 0–100 (demand evidence 40, margin 30, low saturation 20, fast shipping 10).
supplier_search: the exact words Bobby would type into a supplier catalog to find it.
Every product needs at least one evidence URL copied exactly from the list. Already on the radar (don't repeat): ${have.join('; ') || '(none)'}.
JSON only: {"products":[{"title":"","channel":"shopify|tiktok shop|amazon|ebay|etsy","sell_price":0,"est_cost":0,"margin_pct":0,
"shipping_days":0,"saturation":3,"score":0,"why":"","supplier_search":"","evidence":["url"]}]}`);
  const user = evidence.slice(0, 60).map((e) => untrusted(e.url, e.text, 300)).join('\n');
  const { json } = await chat({ ctx, tier: 'fast', json: true, maxTokens: 1800, temperature: 0.3, system, messages: [{ role: 'user', content: user }] });

  const keep = (json.products || []).slice(0, 5)
    .map((p) => ({ ...p, evidence: (p.evidence || []).filter((u) => allowed.has(u)), lane: 'dropshipping', found_by: 'dropship_scout' }))
    .filter((p) => p.title && p.evidence.length && !ipRisk(p.title));
  const added = await addToRadar(keep);
  if (added) ctx.log('scout', `Dropship Scout added ${added} product(s) to the Radar`);
  const note = await maybeNote(ctx);
  return [`evidence ${evidence.length}`, `radar +${added}`, note, ...notes].filter(Boolean).join(' · ');
}

// One Needs-you note every 14 days at most, only when strong candidates exist and no store is set up.
async function maybeNote(ctx) {
  const strong = (await radar()).filter((x) => x.lane === 'dropshipping' && x.score >= 75);
  if (strong.length < 3 || (await kvGet('dropship_store', null))) return null;
  const last = await kvGet('dropship_note_at', null);
  if (last && Date.now() - Date.parse(last) < 14 * 86400000) return null;
  await kvSet('dropship_note_at', new Date().toISOString());
  await db.insertOne('approvals', {
    kind: 'note', created_by: 'dropship_scout', ref_table: null, ref_id: null,
    title: `Dropshipping: ${strong.length} strong products on the Radar`,
    detail: `Top: ${strong.slice(0, 3).map((x) => `${x.title} (score ${x.score}, ~${x.margin_pct ?? '?'}% margin)`).join('; ')}. Selling them needs a store and a supplier account (both cost money), so this waits until you decide to fund it. Nothing else to do now.`,
  });
  return 'left Bobby a note';
}
