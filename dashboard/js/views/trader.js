// Trader: the Paper Trader's account. PAPER MONEY ONLY: nothing here places a real order.
import { sb, q, esc, ago, when, money, badge, on, act, kvGet, kvSet, spark } from '../core.js';

const pnlTone = (n) => (Number(n) > 0 ? 'ok' : Number(n) < 0 ? 'bad' : '');
const signed = (n) => `${Number(n) >= 0 ? '+' : '−'}${money(Math.abs(Number(n)))}`;
const pctS = (x) => (x == null ? '—' : `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}%`);

function what(t) {
  if (t.kind === 'stock') return `${Number(t.qty).toLocaleString()} sh`;
  const c = t.contract || {};
  return `${t.qty}× ${c.strike} ${t.kind} ${c.expiry || ''}`;
}

export async function render(el) {
  let open = [], closed = [], rejected = [], lessons = [], curve = [], agent = null;
  try {
    [open, closed, rejected, lessons, curve, agent] = await Promise.all([
      q(sb.from('pt_trades').select('*').eq('status', 'open').order('entry_at', { ascending: false })),
      q(sb.from('pt_trades').select('*').eq('status', 'closed').order('exit_at', { ascending: false }).limit(40)),
      q(sb.from('pt_trades').select('symbol,kind,setup,reject_reason,created_at').eq('status', 'rejected').order('created_at', { ascending: false }).limit(15)),
      q(sb.from('pt_lessons').select('*').eq('active', true).order('created_at', { ascending: false })),
      q(sb.from('pt_equity').select('*').order('day', { ascending: true })),
      q(sb.from('agents').select('id,enabled,last_summary,last_run_at').eq('id', 'paper_trader').maybeSingle()),
    ]);
  } catch {
    el.innerHTML = `<div class="head"><h1>Trader</h1></div><div class="card"><h2>One database update needed</h2>
      <p class="muted small">Run the Paper Trader SQL block in Supabase once. Claude has it ready for you.</p></div>`;
    return;
  }
  const [state, card, weekly, bench, bt] = await Promise.all([kvGet('pt_state', null), kvGet('pt_scorecard', null), kvGet('pt_weekly_note', null), kvGet('pt_bench', {}), kvGet('pt_backtest', null)]);
  const start = Number(state?.start_cash || 10000);
  const posValue = open.reduce((n, t) => n + Number(t.mark_price ?? t.entry_price) * Number(t.qty) * (t.kind === 'stock' ? 1 : 100), 0);
  const equity = state ? Number(state.cash) + posValue : start;
  const lastEq = curve[curve.length - 1];
  const benchRet = lastEq?.bench_equity ? Number(lastEq.bench_equity) / start - 1 : null;
  const peak = Math.max(Number(state?.peak || start), equity);
  const dd = 1 - equity / peak;
  const mode = dd >= 0.2 ? 'paused' : dd >= 0.1 ? 'half size' : 'normal';
  const allClosed = await q(sb.from('pt_trades').select('pnl').eq('status', 'closed'));
  const wins = allClosed.filter((t) => Number(t.pnl) > 0).length;
  const benched = Object.entries(bench || {}).filter(([, until]) => until > new Date().toISOString().slice(0, 10));

  el.innerHTML = `
  <div class="head"><h1>Trader</h1><div class="small muted">Paper money only · no real orders, ever · weekdays 10am–4pm ET</div></div>
  <div class="st-hud">
    <div class="st-chip"><span>Paper equity</span><strong class="num">${money(equity)}</strong></div>
    <div class="st-chip"><span>Return</span><strong class="num">${pctS(equity / start - 1)}</strong></div>
    <div class="st-chip"><span>Just holding SPY</span><strong class="num">${pctS(benchRet)}</strong></div>
    <div class="st-chip"><span>Closed trades</span><strong class="num">${allClosed.length}${allClosed.length ? ` · ${Math.round((wins / allClosed.length) * 100)}% wins` : ''}</strong></div>
    <div class="st-chip ${mode !== 'normal' ? 'alert' : ''}"><span>Risk mode</span><strong>${mode}${dd > 0.001 ? ` (${pctS(-dd)})` : ''}</strong></div>
  </div>
  <div class="row between">
    <div class="small muted">${agent?.last_summary ? `Last run ${ago(agent.last_run_at)}: ${esc(agent.last_summary)}` : 'Starts on the next weekday market hour.'}</div>
    <span class="row">${agent ? `<label class="small" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="pt-on" ${agent.enabled ? 'checked' : ''}> Trader on</label>` : ''}
    ${mode === 'paused' ? '<button class="ok" data-act="resume">Resume (resets the drop meter)</button>' : ''}</span>
  </div>

  ${curve.length >= 2 ? `<div class="section"><h2>Equity vs SPY</h2><div class="card">${spark(curve.map((r) => r.equity))}
    <div class="small muted">Paper account, ${curve.length} trading days. SPY line: ${money(lastEq.bench_equity)} if the same ${money(start)} had just bought SPY.</div></div></div>` : ''}

  <div class="section"><h2>Ready for real money?</h2><div class="card stack">
    ${card ? `<div>${badge(card.ready ? 'evidence is there' : 'not yet', card.ready ? 'ok' : 'warn')}</div>
      <table class="table"><tbody>${card.checks.map((c) => `<tr><td>${c.pass ? '✅' : '⬜'}</td><td>${esc(c.label)}</td><td class="num">${esc(c.value)}</td></tr>`).join('')}</tbody></table>` : '<div class="small muted">Scorecard appears after the first 4pm close.</div>'}
    <div class="small muted">Even when every box is checked, the trader only suggests. You place any real trade yourself, small, and we keep tracking real against paper.</div>
  </div></div>

  ${backtestSection(bt)}

  <div class="section"><h2>Open positions (${open.length})</h2>
    ${open.length ? `<div class="card"><table class="table"><thead><tr><th>Symbol</th><th>Position</th><th>Setup</th><th>Entry</th><th>Now</th><th>P&amp;L</th><th>Stop / target</th></tr></thead><tbody>
      ${open.map((t) => { const m = t.kind === 'stock' ? 1 : 100; const u = (Number(t.mark_price ?? t.entry_price) - Number(t.entry_price)) * Number(t.qty) * m; return `<tr title="${esc(t.thesis || '')}">
        <td><strong>${esc(t.symbol)}</strong></td><td class="num">${esc(what(t))}</td><td>${esc(t.setup || '')}</td>
        <td class="num">${money(t.entry_price)}</td><td class="num">${money(t.mark_price ?? t.entry_price)}</td>
        <td>${badge(signed(u), pnlTone(u))}</td><td class="num small">${money(t.stop)} / ${money(t.target)}${t.kind !== 'stock' ? ' (stock price)' : ''}</td></tr>`; }).join('')}
    </tbody></table></div>` : '<div class="card empty">No open positions.</div>'}
  </div>

  <div class="section"><h2>Lessons it follows (${lessons.length})</h2>
    ${weekly?.text ? `<div class="card small"><strong>Weekly note (${esc(weekly.day)}):</strong> ${esc(weekly.text)}</div>` : ''}
    ${benched.length ? `<div class="small muted" style="margin:6px 0">Benched for losing money: ${benched.map(([s, u]) => `${esc(s)} until ${esc(u)}`).join(', ')}</div>` : ''}
    <div class="list" style="margin-top:8px">${lessons.map((l) => `<div class="card row between" data-lesson="${l.id}">
      <div><div>${esc(l.lesson)}</div><div class="small muted">${esc(l.origin)}${l.hits > 1 ? ` · learned ${l.hits}x` : ''}${l.evidence ? ` · ${esc(l.evidence)}` : ''}</div></div>
      <button data-act="drop">Drop</button></div>`).join('') || '<div class="card empty">No lessons yet. One is written after every losing or sloppy trade.</div>'}
    </div>
    <form id="pt-lesson" class="row" style="margin-top:8px"><input name="lesson" placeholder="Add your own rule, e.g. No penny stocks in the first 30 minutes" style="flex:1"><button class="primary" type="submit">Add rule</button></form>
  </div>

  <div class="section"><h2>Closed trades</h2>
    ${closed.length ? `<div class="card"><table class="table"><thead><tr><th>Closed</th><th>Symbol</th><th>Setup</th><th>Why it closed</th><th>P&amp;L</th><th>Review</th></tr></thead><tbody>
      ${closed.map((t) => `<tr><td class="small">${when(t.exit_at)}</td><td><strong>${esc(t.symbol)}</strong> <span class="small muted">${esc(t.kind)}</span></td><td>${esc(t.setup || '')}</td><td class="small">${esc(t.exit_reason || '')}</td>
        <td>${badge(`${signed(t.pnl)} · ${Number(t.r_multiple).toFixed(1)}R`, pnlTone(t.pnl))}</td>
        <td class="small">${t.review ? `${badge(`${t.review.process} process`, t.review.process === 'good' ? 'ok' : 'warn')} ${t.review.mistake !== 'none' ? esc(t.review.mistake.replace(/_/g, ' ')) : ''}<div class="muted">${esc(t.review.note || '')}</div>` : '<span class="muted">reviewing…</span>'}</td></tr>`).join('')}
    </tbody></table></div>` : '<div class="card empty">No closed trades yet.</div>'}
  </div>

  ${rejected.length ? `<div class="section"><details><summary>Picks the risk rules blocked (${rejected.length} recent)</summary>
    <div class="card small">${rejected.map((r) => `<div><strong>${esc(r.symbol)}</strong> ${esc(r.kind)} ${esc(r.setup || '')}: ${esc(r.reject_reason || '')} <span class="muted">${ago(r.created_at)}</span></div>`).join('')}</div></details></div>` : ''}`;

  el.querySelector('#pt-on')?.addEventListener('change', (e) => act(null, async () => {
    await q(sb.from('agents').update({ enabled: e.target.checked }).eq('id', 'paper_trader'));
  }, e.target.checked ? 'Trader on' : 'Trader paused'));

  el.querySelector('#pt-lesson').addEventListener('submit', (e) => {
    e.preventDefault();
    const text = e.target.lesson.value.trim();
    if (!text) return;
    act(e.submitter, async () => {
      await q(sb.from('pt_lessons').insert({ lesson: text.slice(0, 200), origin: 'bobby' }));
      window.hqRefresh();
    }, 'Rule added');
  });

  on(el, 'click', '[data-act]', (e, btn) => {
    if (btn.dataset.act === 'resume') {
      act(btn, async () => { await kvSet('pt_state', { ...(await kvGet('pt_state', {})), resume: true }); window.hqRefresh(); }, 'Resumes on the next market hour');
    } else if (btn.dataset.act === 'drop') {
      const id = btn.closest('[data-lesson]')?.dataset.lesson;
      act(btn, async () => { await q(sb.from('pt_lessons').update({ active: false }).eq('id', id)); window.hqRefresh(); }, 'Dropped');
    }
  });
}

// Backtest: the same setups replayed on ~5 years of daily bars. Older years pick a winner; the last 12 months confirm it.
function backtestSection(bt) {
  if (!bt?.older) return '';
  const rows = [['older', 'Older years'], ['recent', 'Last 12 months (unseen)']];
  const names = Object.keys(bt.configs || {});
  const cell = (r) => `<td class="num">${pctS(r.ret)}</td><td class="num">${pctS(r.spy_ret)}</td><td class="num">${pctS(-r.max_dd)}</td>
    <td class="num">${r.all.n}</td><td class="num">${Math.round(r.all.win_rate * 100)}%</td><td class="num">${Number(r.all.avg_r).toFixed(2)}R</td>`;
  const setups = [...new Set(names.flatMap((k) => Object.keys(bt.older[k]?.by_setup || {})))];
  const win = bt.verdict?.winner;
  const tone = win && win !== 'current' && bt.configs?.[win] ? 'ok' : '';
  return `<div class="section"><h2>Backtest</h2><div class="card stack">
    <div>${badge(win && win !== 'current' && bt.configs?.[win] ? `winner: ${bt.configs[win].label}` : 'current rules kept', tone)}
      <span class="small muted">${esc(bt.universe)} stocks · ran ${ago(bt.ran_at)}</span></div>
    <div class="small">${esc(bt.verdict?.text || '')}</div>
    <table class="table"><thead><tr><th>Period</th><th>Rules</th><th>Return</th><th>SPY</th><th>Worst drop</th><th>Trades</th><th>Wins</th><th>Avg</th></tr></thead><tbody>
      ${rows.map(([w, label]) => names.map((k, i) => `<tr><td class="small">${i ? '' : `${esc(label)}<div class="muted">${esc(bt[w][k].from)} → ${esc(bt[w][k].to)}</div>`}</td>
        <td>${esc(bt.configs[k].label)}</td>${cell(bt[w][k])}</tr>`).join('')).join('')}
    </tbody></table>
    <details><summary class="small">By setup (older years)</summary>
      <table class="table"><thead><tr><th>Setup</th>${names.map((k) => `<th>${esc(bt.configs[k].label)}</th>`).join('')}</tr></thead><tbody>
      ${setups.map((s) => `<tr><td>${esc(s)}</td>${names.map((k) => { const g = bt.older[k]?.by_setup?.[s]; return `<td class="num small">${g ? `${g.n} trades · ${Math.round(g.win_rate * 100)}% wins · ${badge(`${Number(g.avg_r).toFixed(2)}R`, g.avg_r > 0 ? 'ok' : g.avg_r < 0 ? 'bad' : '')}` : '—'}</td>`; }).join('')}</tr>`).join('')}
      </tbody></table></details>
    <div class="small muted">Limits: a fixed ranking stands in for the AI's picks; the stock list is today's biggest companies (past losers are missing, which flatters results); long stocks only, no options or penny stocks. Paper only: the backtest never changes the live rules by itself.</div>
  </div></div>`;
}
