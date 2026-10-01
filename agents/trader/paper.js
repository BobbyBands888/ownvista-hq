// Paper Trader — weekdays, every hour 10am–4pm ET. PAPER MONEY ONLY: no brokerage, no real orders.
//  1. Marks open positions and closes them on stop / target / time limit (15-minute bars, delayed quotes).
//  2. At 10am, noon and 2pm it scans the market, tags chart setups in code, lets the AI pick
//     (or pass), then the code checks every pick against hard risk rules and sizes it.
//  3. Learns from mistakes: an AI post-mortem on every closed trade writes lessons it reads before
//     every pick; a numbers scoreboard benches setups that lose money and sizes up ones that work;
//     confidence only changes size once high-confidence trades have actually done better.
//  4. 4pm: equity snapshot vs SPY, drawdown brakes (half size at -10%, pause at -20%), Friday review.
import { db, kvGet, kvSet } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt } from '../lib/guard.js';
import { similarTitle, truncate } from '../lib/text.js';
import { et, etDate, addDays } from '../lib/time.js';
import * as M from './market.js';
import {
  DEFAULT_RULES, SETUPS, stats, setupsFor, shortlist, riskMode, scoreboard, setupMultiplier, newBenches,
  confidenceMultiplier, validatePick, sizeStock, sizeOption, chooseContract, fillPrice, checkExit,
  tradingDaysBetween, rMultiple, round, graduation,
} from './rules.js';

const PICK_HOURS = [10, 12, 14];
const MISTAKES = ['none', 'chased_extended_move', 'stop_too_tight', 'stop_too_loose', 'fought_the_trend', 'thin_liquidity',
  'held_too_long', 'exited_too_early', 'wrong_setup', 'bad_option_choice', 'news_or_gap', 'other'];

export async function run(ctx) {
  const rules = { ...DEFAULT_RULES, ...(await kvGet('pt_rules', {})) };
  const today = etDate();
  const now = et();
  const state = await loadState(rules, today);

  if (now.weekday === 0 || now.weekday === 6) return 'weekend, market closed';
  const spy = await M.chart('SPY', { range: '5d', interval: '15m' });
  const lastBar = spy.bars[spy.bars.length - 1];
  if (!lastBar || etDate(new Date(lastBar.t)) !== today) return 'market closed today (holiday)';
  if (now.hour < 10) return 'before the first check (10am)';

  const out = [];
  const closed = await manageOpen(ctx, rules, state, today);
  if (closed.length) out.push(`closed ${closed.map((t) => `${t.symbol} ${t.pnl >= 0 ? '+' : ''}$${Math.round(t.pnl)}`).join(', ')}`);

  const equity = await equityNow(state);
  const mode = riskMode(equity, state.peak, rules);
  if (now.hour < 16 && PICK_HOURS.includes(now.hour) && !ctx.outOfTime(150000)) {
    out.push(await maybeTrade(ctx, rules, state, equity, mode, today));
  }
  await saveState(state);

  await reviewClosed(ctx, 4);
  if (now.hour >= 16 || String(ctx.trigger || '').startsWith('manual')) {
    if ((await kvGet('pt_eod_day', null)) !== today || String(ctx.trigger || '').startsWith('manual')) {
      out.push(await endOfDay(ctx, rules, state, today, spy));
      await kvSet('pt_eod_day', today);
    }
  }
  return `equity $${Math.round(equity).toLocaleString()} (${mode.mode}) · ${out.filter(Boolean).join(' · ') || 'nothing to do'}`;
}

// ---------- state ----------
async function loadState(rules, today) {
  const s = await kvGet('pt_state', null);
  if (s && Number.isFinite(Number(s.cash))) {
    if (s.resume) { s.peak = await equityNow(s); s.paused_noted = false; delete s.resume; }
    return s;
  }
  const fresh = { cash: rules.start_cash, peak: rules.start_cash, started_on: today, start_cash: rules.start_cash };
  await kvSet('pt_state', fresh);
  return fresh;
}
const saveState = (s) => kvSet('pt_state', s);

async function openTrades() {
  return db.select('pt_trades', { status: 'eq.open', order: 'entry_at.asc' });
}

function positionValue(t) {
  const px = Number(t.mark_price ?? t.entry_price);
  return px * Number(t.qty) * (t.kind === 'stock' ? 1 : 100);
}

async function equityNow(state) {
  const open = await openTrades();
  return Number(state.cash) + open.reduce((n, t) => n + positionValue(t), 0);
}

// ---------- 1. manage open positions ----------
async function manageOpen(ctx, rules, state, today) {
  const closed = [];
  for (const t of await openTrades()) {
    if (ctx.outOfTime(90000)) break;
    try {
      const { bars } = await M.chart(t.symbol, { range: '5d', interval: '15m' });
      const since = Date.parse(t.marked_at || t.entry_at);
      const fresh = bars.filter((b) => b.t > since);
      if (!fresh.length) continue;
      const last = fresh[fresh.length - 1].close;
      const hit = checkExit({ stop: Number(t.stop), target: Number(t.target), bearish: t.bearish, ref: Number(t.entry_underlying) }, fresh);
      const patch = {
        marked_at: new Date(fresh[fresh.length - 1].t).toISOString(),
        mfe: round(Math.max(Number(t.mfe || 0), hit.mfe)), mae: round(Math.max(Number(t.mae || 0), hit.mae)),
      };
      let exit = hit.reason ? { reason: hit.reason, underlying: hit.price } : null;
      const held = tradingDaysBetween(t.entry_day, today);
      if (!exit && held >= t.hold_days) exit = { reason: 'time_limit', underlying: last };

      if (t.kind === 'stock') {
        const penny = Number(t.entry_price) < rules.penny_below;
        patch.mark_price = round(last);
        if (exit) Object.assign(patch, closePatch(t, fillPrice(exit.underlying, 'sell', penny, rules), exit));
      } else {
        const c = t.contract;
        const chain = await M.optionChain(t.symbol, { from: c.expiry, to: c.expiry }).catch((e) => { ctx.note(`${t.symbol} chain: ${e.message}`); return []; });
        const row = chain.find((x) => x.type === c.type && Math.abs(x.strike - c.strike) < 0.001 && x.expiry === c.expiry);
        const bid = row?.bid > 0 ? row.bid : null;
        if (bid != null) patch.mark_price = round(bid);
        const dte = Math.round((Date.parse(c.expiry) - Date.parse(today)) / 86400000);
        if (!exit && bid != null && bid <= Number(t.entry_price) * 0.5) exit = { reason: 'option_stop_-50%', underlying: last };
        if (!exit && bid != null && bid >= Number(t.entry_price) * 2) exit = { reason: 'option_target_+100%', underlying: last };
        if (!exit && dte <= rules.option_exit_dte) exit = { reason: 'expiry_window', underlying: last };
        if (exit) {
          const px = bid ?? (row?.last ? row.last * 0.9 : null);
          if (px == null) ctx.note(`${t.symbol} option should exit (${exit.reason}) but has no quote; retrying next hour`);
          else Object.assign(patch, closePatch(t, px, exit));
        }
      }
      await db.update('pt_trades', { id: `eq.${t.id}` }, patch);
      if (patch.status === 'closed') {
        state.cash = round(Number(state.cash) + patch.proceeds, 2);
        delete patch.proceeds;
        closed.push({ ...t, ...patch });
        ctx.log('trade', `Paper ${patch.pnl >= 0 ? 'win' : 'loss'}: ${t.symbol} ${t.kind} ${exit.reason}, ${patch.pnl >= 0 ? '+' : ''}$${Math.round(patch.pnl)} (${patch.r_multiple}R)`, { table: 'pt_trades', id: t.id });
      }
    } catch (e) {
      ctx.note(`${t.symbol}: ${truncate(e.message, 120)}`);
    }
  }
  return closed;
}

function closePatch(t, exitPx, exit) {
  const mult = t.kind === 'stock' ? 1 : 100;
  const proceeds = exitPx * Number(t.qty) * mult;
  const pnl = proceeds - Number(t.cost_usd);
  return {
    status: 'closed', exit_price: round(exitPx), exit_underlying: round(exit.underlying), exit_reason: exit.reason,
    exit_at: new Date().toISOString(), pnl: round(pnl, 2), r_multiple: round(rMultiple({ pnl, risk_usd: t.risk_usd }), 2),
    mark_price: round(exitPx), proceeds,
  };
}

// ---------- 2. find and open new trades ----------
async function maybeTrade(ctx, rules, state, equity, mode, today) {
  const picked = await kvGet('pt_picked', {});
  const slot = `${today}:${et().hour}`;
  if (picked.slot === slot && !String(ctx.trigger || '').startsWith('manual')) return null;
  await kvSet('pt_picked', { slot });

  if (mode.mode === 'paused') {
    if (!state.paused_noted) {
      state.paused_noted = true;
      await db.insertOne('tasks', {
        title: 'Paper Trader paused: down 20% from its peak',
        detail: 'Paper money only. Read its lessons on the Trader page, then press Resume there if you want it to keep going. Resuming resets the drop meter.',
        assignee: 'bobby', created_by: 'paper_trader',
      }).catch(() => {});
    }
    return 'paused by the 20% drawdown brake';
  }

  const open = await openTrades();
  const todayCount = await db.count('pt_trades', { entry_day: `eq.${today}`, status: 'in.(open,closed)' });
  const slots = Math.min(rules.max_open - open.length, rules.max_new_per_day - todayCount, 2);
  if (slots <= 0) return 'no free slots';

  let rows;
  try { rows = await M.universe(); } catch (e) { return `scan skipped (${truncate(e.message, 100)})`; }
  const held = new Set(open.map((t) => t.symbol));
  const cands = [];
  for (const r of shortlist(rows, rules)) {
    if (held.has(r.symbol) || ctx.outOfTime(120000)) continue;
    try {
      const { bars } = await M.chart(r.symbol, { range: '1y', interval: '1d' });
      const s = stats(bars, dayFraction());
      const setups = setupsFor(s);
      if (setups.length) cands.push({ symbol: r.symbol, name: r.name, sector: r.sector, setups, s });
    } catch { /* skip symbols with bad data */ }
  }
  if (!cands.length) return 'scanned, no clean setups';

  const closedAll = await db.select('pt_trades', { status: 'eq.closed', select: 'setup,kind,pnl,risk_usd,entry_price,confidence' });
  const board = scoreboard(closedAll);
  const bench = await kvGet('pt_bench', {});
  const [mine, learned] = await Promise.all([
    db.select('pt_lessons', { active: 'eq.true', origin: 'eq.bobby', order: 'created_at.desc' }),
    db.select('pt_lessons', { active: 'eq.true', origin: 'neq.bobby', order: 'hits.desc,created_at.desc', limit: 15 }),
  ]);
  const lessons = [...mine.map((l) => ({ ...l, lesson: `${l.lesson} (Bobby's rule)` })), ...learned];

  const system = systemPrompt('the Paper Trader', `You manage a PAPER (simulated) trading account. No real money; nothing you choose is ever sent to a broker.
Style: aggressive but not reckless. Take real swings when a setup is clean; pass when it is not. Passing is a valid answer.
Instruments: stock (long only), call, put. Puts only on 'breakdown' or fading a 'momentum_gap'.
Hard rules the code enforces anyway: reward:risk at least ${rules.min_reward_risk}, stop between 0.5 and 3 ATR from price, max hold ${rules.max_hold_days} trading days.
Set stop and target as UNDERLYING stock prices. Confidence 1–5 (only use 4–5 when the chart and the lessons both agree).
Setups: ${Object.entries(SETUPS).map(([k, v]) => `${k} = ${v}`).join('; ')}.
Benched setups (lost money, do not use): ${Object.keys(bench).filter((k) => bench[k] > today).join(', ') || 'none'}.
Risk mode: ${mode.mode}${mode.mode === 'half' ? ' (account is down 10%+ from its peak; be choosier)' : ''}.
Your lessons from past mistakes (follow them):
${lessons.map((l) => `- ${l.lesson}`).join('\n') || '- none yet'}
Your scoreboard (R = profit ÷ dollars risked):
${boardText(board)}
JSON only: {"picks":[{"symbol":"","setup":"","instrument":"stock|call|put","stop":0,"target":0,"max_hold_days":10,"confidence":3,"thesis":"one sentence"}],"pass_reason":""}
Return at most ${slots} pick(s).`);
  const user = `Open positions: ${open.map((t) => `${t.symbol} ${t.kind}`).join(', ') || 'none'}\nCandidates (delayed data):\n${cands.map(candText).join('\n')}`;
  const { json } = await chat({ ctx, tier: 'smart', system, json: true, maxTokens: 1200, temperature: 0.3, messages: [{ role: 'user', content: user }] });

  const made = [];
  const rejected = [];
  let pennyExp = open.filter((t) => t.kind === 'stock' && Number(t.entry_price) < rules.penny_below).reduce((n, t) => n + positionValue(t), 0);
  let optExp = open.filter((t) => t.kind !== 'stock').reduce((n, t) => n + positionValue(t), 0);
  for (const p of (json.picks || []).slice(0, slots)) {
    const c = cands.find((x) => x.symbol === String(p.symbol || '').toUpperCase());
    const base = { symbol: String(p.symbol || '?').toUpperCase().slice(0, 12), setup: String(p.setup || ''), kind: ['stock', 'call', 'put'].includes(p.instrument) ? p.instrument : 'stock', confidence: Number(p.confidence) || 3, thesis: truncate(p.thesis || '', 400), entry_day: today };
    if (!c) { rejected.push({ ...base, reject_reason: 'not in the candidate list' }); continue; }
    const v = validatePick(p, c.s, c.setups, rules);
    if (!v.ok) { rejected.push({ ...base, signals: c.s, reject_reason: v.problems.join('; ') }); continue; }
    const mult = mode.mult * setupMultiplier(p.setup, board, bench, today, rules) * confidenceMultiplier(p.confidence, board);
    if (mult <= 0) { rejected.push({ ...base, signals: c.s, reject_reason: `setup ${p.setup} is benched` }); continue; }
    const common = { ...base, signals: c.s, stop: v.plan.stop, target: v.plan.target, bearish: v.plan.bearish, hold_days: v.plan.hold, entry_underlying: round(c.s.price), entry_at: new Date().toISOString(), marked_at: new Date().toISOString(), status: 'open' };

    if (base.kind === 'stock') {
      const sz = sizeStock({ equity, cash: state.cash, entry: c.s.price, stop: v.plan.stop, mult, pennyExposure: pennyExp }, rules);
      if (!sz.shares) { rejected.push({ ...base, signals: c.s, reject_reason: sz.why }); continue; }
      const row = await db.insertOne('pt_trades', { ...common, qty: sz.shares, entry_price: sz.fill, mark_price: sz.fill, cost_usd: sz.cost, risk_usd: sz.risk_usd });
      state.cash = round(Number(state.cash) - sz.cost, 2);
      if (sz.penny) pennyExp += sz.cost;
      made.push(row);
    } else {
      const to = addDays(today, rules.option_max_dte + 3);
      const chain = await M.optionChain(c.symbol, { from: addDays(today, rules.option_min_dte), to }).catch(() => []);
      const k = chooseContract(chain, { type: base.kind, price: c.s.price, today }, rules);
      if (!k) { rejected.push({ ...base, signals: c.s, reject_reason: chain.length ? 'no liquid contract 14–45 days out' : 'option chain unavailable' }); continue; }
      const sz = sizeOption({ equity, cash: state.cash, ask: k.ask, mult, optionExposure: optExp }, rules);
      if (!sz.contracts) { rejected.push({ ...base, signals: c.s, reject_reason: sz.why }); continue; }
      const row = await db.insertOne('pt_trades', { ...common, contract: { expiry: k.expiry, strike: k.strike, type: k.type, bid: k.bid, ask: k.ask, oi: k.oi }, qty: sz.contracts, entry_price: k.ask, mark_price: k.bid, cost_usd: sz.cost, risk_usd: sz.risk_usd });
      state.cash = round(Number(state.cash) - sz.cost, 2);
      optExp += sz.cost;
      made.push(row);
    }
  }
  if (rejected.length) await db.insert('pt_trades', rejected.map((r) => ({ ...r, signals: r.signals ?? null, status: 'rejected' }))).catch((e) => ctx.note(`log rejects: ${e.message}`));
  for (const t of made) {
    ctx.log('trade', `Paper buy: ${t.qty} ${t.symbol} ${t.kind === 'stock' ? 'shares' : `${t.contract.strike} ${t.kind}s exp ${t.contract.expiry}`} @ $${t.entry_price} (${t.setup}, stop ${t.stop}, target ${t.target})`, { table: 'pt_trades', id: t.id });
  }
  const passed = !made.length && json.pass_reason ? `passed: ${truncate(json.pass_reason, 120)}` : '';
  return [made.length && `opened ${made.map((t) => `${t.symbol} ${t.kind}`).join(', ')}`, rejected.length && `${rejected.length} pick(s) failed the risk rules`, passed].filter(Boolean).join(', ') || `scanned ${cands.length} setups, no trade`;
}

// Share of the trading session gone (9:30–4:00 ET), so today's partial volume is compared fairly.
function dayFraction(n = et()) {
  const mins = (n.hour * 60 + n.minute) - (9 * 60 + 30);
  return Math.max(0.25, Math.min(1, mins / 390));
}

function candText(c) {
  const s = c.s;
  const f = (x, d = 2) => (x == null ? '—' : Number(x).toFixed(d));
  return `${c.symbol} (${truncate(c.name, 40)}, ${c.sector || '—'}) setups=${c.setups.join('/')} price=${f(s.price)} chg=${f(s.change_pct, 1)}% sma20=${f(s.sma20)} sma50=${f(s.sma50)} rsi=${f(s.rsi14, 0)} atr=${f(s.atr14)} 20d high/low=${f(s.high20)}/${f(s.low20)} rvol=${f(s.rvol, 1)} $vol=${Math.round((s.dollar_volume || 0) / 1e6)}M`;
}

function boardText(board) {
  const line = (k, g) => `${k}: ${g.n} trades, win ${Math.round(g.win_rate * 100)}%, avg ${g.avg_r.toFixed(2)}R`;
  const parts = [...Object.entries(board.setup).map(([k, g]) => line(k, g)), ...Object.entries(board.instrument).map(([k, g]) => line(k, g))];
  return parts.length ? parts.join('\n') : 'no closed trades yet';
}

// ---------- 3. learn from every closed trade ----------
async function reviewClosed(ctx, limit) {
  const rows = await db.select('pt_trades', { status: 'eq.closed', reviewed_at: 'is.null', order: 'exit_at.asc', limit });
  let n = 0;
  for (const t of rows) {
    if (ctx.outOfTime(60000)) break;
    const risk = Math.abs(Number(t.entry_underlying) - Number(t.stop)) || 1;
    const system = systemPrompt('the Paper Trader reviewing its own trade', `Judge the PROCESS, not just the result. A loss that followed the plan is a good loss; a win that broke the rules is a bad win.
Use MFE (best move in its favor) and MAE (worst move against it), both in R, to spot stops that were too tight or exits too early.
Mistake must be one of: ${MISTAKES.join(', ')}.
Lesson: one short imperative rule (max 25 words) the trader should follow next time, specific and testable, or "" if there is nothing to learn.
JSON only: {"process":"good|bad","mistake":"none","lesson":"","note":"max 30 words"}`);
    const facts = {
      symbol: t.symbol, setup: t.setup, instrument: t.kind, contract: t.contract, thesis: t.thesis, confidence: t.confidence,
      entry_underlying: t.entry_underlying, stop: t.stop, target: t.target, exit_reason: t.exit_reason, exit_underlying: t.exit_underlying,
      pnl: t.pnl, r: t.r_multiple, held_trading_days: tradingDaysBetween(t.entry_day, etDate(new Date(t.exit_at))), planned_days: t.hold_days,
      mfe_r: round(Number(t.mfe || 0) / risk, 2), mae_r: round(Number(t.mae || 0) / risk, 2), entry_signals: t.signals,
    };
    try {
      const { json } = await chat({ ctx, tier: 'fast', system, json: true, maxTokens: 400, temperature: 0.2, messages: [{ role: 'user', content: JSON.stringify(facts) }] });
      const mistake = MISTAKES.includes(json.mistake) ? json.mistake : 'other';
      await db.update('pt_trades', { id: `eq.${t.id}` }, { review: { process: json.process === 'bad' ? 'bad' : 'good', mistake, note: truncate(json.note || '', 240) }, reviewed_at: new Date().toISOString() });
      const lesson = truncate(String(json.lesson || '').trim(), 200);
      if (lesson && mistake !== 'none') {
        const existing = await db.select('pt_lessons', { active: 'eq.true', select: 'id,lesson,hits' });
        const dup = existing.find((e) => similarTitle(e.lesson, lesson));
        if (dup) await db.update('pt_lessons', { id: `eq.${dup.id}` }, { hits: (dup.hits || 1) + 1 });
        else await db.insertOne('pt_lessons', { lesson, setup: t.setup, mistake, evidence: `${t.symbol} ${t.kind} ${t.exit_reason} ${t.r_multiple}R`, origin: 'postmortem' });
      }
      n++;
    } catch (e) {
      ctx.note(`review ${t.symbol}: ${truncate(e.message, 100)}`);
      break;
    }
  }
  return n;
}

// ---------- 4. end of day ----------
async function endOfDay(ctx, rules, state, today, spy) {
  const open = await openTrades();
  const positions = open.reduce((n, t) => n + positionValue(t), 0);
  const equity = Number(state.cash) + positions;
  state.peak = Math.max(Number(state.peak) || equity, equity);
  const mode = riskMode(equity, state.peak, rules);

  let spyClose = spy.bars[spy.bars.length - 1]?.close ?? null;
  const first = await db.one('pt_equity', { order: 'day.asc' });
  const benchEquity = first?.spy_close && spyClose ? round((Number(state.start_cash) * spyClose) / Number(first.spy_close), 2) : Number(state.start_cash);
  await db.insert('pt_equity', [{
    day: today, equity: round(equity, 2), cash: round(Number(state.cash), 2), positions_value: round(positions, 2),
    open_count: open.length, spy_close: spyClose, bench_equity: benchEquity, drawdown: round(mode.dd, 4),
  }], { onConflict: 'day', merge: true });

  // Bench setups that have proven to lose (numbers, not opinions).
  const closedAll = await db.select('pt_trades', { status: 'eq.closed', select: 'setup,kind,pnl,risk_usd,entry_price,confidence' });
  const board = scoreboard(closedAll);
  const bench = await kvGet('pt_bench', {});
  const fresh = newBenches(board, bench, today, rules);
  for (const [setup, g] of Object.entries(fresh)) {
    bench[setup] = addDays(today, rules.bench_days);
    ctx.log('learned', `Paper Trader benched "${setup}" for ${rules.bench_days} days: ${g.n} trades averaging ${g.avg_r.toFixed(2)}R`);
  }
  if (Object.keys(fresh).length) await kvSet('pt_bench', bench);
  await saveState(state);

  // Graduation scorecard for the dashboard. It only reports evidence; it never turns on real trading.
  const curve = await db.select('pt_equity', { select: 'equity', order: 'day.asc' });
  const closedPnl = await db.select('pt_trades', { status: 'eq.closed', select: 'pnl' });
  const days = Math.round((Date.parse(today) - Date.parse(state.started_on)) / 86400000);
  const g = graduation({ days, closed: closedPnl, equityCurve: curve.map((r) => Number(r.equity)), benchReturn: benchEquity / Number(state.start_cash) - 1, startCash: Number(state.start_cash) });
  await kvSet('pt_scorecard', { ...g, pf: Number.isFinite(g.pf) ? g.pf : null, day: today });

  // Friday: consolidate lessons and write the weekly note.
  let weekly = '';
  if (et().weekday === 5 && !ctx.outOfTime(90000)) weekly = await weeklyReview(ctx, board);
  return `day closed: equity $${Math.round(equity).toLocaleString()} vs SPY $${Math.round(benchEquity).toLocaleString()}${weekly}`;
}

async function weeklyReview(ctx, board) {
  const lessons = await db.select('pt_lessons', { active: 'eq.true', origin: 'neq.bobby', order: 'created_at.asc' });
  const week = await db.select('pt_trades', { status: 'eq.closed', exit_at: `gte.${new Date(Date.now() - 7 * 86400000).toISOString()}`, select: 'symbol,kind,setup,pnl,r_multiple,exit_reason,review' });
  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 1500, temperature: 0.2,
    system: systemPrompt('the Paper Trader writing its weekly review', `Merge duplicate or overlapping lessons into at most 15 clear rules; drop lessons the scoreboard proves wrong.
Then write a weekly note for Bobby (max 120 words, plain English): result, biggest mistake, what changes next week. Paper money only; never suggest real trades.
JSON only: {"lessons":[""],"note":""}`),
    messages: [{ role: 'user', content: `Lessons:\n${lessons.map((l) => `- (${l.hits || 1}x) ${l.lesson}`).join('\n') || 'none'}\n\nScoreboard:\n${boardText(board)}\n\nThis week's trades:\n${JSON.stringify(week)}` }],
  });
  const merged = (json.lessons || []).map((l) => truncate(String(l).trim(), 200)).filter(Boolean).slice(0, 15);
  if (lessons.length > 15 && merged.length >= 5) {
    await db.update('pt_lessons', { id: `in.(${lessons.map((l) => l.id).join(',')})` }, { active: false });
    await db.insert('pt_lessons', merged.map((lesson) => ({ lesson, origin: 'weekly' })));
  }
  if (json.note) {
    await kvSet('pt_weekly_note', { day: etDate(), text: truncate(json.note, 1200) });
    ctx.log('report', `Paper Trader weekly: ${truncate(json.note, 600)}`);
  }
  return ', weekly review written';
}

// Manual: check that every free data source answers (used once after setup).
export async function probe(ctx) {
  const out = [];
  try { const u = await M.universe(); out.push(`screener ok (${u.length} stocks)`); } catch (e) { out.push(`screener FAILED: ${e.message}`); }
  try { const c = await M.chart('AAPL', { range: '1y', interval: '1d' }); const s = stats(c.bars); out.push(`daily chart ok (${c.bars.length} bars, AAPL ${s?.price?.toFixed(2)}, setups: ${setupsFor(s).join(',') || 'none'})`); } catch (e) { out.push(`daily chart FAILED: ${e.message}`); }
  try { const c = await M.chart('SPY', { range: '5d', interval: '15m' }); out.push(`15m chart ok (${c.bars.length} bars)`); } catch (e) { out.push(`15m chart FAILED: ${e.message}`); }
  try {
    const d = etDate();
    const ch = await M.optionChain('AAPL', { from: addDays(d, 14), to: addDays(d, 48) });
    const k = chooseContract(ch, { type: 'call', price: 200, today: d });
    out.push(`option chain ok (${ch.length} quotes${ch[0] ? `, e.g. ${ch[0].expiry} ${ch[0].strike} ${ch[0].type} ${ch[0].bid}/${ch[0].ask}` : ''}${k ? '' : ', no contract passed filters at $200 ref'})`);
  } catch (e) { out.push(`option chain FAILED: ${e.message}`); }
  const msg = out.join(' · ');
  ctx.log('report', `Paper Trader data check: ${msg}`);
  console.log(msg);
  return msg;
}
