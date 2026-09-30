import { sb, q, esc, ago, when, badge, on, act, kvGet, kvSet } from '../core.js';

const CATEGORIES = ['voice', 'growth', 'scout', 'lab', 'villa', 'guardrails'];

async function snapshot(reason) {
  const version = Number(await kvGet('playbook_version', 1)) + 1;
  const [sections, rules] = await Promise.all([
    q(sb.from('playbook').select('section,content')),
    q(sb.from('playbook_rules').select('rule,category,origin').eq('active', true)),
  ]);
  await q(sb.from('playbook_versions').insert({ version, reason, snapshot: { sections: Object.fromEntries(sections.map((s) => [s.section, s.content])), rules } }));
  await kvSet('playbook_version', version);
}

export async function render(el) {
  const [sections, rules, versions, version] = await Promise.all([
    q(sb.from('playbook').select('*').order('sort')),
    q(sb.from('playbook_rules').select('*').order('active', { ascending: false }).order('created_at', { ascending: false }).limit(200)),
    q(sb.from('playbook_versions').select('*').order('version', { ascending: false }).limit(30)),
    kvGet('playbook_version', 1),
  ]);
  const active = rules.filter((r) => r.active);

  el.innerHTML = `
  <div class="head"><h1>Playbook <span class="muted">v${esc(version)}</span></h1><div class="small muted">Every agent reads this before it writes. Guardrails are also enforced in code.</div></div>
  <div class="grid g2">${sections.map((s) => `
    <form class="card stack" data-section="${esc(s.section)}">
      <div class="row between"><h2>${esc(s.title)}</h2><span class="small muted">edited ${ago(s.updated_at)}</span></div>
      <textarea name="content" rows="${Math.min(16, Math.max(6, s.content.split('\n').length + 1))}">${esc(s.content)}</textarea>
      <div><button type="submit">Save</button></div>
    </form>`).join('')}
  </div>

  <div class="section"><h2>Rules ${badge(`${active.length} active`, active.length > 40 ? 'warn' : 'info')}</h2>
    <form id="add-rule" class="card row">
      <input name="rule" placeholder="Add a rule by hand (manual rules are never merged away)" style="flex:1" required>
      <select name="category" style="width:auto">${CATEGORIES.map((c) => `<option>${c}</option>`).join('')}</select>
      <button class="primary" type="submit">Add</button>
    </form>
    <div class="card list" style="margin-top:12px">${rules.map((r) => `
      <div class="item row between" data-id="${r.id}">
        <div style="flex:1;min-width:0"><div class="${r.active ? '' : 'muted'}">${esc(r.rule)}</div>
          <div class="small muted">${badge(r.category)} ${badge(r.origin, r.origin === 'correction' || r.origin === 'manual' ? 'warn' : 'info')} ${ago(r.created_at)}${r.evidence ? ` · ${esc(r.evidence).slice(0, 140)}` : ''}</div></div>
        <label class="toggle small"><input type="checkbox" data-active ${r.active ? 'checked' : ''}> active</label>
      </div>`).join('') || '<div class="empty">No learned rules yet. They appear after the Learner runs and after you correct a draft.</div>'}
    </div>
  </div>

  <div class="section"><h2>History</h2>
    <div class="card list">${versions.map((v) => `<div class="item"><details><summary>v${v.version} · ${when(v.created_at)} · ${esc(v.reason || '')}</summary>
      <div class="pre">${esc(Object.entries(v.snapshot?.sections || {}).map(([k, c]) => `## ${k}\n${c}`).join('\n\n'))}\n\n## Rules\n${esc((v.snapshot?.rules || []).map((r) => `- [${r.category}] ${r.rule}`).join('\n'))}</div></details></div>`).join('')}
    </div>
  </div>`;

  on(el, 'submit', '[data-section]', (e, form) => {
    e.preventDefault();
    act(form.querySelector('button'), async () => {
      await q(sb.from('playbook').update({ content: form.content.value, updated_at: new Date().toISOString() }).eq('section', form.dataset.section));
      await snapshot(`Bobby edited ${form.dataset.section}`);
      window.hqRefresh();
    }, 'Saved — new playbook version');
  });
  on(el, 'submit', '#add-rule', (e, form) => {
    e.preventDefault();
    act(form.querySelector('button'), async () => {
      await q(sb.from('playbook_rules').insert({ rule: form.rule.value.trim(), category: form.category.value, origin: 'manual' }));
      await snapshot('Bobby added a rule');
      window.hqRefresh();
    }, 'Rule added');
  });
  on(el, 'change', '[data-active]', (e, box) => act(null, async () => {
    await q(sb.from('playbook_rules').update({ active: box.checked }).eq('id', box.closest('[data-id]').dataset.id));
    await snapshot(`Bobby ${box.checked ? 'enabled' : 'disabled'} a rule`);
  }, 'Saved'));
}
