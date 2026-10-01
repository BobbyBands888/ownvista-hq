// Product Radar: products the scouts found that we can't sell automatically yet (physical goods,
// dropshipping). Stored in kv 'product_radar' (newest first, capped) and shown on the Radar page.
import { kvGet, kvSet } from './db.js';
import { similarTitle, truncate } from './text.js';

export const RADAR_MAX = 150;

export async function radar() {
  const r = await kvGet('product_radar', []);
  return Array.isArray(r) ? r : [];
}

// items: [{ title, lane, channel, sell_price, est_cost, margin_pct, shipping_days, saturation, score, why, evidence: [url], supplier_search, found_by }]
export async function addToRadar(items) {
  const cur = await radar();
  const fresh = [];
  for (const it of items) {
    if (!it?.title || cur.some((c) => similarTitle(c.title, it.title)) || fresh.some((c) => similarTitle(c.title, it.title))) continue;
    fresh.push({
      title: truncate(String(it.title), 140),
      lane: it.lane || 'dropshipping',
      channel: truncate(String(it.channel || ''), 60),
      sell_price: num(it.sell_price), est_cost: num(it.est_cost),
      margin_pct: num(it.margin_pct), shipping_days: num(it.shipping_days),
      saturation: Math.max(1, Math.min(5, Math.round(num(it.saturation) || 3))),
      score: Math.max(0, Math.min(100, Math.round(num(it.score) || 0))),
      why: truncate(String(it.why || ''), 400),
      evidence: (it.evidence || []).slice(0, 3),
      supplier_search: truncate(String(it.supplier_search || ''), 120),
      found_by: it.found_by || null,
      at: new Date().toISOString(),
    });
  }
  if (fresh.length) await kvSet('product_radar', [...fresh, ...cur].slice(0, RADAR_MAX));
  return fresh.length;
}

function num(v) {
  const n = Number(String(v ?? '').replace(/[^0-9.\-]/g, ''));
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : null;
}
