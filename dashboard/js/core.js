// Shared dashboard helpers: Supabase client, escaping, formatting, small UI bits.
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

export const cfg = window.HQ_CONFIG || {};
export const sb = createClient(cfg.supabaseUrl, cfg.supabaseAnonKey, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: 'pkce' },
});

export function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Run a Supabase query builder and return data or throw.
export async function q(builder) {
  const { data, error, count } = await builder;
  if (error) throw new Error(error.message);
  return count !== undefined && count !== null && data === null ? count : data;
}

export async function count(table, apply = (x) => x) {
  const { count: n, error } = await apply(sb.from(table).select('*', { count: 'exact', head: true }));
  if (error) throw new Error(error.message);
  return n ?? 0;
}

let toastTimer;
export function toast(msg, ms = 2600) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), ms);
}

export function ago(ts) {
  if (!ts) return 'never';
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  const f = Math.abs(s);
  const unit = f < 60 ? [Math.round(f), 's'] : f < 3600 ? [Math.round(f / 60), 'm'] : f < 86400 ? [Math.round(f / 3600), 'h'] : [Math.round(f / 86400), 'd'];
  return s >= 0 ? `${unit[0]}${unit[1]} ago` : `in ${unit[0]}${unit[1]}`;
}

export const when = (ts) => (ts ? new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—');
export const money = (n) => `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const pct = (n) => (n == null ? '—' : `${Math.round(n * 100)}%`);
export const nf = (n) => Number(n || 0).toLocaleString();

export function badge(text, tone = '') {
  return `<span class="badge ${tone}">${esc(text)}</span>`;
}

export function statusTone(s) {
  return { ok: 'ok', capped: 'warn', error: 'bad', running: 'info', skipped: '' }[s] || '';
}

// Minimal inline sparkline.
export function spark(values, { height = 40 } = {}) {
  const v = values.map((x) => (x == null ? null : Number(x)));
  const pts = v.filter((x) => x != null);
  if (pts.length < 2) return '<div class="muted small">Not enough data yet</div>';
  const min = Math.min(...pts), max = Math.max(...pts), span = max - min || 1;
  const w = 200, step = w / (v.length - 1);
  let d = '', first = true;
  v.forEach((x, i) => {
    if (x == null) return;
    const y = height - 4 - ((x - min) / span) * (height - 8);
    d += `${first ? 'M' : 'L'}${(i * step).toFixed(1)},${y.toFixed(1)} `;
    first = false;
  });
  return `<svg class="spark" viewBox="0 0 ${w} ${height}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}"/></svg>`;
}

export function meter(value, max) {
  const r = max ? Math.min(1, value / max) : 0;
  const tone = r > 0.9 ? 'bad' : r > 0.7 ? 'warn' : '';
  return `<div class="meter ${tone}"><div style="width:${(r * 100).toFixed(1)}%"></div></div>`;
}

// Event delegation: on(root, 'click', '[data-act=x]', fn)
export function on(root, type, selector, fn) {
  root.addEventListener(type, (e) => {
    const t = e.target.closest(selector);
    if (t && root.contains(t)) fn(e, t);
  });
}

export async function act(btn, fn, okMsg) {
  if (btn) btn.disabled = true;
  try {
    await fn();
    if (okMsg) toast(okMsg);
  } catch (e) {
    toast(`Error: ${e.message}`, 5000);
    console.error(e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

export const gmailThread = (id) => `https://mail.google.com/mail/?authuser=${encodeURIComponent(cfg.gmailUser)}#all/${id}`;
export const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');

export async function kvGet(key, fallback = null) {
  const row = await q(sb.from('kv').select('value').eq('key', key).maybeSingle());
  return row && row.value !== null ? row.value : fallback;
}

export async function kvSet(key, value) {
  await q(sb.from('kv').upsert({ key, value, updated_at: new Date().toISOString() }));
}

export const BUSINESSES = ['nashville-buys', 'followup', 'ma-real-estate', 'clearance', 'villa-cinema', 'venture-lab'];

export function fdata(form) {
  return Object.fromEntries(new FormData(form).entries());
}
