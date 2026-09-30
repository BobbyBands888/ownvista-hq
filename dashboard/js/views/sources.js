import { sb, q, esc, ago, pct, badge, on, act, fdata, BUSINESSES } from '../core.js';

const LANES = ['', 'reselling', 'pod', 'dropshipping', 'local-services', 'b2b', 'digital'];

export async function render(el) {
  const rows = await q(sb.from('sources').select('*').in('kind', ['rss', 'search']).order('status').order('useful_count', { ascending: false }));
  el.innerHTML = `
  <div class="head"><h1>Sources</h1><div class="small muted">Public feeds only; robots.txt is checked before every fetch. Search queries run only after you approve web search (Villa view).</div></div>
  <details class="card"><summary>Add a source</summary>
    <form id="add" class="grid g2" style="margin-top:10px">
      <div><label>Name</label><input name="name" required></div>
      <div><label>Type</label><select name="kind"><option value="rss">RSS / Atom feed URL</option><option value="search">Search query</option></select></div>
      <div style="grid-column:1/-1"><label>Feed URL or search query</label><input name="target" required></div>
      <div><label>Business</label><select name="business"><option value="">any</option>${BUSINESSES.map((b) => `<option>${b}</option>`).join('')}</select></div>
      <div><label>Venture Lab lane</label><select name="lane">${LANES.map((l) => `<option value="${l}">${l || 'none'}</option>`).join('')}</select></div>
      <div><button class="primary" type="submit">Add</button></div>
    </form>
  </details>
  <div class="card scroll-x section"><table class="table">
    <tr><th>Source</th><th>Business</th><th>Status</th><th class="num">Fetched</th><th class="num">Relevant</th><th class="num">Useful</th><th>Last fetch</th><th></th></tr>
    ${rows.map((s) => `<tr data-id="${s.id}">
      <td><strong>${esc(s.name)}</strong> ${badge(s.kind)}<div class="small muted mono">${esc(s.kind === 'search' ? s.query : s.url)}</div>${s.last_error ? `<div class="small" style="color:var(--bad)">${esc(s.last_error)}</div>` : ''}</td>
      <td class="small">${esc(s.business || '')}${s.lane ? ` ${badge(s.lane, 'info')}` : ''}</td>
      <td>${badge(s.status, s.status === 'active' ? 'ok' : s.status === 'retired' ? 'bad' : 'warn')}<div class="small muted">by ${esc(s.added_by)}</div></td>
      <td class="num">${s.fetched_count}</td><td class="num">${s.hit_count} <span class="muted small">${s.fetched_count ? pct(s.hit_count / s.fetched_count) : ''}</span></td><td class="num">${s.useful_count}</td>
      <td class="small">${ago(s.last_fetched_at)}</td>
      <td>${s.status === 'active' ? '<button data-set="paused">Pause</button>' : '<button data-set="active">Resume</button>'}</td></tr>`).join('')}
  </table></div>`;

  on(el, 'submit', '#add', (e, form) => {
    e.preventDefault();
    const d = fdata(form);
    const row = d.kind === 'search'
      ? { name: d.name, kind: 'search', query: d.target, url: `search:${d.target.toLowerCase()}` }
      : { name: d.name, kind: 'rss', url: d.target };
    act(form.querySelector('button'), async () => {
      await q(sb.from('sources').insert({ ...row, business: d.business || null, lane: d.lane || null, added_by: 'bobby' }));
      window.hqRefresh();
    }, 'Source added');
  });
  on(el, 'click', '[data-set]', (e, btn) => act(btn, async () => {
    await q(sb.from('sources').update({ status: btn.dataset.set, error_count: 0 }).eq('id', btn.closest('[data-id]').dataset.id));
    window.hqRefresh();
  }, 'Updated'));
}
