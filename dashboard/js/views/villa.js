import { sb, q, count, esc, ago, when, money, badge, meter, on, act, kvGet, kvSet, fdata, toast } from '../core.js';

const STAGES = ['prospect', 'contacted', 'replied', 'paid', 'photos_received', 'producing', 'qa', 'delivered', 'lost', 'unsubscribed', 'bounced'];
const REGIONS = { 'US-HI': 'Hawaii', 'US-FL': 'Florida', 'US-VI': 'USVI', 'US-PR': 'Puerto Rico', 'US-MTN': 'US mountain resorts', 'US-OTHER': 'Other US' };
const COUNTRY_NAMES = { US: 'United States', FR: 'France', BL: 'St Barts', MF: 'St Martin', ID: 'Indonesia (Bali)', BB: 'Barbados', CA: 'Canada', GB: 'United Kingdom', MX: 'Mexico', IT: 'Italy', ES: 'Spain', GR: 'Greece', PT: 'Portugal', TH: 'Thailand', AE: 'UAE' };

export async function render(el) {
  const weekStart = new Date(); weekStart.setDate(weekStart.getDate() - ((weekStart.getDay() + 6) % 7)); weekStart.setHours(0, 0, 0, 0);
  const monthStart = new Date(); monthStart.setDate(1); monthStart.setHours(0, 0, 0, 0);
  const todayStart = new Date(); todayStart.setHours(0, 0, 0, 0);
  const [enabled, paused, pauseReason, reviewMode, approvedFilms, footer, countries, regions, sampleMode, warmStart, preflight, searchEnabled] = await Promise.all(
    ['vc_enabled', 'vc_paused', 'vc_pause_reason', 'vc_review_mode', 'vc_approved_films', 'vc_footer_address', 'vc_countries', 'vc_us_regions', 'vc_sample_mode', 'vc_warmup_start', 'vc_preflight', 'search_enabled'].map((k) => kvGet(k)));
  const [prospects, orders, spend, messages, stageCounts, sentToday, music, samples, directories, suppression] = await Promise.all([
    q(sb.from('vc_prospects').select('*').order('updated_at', { ascending: false }).limit(60)),
    q(sb.from('vc_orders').select('*').order('created_at', { ascending: false }).limit(30)),
    q(sb.from('spend').select('*').gte('at', monthStart.toISOString()).order('at', { ascending: false })),
    q(sb.from('vc_messages').select('*').order('created_at', { ascending: false }).limit(30)),
    Promise.all(STAGES.map((s) => count('vc_prospects', (x) => x.eq('stage', s)))),
    count('vc_messages', (x) => x.eq('direction', 'out').eq('kind', 'first').in('status', ['reserved', 'sent']).gte('created_at', todayStart.toISOString())),
    sb.storage.from('vc-music').list('', { limit: 100 }).then((r) => (r.data || []).filter((f) => f.id)),
    sb.storage.from('vc-photos').list('_samples', { limit: 100 }).then((r) => (r.data || []).filter((f) => f.id)),
    q(sb.from('sources').select('*').eq('kind', 'directory').order('created_at')),
    q(sb.from('vc_suppression').select('*').order('created_at', { ascending: false }).limit(20)),
  ]);

  const live = spend.filter((s) => s.status !== 'released');
  const monthSpent = live.reduce((n, s) => n + +s.amount_usd, 0);
  const weekSamples = live.filter((s) => s.kind === 'sample' && new Date(s.at) >= weekStart).reduce((n, s) => n + +s.amount_usd, 0);
  const warmDay = warmStart ? Math.floor((Date.now() - Date.parse(warmStart)) / 86400000) : 0;
  const cap = Math.min(20, 5 + Math.floor(warmDay * 15 / 14));
  const byOrder = {};
  for (const s of live) if (s.order_id) byOrder[s.order_id] = (byOrder[s.order_id] || 0) + +s.amount_usd;

  el.innerHTML = `
  <div class="head"><h1>Villa Cinema</h1>
    <div class="row">${enabled === true ? (paused === true ? badge('sending paused', 'bad') : badge('outreach on', 'ok')) : badge('outreach off')}
      ${preflight ? badge(preflight.ok ? 'preflight passed' : 'preflight failing', preflight.ok ? 'ok' : 'bad') : badge('preflight not run', 'warn')}</div></div>

  ${paused === true ? `<div class="card" style="border-color:var(--bad)"><strong>Sending is paused.</strong> <span class="muted">${esc(pauseReason || '')}</span>
    <div class="row" style="margin-top:8px"><button data-kv="vc_paused" data-val="false" class="primary">Resume sending</button></div></div>` : ''}

  <div class="grid g4 section">
    <div class="card stat"><div class="label">First emails today</div><div class="value num">${sentToday} / ${cap}</div><div class="sub">warm-up day ${warmStart ? warmDay : '— (starts with the first send)'}</div>${meter(sentToday, cap)}</div>
    <div class="card stat"><div class="label">Sample spend (week)</div><div class="value num">${money(weekSamples)} <span class="muted small">/ $25</span></div>${meter(weekSamples, 25)}</div>
    <div class="card stat"><div class="label">All spend (month)</div><div class="value num">${money(monthSpent)} <span class="muted small">/ $150</span></div>${meter(monthSpent, 150)}</div>
    <div class="card stat"><div class="label">Films approved</div><div class="value num">${Number(approvedFilms || 0)}</div><div class="sub">${Number(approvedFilms || 0) < 3 ? `${3 - Number(approvedFilms || 0)} more before auto-delivery` : reviewMode === 'always' ? 'review is ON' : 'auto-delivery'}</div></div>
  </div>

  <div class="section"><h2>Pipeline</h2>
    <div class="card row">${STAGES.map((s, i) => `<span class="badge ${stageCounts[i] ? 'info' : ''}">${s.replace('_', ' ')} <strong class="num">${stageCounts[i]}</strong></span>`).join('')}</div>
  </div>

  <div class="section grid g2">
    <div class="card stack">
      <h2>Controls</h2>
      <label class="toggle"><input type="checkbox" data-kv-bool="vc_enabled" ${enabled === true ? 'checked' : ''}> Outreach on (first emails + follow-ups)</label>
      <label class="toggle"><input type="checkbox" data-kv-review ${reviewMode === 'always' ? 'checked' : ''}> Review every film before delivery</label>
      <label class="toggle"><input type="checkbox" data-kv-sample ${sampleMode === 'auto' ? 'checked' : ''}> Offer free samples to hot prospects (within $25/week)</label>
      <label class="toggle"><input type="checkbox" data-kv-bool="search_enabled" ${searchEnabled === true ? 'checked' : ''}> Web search approved (Tavily free tier; needs the TAVILY_API_KEY secret)</label>
      <form id="footer-form" class="field"><label>Physical mailing address for the email footer (CAN-SPAM)</label>
        <div class="row"><input name="address" value="${esc(footer || '')}" placeholder="Villa Cinema, PO Box …, City, ST ZIP" style="flex:1"><button type="submit">Save</button></div></form>
      ${preflight ? `<details><summary>Preflight details (${when(preflight.at)})</summary><div class="pre">${esc(JSON.stringify(preflight, null, 2))}</div></details>` : ''}
      <p class="small muted">Rerun preflight: GitHub → Actions → Ownvista HQ → Run workflow → agent <span class="mono">villa_preflight</span>.</p>
    </div>
    <div class="card stack">
      <h2>Where we may send</h2>
      <div class="small muted">Everything outside the US is off by default. Cold email only goes to role addresses (info@, reservations@ …).</div>
      <div class="grid g2">${Object.entries(countries || {}).map(([c, on_]) => `<label class="toggle"><input type="checkbox" data-country="${c}" ${on_ ? 'checked' : ''}> ${esc(COUNTRY_NAMES[c] || c)}</label>`).join('')}</div>
      <h3 style="margin-top:10px">US regions</h3>
      <div class="grid g2">${Object.entries(regions || {}).map(([r, on_]) => `<label class="toggle"><input type="checkbox" data-region="${r}" ${on_ ? 'checked' : ''}> ${esc(REGIONS[r] || r)}</label>`).join('')}</div>
    </div>
  </div>

  <div class="section"><h2>Orders</h2>
    <div class="card scroll-x"><table class="table">
      <tr><th>Order</th><th>Kind</th><th>Status</th><th>Property</th><th>Customer</th><th>Spend</th><th>Film</th></tr>
      ${orders.map((o) => `<tr><td class="mono">${o.id.slice(0, 8)}<div class="small muted">${ago(o.created_at)}</div></td><td>${badge(o.kind, o.kind === 'paid' ? 'ok' : o.kind === 'test' ? 'info' : '')}</td>
        <td>${badge(o.status, o.status === 'failed' ? 'bad' : o.status === 'review' ? 'warn' : o.status === 'delivered' ? 'ok' : 'info')}${o.notes ? `<div class="small muted">${esc(o.notes)}</div>` : ''}</td>
        <td>${esc(o.property_name || '—')}</td><td class="small">${esc(o.customer_email || '—')}</td><td class="num">${money(byOrder[o.id] || 0)}</td>
        <td>${o.film_path ? `<button data-film="${esc(o.film_path)}">Preview</button>` : '—'}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">No orders yet.</td></tr>'}
    </table></div>
    <div id="film-preview"></div>
  </div>

  <div class="section grid g2">
    <div class="card stack">
      <h2>Music (licensed) ${badge(music.length, music.length ? 'ok' : 'warn')}</h2>
      <div class="small muted">Royalty-free or CC0 tracks only. Add a .txt file with the license for each track.</div>
      <div class="small">${music.map((m) => esc(m.name)).join(' · ') || 'None yet — films wait until you add at least one track.'}</div>
      <input type="file" id="music-file" accept="audio/*,.txt" multiple>
    </div>
    <div class="card stack">
      <h2>Sample photos for the test order ${badge(samples.length)}</h2>
      <div class="small muted">Upload 8–12 property photos you have rights to, then run the workflow with agent <span class="mono">villa_test_order</span>.</div>
      <input type="file" id="sample-file" accept="image/*" multiple>
    </div>
  </div>

  <div class="section"><h2>Prospects</h2>
    <div class="card scroll-x"><table class="table">
      <tr><th>Company</th><th>Email</th><th>Region</th><th>Stage</th><th>First sent</th><th>Source</th></tr>
      ${prospects.map((p) => `<tr><td><strong>${esc(p.company)}</strong>${p.hot ? ` ${badge('hot', 'warn')}` : ''}<div class="small muted">${esc((p.markets || []).join(', '))}</div></td>
        <td class="small">${esc(p.contact_email)}</td><td>${esc(p.region || p.country)}</td><td>${badge(p.stage)}</td><td class="num small">${ago(p.first_sent_at)}</td>
        <td class="small">${p.source_url ? `<a href="${esc(p.source_url.startsWith('http') ? p.source_url : '#')}" target="_blank" rel="noopener">source</a>` : '—'}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No prospects yet.</td></tr>'}
    </table></div>
    <details class="card" style="margin-top:12px"><summary>Add a prospect by hand</summary>
      <form id="prospect-form" class="grid g3" style="margin-top:10px">
        <div><label>Company</label><input name="company" required></div>
        <div><label>Role email (info@, reservations@ …)</label><input name="contact_email" type="email" required></div>
        <div><label>Website</label><input name="website" type="url"></div>
        <div><label>Region</label><select name="region">${Object.entries(REGIONS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
        <div><label>Markets (comma separated)</label><input name="markets"></div>
        <div><label>Where you found them (URL)</label><input name="source_url"></div>
        <div style="grid-column:1/-1"><label>What's notable about their portfolio (used to personalize)</label><input name="site_summary"></div>
        <div><button class="primary" type="submit">Add prospect</button></div>
      </form>
    </details>
    <details class="card" style="margin-top:12px"><summary>Directory pages to discover prospects from (${directories.length})</summary>
      <div class="small" style="margin-top:8px">${directories.map((d) => `${esc(d.name)} — ${esc(d.url)} ${badge(d.status)}`).join('<br>') || 'None yet.'}</div>
      <form id="directory-form" class="grid g3" style="margin-top:10px">
        <div><label>Name</label><input name="name" required></div>
        <div><label>Public directory URL</label><input name="url" type="url" required></div>
        <div><label>Region</label><select name="region">${Object.entries(REGIONS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
        <div><button type="submit">Add directory</button></div>
      </form>
    </details>
  </div>

  <div class="section grid g2">
    <div class="card"><h2>Recent messages</h2>
      <div class="list" style="margin-top:8px">${messages.map((m) => `<div class="item small"><span class="row">${badge(m.direction === 'in' ? 'in' : 'out', m.direction === 'in' ? 'info' : '')}${badge(m.kind)}${m.status === 'failed' ? badge('failed', 'bad') : ''}<span class="muted">${ago(m.created_at)}</span></span>
        <div>${esc(m.direction === 'in' ? m.from_email : m.to_email)} — ${esc(m.subject || '')}</div>
        ${m.body ? `<details><summary>Body</summary><div class="pre">${esc(m.body)}</div></details>` : ''}${m.error ? `<div class="muted">${esc(m.error)}</div>` : ''}</div>`).join('') || '<div class="empty">No messages yet.</div>'}</div>
    </div>
    <div class="card stack"><h2>Suppression list</h2>
      <div class="small">${suppression.map((s) => `${esc(s.email)} ${badge(s.reason)}`).join('<br>') || '<span class="muted">Empty.</span>'}</div>
      <form id="suppress-form" class="row"><input name="email" type="email" placeholder="never email this address" style="flex:1" required><button type="submit">Suppress</button></form>
    </div>
  </div>

  <div class="section"><h2>Spend this month</h2>
    <div class="card scroll-x"><table class="table num">
      <tr><th>When</th><th>Order</th><th>Kind</th><th>Purpose</th><th>Amount</th><th>Status</th></tr>
      ${spend.slice(0, 40).map((s) => `<tr><td>${when(s.at)}</td><td class="mono">${s.order_id ? s.order_id.slice(0, 8) : '—'}</td><td>${esc(s.kind)}</td><td>${esc(s.purpose)}</td><td>${money(s.amount_usd)}</td><td>${badge(s.status, s.status === 'charged' ? 'ok' : s.status === 'reserved' ? 'warn' : '')}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No spend yet.</td></tr>'}
    </table></div>
  </div>`;

  const refresh = () => window.hqRefresh();
  on(el, 'change', '[data-kv-bool]', (e, box) => act(null, async () => kvSet(box.dataset.kvBool, box.checked), 'Saved'));
  on(el, 'click', '[data-kv]', (e, btn) => act(btn, async () => { await kvSet(btn.dataset.kv, JSON.parse(btn.dataset.val)); refresh(); }, 'Saved'));
  on(el, 'change', '[data-kv-review]', (e, box) => act(null, () => kvSet('vc_review_mode', box.checked ? 'always' : 'auto'), 'Saved'));
  on(el, 'change', '[data-kv-sample]', (e, box) => act(null, () => kvSet('vc_sample_mode', box.checked ? 'auto' : 'off'), 'Saved'));
  on(el, 'change', '[data-country]', (e, box) => act(null, async () => {
    const cur = (await kvGet('vc_countries', {})) || {};
    cur[box.dataset.country] = box.checked;
    await kvSet('vc_countries', cur);
  }, 'Saved'));
  on(el, 'change', '[data-region]', (e, box) => act(null, async () => {
    const cur = (await kvGet('vc_us_regions', {})) || {};
    cur[box.dataset.region] = box.checked;
    await kvSet('vc_us_regions', cur);
  }, 'Saved'));
  on(el, 'submit', '#footer-form', (e, form) => { e.preventDefault(); act(form.querySelector('button'), () => kvSet('vc_footer_address', fdata(form).address.trim()), 'Footer saved'); });
  on(el, 'submit', '#suppress-form', (e, form) => { e.preventDefault(); act(form.querySelector('button'), async () => {
    await q(sb.from('vc_suppression').upsert({ email: fdata(form).email.trim().toLowerCase(), reason: 'manual' }));
    refresh();
  }, 'Suppressed'); });
  on(el, 'submit', '#prospect-form', (e, form) => { e.preventDefault(); const d = fdata(form); act(form.querySelector('button'), async () => {
    await q(sb.from('vc_prospects').insert({
      company: d.company, contact_email: d.contact_email.trim().toLowerCase(), website: d.website || null, region: d.region, country: 'US',
      markets: d.markets ? d.markets.split(',').map((s) => s.trim()).filter(Boolean) : [], source_url: d.source_url || 'manual', site_summary: d.site_summary || null,
    }));
    refresh();
  }, 'Prospect added'); });
  on(el, 'submit', '#directory-form', (e, form) => { e.preventDefault(); const d = fdata(form); act(form.querySelector('button'), async () => {
    await q(sb.from('sources').insert({ name: d.name, url: d.url, kind: 'directory', query: d.region, business: 'villa-cinema', added_by: 'bobby' }));
    refresh();
  }, 'Directory added'); });
  on(el, 'click', '[data-film]', (e, btn) => act(btn, async () => {
    const { data, error } = await sb.storage.from('vc-films').createSignedUrl(btn.dataset.film, 3600);
    if (error) throw error;
    el.querySelector('#film-preview').innerHTML = `<div class="card" style="margin-top:12px"><video src="${esc(data.signedUrl)}" controls autoplay></video></div>`;
  }));
  const upload = (input, bucket, prefix) => input.addEventListener('change', () => act(null, async () => {
    for (const f of input.files) {
      const name = `${prefix}${f.name.replace(/[^\w.-]+/g, '_')}`;
      const { error } = await sb.storage.from(bucket).upload(name, f, { upsert: true, contentType: f.type || undefined });
      if (error) throw error;
    }
    toast(`Uploaded ${input.files.length} file(s)`);
    refresh();
  }));
  upload(el.querySelector('#music-file'), 'vc-music', '');
  upload(el.querySelector('#sample-file'), 'vc-photos', '_samples/');
}
