// Station: a game-style view of Ownvista HQ. A pixel-art space station drawn in code (no image assets),
// with one crew member per agent. Characters walk and work while their agent is running, show a red "!"
// after a failed run and sleep when paused. Left: crew roster with levels. Right: decisions waiting and live feed.
import { sb, q, count, esc, ago, money, on, act } from '../core.js';

const W = 480, H = 300, S = 3; // logical pixels, scale factor

// ---------- Map ----------
const ROOMS = {
  lab:     { x: 20,  y: 20,  w: 130, h: 80, name: 'RESEARCH LAB', floor: '#1d2b45' },
  war:     { x: 330, y: 20,  w: 130, h: 80, name: 'WAR ROOM',     floor: '#2a2140' },
  mail:    { x: 20,  y: 120, w: 110, h: 70, name: 'MAILROOM',     floor: '#1f3334' },
  deck:    { x: 175, y: 105, w: 130, h: 90, name: 'COMMAND DECK', floor: '#232a3a' },
  numbers: { x: 350, y: 120, w: 110, h: 70, name: 'NUMBERS',      floor: '#1e3025' },
  shop:    { x: 20,  y: 210, w: 130, h: 75, name: 'WORKSHOP',     floor: '#33291d' },
  library: { x: 200, y: 225, w: 80,  h: 60, name: 'LIBRARY',      floor: '#2d2330' },
  studio:  { x: 330, y: 210, w: 130, h: 75, name: 'STUDIO',       floor: '#34202a' },
};
const HALLS = [
  [150, 55, 65, 10], [205, 55, 10, 50], [265, 55, 65, 10], [265, 55, 10, 50],
  [130, 150, 45, 10], [305, 150, 45, 10],
  [150, 240, 40, 10], [180, 195, 10, 55], [290, 240, 40, 10], [290, 195, 10, 55],
  [235, 195, 10, 30],
];
// Where each agent works: room + desk spot + suit color.
const CREW = {
  researcher:     { room: 'lab',     desk: [45, 50],   color: '#4f8cff' },
  scout:          { room: 'lab',     desk: [115, 50],  color: '#35c3e8' },
  strategist:     { room: 'war',     desk: [360, 50],  color: '#b07cff' },
  judge:          { room: 'war',     desk: [430, 50],  color: '#e0566b' },
  operator:       { room: 'mail',    desk: [55, 150],  color: '#3fcf9a' },
  analyst:        { room: 'numbers', desk: [395, 150], color: '#8fd14f' },
  builder:        { room: 'shop',    desk: [55, 240],  color: '#f0a23a' },
  villa_studio:   { room: 'studio',  desk: [360, 240], color: '#ff7aa8' },
  villa_outreach: { room: 'studio',  desk: [430, 240], color: '#ffc24d' },
  learner:        { room: 'library', desk: [240, 250], color: '#c9a2ff' },
};
const DECK_SPOTS = [[200, 140], [240, 140], [280, 140], [200, 170], [280, 170]];

// ---------- Tiny 3x5 pixel font ----------
const G = {
  A: '010101111101101', B: '110101110101110', C: '011100100100011', D: '110101101101110', E: '111100110100111',
  F: '111100110100100', G: '011100101101011', H: '101101111101101', I: '111010010010111', J: '001001001101010',
  K: '101101110101101', L: '100100100100111', M: '101111111101101', N: '110101101101101', O: '010101101101010',
  P: '110101110100100', Q: '010101101110011', R: '110101110101101', S: '011100010001110', T: '111010010010010',
  U: '101101101101111', V: '101101101101010', W: '101101111111101', X: '101101010101101', Y: '101101010010010',
  Z: '111001010100111', 0: '111101101101111', 1: '010110010010111', 2: '110001010100111', 3: '110001010001110',
  4: '101101111001001', 5: '111100110001110', 6: '011100111101111', 7: '111001010010010', 8: '111101111101111',
  9: '111101111001110', ' ': '000000000000000', '!': '010010010000010', '.': '000000000000010', '-': '000000111000000',
  '+': '000010111010000', '/': '001001010100100', '$': '011110010011110', ':': '000010000010000', '?': '110001010000010',
};
function text(ctx, str, x, y, color) {
  ctx.fillStyle = color;
  let cx = Math.round(x);
  for (const ch of String(str).toUpperCase()) {
    const g = G[ch] || G['?'];
    for (let i = 0; i < 15; i++) if (g[i] === '1') ctx.fillRect(cx + (i % 3), Math.round(y) + Math.floor(i / 3), 1, 1);
    cx += 4;
  }
}
const textW = (s) => String(s).length * 4 - 1;

// ---------- Data ----------
const level = (xp) => Math.floor(Math.sqrt(xp / 3)) + 1;
const xpFor = (lv) => 3 * (lv - 1) ** 2;

async function load() {
  const monthStart = new Date(); monthStart.setDate(1); monthStart.setHours(0, 0, 0, 0);
  const since3h = new Date(Date.now() - 3 * 3600000).toISOString();
  const [agents, running, ideas, activity, ledger, approvalsN, emailsN, tasksN] = await Promise.all([
    q(sb.from('agents').select('*').order('sort')),
    q(sb.from('agent_runs').select('agent').eq('status', 'running').gte('started_at', since3h)),
    q(sb.from('ideas').select('id,title,kind,business,score,summary,created_by').eq('status', 'proposed').order('created_at', { ascending: false }).limit(6)),
    q(sb.from('activity').select('id,at,agent,message').order('at', { ascending: false }).limit(18)),
    q(sb.from('ledger').select('revenue,cost').gte('day', monthStart.toISOString().slice(0, 10))),
    count('approvals', (x) => x.eq('status', 'pending')),
    count('emails', (x) => x.eq('needs_bobby', true).in('status', ['flagged', 'drafted'])),
    count('tasks', (x) => x.eq('assignee', 'bobby').eq('status', 'todo')),
  ]);
  const xp = await Promise.all(agents.map((a) => count('agent_runs', (x) => x.eq('agent', a.id).in('status', ['ok', 'capped']))));
  agents.forEach((a, i) => { a.xp = xp[i]; a.level = level(xp[i]); a.running = running.some((r) => r.agent === a.id); });
  return {
    agents, ideas, activity,
    revenue: ledger.reduce((n, l) => n + Number(l.revenue), 0),
    profit: ledger.reduce((n, l) => n + Number(l.revenue) - Number(l.cost), 0),
    needs: approvalsN + emailsN + tasksN + ideas.length,
  };
}

function state(a) {
  if (!a.enabled) return 'paused';
  if (a.running) return 'working';
  if (a.last_status === 'error') return 'error';
  if (!a.last_run_at) return 'new';
  return 'idle';
}
const STATE_LABEL = { working: 'Working now', error: 'Last run failed', paused: 'Paused', new: 'Waiting for first run', idle: 'On standby' };
const STATE_TONE = { working: 'info', error: 'bad', paused: '', new: '', idle: 'ok' };

// ---------- Render ----------
export async function render(el) {
  let data = await load();
  let selected = null;
  let seenActivity = new Set(data.activity.map((a) => a.id));

  el.innerHTML = `
  <div class="head"><h1>Station</h1><div class="row small muted" id="st-updated"></div></div>
  <div class="st-hud" id="st-hud"></div>
  <div class="station">
    <aside class="card st-roster"><h2>Crew</h2><div id="st-roster" class="stack" style="margin-top:8px"></div></aside>
    <section class="st-center">
      <div class="st-screen"><canvas id="st-canvas" width="${W * S}" height="${H * S}" aria-label="Pixel-art station with one crew member per agent"></canvas></div>
      <div class="card st-inspect" id="st-inspect"></div>
    </section>
    <aside class="st-right">
      <div class="card"><h2>Waiting on you</h2><div id="st-waiting" class="stack" style="margin-top:8px"></div></div>
      <div class="card"><h2>Live feed</h2><div id="st-feed" class="list" style="margin-top:8px"></div></div>
    </aside>
  </div>`;

  const canvas = el.querySelector('#st-canvas');
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  ctx.scale(S, S);

  // Sprites keyed by agent id; persist across data refreshes.
  const sprites = {};
  let deckIdx = 0;
  function syncSprites() {
    for (const a of data.agents) {
      if (!sprites[a.id]) {
        const c = CREW[a.id] || { room: 'deck', desk: DECK_SPOTS[deckIdx++ % DECK_SPOTS.length], color: '#9fb3c8' };
        sprites[a.id] = { id: a.id, ...c, x: c.desk[0], y: c.desk[1], tx: c.desk[0], ty: c.desk[1], wait: 0, step: 0, pops: [] };
      }
      sprites[a.id].agent = a;
    }
  }
  syncSprites();

  const stars = Array.from({ length: 90 }, () => ({ x: Math.random() * W, y: Math.random() * H, p: Math.random() * 6.28, s: Math.random() < 0.15 ? 2 : 1 }));
  let frame = 0;

  function drawRoom(r, key) {
    // walls
    ctx.fillStyle = '#6f7d93'; ctx.fillRect(r.x - 2, r.y - 2, r.w + 4, r.h + 4);
    ctx.fillStyle = '#3a4456'; ctx.fillRect(r.x - 1, r.y - 1, r.w + 2, r.h + 2);
    // floor tiles
    ctx.fillStyle = r.floor; ctx.fillRect(r.x, r.y, r.w, r.h);
    ctx.fillStyle = 'rgba(255,255,255,0.035)';
    for (let x = r.x; x < r.x + r.w; x += 10) for (let y = r.y; y < r.y + r.h; y += 10) if (((x - r.x) / 10 + (y - r.y) / 10) % 2 === 0) ctx.fillRect(x, y, 10, 10);
    // label plate
    const lw = textW(r.name) + 4;
    ctx.fillStyle = '#0b0f18'; ctx.fillRect(r.x + 3, r.y + 3, lw, 8);
    text(ctx, r.name, r.x + 5, r.y + 4.5, selectedRoom() === key ? '#ffd166' : '#9fb3d9');
  }

  function desk(x, y, lit) {
    ctx.fillStyle = '#5b4a3a'; ctx.fillRect(x - 7, y - 10, 14, 5);
    ctx.fillStyle = '#2b2f3a'; ctx.fillRect(x - 4, y - 16, 8, 6);
    ctx.fillStyle = lit ? (frame % 20 < 10 ? '#7ff0ff' : '#5fd6f0') : '#1a3244'; ctx.fillRect(x - 3, y - 15, 6, 4);
  }

  function furniture() {
    const R = ROOMS;
    // lab: server racks
    for (let i = 0; i < 3; i++) { ctx.fillStyle = '#2c3446'; ctx.fillRect(R.lab.x + 30 + i * 30, R.lab.y + 62, 10, 14); ctx.fillStyle = frame % 30 < 15 ? '#4cff9a' : '#1f7a4a'; ctx.fillRect(R.lab.x + 32 + i * 30, R.lab.y + 65 + (i % 2) * 4, 2, 1); }
    // war room: big table
    ctx.fillStyle = '#4a3b5e'; ctx.fillRect(R.war.x + 35, R.war.y + 55, 60, 14); ctx.fillStyle = '#6d5a8a'; ctx.fillRect(R.war.x + 37, R.war.y + 57, 56, 2);
    // mailroom: sorting bins
    for (let i = 0; i < 4; i++) { ctx.fillStyle = '#5d6b6c'; ctx.fillRect(R.mail.x + 10 + i * 12, R.mail.y + 50, 10, 10); ctx.fillStyle = '#e8e2cf'; ctx.fillRect(R.mail.x + 12 + i * 12, R.mail.y + 50, 6, 3); }
    // numbers: chart wall
    ctx.fillStyle = '#0e1a14'; ctx.fillRect(R.numbers.x + 60, R.numbers.y + 14, 40, 22);
    ctx.fillStyle = '#8fd14f'; [4, 7, 5, 10, 13, 12, 17].forEach((h, i) => ctx.fillRect(R.numbers.x + 63 + i * 5, R.numbers.y + 34 - h, 3, h));
    // deck: main console + planet window
    ctx.fillStyle = '#0a0f1a'; ctx.fillRect(R.deck.x + 40, R.deck.y + 14, 50, 18);
    ctx.fillStyle = '#3f6fd8'; ctx.fillRect(R.deck.x + 58, R.deck.y + 18, 12, 10); ctx.fillStyle = '#6fa0ff'; ctx.fillRect(R.deck.x + 60, R.deck.y + 19, 5, 3);
    ctx.fillStyle = '#3a4456'; ctx.fillRect(R.deck.x + 45, R.deck.y + 58, 40, 8);
    ctx.fillStyle = frame % 16 < 8 ? '#ff5d5d' : '#ffd166'; ctx.fillRect(R.deck.x + 50, R.deck.y + 60, 2, 2); ctx.fillStyle = '#4cff9a'; ctx.fillRect(R.deck.x + 56, R.deck.y + 60, 2, 2);
    // workshop: workbench + crates
    ctx.fillStyle = '#7a5a36'; ctx.fillRect(R.shop.x + 70, R.shop.y + 45, 45, 8); ctx.fillStyle = '#a07a4a'; ctx.fillRect(R.shop.x + 20, R.shop.y + 52, 10, 10); ctx.fillRect(R.shop.x + 32, R.shop.y + 55, 8, 7);
    // library: shelves
    for (let i = 0; i < 3; i++) { ctx.fillStyle = '#4b3526'; ctx.fillRect(R.library.x + 8 + i * 24, R.library.y + 40, 18, 14); for (let b = 0; b < 5; b++) { ctx.fillStyle = ['#c95b5b', '#5b8cc9', '#d9b44a', '#6fbf73', '#a877d1'][b]; ctx.fillRect(R.library.x + 9 + i * 24 + b * 3, R.library.y + 42, 2, 5); } }
    // studio: camera on tripod + light
    ctx.fillStyle = '#20232b'; ctx.fillRect(R.studio.x + 60, R.studio.y + 40, 10, 6); ctx.fillStyle = '#7d8799'; ctx.fillRect(R.studio.x + 64, R.studio.y + 46, 2, 12);
    ctx.fillStyle = '#fff3c4'; ctx.fillRect(R.studio.x + 95, R.studio.y + 38, 8, 5); ctx.fillStyle = '#7d8799'; ctx.fillRect(R.studio.x + 98, R.studio.y + 43, 2, 14);
    // plants
    [[R.lab.x + 122, R.lab.y + 70], [R.mail.x + 100, R.mail.y + 60], [R.deck.x + 120, R.deck.y + 80], [R.studio.x + 120, R.studio.y + 65]].forEach(([x, y]) => {
      ctx.fillStyle = '#6b4a2e'; ctx.fillRect(x - 2, y, 5, 4); ctx.fillStyle = '#3fae5a'; ctx.fillRect(x - 3, y - 4, 7, 4); ctx.fillRect(x - 1, y - 6, 3, 2);
    });
  }

  function drawCrew(sp) {
    const a = sp.agent, st = state(a);
    const x = Math.round(sp.x), y = Math.round(sp.y);
    const moving = Math.abs(sp.tx - sp.x) + Math.abs(sp.ty - sp.y) > 0.5;
    const bob = !moving && st !== 'paused' && Math.floor(frame / 30) % 2 ? 1 : 0;
    const suit = st === 'paused' ? '#5c6270' : sp.color;
    // shadow
    ctx.fillStyle = 'rgba(0,0,0,0.35)'; ctx.fillRect(x - 3, y + 1, 7, 1);
    // legs
    ctx.fillStyle = '#1b1f29';
    const leg = moving ? (Math.floor(sp.step / 6) % 2) : 0;
    ctx.fillRect(x - 2, y - 2 + (leg ? -1 : 0), 2, 2); ctx.fillRect(x + 1, y - 2 + (leg ? 0 : -1), 2, 2);
    // body
    ctx.fillStyle = suit; ctx.fillRect(x - 3, y - 6 - bob, 7, 4);
    ctx.fillStyle = 'rgba(255,255,255,0.25)'; ctx.fillRect(x - 3, y - 6 - bob, 7, 1);
    // helmet + visor
    ctx.fillStyle = '#e9edf5'; ctx.fillRect(x - 2, y - 11 - bob, 5, 5);
    ctx.fillStyle = st === 'paused' ? '#3a4050' : '#223a66'; ctx.fillRect(x - 1, y - 10 - bob, 3, 2);
    ctx.fillStyle = '#9fd0ff'; ctx.fillRect(x - 1, y - 10 - bob, 1, 1);
    // selection ring
    if (selected === a.id) { ctx.fillStyle = '#ffd166'; ctx.fillRect(x - 4, y + 2, 9, 1); ctx.fillRect(x - 4, y - 13 - bob, 9, 1); }
    // status marks
    if (st === 'error' && frame % 30 < 20) { ctx.fillStyle = '#ff4d4d'; ctx.fillRect(x, y - 19 - bob, 1, 4); ctx.fillRect(x, y - 14 - bob, 1, 1); }
    if (st === 'paused') text(ctx, 'Z', x + 3, y - 16 - ((frame / 10) % 4), '#9aa3b5');
    if (st === 'working' && !moving) {
      ctx.fillStyle = '#ffffff'; ctx.fillRect(x + 3, y - 18, 9, 6); ctx.fillRect(x + 4, y - 12, 2, 1);
      ctx.fillStyle = '#223a66'; for (let d = 0; d < 3; d++) if (Math.floor(frame / 8) % 4 > d) ctx.fillRect(x + 5 + d * 2, y - 15, 1, 1);
    }
    // XP pops
    sp.pops = sp.pops.filter((p) => p.t > 0);
    for (const p of sp.pops) { text(ctx, p.text, x - textW(p.text) / 2, y - 22 - (60 - p.t) / 4, p.t % 10 < 6 ? '#ffd166' : '#fff'); p.t--; }
    // name tag on hover/select
    if (selected === a.id || hover === a.id) {
      const n = (a.name || a.id).toUpperCase(), w = textW(n) + 4;
      ctx.fillStyle = '#0b0f18'; ctx.fillRect(x - w / 2, y + 4, w, 8); text(ctx, n, x - w / 2 + 2, y + 5.5, '#ffd166');
    }
  }

  function move(sp) {
    const st = state(sp.agent);
    const r = ROOMS[sp.room];
    if (st === 'working') {
      if (Math.abs(sp.tx - sp.x) + Math.abs(sp.ty - sp.y) <= 0.5) {
        if (sp.wait-- <= 0) {
          const home = Math.random() < 0.45;
          sp.tx = home ? sp.desk[0] : r.x + 10 + Math.random() * (r.w - 20);
          sp.ty = home ? sp.desk[1] : r.y + 22 + Math.random() * (r.h - 28);
          sp.wait = 50 + Math.random() * 90;
        }
      }
    } else { sp.tx = sp.desk[0]; sp.ty = sp.desk[1]; }
    const dx = sp.tx - sp.x, dy = sp.ty - sp.y, d = Math.hypot(dx, dy);
    if (d > 0.5) { const v = Math.min(0.45, d); sp.x += (dx / d) * v; sp.y += (dy / d) * v; sp.step++; }
  }

  function draw() {
    ctx.fillStyle = '#05070d'; ctx.fillRect(0, 0, W, H);
    for (const s of stars) { const a = 0.35 + 0.65 * Math.abs(Math.sin(s.p + frame / 40)); ctx.fillStyle = `rgba(210,225,255,${a.toFixed(2)})`; ctx.fillRect(Math.round(s.x), Math.round(s.y), s.s, s.s); }
    for (const [x, y, w, h] of HALLS) { ctx.fillStyle = '#6f7d93'; ctx.fillRect(x - 1, y - 1, w + 2, h + 2); ctx.fillStyle = '#2a3242'; ctx.fillRect(x, y, w, h); }
    for (const [k, r] of Object.entries(ROOMS)) drawRoom(r, k);
    for (const [x, y, w, h] of HALLS) { ctx.fillStyle = '#2a3242'; ctx.fillRect(x, y, w, h); }
    furniture();
    const list = Object.values(sprites).filter((s) => s.agent);
    for (const sp of list) desk(sp.desk[0], sp.desk[1], state(sp.agent) === 'working');
    list.sort((a, b) => a.y - b.y).forEach(drawCrew);
    // HUD strip
    const working = data.agents.filter((a) => a.running).length;
    ctx.fillStyle = 'rgba(5,7,13,0.8)'; ctx.fillRect(0, H - 11, W, 11);
    text(ctx, `CREW ${data.agents.length}  WORKING ${working}  WAITING ON YOU ${data.needs}  MONTH $${Math.round(data.revenue)}`, 4, H - 8, '#9fb3d9');
  }

  const selectedRoom = () => (selected && sprites[selected] ? sprites[selected].room : null);

  let raf, last = 0, hover = null;
  function loop(t) {
    if (!el.isConnected) { cleanup(); return; }
    raf = requestAnimationFrame(loop);
    if (t - last < 33) return; // ~30 fps
    last = t; frame++;
    for (const sp of Object.values(sprites)) if (sp.agent) move(sp);
    draw();
  }
  raf = requestAnimationFrame(loop);

  // ---------- Panels ----------
  function renderPanels() {
    el.querySelector('#st-updated').textContent = `Live · refreshed ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
    const hq = data.agents.reduce((n, a) => n + a.level, 0);
    const working = data.agents.filter((a) => a.running).length;
    el.querySelector('#st-hud').innerHTML = `
      <div class="st-chip"><span>HQ level</span><strong class="num">${hq}</strong></div>
      <div class="st-chip"><span>Working now</span><strong class="num">${working}/${data.agents.length}</strong></div>
      <div class="st-chip"><span>Revenue this month</span><strong class="num">${money(data.revenue)}</strong></div>
      <div class="st-chip"><span>Profit this month</span><strong class="num">${money(data.profit)}</strong></div>
      <a class="st-chip ${data.needs ? 'alert' : ''}" href="#needs"><span>Waiting on you</span><strong class="num">${data.needs}</strong></a>`;

    el.querySelector('#st-roster').innerHTML = data.agents.map((a) => {
      const st = state(a), lv = a.level, lo = xpFor(lv), hi = xpFor(lv + 1);
      const pctXp = Math.round(((a.xp - lo) / (hi - lo)) * 100);
      const c = (CREW[a.id] || {}).color || '#9fb3c8';
      return `<button class="st-member ${selected === a.id ? 'sel' : ''}" data-agent="${esc(a.id)}">
        <span class="st-swatch" style="background:${c}"></span>
        <span class="st-mid"><span class="row between"><strong>${esc(a.name)}</strong><span class="num small">Lv ${lv}</span></span>
          <span class="st-xp"><span style="width:${pctXp}%"></span></span>
          <span class="small muted"><span class="dot ${STATE_TONE[st]}"></span> ${STATE_LABEL[st]}</span></span>
      </button>`;
    }).join('');

    const a = data.agents.find((x) => x.id === selected);
    el.querySelector('#st-inspect').innerHTML = a ? `
      <div class="row between"><h3>${esc(a.name)} <span class="muted small">· ${esc(ROOMS[(CREW[a.id] || { room: 'deck' }).room].name.toLowerCase())}</span></h3>
        <span class="small num">Lv ${a.level} · ${a.xp} runs</span></div>
      <div class="small muted" style="margin-top:4px">${esc(a.description || '')}</div>
      <div class="small" style="margin-top:6px"><strong>${STATE_LABEL[state(a)]}</strong> · last run ${ago(a.last_run_at)} · ${esc(a.schedule || '')}</div>
      ${a.last_summary ? `<div class="small muted" style="margin-top:6px">${esc(a.last_summary).slice(0, 300)}</div>` : ''}`
      : '<div class="small muted">Click a crew member or a name in the Crew list to inspect them. Crew walk around while their agent is running; a red "!" means the last run failed.</div>';

    el.querySelector('#st-waiting').innerHTML = data.ideas.map((i) => `
      <div class="st-quest" data-id="${i.id}">
        <div class="small"><strong>${esc(i.title)}</strong></div>
        <div class="small muted">${esc(i.kind)}${i.business ? ` · ${esc(i.business)}` : ''}${i.score != null ? ` · ${i.score}/100` : ''} · by ${esc(i.created_by || 'agent')}</div>
        <input data-note class="small" placeholder="Note (optional)">
        <div class="row"><button class="ok" data-do="approve">Approve</button><button class="danger" data-do="reject">Reject</button><a class="small" href="#ideas">Details</a></div>
      </div>`).join('') + (data.needs > data.ideas.length ? `<a class="small" href="#needs">${data.needs - data.ideas.length} more in Needs you →</a>` : '')
      || '<div class="empty small">Nothing waiting. The crew has it.</div>';

    el.querySelector('#st-feed').innerHTML = data.activity.map((x) => `<div class="item small"><span class="muted num">${ago(x.at)}</span> · <strong>${esc(x.agent || '')}</strong> ${esc(x.message)}</div>`).join('') || '<div class="empty">Nothing yet.</div>';
  }
  renderPanels();

  // ---------- Interaction ----------
  function pick(ev) {
    const r = canvas.getBoundingClientRect();
    const lx = ((ev.clientX - r.left) / r.width) * W, ly = ((ev.clientY - r.top) / r.height) * H;
    let best = null, bd = 9;
    for (const sp of Object.values(sprites)) { if (!sp.agent) continue; const d = Math.hypot(sp.x - lx, sp.y - 5 - ly); if (d < bd) { bd = d; best = sp.id; } }
    if (best) return best;
    const room = Object.entries(ROOMS).find(([, rm]) => lx >= rm.x && lx <= rm.x + rm.w && ly >= rm.y && ly <= rm.y + rm.h);
    return room ? Object.values(sprites).find((s) => s.room === room[0] && s.agent)?.id || null : null;
  }
  canvas.addEventListener('mousemove', (e) => { hover = pick(e); canvas.style.cursor = hover ? 'pointer' : 'default'; });
  canvas.addEventListener('mouseleave', () => { hover = null; });
  canvas.addEventListener('click', (e) => { selected = pick(e); renderPanels(); });
  on(el, 'click', '[data-agent]', (e, b) => { selected = b.dataset.agent === selected ? null : b.dataset.agent; renderPanels(); });
  on(el, 'click', '[data-do]', (e, btn) => {
    const card = btn.closest('[data-id]');
    const id = card.dataset.id;
    const note = card.querySelector('[data-note]').value.trim() || null;
    act(btn, async () => {
      if (btn.dataset.do === 'approve') {
        const r = await q(sb.rpc('approve_idea', { p_id: id, p_note: note }));
        if (r && r.ok === false) throw new Error(r.reason);
        if (sprites.builder) sprites.builder.pops.push({ text: 'NEW JOB', t: 60 });
      } else {
        await q(sb.from('ideas').update({ status: 'rejected', decided_at: new Date().toISOString(), feedback: note }).eq('id', id));
        if (note) await q(sb.from('feedback').insert({ kind: 'idea_rejected', text: note, ref_table: 'ideas', ref_id: id }));
      }
      await refresh();
    }, btn.dataset.do === 'approve' ? 'Approved' : 'Rejected');
  });

  // ---------- Live refresh ----------
  async function refresh() {
    try {
      data = await load();
      syncSprites();
      for (const x of data.activity) {
        if (seenActivity.has(x.id)) continue;
        seenActivity.add(x.id);
        if (x.agent && sprites[x.agent]) sprites[x.agent].pops.push({ text: '+XP', t: 60 });
      }
      renderPanels();
    } catch (e) { console.error(e); }
  }
  const timer = setInterval(() => { if (!el.isConnected) cleanup(); else refresh(); }, 20000);
  function cleanup() { cancelAnimationFrame(raf); clearInterval(timer); }
}
