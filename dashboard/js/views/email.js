import { sb, q, esc, ago, pct, badge, on, act, gmailThread } from '../core.js';

export async function render(el) {
  const [open, sent] = await Promise.all([
    q(sb.from('drafts').select('*, emails(from_name,from_address,needs_bobby,flag_reason)').eq('status', 'open').order('created_at', { ascending: false }).limit(60)),
    q(sb.from('drafts').select('*').eq('status', 'sent').order('sent_at', { ascending: false }).limit(20)),
  ]);

  el.innerHTML = `
  <div class="head"><h1>Email</h1><div class="small muted">Drafts are saved in Gmail. Nothing is ever sent from here.</div></div>

  <div class="section"><h2>Open drafts ${badge(open.length)}</h2>
    <div class="list">${open.map((d) => `
      <div class="card stack" data-id="${d.id}">
        <div class="row between"><strong>${esc(d.subject)}</strong><span class="row">${badge(d.business)}${d.emails?.needs_bobby ? badge('needs Bobby', 'warn') : ''}${d.grade ? badge(`grade ${d.grade}/5`, d.grade >= 4 ? 'ok' : 'warn') : ''}<span class="small muted">${ago(d.created_at)}</span></span></div>
        <div class="small muted">To ${esc(d.to_address || '')}${d.emails?.flag_reason ? ` · ${esc(d.emails.flag_reason)}` : ''}</div>
        <div class="pre">${esc(d.body)}</div>
        ${d.grade_notes ? `<div class="small muted">Learner: ${esc(d.grade_notes)}</div>` : ''}
        <div class="row">${d.gmail_thread_id ? `<a class="btn primary" target="_blank" rel="noopener" href="${gmailThread(d.gmail_thread_id)}">Open in Gmail</a>` : ''}</div>
        <details><summary>Correct the voice</summary>
          <div class="stack" style="margin-top:8px">
            <textarea data-rule placeholder="e.g. Never start with 'Thanks for reaching out'. Put the price question last."></textarea>
            <button data-save-rule>Save as a playbook rule</button>
          </div>
        </details>
      </div>`).join('') || '<div class="card empty">No open drafts.</div>'}
    </div>
  </div>

  <div class="section"><h2>What you actually sent</h2>
    <div class="card scroll-x"><table class="table">
      <tr><th>Subject</th><th>Business</th><th>Sent</th><th>Changed</th></tr>
      ${sent.map((d) => `<tr><td><details><summary>${esc(d.subject)}</summary><div class="grid g2" style="margin-top:8px"><div><label>Draft</label><div class="pre">${esc(d.body)}</div></div><div><label>You sent</label><div class="pre">${esc(d.sent_body || '')}</div></div></div></details></td>
        <td>${esc(d.business || '')}</td><td class="num">${ago(d.sent_at)}</td><td class="num">${d.edit_distance < 0.05 ? badge('unedited', 'ok') : pct(d.edit_distance)}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">Nothing sent from drafts yet.</td></tr>'}
    </table></div>
  </div>`;

  on(el, 'click', '[data-save-rule]', (e, btn) => {
    const card = btn.closest('[data-id]');
    const text = card.querySelector('[data-rule]').value.trim();
    if (!text) return;
    act(btn, async () => {
      await q(sb.from('playbook_rules').insert({ rule: text, category: 'voice', origin: 'correction', evidence: `Correction on draft ${card.dataset.id}` }));
      await q(sb.from('feedback').insert({ kind: 'voice_correction', text, ref_table: 'drafts', ref_id: card.dataset.id }));
      card.querySelector('[data-rule]').value = '';
    }, 'Rule saved — every agent uses it from the next run');
  });
}
