// Shop: what the crew is selling. Launches (live pages + Stripe links) and Asset Studio packs for itch.io.
import { sb, q, esc, ago, money, badge, on, act, toast } from '../core.js';

const BUCKET = 'asset-packs';
const TONE = { live: 'ok', killed: 'bad', needs_bobby: 'warn', waiting_key: 'warn', draft: 'info', ready: 'ok', published: 'ok', generating: 'info', packaging: 'info', planned: 'info', rejected: 'bad' };
const LABEL = { waiting_key: 'waiting for Stripe key', needs_bobby: 'needs you', generating: 'making images', packaging: 'packaging', ready: 'ready to publish' };

async function signed(path, secs = 3600) {
  if (!path) return null;
  const { data } = await sb.storage.from(BUCKET).createSignedUrl(path, secs);
  return data?.signedUrl || null;
}

export async function render(el) {
  let launches = [], packs = [], studio = null, tablesMissing = false;
  try {
    [launches, packs, studio] = await Promise.all([
      q(sb.from('launches').select('*, experiments(ends_on,starts_on,status)').order('created_at', { ascending: false }).limit(50)),
      q(sb.from('asset_packs').select('*').order('created_at', { ascending: false }).limit(40)),
      q(sb.from('agents').select('id,enabled,last_summary,last_run_at').eq('id', 'asset_studio').maybeSingle()),
    ]);
  } catch (e) { tablesMissing = true; }

  if (tablesMissing) {
    el.innerHTML = `<div class="head"><h1>Shop</h1></div><div class="card"><h2>One database update needed</h2>
      <p class="muted small">Run the Launcher + Asset Studio SQL block in Supabase once. Claude has it ready for you.</p></div>`;
    return;
  }

  const live = launches.filter((l) => l.status === 'live');
  const sales = launches.reduce((n, l) => n + l.sales, 0) + packs.reduce((n, p) => n + p.sales, 0);
  const revenue = launches.reduce((n, l) => n + Number(l.revenue), 0) + packs.reduce((n, p) => n + Number(p.revenue), 0);
  const ready = packs.filter((p) => p.status === 'ready');
  const previews = Object.fromEntries(await Promise.all(packs.filter((p) => p.preview_path && ['ready', 'published'].includes(p.status)).map(async (p) => [p.id, await signed(p.preview_path)])));
  const today = new Date().toISOString().slice(0, 10);
  const daysLeft = (l) => (l.experiments?.ends_on ? Math.round((Date.parse(l.experiments.ends_on) - Date.parse(today)) / 86400000) : null);

  el.innerHTML = `
  <div class="head"><h1>Shop</h1><div class="small muted">Launcher and Asset Studio run every hour</div></div>
  <div class="st-hud">
    <div class="st-chip"><span>Live offers</span><strong class="num">${live.length}</strong></div>
    <div class="st-chip"><span>Sales (all time)</span><strong class="num">${sales}</strong></div>
    <div class="st-chip"><span>Revenue</span><strong class="num">${money(revenue)}</strong></div>
    <div class="st-chip ${ready.length ? 'alert' : ''}"><span>Packs to publish</span><strong class="num">${ready.length}</strong></div>
  </div>

  <div class="section"><h2>Offers</h2>
    <div class="list" style="margin-top:8px">${launches.map((l) => `
      <div class="card stack">
        <div class="row between"><h3>${esc(l.title)}</h3><span class="row">${badge(LABEL[l.status] || l.status, TONE[l.status])}${l.price_usd ? badge(money(l.price_usd), 'info') : ''}</span></div>
        <div class="small num">Sales <strong>${l.sales}</strong> / goal ${l.goal_sales} · ${money(l.revenue)}${l.status === 'live' && daysLeft(l) != null ? ` · ${daysLeft(l)} day(s) left before the kill rule` : ''}${l.launched_at ? ` · launched ${ago(l.launched_at)}` : ''}</div>
        ${l.status === 'live' || l.status === 'killed' ? `<div class="small"><a href="/p/${esc(l.slug)}" target="_blank" rel="noopener">levelingclips.com/p/${esc(l.slug)}</a></div>` : ''}
        ${l.note ? `<div class="small muted">${esc(l.note)}</div>` : ''}
        ${l.status === 'waiting_key' ? '<div class="small muted">Ready to go live the hour after the Stripe launch key is saved.</div>' : ''}
      </div>`).join('') || '<div class="card empty">No offers yet. Approve a business idea and the crew builds and launches it.</div>'}
    </div>
  </div>

  <div class="section"><div class="row between"><h2>Asset Studio packs</h2>
      <label class="small" style="display:flex;gap:6px;align-items:center;margin:0">${studio ? `<input type="checkbox" id="studio-on" ${studio.enabled ? 'checked' : ''}> Asset Studio on` : ''}</label></div>
    ${studio?.last_summary ? `<div class="small muted" style="margin-top:4px">Last run ${ago(studio.last_run_at)}: ${esc(studio.last_summary)}</div>` : ''}
    <div class="list" style="margin-top:8px">${packs.map((p) => {
      const done = (p.items || []).filter((i) => i.done).length;
      return `<div class="card stack" data-pack="${p.id}">
        <div class="row between"><h3>${esc(p.title)}</h3><span class="row">${badge(LABEL[p.status] || p.status, TONE[p.status])}${badge(money(p.price_usd), 'info')}</span></div>
        <div class="small muted">${esc(p.theme || '')}</div>
        ${['generating', 'packaging'].includes(p.status) ? `<div class="small num">${done}/${(p.items || []).length} images passed QA · ${p.images_made} generated</div><div class="meter"><div style="width:${Math.round((done / Math.max(1, (p.items || []).length)) * 100)}%"></div></div>` : ''}
        ${previews[p.id] ? `<img src="${esc(previews[p.id])}" alt="Preview of ${esc(p.title)}" style="width:100%;max-width:640px;border-radius:8px;background:#111827">` : ''}
        ${['published', 'killed'].includes(p.status) || p.itch_url ? `<div class="small num">Views ${p.views} · downloads ${p.downloads} · sales ${p.sales} · ${money(p.revenue)}${p.itch_url ? ` · <a href="${esc(p.itch_url)}" target="_blank" rel="noopener">itch.io page</a>` : ''}</div>` : ''}
        ${p.status === 'ready' ? `
          <ol class="small">
            <li><button data-act="zip">Download the zip</button></li>
            <li>Go to <a href="https://itch.io/game/new" target="_blank" rel="noopener">itch.io/game/new</a>. Kind: <strong>Assets</strong>. Title: <strong>${esc(p.title)}</strong>. Pricing: <strong>$${esc(p.price_usd)}</strong> minimum. Upload the zip.</li>
            <li>Paste the description below. In the AI section, tick <strong>AI-generated graphics</strong>. Tags: ${esc((p.tags || []).join(', '))}.</li>
            <li>Upload the preview image as the cover, publish, then paste the page link here.</li>
          </ol>
          <details><summary>Page description</summary><textarea readonly rows="10" style="width:100%" data-copy>${esc(p.page_copy)}</textarea><button data-act="copy">Copy description</button></details>
          <div class="row"><input data-url placeholder="https://yourname.itch.io/pack-name" style="flex:1"><button class="ok" data-act="published">Save link</button><button class="danger" data-act="reject">Reject pack</button></div>` : ''}
        ${p.feedback ? `<div class="small muted">Note: ${esc(p.feedback)}</div>` : ''}
      </div>`;
    }).join('') || `<div class="card empty">No packs yet. ${studio?.last_summary ? esc(studio.last_summary) : 'Once Cloudflare is connected the Asset Studio starts on its own.'}</div>`}
    </div>
  </div>`;

  el.querySelector('#studio-on')?.addEventListener('change', (e) => act(null, async () => {
    await q(sb.from('agents').update({ enabled: e.target.checked }).eq('id', 'asset_studio'));
  }, e.target.checked ? 'Asset Studio on' : 'Asset Studio paused'));

  on(el, 'click', '[data-act]', (e, btn) => {
    const card = btn.closest('[data-pack]');
    const p = packs.find((x) => x.id === card?.dataset.pack);
    if (!p) return;
    const what = btn.dataset.act;
    if (what === 'copy') {
      navigator.clipboard?.writeText(p.page_copy || '').then(() => toast('Copied'), () => { card.querySelector('[data-copy]').select(); toast('Press Cmd+C to copy'); });
      return;
    }
    act(btn, async () => {
      if (what === 'zip') {
        const url = await signed(p.zip_path, 600);
        if (!url) throw new Error('Zip not found');
        location.href = url;
        return;
      }
      if (what === 'published') {
        const url = card.querySelector('[data-url]').value.trim();
        if (!/^https:\/\/[a-z0-9-]+\.itch\.io\/[a-z0-9-_]+\/?$/i.test(url)) throw new Error('Paste the itch.io page link, like https://yourname.itch.io/pack-name');
        await q(sb.from('asset_packs').update({ itch_url: url, status: 'published', published_at: new Date().toISOString() }).eq('id', p.id));
      } else if (what === 'reject') {
        const note = prompt('Why? (the crew learns from it)') || null;
        await q(sb.from('asset_packs').update({ status: 'rejected', feedback: note }).eq('id', p.id));
        if (note) await q(sb.from('feedback').insert({ kind: 'asset_pack_rejected', text: `Bobby rejected pack "${p.title}": ${note}`, ref_table: 'asset_packs', ref_id: p.id }));
      }
      window.hqRefresh();
    }, what === 'zip' ? null : 'Saved');
  });
}
