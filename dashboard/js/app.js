// Ownvista HQ dashboard shell: auth, navigation, theme.
import { sb, cfg, esc, toast, count } from './core.js';

const VIEWS = [
  ['station', 'Station'],
  ['world', 'World'],
  ['needs', 'Needs you'],
  ['email', 'Email'],
  ['economy', 'Economy'],
  ['shop', 'Shop'],
  ['villa', 'Villa Cinema'],
  ['lab', 'Venture Lab'],
  ['trader', 'Trader'],
  ['ideas', 'Ideas'],
  ['tasks', 'Tasks'],
  ['knowledge', 'Knowledge'],
  ['sources', 'Sources'],
  ['playbook', 'Playbook'],
];

const $ = (id) => document.getElementById(id);

function applyTheme() {
  let t = null;
  try { t = localStorage.getItem('hq-theme'); } catch {}
  if (t) document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}

$('theme-btn').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  try { localStorage.setItem('hq-theme', dark ? 'light' : 'dark'); } catch {}
  applyTheme();
});
$('signout-btn').addEventListener('click', async () => { await sb.auth.signOut(); location.reload(); });

$('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = $('login-email').value.trim().toLowerCase();
  $('login-msg').textContent = 'Sending…';
  const { error } = await sb.auth.signInWithOtp({ email, options: { emailRedirectTo: location.origin, shouldCreateUser: false } });
  $('login-msg').textContent = error ? `Could not send: ${error.message}` : 'Check your inbox for the sign-in link.';
});

async function needsCount() {
  const [a, e, i, t] = await Promise.all([
    count('approvals', (x) => x.eq('status', 'pending')),
    count('emails', (x) => x.eq('needs_bobby', true).in('status', ['flagged', 'drafted'])),
    count('ideas', (x) => x.eq('status', 'proposed')),
    count('tasks', (x) => x.eq('assignee', 'bobby').eq('status', 'todo')),
  ]);
  return a + e + i + t;
}

function renderNav(active, needs) {
  $('nav').innerHTML = VIEWS.map(([id, label]) => `<a href="#${id}" class="${id === active ? 'active' : ''}">${esc(label)}${
    id === 'needs' && needs ? `<span class="count">${needs}</span>` : ''}</a>`).join('');
}

let current = null;
async function route() {
  const id = (location.hash.slice(1) || 'station').split('/')[0];
  const view = VIEWS.find(([v]) => v === id) ? id : 'station';
  current = view;
  renderNav(view, 0);
  // A fresh container per render so delegated listeners never stack up.
  const host = $('view');
  const el = document.createElement('div');
  el.innerHTML = '<p class="muted">Loading…</p>';
  host.replaceChildren(el);
  try {
    const mod = await import(`./views/${view}.js`);
    if (current !== view) return;
    await mod.render(el);
  } catch (e) {
    console.error(e);
    el.innerHTML = `<div class="card"><h2>Something went wrong</h2><p class="muted">${esc(e.message)}</p></div>`;
  }
  needsCount().then((n) => renderNav(view, n)).catch(() => {});
}

async function start() {
  applyTheme();
  if (!cfg.supabaseUrl) {
    document.body.innerHTML = '<p style="padding:24px">Missing config.js — set SUPABASE_URL and SUPABASE_ANON_KEY in Vercel and redeploy.</p>';
    return;
  }
  const { data: { session } } = await sb.auth.getSession();
  if (!session) {
    $('login').classList.remove('hidden');
    return;
  }
  const email = (session.user.email || '').toLowerCase();
  if (email !== cfg.allowedEmail) {
    await sb.auth.signOut();
    $('login').classList.remove('hidden');
    $('login-msg').textContent = 'That account is not allowed here.';
    return;
  }
  if (started) return;
  started = true;
  $('login').classList.add('hidden');
  $('app').classList.remove('hidden');
  window.addEventListener('hashchange', route);
  route();
}

// Boot once. Supabase fires SIGNED_IN on every page load that already has a session, so reloading on it
// caused an endless reload loop. Instead, only boot the app when a sign-in arrives before it has started
// (e.g. returning from the magic link), and defer the call: Supabase calls made inside this callback can deadlock.
let started = false;
let booting = null;
const boot = () => (booting ||= start().catch((e) => toast(e.message, 6000)).finally(() => { booting = null; }));

sb.auth.onAuthStateChange((evt) => {
  if (evt === 'SIGNED_IN' && !started) setTimeout(boot, 0);
});

window.hqRefresh = () => route();
boot();
