// Paper Trader backtest. Pure functions, no network, no AI.
// Replays daily bars and trades the code-defined setups with fixed rules, so we can compare rule sets
// on years of history instead of waiting months for live paper trades.
// Honest limits (shown on the dashboard):
//  - The live trader lets the AI choose among candidates; here a fixed ranking (3-month strength) chooses.
//  - Universe = today's biggest US stocks, so past losers that shrank or delisted are missing (flatters results).
//  - Long stocks only: no options, no puts, no penny stocks.
import { stats, setupsFor, sma, round } from './rules.js';

export const CONFIGS = {
  current: {
    label: 'Current rules',
    setups: ['breakout', 'pullback', 'momentum_gap', 'oversold_bounce'],
    risk: 0.02, max_open: 8, max_new_per_day: 3, max_position_pct: 0.20,
    stop_atr: 1.5, target_atr: 3, trail_atr: null, max_hold: 10,
    regime: false, uptrend_only: false, min_price: 1,
  },
  proposed: {
    label: 'Aggressive, not reckless',
    setups: ['breakout', 'pullback', 'oversold_bounce'],
    risk: 0.0125, max_open: 8, max_new_per_day: 3, max_position_pct: 0.20,
    stop_atr: 2, target_atr: null, trail_atr: 3, max_hold: 40,
    regime: true, uptrend_only: true, min_price: 10,
  },
};

const SLIP = 0.0005;
const MIN_DOLLAR_VOLUME = 5e6;
const PAUSE_DAYS = 20; // live trader waits for Bobby; the backtest resumes after 20 trading days

export const dayKey = (t) => new Date(t).toISOString().slice(0, 10);

// series: { SYM: bars[] } (daily, oldest first), spy: bars[]. Returns aligned data used by simulate().
export function prepare(series, spy) {
  const days = spy.map((b) => dayKey(b.t));
  const spyClose = spy.map((b) => b.close);
  const spyAdj = spy.map((b) => b.adj ?? b.close);
  const spySma200 = spyClose.map((_, i) => (i >= 199 ? sma(spyClose.slice(i - 199, i + 1), 200) : null));
  const syms = {};
  for (const [sym, bars] of Object.entries(series)) {
    if (!bars || bars.length < 260) continue;
    const byDay = new Map(bars.map((b, i) => [dayKey(b.t), i]));
    const idx = days.map((d) => (byDay.has(d) ? byDay.get(d) : -1));
    const closes = bars.map((b) => b.close);
    const sma200 = closes.map((_, i) => (i >= 199 ? sma(closes.slice(i - 199, i + 1), 200) : null));
    syms[sym] = { bars, idx, sma200, st: new Array(bars.length) };
  }
  return { days, spyClose, spyAdj, spySma200, syms };
}

// Simulate one rule set from calendar index `from` to `to` (inclusive), starting with `cash`.
export function simulate(data, cfg, { from, to, cash: startCash = 10000 }) {
  let cash = startCash;
  let peak = startCash;
  let pausedUntil = -1;
  let pauses = 0;
  const open = [];
  const closed = [];
  const curve = [];
  let pending = [];

  const barAt = (sym, d) => {
    const s = data.syms[sym];
    const j = s?.idx[d];
    return j >= 0 ? { bar: s.bars[j], j } : null;
  };
  const equityAt = (d) => cash + open.reduce((n, p) => {
    const b = barAt(p.sym, d);
    return n + p.qty * (b ? b.bar.close : p.last);
  }, 0);

  const exit = (p, price, reason, d) => {
    const fill = price * (1 - SLIP);
    const pnl = (fill - p.entry) * p.qty;
    cash += fill * p.qty;
    closed.push({ sym: p.sym, setup: p.setup, pnl, r: pnl / p.risk_usd, reason, days: d - p.d0, entry_day: data.days[p.d0], exit_day: data.days[d] });
  };

  for (let d = from; d <= to; d++) {
    // 1. Fill yesterday's signals at today's open (no peeking at today's close).
    for (const sig of pending) {
      if (open.length >= cfg.max_open) break;
      const b = barAt(sig.sym, d);
      if (!b) continue;
      if (b.bar.open > sig.close + sig.atr) continue; // gapped up more than a normal day: don't chase
      const entry = b.bar.open * (1 + SLIP);
      const stop = entry - cfg.stop_atr * sig.atr;
      if (stop <= 0) continue;
      const equity = equityAt(d - 1);
      const riskUsd = equity * cfg.risk * sig.mult;
      let qty = Math.floor(riskUsd / (entry - stop));
      qty = Math.min(qty, Math.floor((equity * cfg.max_position_pct) / entry), Math.floor((cash * 0.98) / entry));
      if (qty < 1) continue;
      cash -= qty * entry;
      open.push({
        sym: sig.sym, setup: sig.setup, qty, entry, stop, atr: sig.atr, d0: d, high: entry, last: entry,
        target: cfg.target_atr ? entry + cfg.target_atr * sig.atr : null, risk_usd: qty * (entry - stop),
      });
    }
    pending = [];

    // 2. Manage open positions on today's bar. Stop is checked before target (conservative).
    for (let k = open.length - 1; k >= 0; k--) {
      const p = open[k];
      const b = barAt(p.sym, d);
      if (!b) continue;
      const { open: o, high, low, close } = b.bar;
      let done = null;
      if (o <= p.stop) done = [o, 'stop'];
      else if (low <= p.stop) done = [p.stop, 'stop'];
      else if (p.target && high >= p.target) done = [Math.max(p.target, o), 'target'];
      else if (d - p.d0 + 1 >= cfg.max_hold) done = [close, 'time_limit'];
      if (done) { exit(p, done[0], done[1], d); open.splice(k, 1); continue; }
      p.last = close;
      p.high = Math.max(p.high, high);
      if (cfg.trail_atr) p.stop = Math.max(p.stop, p.high - cfg.trail_atr * p.atr);
    }

    // 3. Mark to market, drawdown brakes.
    const equity = equityAt(d);
    curve.push(equity);
    peak = Math.max(peak, equity);
    const dd = 1 - equity / peak;
    let mult = dd >= 0.10 ? 0.5 : 1;
    if (dd >= 0.20 && d > pausedUntil) { pausedUntil = d + PAUSE_DAYS; pauses++; }
    if (d <= pausedUntil) mult = 0;
    if (d === pausedUntil) peak = equity; // resume resets the drop meter, like the live Resume button

    // 4. Scan at the close for tomorrow's entries.
    if (mult === 0 || d === to) continue;
    if (cfg.regime && !(data.spySma200[d] && data.spyClose[d] > data.spySma200[d])) continue;
    const slots = Math.min(cfg.max_new_per_day, cfg.max_open - open.length);
    if (slots <= 0) continue;
    const held = new Set(open.map((p) => p.sym));
    const cands = [];
    for (const [sym, s] of Object.entries(data.syms)) {
      if (held.has(sym)) continue;
      const j = s.idx[d];
      if (j < 0 || j < 120) continue;
      if (s.st[j] === undefined) s.st[j] = stats(s.bars.slice(Math.max(0, j - 259), j + 1)) || null;
      const st = s.st[j];
      if (!st || !st.atr14 || st.price < cfg.min_price || st.dollar_volume < MIN_DOLLAR_VOLUME) continue;
      if (cfg.uptrend_only && !(s.sma200[j] && st.price > s.sma200[j])) continue;
      const setup = setupsFor(st).find((x) => cfg.setups.includes(x));
      if (!setup) continue;
      const strength = j >= 63 ? st.price / s.bars[j - 63].close - 1 : 0;
      cands.push({ sym, setup, close: st.price, atr: st.atr14, strength, mult });
    }
    cands.sort((a, b) => b.strength - a.strength);
    pending = cands.slice(0, slots);
  }

  // Close anything still open at the last close so every trade counts.
  for (const p of open) {
    const b = barAt(p.sym, to);
    exit(p, b ? b.bar.close : p.last, 'end_of_test', to);
  }
  open.length = 0;
  if (curve.length) curve[curve.length - 1] = cash;
  return summarize({ closed, curve, startCash, pauses, spyFrom: data.spyAdj[from], spyTo: data.spyAdj[to], from: data.days[from], to: data.days[to] });
}

function group(trades) {
  const wins = trades.filter((t) => t.pnl > 0);
  const gw = wins.reduce((n, t) => n + t.pnl, 0);
  const gl = -trades.filter((t) => t.pnl < 0).reduce((n, t) => n + t.pnl, 0);
  return {
    n: trades.length,
    win_rate: trades.length ? round(wins.length / trades.length, 3) : 0,
    avg_r: trades.length ? round(trades.reduce((n, t) => n + t.r, 0) / trades.length, 2) : 0,
    pf: gl > 0 ? round(gw / gl, 2) : (gw > 0 ? null : 0), // null = no losses
    pnl: round(trades.reduce((n, t) => n + t.pnl, 0), 2),
    avg_days: trades.length ? round(trades.reduce((n, t) => n + t.days, 0) / trades.length, 1) : 0,
  };
}

export function summarize({ closed, curve, startCash, pauses, spyFrom, spyTo, from, to }) {
  let peak = startCash, maxDd = 0;
  for (const e of curve) { peak = Math.max(peak, e); maxDd = Math.max(maxDd, 1 - e / peak); }
  const end = curve.length ? curve[curve.length - 1] : startCash;
  const years = Math.max(curve.length / 252, 1 / 252);
  const ret = end / startCash - 1;
  const spyRet = spyFrom && spyTo ? spyTo / spyFrom - 1 : null;
  const bySetup = {};
  for (const s of [...new Set(closed.map((t) => t.setup))]) bySetup[s] = group(closed.filter((t) => t.setup === s));
  return {
    from, to, days: curve.length,
    end_equity: round(end, 2), ret: round(ret, 4), cagr: round((1 + ret) ** (1 / years) - 1, 4),
    spy_ret: spyRet == null ? null : round(spyRet, 4),
    max_dd: round(maxDd, 4), pauses,
    all: group(closed), by_setup: bySetup,
  };
}

// Split the history: the older years pick the winner, the last ~12 months confirm it on data it never saw.
export function windows(data, recentDays = 252, warmup = 200) {
  const last = data.days.length - 1;
  const recentFrom = Math.max(warmup, last - recentDays + 1);
  return {
    older: { from: warmup, to: recentFrom - 1 },
    recent: { from: recentFrom, to: last },
  };
}

// Plain-English verdict. It only reports; it never changes the live rules.
export function verdict(res) {
  const score = (r) => r.ret - 0.5 * r.max_dd; // return, penalized for deep drops
  const o = res.older, r = res.recent;
  const pOld = score(o.proposed) > score(o.current);
  const pNew = score(r.proposed) >= score(r.current);
  const beatsSpy = (x) => x.spy_ret != null && x.ret > x.spy_ret;
  let winner = 'mixed';
  if (pOld && pNew) winner = 'proposed';
  else if (!pOld && !pNew) winner = 'current';
  const lines = [];
  if (winner === 'proposed') lines.push('The new rules beat the current ones on the older years AND held up on the last 12 months they never saw.');
  else if (winner === 'current') lines.push('The current rules beat the new ones in both periods. Keep them and look at the per-setup numbers instead.');
  else lines.push('Mixed: the winner on the older years did not hold up on the last 12 months. Not strong enough evidence to switch.');
  for (const k of ['current', 'proposed']) {
    lines.push(`${CONFIGS[k].label}: last 12 months ${beatsSpy(r[k]) ? 'beat' : 'did not beat'} just holding SPY.`);
  }
  const losers = Object.entries(o[winner === 'current' ? 'current' : 'proposed'].by_setup)
    .filter(([, g]) => g.n >= 20 && g.avg_r < 0).map(([s]) => s);
  if (losers.length) lines.push(`Setups that lost money over the older years: ${losers.join(', ')}.`);
  return { winner, text: lines.join(' ') };
}

export function runAll(data, configs = CONFIGS) {
  const w = windows(data);
  const out = { older: {}, recent: {} };
  for (const [name, win] of Object.entries(w)) {
    for (const [k, cfg] of Object.entries(configs)) out[name][k] = simulate(data, cfg, win);
  }
  return { ...out, verdict: verdict(out) };
}
