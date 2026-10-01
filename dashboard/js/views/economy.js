// Economy: runway, P&L per lane and agent, budgets, and the Architect's crew (with a Stop button on each).
import { sb, q, esc, ago, money, badge, on, act, kvGet, kvSet, nf } from '../core.js';

const LANE_NAMES = {
  offers: 'Launcher offers', assets: 'itch.io asset packs', villa: 'Villa Cinema',
  email: "Inbox + Bobby's businesses", growth: 'Research & ideas (overhead)', outside: 'Outside the economy',
};
const STATE_TONE = { earning: 'ok', focus: 'info', grace: '', protected: '', overhead: '', 'cut back': 'warn', 'shut down': 'bad' };
const PROTECTED = ['operator', 'learner', 'launcher', 'villa_outreach', 'economist', 'architect', 'paper_trader'];
const signed = (n) => `${Number(n) >= 0 ? '' : '−'}${money(Math.abs(Number(n || 0)))}`;

export async function render(el) {
  let crew = [], agents = [];
  try {
    [crew, agents] = await Promise.all([
      q(sb.from('crew_specs').select('*').order('created_at', { ascending: false })),
      q(sb.from('agents').select('id,name,enabled').order('sort')),
    ]);
  } catch {
    el.innerHTML = `<div class="head"><h1>Economy</h1></div><div class="card"><h2>One database update needed</h2>
      <p class="muted small">Run the Economy SQL block in Supabase once. Claude has it ready for you.</p></div>`;
    return;
  }
  const [snap, burn, budgets, caps] = await Promise.all([
    kvGet('economy_snapshot', null), kvGet('economy_burn', []), kvGet('economy_budgets', {}), kvGet('llm_caps', {}),
  ]);
  const name = Object.fromEntries(agents.map((a) => [a.id, a.name]));
  const m = snap?.meter || { revenue_30d: 0, burn_month: burn.reduce((n, b) => n + Number(b.usd_month || 0), 0), net_month: 0, covers: null };
  const live = crew.filter((c) => ['probation', 'active'].includes(c.status));
  const past = crew.filter((c) => c.status === 'retired');
  const off = agents.filter((a) => a.enabled === false && !crew.some((c) => c.id === a.id));

  el.innerHTML = `
  <div class="head"><h1>Economy</h1><div class="small muted">${snap ? `Books closed ${ago(snap.at)} · ` : ''}Budget follows money earned · new spend budget $0</div></div>
  <div class="st-hud">
    <div class="st-chip"><span>Revenue (30 days)</span><strong class="num">${money(m.revenue_30d)}</strong></div>
    <div class="st-chip"><span>Bills per month</span><strong class="num">${money(m.burn_month)}</strong></div>
    <div class="st-chip ${m.revenue_30d < m.burn_month ? 'alert' : ''}"><span>Runway</span><strong class="num">${m.burn_month > 0 ? `${signed(m.revenue_30d - m.burn_month)}/mo · covers ${Math.round((m.revenue_30d / m.burn_month) * 100)}%` : 'add your bills below'}</strong></div>
    <div class="st-chip"><span>Focus</span><strong>${snap?.focus ? esc(LANE_NAMES[snap.focus]) : snap ? 'earning lanes' : '—'}</strong></div>
  </div>
  ${!snap ? '<div class="card small muted">The Economist closes the books daily at 11pm ET. Numbers appear after its first run.</div>' : ''}
  <div class="card small" style="margin-top:8px"><strong>First job:</strong> get one lane to its first paying customer.
    Survival pressure only moves effort (tokens, images, minutes). It never changes what any agent may do: no spending, no sends outside the approval rules, no real-money trades.</div>

  <div class="section"><h2>Lanes (30 days)</h2><div class="card"><table class="table"><thead><tr><th>Lane</th><th>State</th><th>Budget</th><th>Revenue</th><th>Shadow cost</th><th>Net</th></tr></thead><tbody>
    ${Object.entries(snap?.lanes || {}).map(([id, l]) => `<tr><td>${esc(LANE_NAMES[id] || id)}</td><td>${badge(l.state || 'new', STATE_TONE[l.state] || '')}</td>
      <td class="num">${l.factor != null ? `${Math.round(l.factor * 100)}%` : '100%'}</td><td class="num">${money(l.revenue)}</td><td class="num">${money(l.shadow_cost)}</td>
      <td>${badge(signed(l.net), Number(l.net) > 0 ? 'ok' : Number(l.net) < 0 ? 'bad' : '')}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No books yet.</td></tr>'}
  </tbody></table>
  <div class="small muted">Shadow cost = what the work would cost on paid tiers ($0.40 per million tokens, images, Actions minutes) plus your time ($40/h, 5 min per approval). Cash cost on free tiers is $0.</div></div></div>

  <div class="section"><h2>Agents (30 days)</h2><div class="card"><table class="table"><thead><tr><th>Agent</th><th>Lane</th><th>Tokens/day budget</th><th>Tokens used</th><th>Revenue</th><th>Shadow cost</th><th>Net</th></tr></thead><tbody>
    ${Object.entries(snap?.agents || {}).sort((a, b) => b[1].shadow_cost - a[1].shadow_cost).map(([id, a]) => `<tr><td>${esc(name[id] || id)}${PROTECTED.includes(id) ? ' <span class="small muted">· protected</span>' : ''}</td>
      <td class="small">${esc(LANE_NAMES[a.lane] || a.lane)}</td><td class="num">${nf(budgets?.tokens?.[id] ?? caps?.agents?.[id] ?? 0) || '—'}</td><td class="num">${nf(a.tokens)}</td>
      <td class="num">${money(a.revenue)}</td><td class="num">${money(a.shadow_cost)}</td><td>${badge(signed(a.net), Number(a.net) > 0 ? 'ok' : Number(a.net) < 0 ? 'bad' : '')}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">No books yet.</td></tr>'}
  </tbody></table></div></div>

  ${off.length ? `<div class="section"><h2>Switched off</h2><div class="card list">${off.map((a) => `<div class="row between"><span>${esc(a.name)}</span><button data-act="restart" data-id="${esc(a.id)}">Turn back on</button></div>`).join('')}</div></div>` : ''}

  <div class="section"><h2>Crew the Architect deployed (${live.length})</h2>
    <div class="small muted" style="margin-bottom:8px">Deployed automatically. Each one is built only from guarded building blocks, starts on probation with a small budget, and is retired on day 14 unless it pays its way. Stop any of them here.</div>
    <div class="list">${live.map(card).join('') || '<div class="card empty">No crew yet. The Architect works Sundays at 7pm ET.</div>'}</div>
    ${past.length ? `<details style="margin-top:8px"><summary class="small muted">Retired (${past.length})</summary><div class="list">${past.map(card).join('')}</div></details>` : ''}
  </div>

  <div class="section"><h2>Your monthly bills</h2><div class="card stack">
    <div class="small muted">What you really pay each month for this setup. The runway meter compares these to real revenue.</div>
    <form id="burn" class="stack">${[...burn, { name: '', usd_month: '' }].map((b, i) => `<div class="row">
      <input name="n${i}" value="${esc(b.name)}" placeholder="Bill name" style="flex:2">
      <input name="v${i}" value="${esc(b.usd_month)}" type="number" min="0" step="0.01" placeholder="$/month" style="flex:1"></div>`).join('')}
      <div><button class="ok" type="submit">Save bills</button></div></form>
  </div></div>`;

  on(el, 'click', '[data-act="stop"]', (e, btn) => act(btn, async () => {
    const id = btn.dataset.id;
    await q(sb.from('crew_specs').update({ status: 'retired', retired_at: new Date().toISOString(), retire_reason: 'Stopped by Bobby' }).eq('id', id));
    await q(sb.from('agents').update({ enabled: false }).eq('id', id));
    window.hqRefresh();
  }, 'Stopped'));
  on(el, 'click', '[data-act="restart"]', (e, btn) => act(btn, async () => {
    await q(sb.from('agents').update({ enabled: true }).eq('id', btn.dataset.id));
    window.hqRefresh();
  }, 'Back on'));
  el.querySelector('#burn').addEventListener('submit', (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const rows = [];
    for (let i = 0; f.has(`n${i}`); i++) {
      const n = String(f.get(`n${i}`)).trim();
      if (n) rows.push({ name: n.slice(0, 80), usd_month: Math.max(0, Number(f.get(`v${i}`)) || 0) });
    }
    act(e.submitter, async () => { await kvSet('economy_burn', rows); window.hqRefresh(); }, 'Bills saved');
  });
}

function card(c) {
  const s = c.stats || {};
  return `<div class="card stack">
    <div class="row between"><strong>${esc(c.name)}</strong><span class="row">${badge(c.kind === 'clone' ? `clone of ${c.base}` : 'new kind')}
      ${badge(c.status, c.status === 'active' ? 'ok' : c.status === 'retired' ? 'bad' : 'warn')}</span></div>
    <div><strong>What:</strong> ${esc(c.mission)}</div>
    <div class="small"><strong>Budget:</strong> ${nf(c.token_budget)} tokens/day · ${esc(LANE_NAMES[c.lane] || c.lane)}${c.blocks?.length ? ` · can: ${esc(c.blocks.join(', '))}` : ''}</div>
    <div class="small"><strong>Expected money:</strong> ${esc(c.expected_money || 'unknown')}</div>
    <div class="small"><strong>Kill metric:</strong> ${esc(c.kill_metric?.text || '')}${c.status === 'probation' ? ` (day 14 = ${esc(c.probation_ends)})` : ''}</div>
    <div class="small muted">So far: ${nf(s.outputs || 0)} outputs, ${nf(s.accepted || 0)} accepted, ${money(s.revenue || 0)} revenue${c.why ? ` · Why: ${esc(c.why)}` : ''}</div>
    ${c.status === 'retired' ? `<div class="small muted">Retired ${ago(c.retired_at)}: ${esc(c.retire_reason || '')}</div>` : `<div><button class="danger" data-act="stop" data-id="${esc(c.id)}">Stop</button></div>`}
  </div>`;
}
