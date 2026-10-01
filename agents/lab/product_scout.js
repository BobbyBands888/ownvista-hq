// Product Scout — hourly on the Vercel tick. Finds products people are already buying on marketplaces and turns them
// into ORIGINAL products we can sell:
//   evidence → Etsy Open API (if ETSY_API_KEY), itch.io + Product Hunt feeds (robots.txt respected), recent research
//   text products (guides, templates, checklists, scripts) → a venture idea that Autopilot approves → Builder →
//                     Launcher builds it to the quality bar and publishes it at levelingclips.com/p/<slug>
//   print-on-demand designs (shirts, mugs, stickers, posters) → the Radar page, lane "pod" (scout only: nothing is
//                     designed, listed or sold until Bobby funds a store and picks a design)
//   everything else (physical, printables, graphics) → the Radar page
// Never copies a listing: titles/prices are evidence of demand only; products must be our own work, no brands.
import { db, kvGet, kvSet } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt, untrusted, realEstateRisk } from '../lib/guard.js';
import { fetchFeed } from '../lib/feeds.js';
import { etsyListings, etsyReady } from '../lib/etsy.js';
import { ipRisk } from '../lib/autopilot.js';
import { addToRadar } from '../lib/radar.js';
import { similarTitle, truncate } from '../lib/text.js';

// A written product (guide/template/checklist) only counts as proven when the evidence itself is a paid written product.
export const WRITTEN = /\b(templates?|guides?|checklists?|planners?|worksheets?|e-?books?|playbooks?|swipe files?|workbooks?|spreadsheets?|printables?|notion|course|scripts? pack)\b/i;
import { daysAgoIso } from '../lib/time.js';
import { KV_KEY as RESULTS_KEY } from '../lib/review.js';

export const FEEDS = [
  'https://itch.io/game-assets/top-sellers.xml',
  'https://itch.io/tools/top-sellers.xml',
  'https://www.producthunt.com/feed',
];
export const ETSY_KEYWORDS = [
  'small business template', 'notion template', 'budget planner', 'resume template', 'social media planner',
  'contractor forms', 'etsy seller guide', 'wedding planner checklist',
  'cleaning business forms', 'meal plan', 'lesson plan template', 'study guide',
];
// Print-on-demand demand checks (one per run). Evidence of what sells, never designs to copy.
export const POD_KEYWORDS = [
  'funny t-shirt', 'graphic tee', 'coffee mug gift', 'vinyl sticker', 'wall art print', 'tote bag design',
  'hoodie design', 'teacher gift shirt', 'nurse gift mug', 'dog lover shirt', 'hiking sticker', 'gamer poster',
];

export async function run(ctx) {
  const evidence = [];
  const notes = [];

  // 1. Etsy (official API only).
  if (etsyReady()) {
    const i = Number(await kvGet('etsy_keyword_i', 0)) || 0;
    const words = [ETSY_KEYWORDS[i % ETSY_KEYWORDS.length], ETSY_KEYWORDS[(i + 1) % ETSY_KEYWORDS.length], POD_KEYWORDS[Math.floor(i / 2) % POD_KEYWORDS.length]];
    await kvSet('etsy_keyword_i', i + 2);
    for (const w of words) {
      const tag = POD_KEYWORDS.includes(w) ? 'Etsy POD' : 'Etsy';
      try {
        const rows = (await etsyListings(w)).sort((a, b) => (b.favorers || 0) - (a.favorers || 0)).slice(0, 10);
        for (const r of rows) evidence.push({ url: r.url, text: `[${tag} "${w}"] ${r.title} — $${r.price ?? '?'}, ${r.favorers ?? '?'} favorites, ${r.views ?? '?'} views${r.digital ? ', digital download' : ''}` });
      } catch (e) { notes.push(`etsy: ${truncate(e.message, 80)}`); }
    }
  } else notes.push('Etsy off (no ETSY_API_KEY)');

  // 2. Marketplace feeds.
  for (const url of [...FEEDS, ...((await kvGet('product_scout_feeds', [])) || [])].slice(0, 6)) {
    if (ctx.outOfTime(120000)) break;
    try {
      const { items } = await fetchFeed({ url });
      for (const it of items.slice(0, 12)) evidence.push({ url: it.url, text: `[${new URL(url).hostname}] ${it.title}: ${truncate(it.snippet, 160)}` });
    } catch (e) { notes.push(`${new URL(url).hostname}: ${truncate(e.message, 60)}`); }
  }

  // 3. What the Researcher already found about product demand.
  const [knowledge, signals] = await Promise.all([
    db.select('knowledge', { created_at: `gte.${daysAgoIso(3)}`, lane: 'in.(pod,digital,dropshipping,reselling)', order: 'usefulness.desc', limit: 12, select: 'url,title,summary' }).catch(() => []),
    db.select('signals', { created_at: `gte.${daysAgoIso(7)}`, order: 'score.desc', limit: 10 }).catch(() => []),
  ]);
  for (const k of knowledge) evidence.push({ url: k.url, text: `[research] ${k.title}: ${truncate(k.summary, 200)}` });
  for (const s of signals.filter((x) => x.url)) evidence.push({ url: s.url, text: `[signal ${s.lane}] ${s.title}: ${truncate(s.evidence || '', 200)}` });
  if (evidence.length < 5) return `not enough evidence yet (${evidence.length})${notes.length ? ` · ${notes.join(' · ')}` : ''}`;

  const allowed = new Set(evidence.map((e) => e.url));
  const recent = await db.select('ideas', { created_at: `gte.${daysAgoIso(45)}`, select: 'title,status', limit: 400 });
  const rejected = recent.filter((r) => r.status === 'rejected').map((r) => r.title).slice(0, 15);

  const results = String((await kvGet(RESULTS_KEY, null).catch(() => null))?.text || '').slice(0, 1200);
  const system = systemPrompt('the Product Scout', `
From the marketplace evidence, find up to 4 products we can sell that people are clearly paying for.
Make each one ORIGINAL: never copy a listing's title, text or design; no brand, character, team or celebrity names.
Bobby's standing rejections (Oct 1): (1) nothing for short-term rental / Airbnb hosts, landlords, property owners or
property managers until he decides otherwise; (2) evidence must show people PAYING for this kind of product (sales,
favorites, top-seller lists), not just that a free thing is popular; (3) never guides on repackaging or reselling
other people's free assets, templates or libraries (licensing risk); we sell only our own original work.
type "text": ONLY when the evidence itself shows people paying for that kind of written product (a paid template, guide or
checklist listing). "X sells, so sell a guide about X" is not evidence. A product delivered as ONE web page of written content — a guide, playbook, template set written as tables,
checklists, scripts, swipe files, worksheets. Our Launcher can build and sell these with no human.
type "asset_pack": a niche for an itch.io game asset pack OUR image model can make well: single objects, icons, item sets,
character portraits, props, seamless textures or painted backgrounds (NOT tilesets, animation frames or anything with text).
Use "deliverable" for the niche and 16 example items. These go to the Asset Studio, our focus lane: prefer them when itch.io evidence shows
asset packs selling. Never turn "asset packs sell" into a guide/calculator/checklist ABOUT asset packs.
type "pod": an ORIGINAL print-on-demand design (shirt, mug, sticker, poster, tote) a supplier like Printify prints and
ships per order. Describe the design concept in "deliverable" (no copied slogans, no trademarks, no brand/character/
team/celebrity names, no real-estate themes). "est_cost" = the supplier's typical base cost per item. Radar only, for later.
type "other": printables/graphics, physical goods or anything needing shipping — these go on a radar for later.
Each needs at least one evidence URL copied exactly from the list, a one-time price, and an honest score 0–100
(demand evidence 40, ease to make it excellent as a web page 30, low competition 30).
Avoid ideas like these rejected ones: ${rejected.join('; ') || '(none)'}.
${results ? `${results}\n` : ''}JSON only: {"products":[{"type":"text|asset_pack|pod|other","title":"","buyer":"who buys it","deliverable":"exactly what they get","price_usd":19,
"why_now":"the evidence in one sentence","score":0,"evidence":["url"],"channel":"etsy|itch|web|amazon|other","est_cost":0}]}`);
  const user = evidence.slice(0, 60).map((e) => untrusted(e.url, e.text, 300)).join('\n');
  const { json } = await chat({ ctx, tier: 'smart', json: true, maxTokens: 2000, system, messages: [{ role: 'user', content: user }] });

  let ideas = 0, onRadar = [], packHints = 0, gated = 0;
  const byUrl = new Map(evidence.map((e) => [e.url, e.text]));
  for (const p of (json.products || []).slice(0, 4)) {
    const urls = (p.evidence || []).filter((u) => allowed.has(u));
    if (!p.title || !urls.length || ipRisk(`${p.title} ${p.deliverable}`)) continue;
    if (realEstateRisk(`${p.title} ${p.deliverable} ${p.buyer}`)) continue; // Bobby's rule: no real estate
    if (recent.some((r) => similarTitle(r.title, p.title))) continue;
    const price = Number(p.price_usd);
    const score = Math.max(0, Math.min(100, Math.round(Number(p.score) || 0)));
    if (p.type === 'asset_pack') {
      const cur = (await kvGet('asset_pack_ideas', [])) || [];
      if (!cur.some((c) => similarTitle(c.niche, p.title))) {
        await kvSet('asset_pack_ideas', [{ niche: truncate(p.title, 120), why: truncate(`${p.deliverable} — ${p.why_now}`, 300), evidence: urls.slice(0, 2), score, at: new Date().toISOString() }, ...cur].slice(0, 20));
        packHints++;
      }
      continue;
    }
    if (p.type === 'text' && !urls.some((u) => WRITTEN.test(byUrl.get(u) || ''))) { gated++; continue; } // no proof this kind of guide sells
    if (p.type === 'text' && price >= 5 && price <= 300) {
      await db.insertOne('ideas', {
        kind: 'venture', business: 'venture-lab', title: truncate(p.title, 200),
        summary: `${p.deliverable}\n\nBuyer: ${p.buyer}\nWhy now: ${p.why_now}\nPrice: $${price} one-time, delivered as a web page.`,
        steps: ['Write the full product to the quality bar', 'Publish the sales page with a Stripe link', 'Kill if under 5 sales in 14 days'],
        score, economics: { price_usd: price, cost_usd: 0 }, source_urls: urls, created_by: 'product_scout',
      });
      ideas++;
    } else {
      const pod = p.type === 'pod';
      onRadar.push({ title: p.title, lane: pod ? 'pod' : 'products', channel: pod ? (p.channel || 'etsy') + ' · print-on-demand' : p.channel, sell_price: price, est_cost: p.est_cost, score, why: `${p.deliverable} — ${p.why_now}`, evidence: urls, supplier_search: pod ? 'Printify / Printful base product' : '', found_by: 'product_scout' });
    }
  }
  const radarAdded = onRadar.length ? await addToRadar(onRadar) : 0;
  if (ideas || radarAdded || packHints) ctx.log('scout', `Product Scout: ${ideas} sellable product idea(s) sent to Autopilot, ${packHints} pack niche(s) to the Asset Studio, ${radarAdded} to the Radar`);
  return [`evidence ${evidence.length}`, `ideas ${ideas}`, `pack niches ${packHints}`, `radar ${radarAdded}`, gated && `guide ideas without proof ${gated}`, ...notes].filter(Boolean).join(' · ');
}
