import { sb, q, esc, ago, money, badge, on, act, gmailThread, md } from '../core.js';

export async function render(el) {
  const [approvals, flagged, drafts, ideas, tasks] = await Promise.all([
    q(sb.from('approvals').select('*').eq('status', 'pending').order('created_at', { ascending: false })),
    q(sb.from('emails').select('*').eq('needs_bobby', true).in('status', ['flagged', 'drafted']).order('received_at', { ascending: false }).limit(50)),
    q(sb.from('drafts').select('id,subject,to_address,business,created_at,gmail_thread_id').eq('status', 'open').order('created_at', { ascending: false }).limit(50)),
    q(sb.from('ideas').select('*').eq('status', 'proposed').order('created_at', { ascending: false }).limit(30)),
    q(sb.from('tasks').select('*').eq('assignee', 'bobby').neq('status', 'done').order('created_at', { ascending: false })),
  ]);

  const films = approvals.filter((a) => a.kind === 'film');
  const filmUrls = {};
  for (const f of films) {
    const order = await q(sb.from('vc_orders').select('film_path').eq('id', f.ref_id).maybeSingle());
    if (order?.film_path) {
      const { data } = await sb.storage.from('vc-films').createSignedUrl(order.film_path, 3600);
      filmUrls[f.id] = data?.signedUrl;
    }
  }

  const total = approvals.length + flagged.length + ideas.length + tasks.length;
  el.innerHTML = `
  <div class="head"><h1>Needs you <span class="muted">${total}</span></h1><div class="small muted">${drafts.length} Gmail draft(s) waiting in your Drafts folder</div></div>

  <div class="section"><h2>Approvals & alerts ${badge(approvals.length, approvals.length ? 'bad' : '')}</h2>
    <div class="card list">${approvals.map((a) => `
      <div class="item stack" data-id="${a.id}">
        <div class="row between"><strong>${esc(a.title)}</strong><span class="row">${badge(a.kind, a.kind.includes('pause') || a.kind === 'spend_cap' ? 'bad' : 'info')}${a.amount_usd != null ? badge(money(a.amount_usd), 'warn') : ''}<span class="small muted">${ago(a.created_at)}</span></span></div>
        ${a.detail ? `<div class="pre">${esc(a.detail)}</div>` : ''}
        ${filmUrls[a.id] ? `<video src="${esc(filmUrls[a.id])}" controls preload="metadata"></video>` : ''}
        <div class="row"><input data-note placeholder="Note (optional — the Learner reads it)" style="flex:1">
          <button class="ok" data-decide="approved">${a.kind === 'vc_paused' ? 'Resume sending' : a.kind === 'film' ? 'Approve & deliver' : 'Approve'}</button>
          <button class="danger" data-decide="rejected">Reject</button>
          <button data-decide="dismissed">Dismiss</button></div>
      </div>`).join('') || '<div class="empty">Nothing waiting.</div>'}
    </div>
  </div>

  <div class="section"><h2>Flagged email ${badge(flagged.length, flagged.length ? 'warn' : '')}</h2>
    <div class="card list">${flagged.map((m) => `
      <div class="item">
        <div class="row between"><strong>${esc(m.subject || '(no subject)')}</strong><span class="small muted">${ago(m.received_at)}</span></div>
        <div class="small muted">${esc(m.from_name || '')} &lt;${esc(m.from_address)}&gt; → ${esc(m.to_address)} · ${badge(m.business)}</div>
        <div class="small" style="margin-top:6px">${badge('needs Bobby', 'warn')} ${esc(m.flag_reason || '')}</div>
        <div class="row" style="margin-top:8px"><a class="btn" target="_blank" rel="noopener" href="${gmailThread(m.gmail_thread_id)}">Open in Gmail</a>
          <button data-handled="${m.id}">Mark handled</button></div>
      </div>`).join('') || '<div class="empty">No flagged mail.</div>'}
    </div>
  </div>

  <div class="section"><h2>New ideas ${badge(ideas.length)}</h2>
    <div class="card list">${ideas.map((i) => `
      <div class="item">
        <div class="row between"><strong>${esc(i.title)}</strong><span class="row">${badge(i.kind, 'info')}${i.score != null ? badge(`${i.score}/100`) : ''}</span></div>
        <div class="small muted" style="margin-top:4px">${md((i.summary || '').slice(0, 400))}</div>
        <div class="row" style="margin-top:6px"><a href="#ideas">Review in Ideas →</a></div>
      </div>`).join('') || '<div class="empty">No new ideas.</div>'}
    </div>
  </div>

  <div class="section"><h2>Your tasks ${badge(tasks.length)}</h2>
    <div class="card list">${tasks.map((t) => `
      <div class="item row between"><div><strong>${esc(t.title)}</strong><div class="small muted">${esc(t.detail || '').slice(0, 200)}</div></div>
      <button data-done="${t.id}">Done</button></div>`).join('') || '<div class="empty">No tasks for you.</div>'}
    </div>
  </div>`;

  on(el, 'click', '[data-decide]', (e, btn) => {
    const item = btn.closest('[data-id]');
    const note = item.querySelector('[data-note]').value.trim() || null;
    act(btn, async () => {
      const r = await q(sb.rpc('decide_approval', { p_id: item.dataset.id, p_decision: btn.dataset.decide, p_note: note }));
      if (r && r.ok === false) throw new Error(r.reason);
      window.hqRefresh();
    }, 'Saved');
  });
  on(el, 'click', '[data-handled]', (e, btn) => act(btn, async () => {
    await q(sb.from('emails').update({ status: 'handled', needs_bobby: false }).eq('id', btn.dataset.handled));
    window.hqRefresh();
  }, 'Marked handled'));
  on(el, 'click', '[data-done]', (e, btn) => act(btn, async () => {
    await q(sb.from('tasks').update({ status: 'done', updated_at: new Date().toISOString() }).eq('id', btn.dataset.done));
    window.hqRefresh();
  }, 'Done'));
}
