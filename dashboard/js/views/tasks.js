import { sb, q, esc, ago, badge, on, act, fdata, md, BUSINESSES } from '../core.js';

const COLS = [['todo', 'To do'], ['doing', 'Doing'], ['blocked', 'Blocked'], ['done', 'Done']];

export async function render(el) {
  const tasks = await q(sb.from('tasks').select('*').order('updated_at', { ascending: false }).limit(200));
  el.innerHTML = `
  <div class="head"><h1>Tasks</h1></div>
  <details class="card"><summary>New task</summary>
    <form id="task-form" class="grid g2" style="margin-top:10px">
      <div><label>Title</label><input name="title" required></div>
      <div><label>Business</label><select name="business"><option value="">any</option>${BUSINESSES.map((b) => `<option>${b}</option>`).join('')}</select></div>
      <div style="grid-column:1/-1"><label>Detail</label><textarea name="detail"></textarea></div>
      <div><label>Assign to</label><select name="assignee"><option value="agent">Agent (Operator works it)</option><option value="bobby">Bobby</option></select></div>
      <div style="align-self:end"><button class="primary" type="submit">Add task</button></div>
    </form>
  </details>
  <div class="board section">${COLS.map(([k, label]) => {
    const list = tasks.filter((t) => t.status === k).slice(0, k === 'done' ? 20 : 100);
    return `<div class="col"><h3>${label} <span class="muted">${list.length}</span></h3>${list.map((t) => `
      <div class="card small stack" data-id="${t.id}">
        <strong>${esc(t.title)}</strong>
        <div class="row">${badge(t.assignee, t.assignee === 'agent' ? 'info' : 'warn')}${t.business ? badge(t.business) : ''}<span class="muted">${ago(t.updated_at)}</span></div>
        ${t.detail ? `<div class="muted">${esc(t.detail).slice(0, 240)}</div>` : ''}
        ${t.result ? `<details><summary>Result</summary><div class="pre">${md(t.result)}</div></details>` : ''}
        <div class="row">
          <select data-move>${COLS.map(([s, l]) => `<option value="${s}" ${s === t.status ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <button data-assign="${t.assignee === 'agent' ? 'bobby' : 'agent'}">→ ${t.assignee === 'agent' ? 'Bobby' : 'Agent'}</button>
        </div>
      </div>`).join('')}</div>`;
  }).join('')}</div>`;

  on(el, 'submit', '#task-form', (e, form) => {
    e.preventDefault();
    const d = fdata(form);
    act(form.querySelector('button'), async () => {
      await q(sb.from('tasks').insert({ title: d.title, detail: d.detail || null, business: d.business || null, assignee: d.assignee, created_by: 'bobby' }));
      window.hqRefresh();
    }, 'Task added');
  });
  on(el, 'change', '[data-move]', (e, sel) => act(null, async () => {
    await q(sb.from('tasks').update({ status: sel.value, updated_at: new Date().toISOString() }).eq('id', sel.closest('[data-id]').dataset.id));
    window.hqRefresh();
  }, 'Moved'));
  on(el, 'click', '[data-assign]', (e, btn) => act(btn, async () => {
    await q(sb.from('tasks').update({ assignee: btn.dataset.assign, status: 'todo', updated_at: new Date().toISOString() }).eq('id', btn.closest('[data-id]').dataset.id));
    window.hqRefresh();
  }, 'Reassigned'));
}
