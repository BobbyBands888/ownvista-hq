#!/usr/bin/env node
// Post-setup security check against the REAL Supabase project. Proves:
//   (a) the anon/publishable key reads zero rows from every table (and can't write or call agent functions),
//   (b) a signed-in user who is NOT bobbybands888@gmail.com reads zero rows (and can't write or call them),
//   (c) the service-role/secret key can read and write every table.
// It first puts a marked "canary" row into every table so "zero rows" means RLS hid them, not that the
// table was empty. It creates one throwaway auth user for (b). Everything it creates is deleted at the end.
//
// Run:  node scripts/rls-check.js
// Keys come from env (SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY) or are asked for;
// typed keys are hidden and never saved. Exit code 0 = all checks passed.
import { createInterface } from 'node:readline';
import { randomBytes } from 'node:crypto';

const TAG = `rlscheck-${Date.now()}`;
const TABLES = [
  'kv', 'agents', 'job_runs', 'agent_runs', 'activity', 'llm_usage', 'emails', 'drafts', 'tasks', 'ideas',
  'experiments', 'assets', 'signals', 'ledger', 'approvals', 'sources', 'knowledge', 'seen_urls', 'playbook',
  'playbook_rules', 'playbook_versions', 'feedback', 'self_reviews', 'metrics_daily', 'vc_prospects',
  'vc_orders', 'vc_clips', 'vc_messages', 'vc_suppression', 'spend',
];
const BUCKETS = ['vc-photos', 'vc-films', 'vc-music'];
// Functions only agents may call (service role). Args don't need to be valid: permission is checked first.
const AGENT_RPCS = {
  vc_reserve_spend: { p_order: '00000000-0000-0000-0000-000000000000', p_clip: null, p_purpose: 'generate', p_amount: 1, p_note: TAG },
  vc_reserve_send: { p_kind: 'test', p_to: 'x@example.com', p_prospect: null, p_order: null, p_subject: TAG, p_body: TAG, p_in_reply_to: null },
  vc_settle_spend: { p_id: '00000000-0000-0000-0000-000000000000', p_actual: 1, p_ref: TAG },
  vc_pause: { p_reason: TAG },
  llm_log: { p_model: TAG, p_agent: TAG, p_in: 1, p_out: 1 },
  kv_get: { p_key: 'bobby_email' },
};

// Primary key used to find each canary row again (default: id).
const PK = { kv: 'key', agents: 'id', playbook: 'section', seen_urls: 'url_hash', vc_suppression: 'email', self_reviews: 'day', metrics_daily: 'day', llm_usage: 'model' };

// Minimal canary row per table, clearly marked with TAG.
const day = '1999-01-01';
const canary = (t, ids) => ({
  job_runs: { trigger: TAG },
  agent_runs: { agent: TAG },
  activity: { kind: TAG, message: TAG },
  llm_usage: { day, model: TAG, agent: TAG },
  emails: { gmail_thread_id: TAG },
  drafts: { body: TAG },
  tasks: { title: TAG },
  ideas: { kind: 'growth', title: TAG },
  experiments: { title: TAG },
  assets: { kind: TAG, body: TAG },
  signals: { lane: 'b2b', title: TAG },
  ledger: { line: TAG },
  approvals: { kind: TAG, title: TAG },
  knowledge: { title: TAG, url: `https://example.com/${TAG}` },
  seen_urls: { url_hash: TAG },
  playbook_rules: { rule: TAG, origin: 'manual' },
  feedback: { kind: TAG, text: TAG },
  self_reviews: { day, text: TAG },
  metrics_daily: { day },
  vc_prospects: { company: TAG, contact_email: `${TAG}@example.com` },
  vc_orders: { kind: 'test', notes: TAG },
  vc_clips: { order_id: ids.order, photo_path: TAG },
  vc_messages: { direction: 'in', kind: TAG, subject: TAG },
  vc_suppression: { email: `${TAG}@example.com`, reason: 'manual' },
  spend: { kind: 'order', purpose: 'generate', amount_usd: 0.01, status: 'released', note: TAG, order_id: ids.order },
  sources: { name: TAG, url: `https://example.com/${TAG}.xml`, status: 'paused' },
  playbook: { section: TAG, title: TAG, content: TAG },
  playbook_versions: { version: 0, snapshot: {}, reason: TAG },
  kv: { key: TAG, value: true },
  agents: { id: TAG, name: TAG, enabled: false },
}[t]);

// ---------------------------------------------------------------- keys

function ask(question, hidden = true) {
  return new Promise((resolve) => {
    const rl = createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    if (hidden) rl._writeToOutput = (s) => { if (s.includes(question)) rl.output.write(s); };
    rl.question(question, (a) => { rl.close(); if (hidden) process.stdout.write('\n'); resolve(a.trim()); });
  });
}

const URL_ = (process.env.SUPABASE_URL || await ask('Supabase Project URL (https://xxxx.supabase.co): ', false)).replace(/\/$/, '');
const ANON = process.env.SUPABASE_ANON_KEY || await ask('Publishable (anon) key: ');
const SECRET = process.env.SUPABASE_SERVICE_ROLE_KEY || await ask('Secret (service role) key: ');

const keyHeaders = (k) => ({ apikey: k, ...(k.startsWith('eyJ') ? { Authorization: `Bearer ${k}` } : {}) });
const as = {
  service: keyHeaders(SECRET),
  anon: keyHeaders(ANON),
  user: null, // filled after sign-in: { apikey: ANON, Authorization: Bearer <user JWT> }
};

async function call(who, method, path, body, extra = {}) {
  const res = await fetch(`${URL_}${path}`, {
    method,
    headers: { ...as[who], 'Content-Type': 'application/json', ...extra },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  return { status: res.status, ok: res.ok, data };
}

// ---------------------------------------------------------------- results

const results = [];
const check = (group, name, pass, detail = '') => {
  results.push({ group, name, pass, detail });
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${group.padEnd(9)} ${name}${detail ? `  (${detail})` : ''}`);
};
const rowsFrom = (r) => (r.ok && Array.isArray(r.data) ? r.data.length : 0);

const created = { rows: [], objects: [], userId: null };

async function cleanup() {
  for (const { table, filter } of created.rows.reverse()) {
    await call('service', 'DELETE', `/rest/v1/${table}?${filter}`).catch(() => {});
  }
  for (const { bucket, path } of created.objects) {
    await call('service', 'DELETE', `/storage/v1/object/${bucket}`, { prefixes: [path] }).catch(() => {});
  }
  if (created.userId) await call('service', 'DELETE', `/auth/v1/admin/users/${created.userId}`).catch(() => {});
}

// ---------------------------------------------------------------- (c) service role: read + write, seed canaries

async function seed() {
  console.log('\n(c) Service role can read and write every table (and seeds canary rows)\n');
  const ids = {};
  const order = await call('service', 'POST', '/rest/v1/vc_orders', [{ kind: 'test', notes: TAG }], { Prefer: 'return=representation' });
  check('service', 'insert vc_orders canary', order.ok, order.ok ? '' : JSON.stringify(order.data).slice(0, 160));
  if (!order.ok) return false;
  ids.order = order.data[0].id;
  created.rows.push({ table: 'vc_orders', filter: `id=eq.${ids.order}` });

  // One canary row per table (even tables that already have data), then read it back.
  for (const t of TABLES) {
    const row = canary(t, ids);
    const ins = await call('service', 'POST', `/rest/v1/${t}`, [row], { Prefer: 'return=representation' });
    check('service', `write ${t}`, ins.ok, ins.ok ? '' : JSON.stringify(ins.data).slice(0, 160));
    if (!ins.ok) continue;
    const pk = PK[t] || 'id';
    const val = pk === 'id' ? ins.data[0].id : row[pk];
    const filter = `${pk}=eq.${encodeURIComponent(val)}`;
    created.rows.push({ table: t, filter });
    const read = await call('service', 'GET', `/rest/v1/${t}?select=*&${filter}`);
    check('service', `read ${t}`, rowsFrom(read) === 1, read.ok ? `${rowsFrom(read)} canary row` : `status ${read.status}`);
  }

  for (const b of BUCKETS) {
    const path = `${TAG}/canary.txt`;
    const up = await fetch(`${URL_}/storage/v1/object/${b}/${path}`, {
      method: 'POST', headers: { ...as.service, 'Content-Type': 'text/plain', 'x-upsert': 'true' }, body: 'canary',
    });
    // vc-photos/vc-films only allow images/video; fall back to a tiny valid type for those buckets.
    let ok = up.ok;
    let usedPath = path;
    if (!ok) {
      const alt = b === 'vc-films' ? { p: `${TAG}/canary.mp4`, t: 'video/mp4' } : { p: `${TAG}/canary.png`, t: 'image/png' };
      const up2 = await fetch(`${URL_}/storage/v1/object/${b}/${alt.p}`, {
        method: 'POST', headers: { ...as.service, 'Content-Type': alt.t, 'x-upsert': 'true' }, body: 'canary',
      });
      ok = up2.ok;
      usedPath = alt.p;
    }
    if (ok) created.objects.push({ bucket: b, path: usedPath });
    check('service', `storage write ${b}`, ok);
    const list = await call('service', 'POST', `/storage/v1/object/list/${b}`, { prefix: TAG, limit: 10 });
    check('service', `storage read ${b}`, rowsFrom(list) > 0, `${rowsFrom(list)} object(s)`);
  }
  return true;
}

// ---------------------------------------------------------------- (a)/(b) outsiders see nothing, change nothing

async function outsider(who, label) {
  console.log(`\n${label}\n`);
  for (const t of TABLES) {
    const r = await call(who, 'GET', `/rest/v1/${t}?select=*&limit=5`);
    const n = rowsFrom(r);
    check(who, `read ${t}`, n === 0, r.ok ? `${n} rows` : `denied ${r.status}`);
  }
  // Writes must fail (RLS "with check" or missing grant).
  const w1 = await call(who, 'POST', '/rest/v1/tasks', [{ title: `${TAG}-${who}` }], { Prefer: 'return=representation' });
  check(who, 'insert into tasks refused', !w1.ok, `status ${w1.status}`);
  if (w1.ok) created.rows.push({ table: 'tasks', filter: `title=eq.${encodeURIComponent(`${TAG}-${who}`)}` });
  const w2 = await call(who, 'PATCH', `/rest/v1/kv?key=eq.vc_enabled`, { value: true }, { Prefer: 'return=representation' });
  check(who, 'update kv (vc_enabled) changes nothing', !w2.ok || rowsFrom(w2) === 0, w2.ok ? `${rowsFrom(w2)} rows changed` : `denied ${w2.status}`);
  const w3 = await call(who, 'DELETE', `/rest/v1/agents?id=eq.operator`, undefined, { Prefer: 'return=representation' });
  check(who, 'delete from agents changes nothing', !w3.ok || rowsFrom(w3) === 0, w3.ok ? `${rowsFrom(w3)} rows deleted` : `denied ${w3.status}`);

  for (const [fn, args] of Object.entries(AGENT_RPCS)) {
    const r = await call(who, 'POST', `/rest/v1/rpc/${fn}`, args);
    check(who, `rpc ${fn} refused`, !r.ok, `status ${r.status}`);
  }
  const ap = await call(who, 'POST', '/rest/v1/rpc/approve_idea', { p_id: '00000000-0000-0000-0000-000000000000', p_note: null });
  check(who, 'rpc approve_idea refused', !ap.ok, `status ${ap.status}`);
  const da = await call(who, 'POST', '/rest/v1/rpc/decide_approval', { p_id: '00000000-0000-0000-0000-000000000000', p_decision: 'approved', p_note: null });
  check(who, 'rpc decide_approval refused', !da.ok, `status ${da.status}`);

  for (const b of BUCKETS) {
    const list = await call(who, 'POST', `/storage/v1/object/list/${b}`, { prefix: TAG, limit: 10 });
    check(who, `storage list ${b} empty`, rowsFrom(list) === 0, list.ok ? `${rowsFrom(list)} objects` : `denied ${list.status}`);
    const obj = created.objects.find((o) => o.bucket === b);
    if (obj) {
      const get = await fetch(`${URL_}/storage/v1/object/${b}/${obj.path}`, { headers: as[who] });
      check(who, `storage download ${b} refused`, !get.ok, `status ${get.status}`);
    }
    const put = await fetch(`${URL_}/storage/v1/object/${b}/${TAG}/intruder-${who}.png`, {
      method: 'POST', headers: { ...as[who], 'Content-Type': 'image/png' }, body: 'x',
    });
    if (put.ok) created.objects.push({ bucket: b, path: `${TAG}/intruder-${who}.png` });
    check(who, `storage upload ${b} refused`, !put.ok, `status ${put.status}`);
  }
}

async function signInStranger() {
  const email = `${TAG}@example.com`;
  const password = randomBytes(18).toString('base64url');
  const mk = await call('service', 'POST', '/auth/v1/admin/users', { email, password, email_confirm: true });
  if (!mk.ok) {
    check('user', 'create throwaway auth user', false, JSON.stringify(mk.data).slice(0, 160));
    return false;
  }
  created.userId = mk.data.id;
  const tok = await fetch(`${URL_}/auth/v1/token?grant_type=password`, {
    method: 'POST', headers: { apikey: ANON, 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
  });
  const data = await tok.json();
  if (!tok.ok || !data.access_token) {
    check('user', 'sign in as throwaway user', false, JSON.stringify(data).slice(0, 160));
    return false;
  }
  as.user = { apikey: ANON, Authorization: `Bearer ${data.access_token}` };
  check('user', `signed in as ${email} (not allowlisted)`, true);
  return true;
}

// ---------------------------------------------------------------- run

try {
  console.log(`Ownvista HQ RLS check against ${URL_}`);
  if (await seed()) {
    await outsider('anon', '(a) Anon / publishable key must read zero rows and change nothing');
    if (await signInStranger()) await outsider('user', '(b) Signed-in user who is not Bobby must read zero rows and change nothing');
  }
} catch (e) {
  check('script', 'unexpected error', false, e.message);
} finally {
  await cleanup();
  console.log('\nCleaned up canary rows, storage objects and the throwaway user.');
}

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed.`);
if (failed.length) {
  console.log('\nFAILED:');
  for (const f of failed) console.log(`- [${f.group}] ${f.name} ${f.detail}`);
  console.log('\nDo not continue setup until this is fixed.');
  process.exit(1);
}
console.log('RLS is working: only the service role (agents) and Bobby\'s login can see data.');
