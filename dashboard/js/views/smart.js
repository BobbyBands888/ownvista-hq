// "Smarter?" — is the system actually learning? Weekly scoreboard (agents/smart_score.js, daily 11pm ET)
// plus the failure backlog (agents/lib/failures.js): what failed or got rejected, why, and what's blocked from repeating.
import { esc, ago, badge, kvGet, spark } from '../core.js';

const TONE = { better: 'ok', worse: 'bad', flat: '', none: '', info: '' };
const LABEL = { better: 'getting better', worse: 'getting worse', flat: 'no change', none: 'not enough data', info: 'context' };
const fmtWeek = (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString([], { month: 'short', day: 'numeric' });

function val(m, w) {
  if (w.v == null) return '<span class="muted">—</span>';
  const v = m.unit === '%' ? `${w.v}%` : m.unit === '$' ? `$${Number(w.v).toFixed(2)}` : `${w.v}`;
  const n = m.unit === '%' || m.id === 'email_edit_size' ? `<div class="muted small">n=${w.n}</div>` : '';
  return `${esc(v)}${n}`;
}

function scoreSection(s) {
  if (!s) {
    return `<div class="card stack"><h2>Are the agents getting smarter?</h2>
      <p class="muted">No scoreboard yet. It runs daily at 11pm ET (or run the <code>smart_score</code> command).</p></div>`;
  }
  const weeks = s.metrics[0]?.weeks.map((w) => w.week) || [];
  const head = weeks.map((w, i) => `<th class="num">${i === weeks.length - 1 ? 'This week<div class="muted small">so far</div>' : fmtWeek(w)}</th>`).join('');
  const rows = s.metrics.map((m) => {
    const t = m.trend || {};
    const arrow = m.better === 'down' ? '↓ is better' : m.better === 'up' ? '↑ is better' : '';
    return `<tr>
      <td><strong>${esc(m.label)}</strong><div class="muted small">${esc(m.what)}${arrow ? ` (${arrow})` : ''}</div></td>
      <td>${badge(LABEL[t.verdict] || '—', TONE[t.verdict])}${t.note ? `<div class="muted small">${esc(t.note)}</div>` : ''}</td>
      <td style="min-width:110px">${spark(m.weeks.map((w) => w.v), { height: 30 })}</td>
      ${m.weeks.map((w) => `<td class="num">${val(m, w)}</td>`).join('')}
    </tr>`;
  }).join('');
  const tone = /^Smarter/.test(s.verdict) ? 'ok' : /^Not smarter/.test(s.verdict) ? 'bad' : '';
  return `<div class="card stack"><h2>Are the agents getting smarter?</h2>
    <div>${badge(tone === 'ok' ? 'yes' : tone === 'bad' ? 'no' : 'unclear', tone)} <span>${esc(s.verdict)}</span></div>
    <div class="small muted">Latest full week vs the weeks before it. A metric only counts with 5+ data points in a week. Updated ${ago(s.at)}${s.start?.day ? ` · starting point ${esc(s.start.day)}` : ''}.</div>
    <div style="overflow-x:auto"><table class="table"><thead><tr><th>Metric</th><th>Trend</th><th></th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    ${s.rule_breaks?.length ? `<details><summary class="small">Ideas that broke your rules (${s.rule_breaks.length})</summary>
      <table class="table"><tbody>${s.rule_breaks.map((b) => `<tr><td class="small">${fmtWeek(b.week)}</td><td>${esc(b.title)}</td><td class="small muted">${esc(b.why)}</td></tr>`).join('')}</tbody></table></details>` : ''}
  </div>`;
}

function failureSection(f) {
  const items = f?.items || [];
  if (!items.length) {
    return `<div class="card stack"><h2>Failure backlog</h2><p class="muted">Nothing logged yet. Autopilot builds this every hour from rejected ideas, killed launches and failed asset packs.</p></div>`;
  }
  const counts = Object.entries(f.counts || {}).sort((a, b) => b[1] - a[1]);
  const noReason = f.counts?.['rejected, no reason given'] || 0;
  return `<div class="card stack"><h2>Failure backlog</h2>
    <div class="small">Every failure is audited for a reason. The idea agents read this list, and Autopilot rejects any new idea that repeats one.</div>
    <div>${counts.map(([c, n]) => badge(`${c}: ${n}`, c === 'repeat of a failure' ? 'ok' : c === 'rejected, no reason given' ? 'warn' : '')).join(' ')}</div>
    ${noReason ? `<div class="small muted">${noReason} rejection${noReason === 1 ? ' has' : 's have'} no reason. The agents learn most when you add a one-line note when you reject.</div>` : ''}
    <div style="overflow-x:auto"><table class="table"><thead><tr><th>What</th><th>Why it failed</th><th>When</th></tr></thead><tbody>
      ${items.slice(0, 60).map((x) => `<tr><td>${esc(x.title)}<div class="muted small">${esc(x.kind)}</div></td>
        <td>${badge(x.category, x.category === 'repeat of a failure' ? 'ok' : x.category === 'broke a hard rule' ? 'bad' : '')}<div class="small">${esc(x.why)}</div></td>
        <td class="small muted">${ago(x.at)}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="small muted">Updated ${ago(f.at)}.</div>
  </div>`;
}

export async function render(el) {
  const [score, failures] = await Promise.all([kvGet('smart_score', null), kvGet('failure_log', null)]);
  el.innerHTML = `<div class="section">${scoreSection(score)}</div><div class="section">${failureSection(failures)}</div>`;
}
