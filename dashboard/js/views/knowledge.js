import { sb, q, esc, ago, badge, BUSINESSES } from '../core.js';

let query = '';
let business = '';

export async function render(el) {
  let rows;
  if (query) {
    rows = await q(sb.rpc('search_knowledge', { q: query, lim: 60 }));
  } else {
    let b = sb.from('knowledge').select('*').order('created_at', { ascending: false }).limit(60);
    rows = await q(b);
  }
  if (business) rows = rows.filter((r) => (r.businesses || []).includes(business));

  el.innerHTML = `
  <div class="head"><h1>Knowledge</h1></div>
  <form id="search" class="row card">
    <input name="q" value="${esc(query)}" placeholder="Search everything the Researcher kept (e.g. FSBO commission, estimate follow-up)" style="flex:1">
    <select name="b"><option value="">all businesses</option>${BUSINESSES.map((x) => `<option ${x === business ? 'selected' : ''}>${x}</option>`).join('')}</select>
    <button class="primary" type="submit">Search</button>
  </form>
  <div class="card list section">${rows.map((k) => `
    <div class="item">
      <div class="row between"><a href="${esc(k.url)}" target="_blank" rel="noopener"><strong>${esc(k.title)}</strong></a>
        <span class="row">${(k.businesses || []).map((b) => badge(b)).join('')}${k.lane ? badge(k.lane, 'info') : ''}${badge(`u${k.usefulness}`, k.usefulness >= 4 ? 'ok' : '')}</span></div>
      <div class="small">${esc(k.summary || '')}</div>
      <div class="small muted">${ago(k.created_at)}</div>
    </div>`).join('') || '<div class="empty">No results.</div>'}
  </div>`;

  el.querySelector('#search').addEventListener('submit', (e) => {
    e.preventDefault();
    const d = new FormData(e.target);
    query = String(d.get('q') || '').trim();
    business = String(d.get('b') || '');
    window.hqRefresh();
  });
}
