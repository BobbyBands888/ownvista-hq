// Paper Trader rules. Pure functions, no network, no AI: indicators, setups, sizing,
// validation, fills, exits and the scoreboard the trader learns from.
// PAPER ONLY. Nothing in this lane places real orders or touches a brokerage.

export const DEFAULT_RULES = {
  start_cash: 10000,
  risk_per_trade: 0.02,        // aggressive: 2% of equity at risk per trade (pros use 0.5–1%)
  max_position_pct: 0.20,      // one stock position ≤ 20% of equity
  max_penny_position_pct: 0.08,
  max_penny_exposure: 0.25,    // all penny stocks together ≤ 25% of equity
  max_option_premium_pct: 0.04,// premium = max loss on a long option; ≤ 4% of equity per trade
  max_option_exposure: 0.20,
  max_open: 8,
  max_new_per_day: 3,
  min_reward_risk: 2,
  min_price: 5,                // no stocks under $5 (Oct 1): penny names made every result noise
  penny_below: 5,
  min_dollar_volume: 5e6,
  min_penny_dollar_volume: 3e6,
  max_hold_days: 20,
  option_min_dte: 14,
  option_max_dte: 45,
  option_max_spread: 0.15,     // skip contracts whose bid/ask spread is >15% of mid
  option_exit_dte: 5,          // never hold into the last week
  slip_stock: 0.0005,
  slip_penny: 0.005,
  drawdown_half: 0.10,         // 10% off the peak → half size
  drawdown_pause: 0.20,        // 20% off the peak → no new trades until Bobby resumes
  bench_min_trades: 8,         // a setup with 8+ trades and negative expectancy is benched
  bench_days: 21,
};

export const SETUPS = {
  breakout: 'New 20-day high on heavy volume, above the 50-day average',
  pullback: 'Uptrend (20-day above 50-day) dipping to the 20-day with RSI under 45',
  momentum_gap: 'Up 8%+ today on 3x normal volume',
  oversold_bounce: 'RSI under 30 and turning up from the prior close',
  breakdown: 'New 20-day low on heavy volume, below the 50-day average (puts only)',
};

// ---------- indicators ----------
export function sma(values, n) {
  if (values.length < n) return null;
  let s = 0;
  for (let i = values.length - n; i < values.length; i++) s += values[i];
  return s / n;
}

export function rsi(closes, n = 14) {
  if (closes.length < n + 1) return null;
  let gain = 0, loss = 0;
  for (let i = 1; i <= n; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  gain /= n; loss /= n;
  for (let i = n + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gain = (gain * (n - 1) + Math.max(d, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-d, 0)) / n;
  }
  if (loss === 0) return 100;
  return 100 - 100 / (1 + gain / loss);
}

export function atr(bars, n = 14) {
  if (bars.length < n + 1) return null;
  const trs = [];
  for (let i = 1; i < bars.length; i++) {
    const b = bars[i], p = bars[i - 1].close;
    trs.push(Math.max(b.high - b.low, Math.abs(b.high - p), Math.abs(b.low - p)));
  }
  return sma(trs, n);
}

// bars: [{t, open, high, low, close, volume}] daily, oldest first (last bar may be today, partial).
// dayFraction < 1 projects today's partial volume to a full day.
export function stats(bars, dayFraction = 1) {
  if (!bars || bars.length < 55) return null;
  const closes = bars.map((b) => b.close);
  const last = bars[bars.length - 1];
  const prev = bars[bars.length - 2];
  const prior20 = bars.slice(-21, -1);
  const avgVol20 = sma(prior20.map((b) => b.volume), 20);
  return {
    price: last.close,
    change_pct: (last.close / prev.close - 1) * 100,
    sma20: sma(closes, 20),
    sma50: sma(closes, 50),
    rsi14: rsi(closes.slice(-120), 14),
    atr14: atr(bars.slice(-40), 14),
    high20: Math.max(...prior20.map((b) => b.high)),
    low20: Math.min(...prior20.map((b) => b.low)),
    rvol: avgVol20 ? last.volume / Math.max(0.25, Math.min(1, dayFraction)) / avgVol20 : null,
    dollar_volume: avgVol20 ? avgVol20 * last.close : 0,
    rsi_prev: rsi(closes.slice(-121, -1), 14),
    prev_close: prev.close,
  };
}

// Which named setups does this chart show right now?
export function setupsFor(s) {
  if (!s || !s.atr14) return [];
  const out = [];
  const up = s.sma20 > s.sma50 && s.price > s.sma50;
  if (s.price >= s.high20 * 0.99 && s.rvol >= 1.5 && s.price > s.sma50) out.push('breakout');
  if (up && s.rsi14 < 45 && Math.abs(s.price - s.sma20) <= s.atr14) out.push('pullback');
  if (s.change_pct >= 8 && s.rvol >= 3) out.push('momentum_gap');
  if (s.rsi14 < 30 && s.price > s.prev_close) out.push('oversold_bounce');
  if (s.price <= s.low20 * 1.01 && s.rvol >= 1.5 && s.price < s.sma50) out.push('breakdown');
  return out;
}

// ---------- universe ----------
const BAD_SYMBOL = /[^A-Z]|^[A-Z]{4}[WRU]$/; // warrants, rights, units, preferreds, classes with dots

export function isTradableRow(r, rules = DEFAULT_RULES) {
  if (!r?.symbol || BAD_SYMBOL.test(r.symbol)) return false;
  if (!(r.price >= rules.min_price) || r.price > 1500) return false;
  const dv = r.price * (r.volume || 0);
  return r.price < rules.penny_below ? dv >= rules.min_penny_dollar_volume : dv >= rules.min_dollar_volume;
}

// Pick the symbols worth pulling charts for: big movers, heaviest traded, and a few cheap movers.
export function shortlist(rows, rules = DEFAULT_RULES, n = 18) {
  const ok = rows.filter((r) => isTradableRow(r, rules));
  const pick = new Map();
  const add = (list, k) => { for (const r of list.slice(0, k)) if (pick.size < n) pick.set(r.symbol, r); };
  add([...ok].sort((a, b) => b.change_pct - a.change_pct), 6);              // gainers
  add([...ok].sort((a, b) => a.change_pct - b.change_pct), 3);              // losers (bounces / puts)
  add(ok.filter((r) => r.price < rules.penny_below).sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct)), 4);
  add([...ok].sort((a, b) => b.price * b.volume - a.price * a.volume), n);  // most traded
  return [...pick.values()];
}

// ---------- risk state ----------
export function drawdown(equity, peak) {
  return peak > 0 ? Math.max(0, 1 - equity / peak) : 0;
}

export function riskMode(equity, peak, rules = DEFAULT_RULES) {
  const dd = drawdown(equity, peak);
  if (dd >= rules.drawdown_pause) return { mode: 'paused', mult: 0, dd };
  if (dd >= rules.drawdown_half) return { mode: 'half', mult: 0.5, dd };
  return { mode: 'normal', mult: 1, dd };
}

// ---------- scoreboard (what the trader learns from, in numbers) ----------
// R = profit divided by the dollars that were at risk when the trade was opened.
export function rMultiple(t) {
  const risk = Number(t.risk_usd);
  return risk > 0 ? Number(t.pnl) / risk : 0;
}

export function scoreboard(closed) {
  const by = (key) => {
    const groups = {};
    for (const t of closed) {
      const k = key(t);
      const g = (groups[k] ||= { n: 0, wins: 0, r: 0, pnl: 0 });
      g.n++; g.r += rMultiple(t); g.pnl += Number(t.pnl);
      if (Number(t.pnl) > 0) g.wins++;
    }
    for (const g of Object.values(groups)) { g.win_rate = g.wins / g.n; g.avg_r = g.r / g.n; }
    return groups;
  };
  return {
    setup: by((t) => t.setup),
    instrument: by((t) => (t.kind === 'stock' ? (Number(t.entry_price) < 5 ? 'penny' : 'stock') : t.kind)),
    confidence: by((t) => (Number(t.confidence) >= 4 ? 'high' : 'normal')),
    all: by(() => 'all').all || { n: 0, wins: 0, r: 0, pnl: 0, win_rate: 0, avg_r: 0 },
  };
}

// Setups that have proven to lose money get benched; setups that work get a size boost.
export function setupMultiplier(setup, board, bench = {}, today, rules = DEFAULT_RULES) {
  if (bench[setup] && bench[setup] > today) return 0;
  const g = board.setup[setup];
  if (!g || g.n < rules.bench_min_trades) return 1;
  if (g.avg_r < -0.1) return 0;
  if (g.avg_r > 0.3) return 1.25;
  return 1;
}

// Newly benched setups (enough trades, negative expectancy, not benched already).
export function newBenches(board, bench = {}, today, rules = DEFAULT_RULES) {
  const out = {};
  for (const [setup, g] of Object.entries(board.setup)) {
    if (g.n >= rules.bench_min_trades && g.avg_r < -0.1 && !(bench[setup] > today)) out[setup] = g;
  }
  return out;
}

// Confidence only changes size if high-confidence trades have actually done better.
export function confidenceMultiplier(conf, board) {
  const hi = board.confidence.high, lo = board.confidence.normal;
  const trusted = !(hi && lo && hi.n + lo.n >= 15 && hi.avg_r <= lo.avg_r);
  if (!trusted) return 1;
  const c = Math.max(1, Math.min(5, Number(conf) || 3));
  return 0.5 + 0.15 * c; // 1 → 0.65x, 3 → 0.95x, 5 → 1.25x
}

// ---------- validation + sizing ----------
// pick: { symbol, setup, instrument: 'stock'|'call'|'put', stop, target, max_hold_days, confidence }
// s: stats(). Returns { ok, problems, plan } where plan has the corrected stop/target.
export function validatePick(pick, s, setups, rules = DEFAULT_RULES) {
  const problems = [];
  const inst = pick.instrument;
  if (!['stock', 'call', 'put'].includes(inst)) problems.push(`unknown instrument ${inst}`);
  if (!setups.includes(pick.setup)) problems.push(`setup ${pick.setup} is not on this chart (${setups.join(', ') || 'none'})`);
  const bearish = inst === 'put';
  if (pick.setup === 'breakdown' && !bearish) problems.push('breakdown is a puts-only setup');
  if (bearish && pick.setup !== 'breakdown' && pick.setup !== 'momentum_gap') problems.push('puts only on breakdown or fading a gap');
  const entry = s.price;
  const a = s.atr14;
  let stop = Number(pick.stop), target = Number(pick.target);
  if (!Number.isFinite(stop) || stop <= 0) stop = bearish ? entry + 1.5 * a : entry - 1.5 * a;
  if (!Number.isFinite(target) || target <= 0) target = bearish ? entry - 3 * a : entry + 3 * a;
  const risk = bearish ? stop - entry : entry - stop;
  const reward = bearish ? entry - target : target - entry;
  if (risk <= 0) problems.push('stop is on the wrong side of the price');
  else {
    if (risk < 0.5 * a) problems.push('stop is tighter than half a normal day’s move (gets shaken out)');
    if (risk > 3 * a) problems.push('stop is wider than 3 normal days’ moves (too loose)');
    if (reward / risk < rules.min_reward_risk) problems.push(`reward:risk ${(reward / risk).toFixed(1)} is under ${rules.min_reward_risk}`);
  }
  const hold = Math.max(1, Math.min(rules.max_hold_days, Math.round(Number(pick.max_hold_days) || 10)));
  return { ok: problems.length === 0, problems, plan: { entry, stop: round(stop), target: round(target), hold, bearish } };
}

// Size a stock trade. Returns shares (0 = skip) and the reason if skipped.
export function sizeStock({ equity, cash, entry, stop, mult, pennyExposure }, rules = DEFAULT_RULES) {
  const penny = entry < rules.penny_below;
  const fill = fillPrice(entry, 'buy', penny, rules);
  const riskUsd = equity * rules.risk_per_trade * mult;
  const perShare = fill - stop;
  if (!(riskUsd > 0) || !(perShare > 0)) return { shares: 0, why: 'no risk budget' };
  let shares = Math.floor(riskUsd / perShare);
  const capPct = penny ? rules.max_penny_position_pct : rules.max_position_pct;
  shares = Math.min(shares, Math.floor((equity * capPct) / fill), Math.floor((cash * 0.98) / fill));
  if (penny) shares = Math.min(shares, Math.floor(Math.max(0, equity * rules.max_penny_exposure - pennyExposure) / fill));
  if (shares < 1) return { shares: 0, why: penny ? 'penny exposure or cash limit reached' : 'position or cash limit reached' };
  return { shares, fill: round(fill), cost: round(shares * fill), risk_usd: round(shares * perShare), penny };
}

// Size a long option. Premium paid is the most it can lose.
export function sizeOption({ equity, cash, ask, mult, optionExposure }, rules = DEFAULT_RULES) {
  const per = ask * 100;
  if (!(per > 0)) return { contracts: 0, why: 'no ask price' };
  const budget = Math.min(
    equity * rules.max_option_premium_pct * mult,
    equity * rules.max_option_exposure - optionExposure,
    cash * 0.98,
  );
  const contracts = Math.floor(budget / per);
  if (contracts < 1) return { contracts: 0, why: 'one contract costs more than the per-trade or total options limit' };
  return { contracts, fill: ask, cost: round(contracts * per), risk_usd: round(contracts * per) };
}

// Choose a contract: 14–45 days out, nearest the money (slightly in the money preferred), tight spread.
// chain rows: { expiry:'YYYY-MM-DD', strike, type:'call'|'put', bid, ask, oi }
export function chooseContract(chain, { type, price, today }, rules = DEFAULT_RULES) {
  const dte = (d) => Math.round((Date.parse(d) - Date.parse(today)) / 86400000);
  const ok = chain.filter((c) => c.type === type && c.bid > 0 && c.ask > 0
    && dte(c.expiry) >= rules.option_min_dte && dte(c.expiry) <= rules.option_max_dte
    && (c.ask - c.bid) / ((c.ask + c.bid) / 2) <= rules.option_max_spread
    && (c.oi == null || c.oi >= 50));
  if (!ok.length) return null;
  const itm = (c) => (type === 'call' ? c.strike <= price : c.strike >= price);
  ok.sort((a, b) => {
    const da = Math.abs(a.strike - price) / price - (itm(a) ? 0.01 : 0);
    const dbb = Math.abs(b.strike - price) / price - (itm(b) ? 0.01 : 0);
    return da - dbb || dte(a.expiry) - dte(b.expiry);
  });
  return ok[0];
}

// ---------- fills + exits ----------
export function fillPrice(price, side, penny, rules = DEFAULT_RULES) {
  const slip = penny ? rules.slip_penny : rules.slip_stock;
  return side === 'buy' ? price * (1 + slip) : price * (1 - slip);
}

// Walk intraday bars since the last check. Stops are checked before targets inside the same bar
// (the conservative assumption). Gaps through a stop fill at the bar's open, not the stop.
// trade: { stop, target, bearish } on the underlying. bars oldest first.
export function checkExit(trade, bars) {
  let mfe = 0, mae = 0;
  for (const b of bars) {
    if (!trade.bearish) {
      mfe = Math.max(mfe, b.high - trade.ref); mae = Math.max(mae, trade.ref - b.low);
      if (b.low <= trade.stop) return { reason: 'stop', price: Math.min(trade.stop, b.open), t: b.t, mfe, mae };
      if (b.high >= trade.target) return { reason: 'target', price: Math.max(trade.target, b.open), t: b.t, mfe, mae };
    } else {
      mfe = Math.max(mfe, trade.ref - b.low); mae = Math.max(mae, b.high - trade.ref);
      if (b.high >= trade.stop) return { reason: 'stop', price: Math.max(trade.stop, b.open), t: b.t, mfe, mae };
      if (b.low <= trade.target) return { reason: 'target', price: Math.min(trade.target, b.open), t: b.t, mfe, mae };
    }
  }
  return { reason: null, mfe, mae };
}

// Trading days between two YYYY-MM-DD dates (weekdays; holidays ignored).
export function tradingDaysBetween(a, b) {
  let n = 0;
  const d = new Date(`${a}T12:00:00Z`), end = new Date(`${b}T12:00:00Z`);
  while (d < end) { d.setUTCDate(d.getUTCDate() + 1); const w = d.getUTCDay(); if (w !== 0 && w !== 6) n++; }
  return n;
}

// ---------- graduation scorecard (never automates anything; it only says whether the evidence is there) ----------
export function graduation({ days, closed, equityCurve, benchReturn, startCash }) {
  const pnl = closed.reduce((n, t) => n + Number(t.pnl), 0);
  const wins = closed.filter((t) => Number(t.pnl) > 0);
  const grossWin = wins.reduce((n, t) => n + Number(t.pnl), 0);
  const grossLoss = -closed.filter((t) => Number(t.pnl) < 0).reduce((n, t) => n + Number(t.pnl), 0);
  const pf = grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? Infinity : 0);
  const biggest = wins.reduce((m, t) => Math.max(m, Number(t.pnl)), 0);
  let peak = startCash, maxDd = 0;
  for (const e of equityCurve) { peak = Math.max(peak, e); maxDd = Math.max(maxDd, 1 - e / peak); }
  const ret = pnl / startCash;
  const checks = [
    ['90+ days of paper trading', days >= 90, `${days} days`],
    ['50+ closed trades', closed.length >= 50, `${closed.length} trades`],
    ['Beats just holding SPY', benchReturn != null && ret > benchReturn, `${pctStr(ret)} vs SPY ${benchReturn == null ? '—' : pctStr(benchReturn)}`],
    ['Profit factor 1.3+ (wins ÷ losses)', pf >= 1.3, Number.isFinite(pf) ? pf.toFixed(2) : '∞'],
    ['Worst drop under 25%', maxDd < 0.25, pctStr(-maxDd)],
    ['No single trade is 30%+ of profits', pnl <= 0 ? false : biggest / pnl < 0.3, pnl > 0 ? pctStr(biggest / pnl) : 'no profit yet'],
  ];
  return { ready: checks.every((c) => c[1]), checks: checks.map(([label, pass, value]) => ({ label, pass, value })), ret, pf, maxDd };
}

const pctStr = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}%`;
export function round(x, d = 4) { const f = 10 ** d; return Math.round(x * f) / f; }
