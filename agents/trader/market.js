// Free, keyless market data for the Paper Trader. Quotes are delayed ~15 minutes, which is fine
// for paper trading on hourly checks. Every source is optional: when one fails we skip, never guess.
//   Universe:      Nasdaq screener (all US-listed stocks, one call)
//   Charts:        Yahoo Finance chart API (daily + 15-minute bars)
//   Option chains: Nasdaq option-chain API (bid/ask/open interest)
import { sleep } from '../lib/time.js';

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36';
const HEADERS = { 'User-Agent': UA, Accept: 'application/json, text/plain, */*', 'Accept-Language': 'en-US,en;q=0.9' };
const NASDAQ_HEADERS = { ...HEADERS, Origin: 'https://www.nasdaq.com', Referer: 'https://www.nasdaq.com/' };

async function getJson(url, headers = HEADERS, tries = 2) {
  let last;
  for (let i = 0; i < tries; i++) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 20000);
      const res = await fetch(url, { headers, signal: ctrl.signal });
      clearTimeout(timer);
      const text = await res.text();
      if (!res.ok) throw new Error(`${res.status} ${text.slice(0, 160)}`);
      return JSON.parse(text);
    } catch (e) {
      last = e;
      await sleep(1500 * (i + 1));
    }
  }
  throw new Error(`${new URL(url).host}: ${last?.message || last}`);
}

export const num = (v) => {
  if (v == null) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const s = String(v).replace(/[$,%\s]/g, '');
  if (!s || s === '--' || s === 'N/A' || s === 'NA') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
};

// ---------- universe ----------
export function parseScreener(json) {
  const rows = json?.data?.rows || json?.data?.table?.rows || [];
  return rows.map((r) => ({
    symbol: String(r.symbol || '').trim().toUpperCase(),
    name: r.name || '',
    price: num(r.lastsale),
    change_pct: num(r.pctchange) ?? 0,
    volume: num(r.volume) ?? 0,
    market_cap: num(r.marketCap),
    sector: r.sector || '',
  })).filter((r) => r.symbol && r.price != null);
}

export async function universe() {
  const json = await getJson('https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true', NASDAQ_HEADERS);
  const rows = parseScreener(json);
  if (rows.length < 500) throw new Error(`screener returned only ${rows.length} rows`);
  return rows;
}

// ---------- charts ----------
export function parseChart(json) {
  const r = json?.chart?.result?.[0];
  if (!r) throw new Error(json?.chart?.error?.description || 'no chart result');
  const q = r.indicators?.quote?.[0] || {};
  const adj = r.indicators?.adjclose?.[0]?.adjclose || [];
  const bars = [];
  (r.timestamp || []).forEach((t, i) => {
    const b = { t: t * 1000, open: q.open?.[i], high: q.high?.[i], low: q.low?.[i], close: q.close?.[i], volume: q.volume?.[i] ?? 0 };
    if (typeof adj[i] === 'number' && Number.isFinite(adj[i])) b.adj = adj[i]; // dividend-adjusted close (for the SPY benchmark)
    if ([b.open, b.high, b.low, b.close].every((x) => typeof x === 'number' && Number.isFinite(x))) bars.push(b);
  });
  return { bars, meta: { price: r.meta?.regularMarketPrice ?? null, time: (r.meta?.regularMarketTime ?? 0) * 1000, currency: r.meta?.currency } };
}

export async function chart(symbol, { range = '6mo', interval = '1d' } = {}) {
  const host = Math.random() < 0.5 ? 'query1' : 'query2';
  const url = `https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=${range}&interval=${interval}&includePrePost=false`;
  return parseChart(await getJson(url));
}

// ---------- options ----------
const MONTHS = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };

// "October 17, 2026" or "Oct 17" (+ fallback year) → YYYY-MM-DD
export function parseExpiry(text, fallbackYear) {
  const m = /([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?/.exec(String(text || ''));
  if (!m || MONTHS[m[1].toLowerCase()] == null) return null;
  const y = Number(m[3] || fallbackYear);
  if (!y) return null;
  return `${y}-${String(MONTHS[m[1].toLowerCase()] + 1).padStart(2, '0')}-${String(m[2]).padStart(2, '0')}`;
}

// Nasdaq option chain → [{ expiry, strike, type, bid, ask, last, oi, volume }]
export function parseOptionChain(json) {
  const rows = json?.data?.table?.rows || json?.data?.rows || [];
  const out = [];
  let group = null;
  for (const r of rows) {
    if (r.expirygroup) { group = parseExpiry(r.expirygroup); if (r.strike == null) continue; }
    const strike = num(r.strike);
    if (strike == null) continue;
    const expiry = parseExpiry(r.expiryDate, group?.slice(0, 4)) || group;
    if (!expiry) continue;
    for (const [type, p] of [['call', 'c_'], ['put', 'p_']]) {
      const bid = num(r[`${p}Bid`]), ask = num(r[`${p}Ask`]);
      if (bid == null && ask == null) continue;
      out.push({ expiry, strike, type, bid: bid ?? 0, ask: ask ?? 0, last: num(r[`${p}Last`]), oi: num(r[`${p}Openinterest`]), volume: num(r[`${p}Volume`]) });
    }
  }
  return out;
}

export async function optionChain(symbol, { from, to }) {
  const url = `https://api.nasdaq.com/api/quote/${encodeURIComponent(symbol)}/option-chain?assetclass=stocks&limit=500&fromdate=${from}&todate=${to}&excode=oprac&callput=callput&money=all&type=all`;
  return parseOptionChain(await getJson(url, NASDAQ_HEADERS));
}
