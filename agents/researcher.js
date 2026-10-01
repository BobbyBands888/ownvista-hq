// Researcher — hourly, 24/7 (learns constantly; findings are routed to the agents that can use them). Pulls public feeds (robots.txt respected) and approved search
// queries, keeps only relevant items (tagged by business, usefulness 1–5), tracks per-source
// hit/useful counts and retires sources that stay useless. Hunter extracts demand signals.
import { db } from './lib/db.js';
import { chat } from './lib/llm.js';
import { systemPrompt, untrusted } from './lib/guard.js';
import { fetchFeed } from './lib/feeds.js';
import { webSearch } from './lib/search.js';
import { sha256, truncate } from './lib/text.js';
import { BUSINESSES, LANES } from './lib/context.js';
import { hunt } from './lab/hunter.js';
import { routeFindings } from './lib/briefs.js';

const MAX_SOURCES = 25;
const MAX_NEW_PER_SOURCE = 8;
const MAX_ITEMS = 48;
const BATCH = 8;

export async function run(ctx) {
  const sources = await db.select('sources', {
    status: 'eq.active', kind: 'in.(rss,search)', order: 'last_fetched_at.asc.nullsfirst', limit: MAX_SOURCES,
  });
  const pending = [];
  let fetched = 0, failed = 0;
  for (const s of sources) {
    if (pending.length >= MAX_ITEMS || ctx.outOfTime(150000)) break;
    try {
      const items = await pull(s);
      fetched++;
      // Newest 30 items; one round trip marks them seen and tells us which are new.
      const top = [...new Map(items.slice(0, 30).map((it) => [sha256(it.url), it])).entries()];
      const inserted = top.length
        ? await db.insert('seen_urls', top.map(([h]) => ({ url_hash: h, source_id: s.id })), { onConflict: 'url_hash', ignoreDuplicates: true })
        : [];
      const isNew = new Set(inserted.map((r) => r.url_hash));
      const fresh = top.filter(([h]) => isNew.has(h)).slice(0, MAX_NEW_PER_SOURCE).map(([, it]) => ({ ...it, source: s }));
      pending.push(...fresh);
      await db.update('sources', { id: `eq.${s.id}` }, {
        last_fetched_at: new Date().toISOString(), error_count: 0, last_error: null,
        fetched_count: s.fetched_count + fresh.length,
        ...(items.etag !== undefined ? { etag: items.etag, last_modified: items.lastModified } : {}),
      });
      s.fetched_count += fresh.length;
    } catch (e) {
      failed++;
      const errors = s.error_count + 1;
      await db.update('sources', { id: `eq.${s.id}` }, {
        last_fetched_at: new Date().toISOString(), error_count: errors, last_error: truncate(e.message, 300),
        ...(e.robots || errors >= 6 ? { status: 'retired' } : {}),
      });
      if (e.robots || errors >= 6) ctx.log('source_retired', `Retired "${s.name}": ${e.robots ? 'robots.txt disallows it' : '6 failures in a row'}`, { table: 'sources', id: s.id });
    }
  }

  let kept = 0;
  const signalCandidates = [];
  const newKnowledge = [];
  for (let i = 0; i < pending.length; i += BATCH) {
    if (ctx.outOfTime(90000)) break;
    const batch = pending.slice(i, i + BATCH);
    const judged = await judge(ctx, batch);
    for (const [idx, j] of judged.entries()) {
      const it = batch[idx];
      if (!j) continue;
      const src = it.source;
      if (j.relevant && j.usefulness >= 2) {
        const added = await db.insert('knowledge', [{
          source_id: src.id, url: it.url, title: it.title, summary: j.summary,
          businesses: j.businesses, lane: j.lane, usefulness: j.usefulness, published_at: it.publishedAt,
        }], { onConflict: 'url', ignoreDuplicates: true });
        if (added?.[0]) newKnowledge.push(added[0]);
        kept++;
        src.hit_count++;
        if (j.usefulness >= 4) src.useful_count++;
        if (j.signal) signalCandidates.push({ ...it, judged: j });
      }
    }
  }

  // Persist hit/useful counts and retire sources that stay useless.
  let retired = 0;
  for (const s of new Set(pending.map((p) => p.source))) {
    const useless = s.fetched_count >= 40 && s.hit_count / s.fetched_count < 0.05 && s.useful_count === 0;
    await db.update('sources', { id: `eq.${s.id}` }, {
      hit_count: s.hit_count, useful_count: s.useful_count, ...(useless ? { status: 'retired' } : {}),
    });
    if (useless) {
      retired++;
      ctx.log('source_retired', `Retired "${s.name}": ${s.hit_count}/${s.fetched_count} relevant, none useful`, { table: 'sources', id: s.id });
    }
  }

  const signals = ctx.outOfTime(60000) ? 0 : await hunt(ctx, signalCandidates);

  // Deploy what was learned: brief the agents that can use it, queue uncovered opportunities for the Architect.
  let routed = { routed: 0, gaps: 0 };
  if (newKnowledge.length && !ctx.outOfTime(45000)) {
    try { routed = await routeFindings(ctx, newKnowledge); } catch (e) {
      if (e.name === 'CapError') throw e;
      ctx.note(`routing skipped: ${truncate(e.message, 120)}`);
    }
  }
  if (kept) ctx.log('knowledge', `Added ${kept} knowledge item(s) from ${fetched} source(s)`);
  return `sources ${fetched} (${failed} failed), new items ${pending.length}, kept ${kept}, signals ${signals}, retired ${retired}, briefs ${routed.routed}, gaps ${routed.gaps}`;
}

async function pull(source) {
  if (source.kind === 'search') {
    const r = await webSearch(source.query || source.name, { purpose: 'research', maxResults: 8 });
    if (r.disabled || r.capped) return [];
    return r.results.map((x) => ({ title: x.title, url: x.url, snippet: x.snippet, publishedAt: null }));
  }
  const r = await fetchFeed(source);
  const items = r.items;
  items.etag = r.etag ?? null;
  items.lastModified = r.lastModified ?? null;
  return items;
}

async function judge(ctx, batch) {
  const system = systemPrompt('the Researcher', `
Bobby's businesses (use these exact keys): ${BUSINESSES.join(', ')}.
- nashville-buys: FSBO listings + home-service vendor directory, Greater Nashville.
- followup: email follow-up of home-service contractors' unsold estimates.
- ma-real-estate: Bobby's Massachusetts real estate agent business.
- clearance: Home Depot / Lowe's deep-clearance reselling, Greater Boston.
- villa-cinema: AI walkthrough films for luxury villa rental managers.
- venture-lab: new business experiments. Lanes: ${LANES.join(', ')}.

For each numbered item decide if it is relevant to any business. Be strict: generic news is not relevant.
"signal": true only when the item shows demand people pay for (sold prices, people saying "I'd pay for", rising product demand, complaints about a local service, a gap in a market).
JSON only: {"items":[{"i":0,"relevant":true,"businesses":["followup"],"lane":null|"<lane>","usefulness":1-5,"summary":"2 sentences: what it says and why it matters to Bobby","signal":false}]}`);
  const user = batch.map((it, i) => `[${i}] ${untrusted(it.source.name, `Title: ${it.title}\nURL: ${it.url}\n${it.snippet}`, 1200)}`).join('\n\n');
  try {
    const { json } = await chat({ ctx, tier: 'fast', system, json: true, maxTokens: 1800, temperature: 0.2, messages: [{ role: 'user', content: user }] });
    const out = [];
    for (const r of json.items || []) {
      if (typeof r.i !== 'number' || !batch[r.i]) continue;
      out[r.i] = {
        relevant: Boolean(r.relevant),
        businesses: (r.businesses || []).filter((b) => BUSINESSES.includes(b)),
        lane: LANES.includes(r.lane) ? r.lane : (batch[r.i].source.lane || null),
        usefulness: Math.max(1, Math.min(5, Number(r.usefulness) || 1)),
        summary: truncate(String(r.summary || ''), 600),
        signal: Boolean(r.signal),
      };
    }
    return out;
  } catch (e) {
    if (e.name === 'CapError') throw e;
    ctx.note(`judge batch failed: ${e.message.slice(0, 120)}`);
    return [];
  }
}
