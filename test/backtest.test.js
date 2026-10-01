import { test } from 'node:test';
import assert from 'node:assert/strict';
import { prepare, simulate, runAll, windows, CONFIGS } from '../agents/trader/backtest.js';

const DAY = 86400000;
const T0 = Date.parse('2021-01-04T14:30:00Z');
// Deterministic pseudo-random walk so tests are repeatable.
function walk(seed, n, drift, vol, start = 50) {
  let x = seed, px = start;
  const rnd = () => { x = (x * 1103515245 + 12345) % 2147483648; return x / 2147483648; };
  return Array.from({ length: n }, (_, i) => {
    const o = px;
    px = Math.max(1, px * (1 + drift + (rnd() - 0.5) * vol));
    const hi = Math.max(o, px) * (1 + rnd() * vol / 3), lo = Math.min(o, px) * (1 - rnd() * vol / 3);
    return { t: T0 + i * DAY, open: o, high: hi, low: lo, close: px, volume: 2e6 * (rnd() < 0.1 ? 4 : 1), adj: px };
  });
}

function fixture(n = 700) {
  const spy = walk(7, n, 0.0004, 0.02, 400);
  const series = {};
  for (let k = 0; k < 25; k++) series[`S${String.fromCharCode(65 + k)}`] = walk(100 + k, n, k % 3 === 0 ? 0.001 : -0.0002, 0.04, 30 + k);
  return prepare(series, spy);
}

test('backtest runs both rule sets, never goes below zero cash, and closes every trade', () => {
  const data = fixture();
  const res = runAll(data);
  for (const w of ['older', 'recent']) {
    for (const k of Object.keys(CONFIGS)) {
      const r = res[w][k];
      assert.ok(Number.isFinite(r.end_equity) && r.end_equity > 0, `${w}/${k} equity ${r.end_equity}`);
      assert.ok(r.max_dd >= 0 && r.max_dd < 1);
      assert.ok(r.spy_ret != null);
    }
  }
  assert.ok(res.older.current.all.n > 0, 'current rules trade on a noisy universe');
  assert.ok(['proposed', 'current', 'mixed'].includes(res.verdict.winner));
  assert.ok(res.verdict.text.length > 20);
});

test('windows split older years from the last ~12 months without overlap', () => {
  const data = fixture();
  const w = windows(data);
  assert.equal(w.older.from, 200);
  assert.equal(w.recent.to, data.days.length - 1);
  assert.equal(w.older.to + 1, w.recent.from);
  assert.equal(w.recent.to - w.recent.from + 1, 252);
});

test('market filter: proposed rules take no new trades while SPY is below its 200-day average', () => {
  const data = fixture();
  // Force SPY under its 200-day average everywhere.
  data.spyClose = data.spyClose.map((c, i) => (data.spySma200[i] ? data.spySma200[i] * 0.9 : c));
  const r = simulate(data, CONFIGS.proposed, { from: 200, to: data.days.length - 1 });
  assert.equal(r.all.n, 0);
  assert.equal(r.end_equity, 10000);
});

test('risk per trade is respected: one stop-out costs about the configured risk', () => {
  // One stock that breaks out on heavy volume, then gaps nowhere and drifts down through the stop.
  const n = 320;
  const spy = Array.from({ length: n }, (_, i) => ({ t: T0 + i * DAY, open: 400 + i * 0.1, high: 401 + i * 0.1, low: 399 + i * 0.1, close: 400 + i * 0.1, volume: 1e8, adj: 400 + i * 0.1 }));
  const bars = Array.from({ length: n }, (_, i) => {
    let c = 50 + i * 0.05;
    if (i === 300) c = 70;
    if (i > 300) c = 70 - (i - 300) * 2;
    return { t: T0 + i * DAY, open: i > 300 ? c + 2 : c, high: (i > 300 ? c + 2 : c) * 1.005, low: c * 0.995, close: c, volume: i === 300 ? 9e6 : 2e6 };
  });
  bars[301].open = 70; bars[301].high = 70.5;
  const data = prepare({ AAA: bars }, spy);
  const r = simulate(data, { ...CONFIGS.proposed, setups: ['breakout'], uptrend_only: false, regime: false }, { from: 250, to: n - 1 });
  assert.equal(r.all.n, 1);
  const loss = -r.all.pnl;
  assert.ok(loss > 0 && loss <= 10000 * CONFIGS.proposed.risk * 1.6, `loss ${loss}`); // stop + slippage + a gap
});
