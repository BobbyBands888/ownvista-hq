// "Smarter?" — the HQ brain as a game character. Stats come from the weekly scoreboard
// (agents/smart_score.js, daily 11pm ET); the Graveyard is the failure backlog (agents/lib/failures.js).
// Every number on screen is a real logged result; nothing here is decoration-only.
import { esc, ago, badge, kvGet } from '../core.js';

const FONT = 'https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap';
const CSS = `
.gm { background:#05070d; color:#d7e0ff; border:2px solid #2a3350; border-radius:10px; padding:16px; box-shadow:0 0 0 1px rgba(80,120,255,.15),0 8px 30px rgba(40,70,200,.18); }
.gm * { box-sizing:border-box; }
.gm-px { font-family:'Press Start 2P',ui-monospace,monospace; letter-spacing:.5px; }
.gm h2 { margin:0; font-size:15px; line-height:1.5; color:#ffd84a; text-shadow:2px 2px 0 #7a4b00; }
.gm h3 { margin:0 0 8px; font-size:11px; color:#8fb0ff; }
.gm-sub { font-size:12px; color:#8b95b8; }
.gm-top { display:flex; flex-wrap:wrap; gap:14px; align-items:center; justify-content:space-between; }
.gm-lvl { display:flex; gap:12px; align-items:center; }
.gm-badge { width:64px; height:64px; display:grid; place-items:center; border:3px solid #ffd84a; background:#1a1430; color:#ffd84a; font-size:20px; image-rendering:pixelated; box-shadow:4px 4px 0 #000; }
.gm-xp { width:220px; max-width:60vw; height:14px; border:2px solid #d7e0ff; background:#111830; position:relative; margin-top:6px; }
.gm-xp span { position:absolute; inset:0 auto 0 0; background:repeating-linear-gradient(90deg,#4cc27f 0 8px,#3aa36a 8px 10px); }
.gm-banner { margin:14px 0; padding:10px 12px; border:2px dashed; font-size:11px; line-height:1.7; }
.gm-banner.up { border-color:#4cc27f; color:#4cc27f; } .gm-banner.down { border-color:#ff6b5f; color:#ff6b5f; } .gm-banner.wait { border-color:#e6a53d; color:#e6a53d; }
.gm-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:10px; }
.gm-stat { border:2px solid #2a3350; background:#0b1022; padding:10px; }
.gm-stat .row1 { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.gm-stat .nm { font-size:10px; color:#d7e0ff; } .gm-stat .val { font-size:12px; color:#fff; }
.gm-bar { height:12px; border:2px solid #3a4670; background:#111830; margin:8px 0 6px; }
.gm-bar span { display:block; height:100%; }
.gm-bar.hi span { background:#4cc27f; } .gm-bar.mid span { background:#e6a53d; } .gm-bar.lo span { background:#ff6b5f; }
.gm-locked { opacity:.55; } .gm-locked .gm-bar { border-style:dashed; }
.gm-trend { font-size:11px; } .gm-trend.up { color:#4cc27f; } .gm-trend.down { color:#ff6b5f; } .gm-trend.flat { color:#8b95b8; }
.gm-loot { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
.gm-coin { flex:1 1 140px; border:2px solid #2a3350; background:#0b1022; padding:10px; }
.gm-coin .big { font-size:14px; color:#ffd84a; margin-top:6px; }
.gm-grave { margin-top:16px; }
.gm-enemies { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }
.gm-enemy { font-size:9px; padding:6px 8px; border:2px solid #3a4670; background:#111830; }
.gm-enemy.rule { border-color:#ff6b5f; color:#ff6b5f; } .gm-enemy.shield { border-color:#4cc27f; color:#4cc27f; } .gm-enemy.quiet { border-color:#e6a53d; color:#e6a53d; }
.gm-tomb { display:grid; grid-template-columns:22px 1fr; gap:8px; padding:8px 0; border-top:1px solid #1d2642; font-size:13px; }
.gm-tomb .why { color:#8b95b8; font-size:12px; margin-top:2px; }
.gm details { margin-top:14px; } .gm summary { cursor:pointer; font-size:10px; color:#8fb0ff; }
.gm table { width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }
.gm th, .gm td { padding:6px; border-bottom:1px solid #1d2642; text-align:right; white-space:nowrap; } .gm th:first-child, .gm td:first-child { text-align:left; white-space:normal; }
.gm th { color:#8b95b8; font-weight:600; }
`;

// Each scoreboard metric as a stat. flip: shown as 100 − value so a fuller bar is always better.
const STATS = [
  ['idea_reject', 'WISDOM', 'flip', 'Ideas you accept'],
  ['idea_rulebreak', 'DISCIPLINE', 'flip', 'Ideas that follow your rules'],
  ['idea_repeat', 'MEMORY', 'flip', 'Ideas that don\'t repeat a failure'],
  ['image_pass', 'CRAFT', 'keep', 'Images passing QA'],
  ['product_first_pass', 'QUALITY', 'keep', 'Products passing on try 1'],
  ['email_edited', 'VOICE', 'flip', 'Emails sent without your edits'],
];

const fmtWeek = (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString([], { month: 'short', day: 'numeric' });

// The newest week with data, and the week before that one with data.
function latest(m) {
  const withData = m.weeks.filter((w) => w.v != null && w.n > 0);
  return { now: withData[withData.length - 1] || null, prev: withData[withData.length - 2] || null };
}

function statCard(m, [, name, mode, plain]) {
  const { now, prev } = latest(m);
  const show = (w) => (w ? (mode === 'flip' ? Math.max(0, 100 - w.v) : w.v) : null);
  const v = show(now);
  if (v == null) {
    return `<div class="gm-stat gm-locked"><div class="row1"><span class="nm gm-px">${name}</span><span class="val gm-px">LOCKED</span></div>
      <div class="gm-bar"><span style="width:0"></span></div><div class="gm-sub">${esc(plain)} · no data yet</div></div>`;
  }
  const tier = v >= 70 ? 'hi' : v >= 40 ? 'mid' : 'lo';
  const p = show(prev);
  const d = p == null ? null : Math.round((v - p) * 10) / 10;
  const trend = d == null ? '<span class="gm-trend flat">first reading</span>'
    : Math.abs(d) < 5 ? '<span class="gm-trend flat">= steady</span>'
      : d > 0 ? `<span class="gm-trend up">▲ +${d} since ${fmtWeek(prev.week)}</span>` : `<span class="gm-trend down">▼ ${d} since ${fmtWeek(prev.week)}</span>`;
  return `<div class="gm-stat"><div class="row1"><span class="nm gm-px">${name}</span><span class="val gm-px">${Math.round(v)}</span></div>
    <div class="gm-bar ${tier}"><span style="width:${Math.min(100, v)}%"></span></div>
    <div class="row1"><span class="gm-sub">${esc(plain)} · ${now.n} counted</span>${trend}</div></div>`;
}

function hero(s) {
  const byId = Object.fromEntries((s?.metrics || []).map((m) => [m.id, m]));
  const vals = STATS.map(([id, , mode]) => { const n = byId[id] && latest(byId[id]).now; return n ? (mode === 'flip' ? 100 - n.v : n.v) : null; }).filter((x) => x != null);
  const power = vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : 0;
  const level = Math.max(1, Math.floor(power / 10));
  const sum = (id) => (byId[id]?.weeks || []).reduce((a, w) => a + (Number(w.v) || 0), 0);
  const gold = sum('revenue');
  const tone = /^Smarter/.test(s?.verdict || '') ? 'up' : /^Not smarter/.test(s?.verdict || '') ? 'down' : 'wait';
  const head = tone === 'up' ? 'LEVEL UP!' : tone === 'down' ? 'LOSING XP' : 'TRAINING…';
  return `<div class="gm-top">
      <div class="gm-lvl"><div class="gm-badge gm-px">${level}</div>
        <div><h2 class="gm-px">HQ BRAIN</h2><div class="gm-sub">Level ${level} · power ${power}/100 (average of the stats below)</div>
          <div class="gm-xp" title="${power}%"><span style="width:${power}%"></span></div></div></div>
      <div class="gm-sub">Updated ${ago(s?.at)}${s?.start?.day ? `<br>Save point ${esc(s.start.day)}` : ''}</div>
    </div>
    <div class="gm-banner ${tone} gm-px">${head}<div class="gm-sub" style="margin-top:6px;font-family:inherit;color:inherit">${esc(s?.verdict || 'No scoreboard yet. It runs daily at 11pm ET.')}</div></div>
    <div class="gm-grid">${STATS.map((st) => (byId[st[0]] ? statCard(byId[st[0]], st) : '')).join('')}</div>
    <div class="gm-loot">
      <div class="gm-coin"><div class="gm-px" style="font-size:9px">GOLD (8 WKS)</div><div class="big gm-px">$${gold.toFixed(2)}</div><div class="gm-sub">Stripe, itch and KDP royalties</div></div>
      <div class="gm-coin"><div class="gm-px" style="font-size:9px">LAUNCHES</div><div class="big gm-px">${sum('launches')}</div><div class="gm-sub">Offers and packs gone live</div></div>
      <div class="gm-coin"><div class="gm-px" style="font-size:9px">LESSONS</div><div class="big gm-px">${sum('lessons')}</div><div class="gm-sub">Rules + feedback to learn from</div></div>
    </div>`;
}

function graveyard(f) {
  const items = f?.items || [];
  const c = f?.counts || {};
  const enemy = (label, n, cls) => (n ? `<span class="gm-enemy gm-px ${cls}">${label} ×${n}</span>` : '');
  return `<div class="gm-grave"><h3 class="gm-px">GRAVEYARD · ${items.length} FALLEN IDEAS</h3>
    <div class="gm-sub" style="margin-bottom:8px">Every failure is audited. The idea agents study this list; Autopilot blocks any idea that repeats one.</div>
    <div class="gm-enemies">
      ${enemy('RULE BREAK', c['broke a hard rule'], 'rule')}${enemy('REJECTED', c['rejected by Bobby'], '')}
      ${enemy('NO SALES', c['did not sell'], '')}${enemy('BAD ART', c['failed quality'], '')}
      ${enemy('NO REASON', c['rejected, no reason given'], 'quiet')}${enemy('REPEATS BLOCKED', c['repeat of a failure'], 'shield')}
    </div>
    ${c['rejected, no reason given'] ? '<div class="gm-sub" style="color:#e6a53d;margin-bottom:6px">Tip: a one-line note when you reject gives the agents a lesson. "No reason" teaches nothing.</div>' : ''}
    ${items.length ? items.slice(0, 25).map((x) => `<div class="gm-tomb"><span>${x.category === 'repeat of a failure' ? '🛡' : '🪦'}</span>
      <div>${esc(x.title)} <span class="gm-sub">· ${esc(x.kind)} · ${ago(x.at)}</span><div class="why">${esc(x.category)}: ${esc(x.why)}</div></div></div>`).join('')
    : '<div class="gm-sub">Empty. Nothing has failed yet.</div>'}
  </div>`;
}

function fullStats(s) {
  if (!s?.metrics?.length) return '';
  const weeks = s.metrics[0].weeks.map((w) => w.week);
  const cell = (m, w) => (w.v == null ? '—' : m.unit === '%' ? `${w.v}%` : m.unit === '$' ? `$${Number(w.v).toFixed(2)}` : `${w.v}`);
  return `<details><summary class="gm-px">FULL STATS BY WEEK</summary><div style="overflow-x:auto"><table>
    <thead><tr><th>Metric</th>${weeks.map((w, i) => `<th>${i === weeks.length - 1 ? 'Now' : fmtWeek(w)}</th>`).join('')}</tr></thead>
    <tbody>${s.metrics.map((m) => `<tr><td>${esc(m.label)}</td>${m.weeks.map((w) => `<td>${cell(m, w)}</td>`).join('')}</tr>`).join('')}</tbody>
  </table></div>
  ${s.rule_breaks?.length ? `<div class="gm-sub" style="margin-top:8px">Rule breaks: ${s.rule_breaks.map((b) => `${esc(b.title)} (${esc(b.why)})`).join(' · ')}</div>` : ''}</details>`;
}

export async function render(el) {
  if (!document.getElementById('gm-font')) {
    const l = document.createElement('link'); l.id = 'gm-font'; l.rel = 'stylesheet'; l.href = FONT; document.head.appendChild(l);
  }
  const [score, failures] = await Promise.all([kvGet('smart_score', null), kvGet('failure_log', null)]);
  el.innerHTML = `<style>${CSS}</style><div class="gm">${hero(score)}${graveyard(failures)}${fullStats(score)}</div>
    <div class="small muted" style="margin-top:8px">${badge('honest mode')} Stats use the newest week with data vs the one before it. The official yes/no verdict only counts weeks with 5+ data points.</div>`;
}
