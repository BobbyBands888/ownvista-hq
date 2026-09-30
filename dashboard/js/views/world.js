import { sb, q, count, esc, ago, when, money, pct, nf, badge, statusTone, spark, meter, on, act, fdata, BUSINESSES } from '../core.js';

// How long an agent may go without a run before it counts as unhealthy (hours).
const EXPECT = {
  villa_outreach: 'day', operator: 2.5, builder: 2.5,
  villa_studio: 'work', researcher: 7, strategist: 26, analyst: 26, learner: 2.5, scout: 100, judge: 8 * 24,
};

function health(a) {
  if (!a.last_run_at) return { tone: '', label: 'waiting for first run' };
  if (a.last_status === 'error') return { tone: 'bad', label: 'last run failed' };
  const hours = (Date.now() - Date.parse(a.last_run_at)) / 3600000;
  const exp = EXPECT[a.id];
  const etHour = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', hourCycle: 'h23' }).format(new Date()));
  let limit = typeof exp === 'number' ? exp : exp === 'day' ? (etHour < 7 ? 9 : 2.5) : Infinity;
  if (!a.enabled) return { tone: '', label: 'paused' };
  if (hours > limit) return { tone: 'warn', label: `no run for ${Math.round(hours)}h` };
  return { tone: a.last_status === 'capped' ? 'warn' : 'ok', label: a.last_status === 'capped' ? 'healthy · hit a cap' : 'healthy' };
}

export async function render(el) {
  const monthStart = new Date(); monthStart.setDate(1); monthStart.setHours(0, 0, 0, 0);
  const since30 = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date());
  const [agents, metrics, jobs, usage, caps, ledger, activity, spendMonth, vcEnabled, vcPaused] = await Promise.all([
    q(sb.from('agents').select('*').order('sort')),
    q(sb.from('metrics_daily').select('*').gte('day', since30).order('day')),
    q(sb.from('job_runs').select('minutes').gte('started_at', monthStart.toISOString())),
    q(sb.from('llm_usage').select('*').eq('day', today)),
    q(sb.from('kv').select('value').eq('key', 'llm_caps').maybeSingle()),
    q(sb.from('ledger').select('*').order('day', { ascending: false }).limit(1000)),
    q(sb.from('activity').select('*').order('at', { ascending: false }).limit(25)),
    q(sb.from('spend').select('amount_usd,status').gte('at', monthStart.toISOString()).in('status', ['reserved', 'charged'])),
    q(sb.from('kv').select('value').eq('key', 'vc_enabled').maybeSingle()),
    q(sb.from('kv').select('value').eq('key', 'vc_paused').maybeSingle()),
  ]);
  const [knowledgeN, sourcesN, ideasProposed, ideasApproved, rulesN] = await Promise.all([
    count('knowledge'), count('sources', (x) => x.eq('status', 'active')),
    count('ideas', (x) => x.eq('status', 'proposed')), count('ideas', (x) => x.in('status', ['approved', 'launched'])),
    count('playbook_rules', (x) => x.eq('active', true)),
  ]);

  const healthy = agents.filter((a) => health(a).tone === 'ok' || health(a).tone === 'warn' && a.last_status === 'capped').length;
  const minutes = jobs.reduce((n, j) => n + (j.minutes || 0), 0);
  const byModel = {};
  for (const u of usage) {
    const m = (byModel[u.model] ||= { tokens: 0, requests: 0 });
    m.tokens += u.tokens_in + u.tokens_out; m.requests += u.requests;
  }
  const capTokens = caps?.value?.smart?.tokens || 150000;
  const spent = spendMonth.reduce((n, s) => n + Number(s.amount_usd), 0);

  // Scorecard: last 7 days vs the 7 before.
  const avg = (rows, k) => { const v = rows.map((r) => r[k]).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const last7 = metrics.slice(-7), prev7 = metrics.slice(-14, -7);
  const unedited = (rows) => { const s = rows.reduce((n, r) => n + r.sent, 0); return s ? rows.reduce((n, r) => n + r.sent_unedited, 0) / s : null; };
  const trend = (a, b, lowerIsBetter) => (a == null || b == null ? '' : (lowerIsBetter ? a < b : a > b) ? badge('improving', 'ok') : a === b ? badge('flat') : badge('slipping', 'warn'));

  // Profit by line.
  const lines = {};
  for (const l of ledger) {
    const x = (lines[l.line] ||= { revenue: 0, cost: 0, hours: 0 });
    x.revenue += +l.revenue; x.cost += +l.cost; x.hours += +l.bobby_hours;
  }
  const total = Object.values(lines).reduce((t, x) => ({ revenue: t.revenue + x.revenue, cost: t.cost + x.cost, hours: t.hours + x.hours }), { revenue: 0, cost: 0, hours: 0 });

  el.innerHTML = `
  <div class="head"><h1>World</h1><div class="row small muted">Updated ${when(new Date())}</div></div>
  <div class="grid g4">
    <div class="card stat"><div class="label">Agents healthy</div><div class="value num">${healthy}/${agents.length}</div><div class="sub">${agents.filter((a) => a.last_status === 'error').length} with errors</div></div>
    <div class="card stat"><div class="label">Actions minutes (month)</div><div class="value num">${nf(minutes)} <span class="muted small">/ 2,000</span></div>${meter(minutes, 2000)}</div>
    <div class="card stat"><div class="label">LLM tokens today</div><div class="value num">${nf(Object.values(byModel).reduce((n, m) => n + m.tokens, 0))}</div>
      <div class="sub">${Object.entries(byModel).map(([m, x]) => `${esc(m.split('/').pop())}: ${nf(x.tokens)} / ${nf(capTokens)}`).join(' · ') || 'no calls yet'}</div></div>
    <div class="card stat"><div class="label">Villa spend (month)</div><div class="value num">${money(spent)} <span class="muted small">/ $150</span></div>${meter(spent, 150)}
      <div class="sub">Outreach ${vcEnabled?.value === true ? (vcPaused?.value === true ? badge('paused', 'bad') : badge('on', 'ok')) : badge('off')}</div></div>
  </div>

  <div class="section"><h2>Agents</h2>
    <div class="grid agents">${agents.map((a) => { const h = health(a); return `
      <div class="card">
        <div class="row between"><div class="row"><span class="dot ${h.tone}"></span><h3>${esc(a.name)}</h3></div>${badge(a.last_status || 'new', statusTone(a.last_status))}</div>
        <div class="small muted" style="margin-top:4px">${esc(a.schedule || '')}</div>
        <div class="small" style="margin-top:8px">Last: <span class="num">${ago(a.last_run_at)}</span> · Next: <span class="num">${a.next_run_at ? ago(a.next_run_at) : '—'}</span></div>
        <div class="small muted" style="margin-top:4px">${esc(h.label)}</div>
        ${a.last_summary ? `<div class="small muted" style="margin-top:6px">${esc(a.last_summary).slice(0, 220)}</div>` : ''}
      </div>`; }).join('')}
    </div>
  </div>

  <div class="section grid g4">
    <div class="card stat"><div class="label">Knowledge</div><div class="value num">${nf(knowledgeN)}</div></div>
    <div class="card stat"><div class="label">Active sources</div><div class="value num">${nf(sourcesN)}</div></div>
    <div class="card stat"><div class="label">Ideas</div><div class="value num">${nf(ideasProposed)} <span class="muted small">new</span></div><div class="sub">${nf(ideasApproved)} approved/launched</div></div>
    <div class="card stat"><div class="label">Playbook rules</div><div class="value num">${nf(rulesN)}</div></div>
  </div>

  <div class="section"><h2>Is it getting better? <span class="muted small">last 7 days vs previous 7</span></h2>
    <div class="grid g4">
      <div class="card stat"><div class="label">Avg edit distance</div><div class="value num">${avg(last7, 'avg_edit_distance') == null ? '—' : pct(avg(last7, 'avg_edit_distance'))}</div>
        <div class="sub">lower = Bobby rewrites less ${trend(avg(last7, 'avg_edit_distance'), avg(prev7, 'avg_edit_distance'), true)}</div>${spark(metrics.map((m) => m.avg_edit_distance))}</div>
      <div class="card stat"><div class="label">Sent unedited</div><div class="value num">${pct(unedited(last7))}</div>
        <div class="sub">${trend(unedited(last7), unedited(prev7), false)}</div>${spark(metrics.map((m) => (m.sent ? m.sent_unedited / m.sent : null)))}</div>
      <div class="card stat"><div class="label">Draft grade (1–5)</div><div class="value num">${avg(last7, 'avg_grade')?.toFixed(1) ?? '—'}</div>
        <div class="sub">${trend(avg(last7, 'avg_grade'), avg(prev7, 'avg_grade'), false)}</div>${spark(metrics.map((m) => m.avg_grade))}</div>
      <div class="card stat"><div class="label">Ideas approved</div><div class="value num">${last7.reduce((n, m) => n + m.ideas_approved, 0)}</div>
        <div class="sub">of ${last7.reduce((n, m) => n + m.ideas_proposed, 0)} proposed</div>${spark(metrics.map((m) => m.ideas_approved))}</div>
    </div>
  </div>

  <div class="section grid g2">
    <div class="card">
      <h2>Profit by line</h2>
      <div class="scroll-x"><table class="table num" style="margin-top:8px">
        <tr><th>Line</th><th>Revenue</th><th>Cost</th><th>Profit</th><th>Hours</th><th>$/hour</th></tr>
        ${Object.entries(lines).map(([k, x]) => `<tr><td>${esc(k)}</td><td>${money(x.revenue)}</td><td>${money(x.cost)}</td><td>${money(x.revenue - x.cost)}</td><td>${x.hours}</td><td>${x.hours ? money((x.revenue - x.cost) / x.hours) : '—'}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No entries yet — log one below.</td></tr>'}
        ${Object.keys(lines).length ? `<tr><td><strong>Total</strong></td><td>${money(total.revenue)}</td><td>${money(total.cost)}</td><td><strong>${money(total.revenue - total.cost)}</strong></td><td>${total.hours}</td><td>${total.hours ? money((total.revenue - total.cost) / total.hours) : '—'}</td></tr>` : ''}
      </table></div>
      <details style="margin-top:10px"><summary>Log revenue, cost or hours</summary>
        <form id="ledger-form" class="grid g2" style="margin-top:10px">
          <div><label>Line</label><select name="line">${[...BUSINESSES, 'experiment'].map((b) => `<option>${b}</option>`).join('')}</select></div>
          <div><label>Date</label><input name="day" type="date" value="${today}"></div>
          <div><label>Revenue $</label><input name="revenue" type="number" step="0.01" value="0"></div>
          <div><label>Cost $</label><input name="cost" type="number" step="0.01" value="0"></div>
          <div><label>Your hours</label><input name="bobby_hours" type="number" step="0.25" value="0"></div>
          <div><label>Note</label><input name="note"></div>
          <div><button class="primary" type="submit">Save entry</button></div>
        </form>
      </details>
    </div>
    <div class="card">
      <h2>Activity</h2>
      <div class="list" style="margin-top:8px">${activity.map((a) => `<div class="item small"><span class="muted num">${ago(a.at)}</span> · <strong>${esc(a.agent || '')}</strong> ${esc(a.message)}</div>`).join('') || '<div class="empty">Nothing yet.</div>'}</div>
    </div>
  </div>`;

  on(el, 'submit', '#ledger-form', (e, form) => {
    e.preventDefault();
    const d = fdata(form);
    act(form.querySelector('button'), async () => {
      await q(sb.from('ledger').insert({ line: d.line, day: d.day, revenue: +d.revenue, cost: +d.cost, bobby_hours: +d.bobby_hours, note: d.note || null }));
      window.hqRefresh();
    }, 'Saved');
  });
}
