// Marketer — 3x a day (hourly GitHub job, not the Vercel tick). Writes DRAFT-ONLY marketing kits for what we sell:
//   live Launcher offers (levelingclips.com/p/<slug>), Asset Studio packs (itch.io) and live Book Studio paperbacks (Amazon).
//   kit = better marketplace listing (title, short line, tags, description, price note), 3 Pinterest pins,
//         2 Reddit post drafts (with the subreddit rule to check), search title/description, 3 hooks.
// Never posts, sends, publishes, edits listings or contacts anyone. Bobby copies what he likes from the Shop page.
// Every piece goes through the same copy checks as the rest of HQ (no fake offers, no phone calls, no made-up
// prices, links only to our own pages, no brands, no real estate); a piece that fails is dropped, not "fixed".
import { db, kvGet, kvSet } from '../lib/db.js';
import { chat, parseJson } from '../lib/llm.js';
import { systemPrompt, untrusted, checkCopy, realEstateRisk } from '../lib/guard.js';
import { ipRisk } from '../lib/autopilot.js';
import { fetchFeed } from '../lib/feeds.js';
import { htmlToText, truncate } from '../lib/text.js';
import { KV_KEY as BOOKS_KEY } from '../lib/books.js';

export const KIT_KEY = 'marketing_kits';
const SITE = 'https://www.levelingclips.com';
const TREND_FEED = 'https://itch.io/game-assets/top-sellers.xml';
export const KIT_VERSION = 3; // bump to rewrite every kit with new rules
const HANDMADE = /\b(hand[- ]?(painted|drawn|crafted|made|illustrated)|handmade|artist[- ]made|drawn by (an? )?(artist|illustrator)|by a human)\b/i;
const RULES = async () => ({ per_run: 2, refresh_days: 7, ...(await kvGet('marketer_rules', {})) });

// Pure: which targets need a kit now (missing, or older than refresh_days). Oldest first.
export function pickTargets(targets, kits = {}, { per_run = 2, refresh_days = 7, now = Date.now() } = {}) {
  const stale = (k) => !k || (k.v || 1) < KIT_VERSION || now - Date.parse(k.made_at || 0) > refresh_days * 86400000;
  return targets
    .filter((t) => stale(kits[t.key]))
    .sort((a, b) => Date.parse(kits[a.key]?.made_at || 0) - Date.parse(kits[b.key]?.made_at || 0))
    .slice(0, per_run);
}

// Pure: run every text piece through the guards. Returns { kit, dropped: [reasons] }.
export function vetKit(raw = {}, target) {
  const allowLinks = [SITE, 'https://levelingclips.com', ...(target.itch_url ? [target.itch_url] : [])];
  const prices = target.price ? [Number(target.price)] : undefined;
  const dropped = [];
  const ok = (label, text) => {
    const t = String(text || '');
    if (!t.trim()) return false;
    const problems = [...checkCopy(t, { allowLinks, prices })];
    const re = realEstateRisk(t); if (re) problems.push(`real estate ("${re}")`);
    const ip = ipRisk(t); if (ip) problems.push(`brand/character ("${ip}")`);
    if (['asset_pack', 'book'].includes(target.kind) && HANDMADE.test(t)) problems.push('calls AI-generated art hand-made');
    if (/\b(\d+\s*\+?\s*(happy )?(customers|buyers|downloads|sales)|best[- ]?selling|#1|five[- ]star|5[- ]star)\b/i.test(t)) problems.push('claims sales/reviews we do not have');
    if (problems.length) { dropped.push(`${label}: ${problems.join('; ')}`); return false; }
    return true;
  };
  const s = (v, n) => truncate(String(v || '').trim(), n);
  // Asset packs: the AI disclosure is added in code when the model leaves it out, so it is always there.
  const AI_LINE = 'Note: these images are AI-generated (FLUX.1), then checked and cleaned up.';
  const withAi = (text) => (target.kind !== 'asset_pack' || /\bAI[- ]?(generated|made|assisted)\b/i.test(text) ? text : `${text}\n\n${AI_LINE}`);
  const kit = {};

  const L = raw.listing || {};
  const listing = { title: s(L.title, 80), short: s(L.short, 140), tags: (L.tags || []).map((x) => s(x, 30).toLowerCase()).filter(Boolean).slice(0, 10), description: withAi(s(L.description, 3000)), price_note: s(L.price_note, 300) };
  if (ok('listing', [listing.title, listing.short, listing.tags.join(' '), listing.description, listing.price_note].join('\n'))) kit.listing = listing;

  kit.pins = (raw.pins || []).slice(0, 3).map((p) => ({ title: s(p.title, 100), description: s(p.description, 500), board: s(p.board, 50) }))
    .filter((p, i) => p.title && ok(`pin ${i + 1}`, `${p.title}\n${p.description}\n${p.board}`));
  kit.reddit = (raw.reddit || []).slice(0, 2).map((r) => ({ subreddit: s(r.subreddit, 40).replace(/^\/?r\//i, ''), title: s(r.title, 200), body: withAi(s(r.body, 2500)), rule_check: s(r.rule_check, 300) }))
    .filter((r, i) => r.subreddit && r.title && ok(`reddit ${i + 1}`, `${r.title}\n${r.body}`));
  const seo = { title: s(raw.seo?.title, 70), description: s(raw.seo?.description, 160) };
  if (ok('search', `${seo.title}\n${seo.description}`)) kit.seo = seo;
  kit.hooks = (raw.hooks || []).slice(0, 3).map((h) => s(h, 160)).filter((h, i) => ok(`hook ${i + 1}`, h));
  return { kit, dropped };
}

async function loadTargets() {
  const [launches, packs, books] = await Promise.all([
    db.select('launches', { status: 'eq.live', order: 'launched_at.desc', limit: 20, select: 'id,slug,title,price_usd,page_html,sales,goal_sales' }).catch(() => []),
    db.select('asset_packs', { status: 'in.(ready,published)', order: 'created_at.desc', limit: 20, select: 'id,title,theme,style,page_copy,tags,price_usd,itch_url,status,views,downloads,sales,items' }).catch(() => []),
    kvGet(BOOKS_KEY, []).catch(() => []),
  ]);
  return [
    ...launches.map((l) => ({
      key: `launch:${l.id}`, kind: 'offer', title: l.title, price: l.price_usd, url: `${SITE}/p/${l.slug}`,
      facts: `Live offer page: ${SITE}/p/${l.slug}\nPrice: $${l.price_usd} one-time, delivered as a web page.\nSales so far: ${l.sales}/${l.goal_sales}.\nPage text:\n${truncate(htmlToText(l.page_html || ''), 3500)}`,
    })),
    ...packs.map((p) => ({
      key: `pack:${p.id}`, kind: 'asset_pack', title: p.title, price: p.price_usd, url: p.itch_url || null, itch_url: p.itch_url || null,
      facts: `itch.io game asset pack (${p.status === 'ready' ? 'not published yet' : 'published'}${p.itch_url ? `: ${p.itch_url}` : ''}).\nTheme: ${p.theme || ''}\nStyle: ${p.style || ''}\nItems: ${(p.items || []).map((i) => i.name || i.title).filter(Boolean).slice(0, 20).join(', ')}\nPrice: $${p.price_usd}\nCurrent tags: ${(p.tags || []).join(', ')}\nStats: ${p.views} views, ${p.downloads} downloads, ${p.sales} sales.\nAI-generated graphics (must stay disclosed).\nCurrent description:\n${truncate(p.page_copy || '', 2500)}`,
    })),
    // Live Amazon paperbacks (Book Studio). No Amazon link is stored, so kits use no links.
    ...(Array.isArray(books) ? books : []).filter((b) => b.status === 'live').map((b) => ({
      key: `book:${b.slug}`, kind: 'book', title: b.title, price: b.list_price || b.recommended_price, url: null,
      facts: `Amazon paperback coloring book (live on Amazon.com).\nTitle: ${b.title}\nSubtitle: ${b.subtitle || ''}\nAuthor (pen name): ${b.author}\nPages: ${b.pages || 'unknown'}\nPrice: $${b.list_price || b.recommended_price}\nSingle-sided pages, 8.5 x 11 in. Art made with AI tools; never call it hand-drawn.\nListing description:\n${truncate(htmlToText(b.listing?.description || ''), 2000)}`,
    })),
  ];
}

export async function run(ctx) {
  const rules = await RULES();
  const kits = (await kvGet(KIT_KEY, {})) || {};
  const targets = await loadTargets();
  if (!targets.length) return 'nothing live to market yet';
  const todo = pickTargets(targets, kits, rules);
  if (!todo.length) return `all ${targets.length} kit(s) fresh`;

  let trends = '';
  try {
    const { items } = await fetchFeed({ url: TREND_FEED });
    trends = items.slice(0, 15).map((it) => `- ${it.title}`).join('\n');
  } catch { /* trends are optional */ }

  const out = [];
  for (const t of todo) {
    if (ctx.outOfTime(90000)) break;
    const system = systemPrompt('the Marketer', `
Write a DRAFT marketing kit for one product. Bobby reviews and posts it himself; you never post.
Honest only: describe exactly what the buyer gets. No discounts, coupons, previews, samples, free trials, guarantees,
deadlines or scarcity. No invented reviews, testimonials, sales counts, "best-selling" or rankings. No phone calls.
Only link to the product's own page (${t.url || 'none yet: use no links'}). Price is $${t.price}; mention no other price.
No brand, character, team or celebrity names.${t.kind === 'asset_pack' ? `
These images are AI-generated. NEVER call them hand-painted, hand-drawn, handmade or artist-made ("painterly style" is fine).
Say "AI-generated" plainly in the listing description and in every Reddit body. Many game-dev subreddits ban AI art
or its promotion: only pick subreddits that allow it, and put that in rule_check.` : ''}
listing: the marketplace listing (${t.kind === 'asset_pack' ? 'itch.io' : t.kind === 'book' ? 'Amazon A+ / description ideas for Bobby to paste on KDP himself' : 'Gumroad/itch-style'}): title under 80 chars, short one-liner,
up to 10 lowercase search tags buyers actually type, description in plain text with short sections (under 1200 characters),
price_note (one sentence: why this price, from the facts).
pins: 3 Pinterest pins (title, description with natural keywords, board name).
reddit: 2 posts for subreddits where this is genuinely useful (body under 900 characters). Lead with value (a tip, a free insight), mention the product once at the end.
  rule_check: what Bobby must confirm in that subreddit's rules first (e.g. self-promotion day, flair).
seo: page title under 60 chars and meta description under 155 chars.
hooks: 3 short opening lines for posts.
JSON only: {"listing":{"title":"","short":"","tags":[""],"description":"","price_note":""},"pins":[{"title":"","description":"","board":""}],
"reddit":[{"subreddit":"","title":"","body":"","rule_check":""}],"seo":{"title":"","description":""},"hooks":[""]}`);
    const user = [untrusted('product facts', t.facts, 6000), trends && t.kind === 'asset_pack' ? untrusted('itch.io top-selling asset titles (for tag and naming ideas only, never copy)', trends, 1500) : ''].filter(Boolean).join('\n');
    try {
      const messages = [{ role: 'user', content: user }];
      // Groq's JSON mode rejects long or slightly-off output; fall back to plain text and parse it ourselves.
      let json;
      try { ({ json } = await chat({ ctx, tier: 'smart', json: true, maxTokens: 4000, system, messages })); }
      catch (e) {
        if (!/json/i.test(String(e.message))) throw e;
        const { text } = await chat({ ctx, tier: 'smart', maxTokens: 4000, system: `${system}\nReturn ONLY the JSON object, no other text.`, messages });
        json = parseJson(text);
      }
      if (!json || typeof json !== 'object') throw new Error('model returned no usable JSON');
      const { kit, dropped } = vetKit(json || {}, t);
      const pieces = (kit.listing ? 1 : 0) + kit.pins.length + kit.reddit.length + (kit.seo ? 1 : 0) + kit.hooks.length;
      if (!pieces) { out.push(`"${truncate(t.title, 40)}": nothing passed checks`); continue; }
      kits[t.key] = { ...kit, v: KIT_VERSION, kind: t.kind, title: t.title, url: t.url, dropped, made_at: new Date().toISOString() };
      await kvSet(KIT_KEY, kits);
      ctx.log('marketing', `Marketer: draft kit for "${truncate(t.title, 70)}" (${pieces} pieces${dropped.length ? `, ${dropped.length} dropped by checks` : ''}) on the Shop page`);
      out.push(`kit "${truncate(t.title, 40)}" ${pieces} pieces${dropped.length ? ` (${dropped.length} dropped)` : ''}`);
    } catch (e) { out.push(`"${truncate(t.title, 40)}": ${truncate(e.message, 80)}`); }
  }
  return out.join(' · ') || 'no kits written';
}
