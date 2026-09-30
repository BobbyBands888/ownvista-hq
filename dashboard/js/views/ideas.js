import { sb, q, esc, ago, money, badge, on, act, md } from '../core.js';

const TABS = [['growth', 'Growth'], ['business', 'New business'], ['venture', 'Venture Lab']];
let tab = null; // picked on first render: the first tab with ideas waiting
let statusFilter = 'proposed';

export async function render(el) {
  // Count ideas waiting for a decision per tab, so the page opens where the work is
  // and each tab shows how many are waiting.
  const waiting = await q(sb.from('ideas').select('kind').eq('status', 'proposed').limit(500));
  const counts = Object.fromEntries(TABS.map(([k]) => [k, waiting.filter((w) => w.kind === k).length]));
  if (!tab) tab = (TABS.find(([k]) => counts[k] > 0) || TABS[0])[0];

  const ideas = await q(sb.from('ideas').select('*, assets(id,kind,title,body,gmail_draft_id)').eq('kind', tab)
    .in('status', statusFilter === 'all' ? ['proposed', 'approved', 'rejected', 'launched'] : [statusFilter])
    .order('created_at', { ascending: false }).limit(40));

  el.innerHTML = `
  <div class="head"><h1>Ideas</h1>
    <div class="row"><select id="status">${['proposed', 'approved', 'launched', 'rejected', 'all'].map((s) => `<option ${s === statusFilter ? 'selected' : ''}>${s}</option>`).join('')}</select></div></div>
  <div class="tabs">${TABS.map(([k, v]) => `<button data-tab="${k}" class="${k === tab ? 'active' : ''}">${v}${counts[k] ? ` (${counts[k]})` : ''}</button>`).join('')}</div>
  <div class="list">${ideas.map((i) => `
    <div class="card stack" data-id="${i.id}">
      <div class="row between"><h2>${esc(i.title)}</h2>
        <span class="row">${badge(i.status, i.status === 'approved' || i.status === 'launched' ? 'ok' : i.status === 'rejected' ? 'bad' : 'info')}${i.business ? badge(i.business) : ''}${i.score != null ? badge(`${i.score}/100`, 'info') : ''}<span class="small muted">${esc(i.created_by || '')} · ${ago(i.created_at)}</span></span></div>
      ${i.score_breakdown ? `<div class="small muted num">Time to revenue ${i.score_breakdown.time_to_revenue}/30 · Fit ${i.score_breakdown.fit}/25 · Cost ${i.score_breakdown.cost}/20 · Hours ${i.score_breakdown.hours}/15 · Evidence ${i.score_breakdown.evidence}/10</div>` : ''}
      <div class="small">${md(i.summary || '')}</div>
      ${(i.steps || []).length ? `<ol class="small">${i.steps.map((s) => `<li>${esc(typeof s === 'string' ? s : JSON.stringify(s))}</li>`).join('')}</ol>` : ''}
      ${i.economics && Object.keys(i.economics).length ? `<div class="small num"><strong>Economics:</strong> ${Object.entries(i.economics).filter(([k]) => k !== 'assumptions').map(([k, v]) => `${esc(k.replace(/_/g, ' '))}: ${esc(v ?? '—')}`).join(' · ')}${i.economics.assumptions?.length ? `<div class="muted">Assumptions: ${esc(i.economics.assumptions.join('; '))}</div>` : ''}</div>` : ''}
      ${i.experiment ? `<div class="small"><strong>Experiment:</strong> ${money(i.experiment.cost_usd)} · ${esc(i.experiment.days)} days · pass: ${esc(i.experiment.pass_metric || '—')} · kill: ${esc(i.experiment.kill_metric || '—')}${i.experiment.needs_accounts?.length ? ` · accounts: ${esc(i.experiment.needs_accounts.join(', '))}` : ''}${i.profit_per_hour != null ? ` · expected ${money(i.profit_per_hour)}/hour` : ''}</div>` : ''}
      ${(i.source_urls || []).length ? `<div class="small">Sources: ${i.source_urls.map((u, n) => `<a href="${esc(u)}" target="_blank" rel="noopener">[${n + 1}]</a>`).join(' ')}</div>` : ''}
      ${i.launch_kit ? `<details><summary>Launch kit</summary><div class="pre">${esc(i.launch_kit)}</div></details>` : ''}
      ${(i.assets || []).length ? `<details><summary>${i.assets.length} asset(s) built</summary>${i.assets.map((a) => `<div style="margin-top:8px"><strong class="small">${esc(a.kind)} — ${esc(a.title || '')}</strong>${a.gmail_draft_id ? ` ${badge('Gmail draft', 'info')}` : ''}<div class="pre">${esc(a.body)}</div></div>`).join('')}</details>` : ''}
      ${i.feedback ? `<div class="small muted">Your note: ${esc(i.feedback)}</div>` : ''}
      <div class="row"><input data-note placeholder="Feedback note (the agents learn from it)" style="flex:1">
        ${i.status === 'proposed' ? '<button class="ok" data-do="approve">Approve</button><button class="danger" data-do="reject">Reject</button>' : ''}
        ${i.status === 'approved' ? '<button data-do="launched">Mark launched</button>' : ''}
        ${i.status !== 'proposed' ? '<button data-do="note">Save note</button>' : ''}</div>
    </div>`).join('') || '<div class="card empty">Nothing here.</div>'}
  </div>`;

  on(el, 'click', '[data-tab]', (e, b) => { tab = b.dataset.tab; window.hqRefresh(); });
  el.querySelector('#status').addEventListener('change', (e) => { statusFilter = e.target.value; window.hqRefresh(); });
  on(el, 'click', '[data-do]', (e, btn) => {
    const card = btn.closest('[data-id]');
    const id = card.dataset.id;
    const note = card.querySelector('[data-note]').value.trim() || null;
    act(btn, async () => {
      if (btn.dataset.do === 'approve') {
        const r = await q(sb.rpc('approve_idea', { p_id: id, p_note: note }));
        if (r && r.ok === false) throw new Error(r.reason);
      } else if (btn.dataset.do === 'reject') {
        await q(sb.from('ideas').update({ status: 'rejected', decided_at: new Date().toISOString(), feedback: note }).eq('id', id));
        if (note) await q(sb.from('feedback').insert({ kind: 'idea_rejected', text: note, ref_table: 'ideas', ref_id: id }));
      } else if (btn.dataset.do === 'launched') {
        await q(sb.from('ideas').update({ status: 'launched', ...(note ? { feedback: note } : {}) }).eq('id', id));
        if (note) await q(sb.from('feedback').insert({ kind: 'idea_note', text: note, ref_table: 'ideas', ref_id: id }));
      } else if (note) {
        await q(sb.from('ideas').update({ feedback: note }).eq('id', id));
        await q(sb.from('feedback').insert({ kind: 'idea_note', text: note, ref_table: 'ideas', ref_id: id }));
      }
      window.hqRefresh();
    }, 'Saved');
  });
}
