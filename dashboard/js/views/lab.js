import { sb, q, esc, ago, money, badge, on, act, fdata } from '../core.js';

const LANES = ['reselling', 'pod', 'dropshipping', 'local-services', 'b2b', 'digital'];

export async function render(el) {
  const [experiments, signals, ledger] = await Promise.all([
    q(sb.from('experiments').select('*').order('created_at', { ascending: false }).limit(30)),
    q(sb.from('signals').select('*').order('created_at', { ascending: false }).limit(40)),
    q(sb.from('ledger').select('*').not('experiment_id', 'is', null)),
  ]);
  const byExp = {};
  for (const l of ledger) {
    const x = (byExp[l.experiment_id] ||= { revenue: 0, cost: 0, hours: 0 });
    x.revenue += +l.revenue; x.cost += +l.cost; x.hours += +l.bobby_hours;
  }
  const active = experiments.filter((x) => ['running', 'awaiting_approval'].includes(x.status));

  el.innerHTML = `
  <div class="head"><h1>Venture Lab</h1><div class="small muted">Scored on dollars earned. ${active.length}/3 active experiments.</div></div>

  <div class="section"><h2>Experiments</h2>
    <div class="list">${experiments.map((x) => { const e = byExp[x.id] || { revenue: 0, cost: 0, hours: 0 }; const profit = e.revenue - e.cost; return `
      <div class="card stack" data-id="${x.id}">
        <div class="row between"><strong>${esc(x.title)}</strong><span class="row">${badge(x.status, x.status === 'running' ? 'ok' : x.status === 'killed' ? 'bad' : 'info')}${x.verdict ? badge(`judge: ${x.verdict}`, x.verdict === 'kill' ? 'bad' : x.verdict === 'scale' ? 'ok' : '') : ''}</span></div>
        <div class="small muted">${esc(x.lane || '')} · ${x.starts_on || '?'} → ${x.ends_on || '?'} · budget ${money(x.budget_usd)}${x.needs_accounts?.length ? ` · accounts: ${esc(x.needs_accounts.join(', '))}` : ''}</div>
        <div class="grid g3 small">
          <div><strong>Pass:</strong> ${esc(x.pass_metric || '—')}</div><div><strong>Kill:</strong> ${esc(x.kill_metric || '—')}</div>
          <div class="num"><strong>So far:</strong> ${money(profit)} profit · ${e.hours}h · ${e.hours ? money(profit / e.hours) + '/h' : '—'} (expected ${x.expected_profit_per_hour != null ? money(x.expected_profit_per_hour) + '/h' : '?'})</div>
        </div>
        ${x.judge_notes ? `<div class="small muted">Judge: ${esc(x.judge_notes)}</div>` : ''}
        ${x.status === 'running' ? `<details><summary>Log a result</summary>
          <form class="grid g4 log-form" style="margin-top:8px">
            <div><label>Revenue $</label><input name="revenue" type="number" step="0.01" value="0"></div>
            <div><label>Cost $</label><input name="cost" type="number" step="0.01" value="0"></div>
            <div><label>Hours</label><input name="hours" type="number" step="0.25" value="0"></div>
            <div><label>Note</label><input name="note"></div>
            <div><button class="primary" type="submit">Log</button></div>
          </form></details>
          <div class="row"><button data-status="scaled" class="ok">Scale</button><button data-status="killed" class="danger">Kill</button><button data-status="done">Done</button></div>` : ''}
      </div>`; }).join('') || '<div class="card empty">No experiments yet. Approve a venture idea in Ideas to start one.</div>'}
    </div>
  </div>

  <div class="section grid g2">
    <div class="card"><h2>Demand signals</h2>
      <div class="list" style="margin-top:8px">${signals.map((s) => `<div class="item small">
        <div class="row between"><strong>${esc(s.title)}</strong><span class="row">${badge(s.lane, 'info')}${badge(`${s.score ?? '?'}`)}${s.metrics?.trademark_risk ? badge('trademark risk', 'bad') : ''}</span></div>
        <div class="muted">${esc(s.evidence || '')}</div>
        <div class="muted">${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">source</a> · ` : ''}${esc(s.source)} · ${ago(s.created_at)}${s.processed_at ? ' · analyzed' : ''}</div></div>`).join('') || '<div class="empty">No signals yet.</div>'}</div>
    </div>
    <div class="card stack"><h2>Log a find or sold comp</h2>
      <div class="small muted">Home Depot / Lowe's clearance finds and eBay sold comps you checked yourself. The Analyst treats these as evidence.</div>
      <form id="comp-form" class="stack">
        <div class="grid g2"><div><label>Lane</label><select name="lane">${LANES.map((l) => `<option>${l}</option>`).join('')}</select></div>
          <div><label>Item</label><input name="title" required placeholder="Ryobi 18V combo kit, clearance"></div></div>
        <div class="grid g2"><div><label>Buy price $</label><input name="buy" type="number" step="0.01"></div>
          <div><label>Sold comps $ (comma separated)</label><input name="comps" placeholder="89, 95, 102"></div></div>
        <div><label>Evidence / notes</label><input name="evidence" placeholder="3 sold in last 30 days on eBay, store #2615 had 6 units"></div>
        <div><label>Link (optional)</label><input name="url" type="url"></div>
        <button class="primary" type="submit">Save signal</button>
      </form>
    </div>
  </div>`;

  on(el, 'submit', '.log-form', (e, form) => {
    e.preventDefault();
    const d = fdata(form); const id = form.closest('[data-id]').dataset.id;
    act(form.querySelector('button'), async () => {
      await q(sb.from('ledger').insert({ line: 'experiment', experiment_id: id, revenue: +d.revenue, cost: +d.cost, bobby_hours: +d.hours, note: d.note || null }));
      window.hqRefresh();
    }, 'Logged');
  });
  on(el, 'click', '[data-status]', (e, btn) => act(btn, async () => {
    await q(sb.from('experiments').update({ status: btn.dataset.status }).eq('id', btn.closest('[data-id]').dataset.id));
    window.hqRefresh();
  }, 'Updated'));
  on(el, 'submit', '#comp-form', (e, form) => {
    e.preventDefault();
    const d = fdata(form);
    const comps = (d.comps || '').split(',').map((x) => +x.trim()).filter((x) => x > 0);
    act(form.querySelector('button'), async () => {
      await q(sb.from('signals').insert({
        lane: d.lane, title: d.title, url: d.url || null, evidence: d.evidence || null, source: 'bobby', score: 70,
        metrics: { buy_price: d.buy ? +d.buy : null, sold_comps: comps, avg_sold: comps.length ? +(comps.reduce((a, b) => a + b, 0) / comps.length).toFixed(2) : null },
      }));
      window.hqRefresh();
    }, 'Signal saved');
  });
}
