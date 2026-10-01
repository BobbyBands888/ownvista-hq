import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_RULES as R, rsi, stats, setupsFor, isTradableRow, riskMode, scoreboard, setupMultiplier, newBenches,
  confidenceMultiplier, validatePick, sizeStock, sizeOption, chooseContract, checkExit, tradingDaysBetween, graduation,
} from '../agents/trader/rules.js';
import { parseScreener, parseChart, parseOptionChain, parseExpiry, num } from '../agents/trader/market.js';
import { SCHEDULE, isDue } from '../agents/router.js';

const bar = (close, i, o = {}) => ({ t: i, open: close, high: close * 1.01, low: close * 0.99, close, volume: 1e6, ...o });
const trend = (n, from, step) => Array.from({ length: n }, (_, i) => bar(from + i * step, i));

test('RSI is 100 straight up and low straight down', () => {
  assert.equal(rsi(trend(30, 10, 1).map((b) => b.close)), 100);
  assert.ok(rsi(trend(30, 50, -1).map((b) => b.close)) < 5);
});

test('breakout is tagged on a new high with heavy volume, not on a quiet day', () => {
  const bars = trend(60, 50, 0.2);
  bars.push(bar(64, 60, { volume: 3e6 }));
  assert.ok(setupsFor(stats(bars)).includes('breakout'));
  const quiet = trend(60, 50, 0.2); quiet.push(bar(64, 60));
  assert.ok(!setupsFor(stats(quiet)).includes('breakout'));
});

test('partial-day volume is projected so 10am rvol is not undercounted', () => {
  const bars = trend(60, 50, 0.1); bars.push(bar(56.2, 60, { volume: 5e5 }));
  assert.ok(stats(bars, 0.25).rvol > stats(bars, 1).rvol * 3.9);
});

test('universe skips stocks under $5, warrants and thin names', () => {
  assert.equal(isTradableRow({ symbol: 'ABCD', price: 0.6, volume: 9e7 }), false);
  assert.equal(isTradableRow({ symbol: 'ABCDW', price: 2, volume: 9e7 }), false);
  assert.equal(isTradableRow({ symbol: 'BRK.B', price: 400, volume: 9e7 }), false);
  assert.equal(isTradableRow({ symbol: 'THIN', price: 3, volume: 1e5 }), false);
  assert.equal(isTradableRow({ symbol: 'SOFI', price: 3, volume: 5e6 }), false);
  assert.equal(isTradableRow({ symbol: 'SOFI', price: 12, volume: 5e6 }), true);
});

test('drawdown brakes: half size at -10%, pause at -20%', () => {
  assert.equal(riskMode(9500, 10000).mode, 'normal');
  assert.equal(riskMode(8900, 10000).mult, 0.5);
  assert.equal(riskMode(7900, 10000).mode, 'paused');
});

test('pick validation enforces 2:1 reward:risk and sane stops', () => {
  const s = { price: 100, atr14: 2 };
  assert.ok(validatePick({ instrument: 'stock', setup: 'breakout', stop: 97, target: 106 }, s, ['breakout']).ok);
  assert.match(validatePick({ instrument: 'stock', setup: 'breakout', stop: 97, target: 104 }, s, ['breakout']).problems.join(), /reward:risk/);
  assert.match(validatePick({ instrument: 'stock', setup: 'breakout', stop: 99.8, target: 110 }, s, ['breakout']).problems.join(), /tighter/);
  assert.match(validatePick({ instrument: 'stock', setup: 'breakout', stop: 90, target: 130 }, s, ['breakout']).problems.join(), /wider/);
  assert.match(validatePick({ instrument: 'stock', setup: 'pullback', stop: 97, target: 106 }, s, ['breakout']).problems.join(), /not on this chart/);
  assert.match(validatePick({ instrument: 'stock', setup: 'breakdown', stop: 103, target: 94 }, s, ['breakdown']).problems.join(), /puts-only/);
  assert.ok(validatePick({ instrument: 'put', setup: 'breakdown', stop: 103, target: 94 }, s, ['breakdown']).ok);
  // Missing levels get ATR defaults that pass.
  assert.ok(validatePick({ instrument: 'stock', setup: 'breakout' }, s, ['breakout']).ok);
});

test('stock sizing risks ~2% and respects position, penny and cash caps', () => {
  const a = sizeStock({ equity: 10000, cash: 10000, entry: 100, stop: 97, mult: 1, pennyExposure: 0 });
  assert.ok(a.risk_usd <= 200.5 && a.cost <= 2000.01, JSON.stringify(a)); // 20% position cap binds
  const p = sizeStock({ equity: 10000, cash: 10000, entry: 3, stop: 2.8, mult: 1, pennyExposure: 0 });
  assert.ok(p.cost <= 800.01, 'penny position ≤ 8%');
  assert.equal(sizeStock({ equity: 10000, cash: 10000, entry: 3, stop: 2.8, mult: 1, pennyExposure: 2500 }).shares, 0);
  assert.equal(sizeStock({ equity: 10000, cash: 50, entry: 100, stop: 97, mult: 1, pennyExposure: 0 }).shares, 0);
  assert.equal(sizeStock({ equity: 10000, cash: 10000, entry: 100, stop: 97, mult: 0, pennyExposure: 0 }).shares, 0);
});

test('option sizing caps premium at 4% per trade and 20% total', () => {
  assert.equal(sizeOption({ equity: 10000, cash: 10000, ask: 1.2, mult: 1, optionExposure: 0 }).contracts, 3);
  assert.equal(sizeOption({ equity: 10000, cash: 10000, ask: 5, mult: 1, optionExposure: 0 }).contracts, 0);
  assert.equal(sizeOption({ equity: 10000, cash: 10000, ask: 1.2, mult: 1, optionExposure: 1950 }).contracts, 0);
});

test('contract choice: 14–45 days out, near the money, tight spread, some open interest', () => {
  const chain = [
    { expiry: '2026-10-09', strike: 100, type: 'call', bid: 2, ask: 2.1, oi: 900 },  // too soon
    { expiry: '2026-10-30', strike: 100, type: 'call', bid: 2, ask: 3, oi: 900 },    // spread too wide
    { expiry: '2026-10-30', strike: 98, type: 'call', bid: 3.4, ask: 3.6, oi: 900 },
    { expiry: '2026-10-30', strike: 110, type: 'call', bid: 0.4, ask: 0.45, oi: 900 },
    { expiry: '2026-10-30', strike: 99, type: 'call', bid: 2.9, ask: 3.1, oi: 10 },  // no open interest
  ];
  assert.equal(chooseContract(chain, { type: 'call', price: 100, today: '2026-10-01' }).strike, 98);
  assert.equal(chooseContract(chain, { type: 'put', price: 100, today: '2026-10-01' }), null);
});

test('exits: stop checked before target, gaps fill at the open', () => {
  const t = { stop: 95, target: 110, bearish: false, ref: 100 };
  assert.equal(checkExit(t, [{ t: 1, open: 100, high: 111, low: 94, close: 100 }]).reason, 'stop');
  assert.equal(checkExit(t, [{ t: 1, open: 90, high: 91, low: 89, close: 90 }]).price, 90);
  assert.equal(checkExit(t, [{ t: 1, open: 101, high: 111, low: 100, close: 109 }]).reason, 'target');
  const p = checkExit({ stop: 105, target: 90, bearish: true, ref: 100 }, [{ t: 1, open: 99, high: 101, low: 89, close: 90 }]);
  assert.equal(p.reason, 'target');
  assert.equal(p.mfe, 11);
});

test('learning in numbers: losing setups get benched, winners sized up, confidence must earn trust', () => {
  const mk = (setup, pnl, confidence = 3) => ({ setup, kind: 'stock', entry_price: 50, pnl, risk_usd: 100, confidence });
  const closed = [...Array(8)].map(() => mk('breakout', -60)).concat([...Array(8)].map(() => mk('pullback', 80)));
  const board = scoreboard(closed);
  assert.equal(setupMultiplier('breakout', board, {}, '2026-10-01'), 0);
  assert.equal(setupMultiplier('pullback', board, {}, '2026-10-01'), 1.25);
  assert.equal(setupMultiplier('pullback', board, { pullback: '2026-10-20' }, '2026-10-01'), 0);
  assert.deepEqual(Object.keys(newBenches(board, {}, '2026-10-01')), ['breakout']);
  assert.ok(confidenceMultiplier(5, board) > 1);
  const overconfident = scoreboard([...Array(8)].map(() => mk('breakout', -50, 5)).concat([...Array(8)].map(() => mk('pullback', 50, 3))));
  assert.equal(confidenceMultiplier(5, overconfident), 1);
});

test('graduation needs every check, including beating SPY', () => {
  const closed = [...Array(60)].map((_, i) => ({ pnl: i % 2 ? 120 : -60 }));
  const g = graduation({ days: 95, closed, equityCurve: [10000, 10500, 11800], benchReturn: 0.05, startCash: 10000 });
  assert.ok(g.ready, JSON.stringify(g.checks));
  assert.equal(graduation({ days: 30, closed, equityCurve: [10000], benchReturn: 0.05, startCash: 10000 }).ready, false);
  assert.equal(graduation({ days: 95, closed, equityCurve: [10000], benchReturn: 0.5, startCash: 10000 }).ready, false);
});

test('trading days skip weekends', () => {
  assert.equal(tradingDaysBetween('2026-10-02', '2026-10-05'), 1); // Fri → Mon
  assert.equal(tradingDaysBetween('2026-10-01', '2026-10-08'), 5);
});

test('data parsers: Nasdaq screener, Yahoo chart, Nasdaq option chain', () => {
  assert.equal(num('$1,234.50'), 1234.5);
  assert.equal(num('--'), null);
  const rows = parseScreener({ data: { rows: [{ symbol: 'SOFI', name: 'SoFi', lastsale: '$9.12', pctchange: '-2.1%', volume: '45,000,000', marketCap: '9,000,000,000', sector: 'Finance' }] } });
  assert.deepEqual([rows[0].price, rows[0].change_pct, rows[0].volume], [9.12, -2.1, 45000000]);
  const c = parseChart({ chart: { result: [{ meta: { regularMarketPrice: 5, regularMarketTime: 100 }, timestamp: [1, 2], indicators: { quote: [{ open: [1, null], high: [2, 2], low: [0.5, 1], close: [1.5, 1.8], volume: [10, 20] }] } }] } });
  assert.equal(c.bars.length, 1);
  assert.equal(parseExpiry('October 17, 2026'), '2026-10-17');
  assert.equal(parseExpiry('Nov 20', '2026'), '2026-11-20');
  const ch = parseOptionChain({ data: { table: { rows: [
    { expirygroup: 'October 30, 2026', strike: null },
    { expirygroup: '', expiryDate: 'Oct 30', strike: '100.00', c_Bid: '2.10', c_Ask: '2.25', c_Last: '2.2', c_Openinterest: '1,200', p_Bid: '--', p_Ask: '--' },
  ] } } });
  assert.equal(ch.length, 1);
  assert.deepEqual([ch[0].expiry, ch[0].strike, ch[0].type, ch[0].ask, ch[0].oi], ['2026-10-30', 100, 'call', 2.25, 1200]);
});

test('Paper Trader runs weekdays 10am–4pm ET only', () => {
  const s = SCHEDULE.find((x) => x.id === 'paper_trader');
  assert.ok(isDue(s, new Date('2026-10-01T14:07:00Z'), []), 'Thu 10:07am');
  assert.ok(isDue(s, new Date('2026-10-01T20:07:00Z'), []), 'Thu 4:07pm');
  assert.ok(!isDue(s, new Date('2026-10-01T21:07:00Z'), []), 'Thu 5:07pm');
  assert.ok(!isDue(s, new Date('2026-10-03T15:07:00Z'), []), 'Saturday');
});
