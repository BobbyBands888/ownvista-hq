import { sb, q, esc, ago, badge, on, act, kvGet, kvSet, money } from '../core.js';

// Radar: what's running non-stop (the 5-minute tick), what Autopilot sent live, and the products the scouts found.
export async function render(el) {
  const [radar, pilot, tick, approvals, launches] = await Promise.all([
    kvGet('product_radar', []),
    kvGet('autopilot', {}),
    kvGet('tick_lock', null),
    q(sb.from('activity').select('message,at,ref_id').eq('agent', 'autopilot').order('at', { ascending: false }).limit(15)),
    q(sb.from('launches').select('title,status,slug,price_usd,sales').order('created_at', { ascending: false }).limit(8)),
  ]);
  const enabled = pilot?.enabled !== false;
  const maxDay = Math.min(pilot?.max_per_day ?? 3, 3);
  const rows = (Array.isArray(radar) ? radar : []).slice().sort((a, b) => (b.score || 0) - (a.score || 0));
  const lastTick = tick?.at;
  const tickLate = !lastTick || Date.now() - Date.parse(lastTick) > 20 * 60000;

  el.innerHTML = `
  <div class="head"><h1>Radar</h1><div class="small muted">Autopilot (every 15 min) approves new ideas so the Launcher builds and publishes them without waiting for you.</div></div>
  <div class="grid g2">
    <div class="card">
      <h2>Autopilot ${badge(enabled ? 'on' : 'paused', enabled ? 'ok' : 'warn')}</h2>
      <p class="small">Approves up to <strong>${esc(maxDay)}</strong> ideas a day. Skips brand names, phone offers, made-up discounts or previews, anything real estate, Nashville Buys and Villa Cinema. Live offers still face the 14-day kill rule.</p>
      <div class="row"><button id="pilot" class="${enabled ? '' : 'primary'}">${enabled ? 'Pause Autopilot' : 'Turn Autopilot on'}</button></div>
    </div>
    <div class="card">
      <h2>Continuous shift ${badge(tickLate ? 'not running' : 'running', tickLate ? 'bad' : 'ok')}</h2>
      <p class="small">Last tick ${lastTick ? ago(lastTick) : 'never'}${tick?.last ? ` · ${esc(Object.entries(tick.last).map(([k, v]) => `${k}: ${v}`).join(', '))}` : ''}.</p>
      ${tickLate ? '<p class="small muted">The hourly job keeps research going as a backup until the tick runs.</p>' : ''}
    </div>
  </div>
  <div class="card section"><h2>Sent live by Autopilot</h2><div class="list">
    ${approvals.map((a) => `<div class="item"><div class="small">${esc(a.message)}</div><div class="small muted">${ago(a.at)}</div></div>`).join('') || '<div class="empty">Nothing approved yet.</div>'}
  </div>
  <div class="small muted section">Offers: ${launches.map((l) => `${esc(l.title)} ${badge(l.status, l.status === 'live' ? 'ok' : '')}${l.status === 'live' ? ` <a href="/p/${esc(l.slug)}" target="_blank" rel="noopener">page</a>` : ''}`).join(' · ') || 'none yet'}</div></div>
  <div class="card scroll-x section"><h2>Products found (${rows.length})</h2>
    <table class="table"><tr><th>Product</th><th>Lane</th><th class="num">Score</th><th class="num">Sell</th><th class="num">Cost</th><th class="num">Margin</th><th class="num">Ship</th><th>Saturation</th><th>Found</th></tr>
    ${rows.map((r) => `<tr>
      <td><strong>${esc(r.title)}</strong><div class="small muted">${esc(r.why || '')}</div>
        ${r.supplier_search ? `<div class="small mono">supplier search: ${esc(r.supplier_search)}</div>` : ''}
        <div class="small">${(r.evidence || []).map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener">source ${i + 1}</a>`).join(' · ')}</div></td>
      <td>${badge(r.lane || '', 'info')}<div class="small muted">${esc(r.channel || '')}</div></td>
      <td class="num">${r.score ?? '—'}</td>
      <td class="num">${r.sell_price != null ? money(r.sell_price) : '—'}</td>
      <td class="num">${r.est_cost != null ? money(r.est_cost) : '—'}</td>
      <td class="num">${r.margin_pct != null ? `${r.margin_pct}%` : '—'}</td>
      <td class="num">${r.shipping_days != null ? `${r.shipping_days}d` : '—'}</td>
      <td>${r.saturation ? '●'.repeat(r.saturation) + '○'.repeat(5 - r.saturation) : '—'}</td>
      <td class="small">${esc(r.found_by || '')}<div class="muted">${ago(r.at)}</div></td></tr>`).join('') || '<tr><td colspan="9" class="empty">The scouts haven\'t found anything yet.</td></tr>'}
    </table>
    <p class="small muted">Physical products can't go live until there's a store and a supplier (both cost money). Text products skip this list and go straight to the Launcher.</p>
  </div>`;

  on(el, 'click', '#pilot', (e, btn) => act(btn, async () => {
    await kvSet('autopilot', { ...(pilot || {}), enabled: !enabled });
    window.hqRefresh();
  }, enabled ? 'Autopilot paused' : 'Autopilot on'));
}
