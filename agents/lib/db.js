// Supabase REST (PostgREST) client over fetch. Agents use the service-role key.
import { requireEnv } from './env.js';

const base = () => requireEnv('SUPABASE_URL').replace(/\/$/, '');
const key = () => requireEnv('SUPABASE_SERVICE_ROLE_KEY');

// New sb_secret_… keys go on the apikey header only; legacy service_role JWTs also need Bearer.
export function authHeaders(extra = {}) {
  const k = key();
  return { apikey: k, ...(k.startsWith('eyJ') ? { Authorization: `Bearer ${k}` } : {}), ...extra };
}

async function call(method, path, { body, headers = {}, raw = false } = {}) {
  const res = await fetch(`${base()}${path}`, {
    method,
    headers: authHeaders({ 'Content-Type': 'application/json', ...headers }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (raw) return res;
  const text = await res.text();
  if (!res.ok) throw new Error(`Supabase ${method} ${path.split('?')[0]} → ${res.status}: ${text.slice(0, 400)}`);
  return text ? JSON.parse(text) : null;
}

const enc = (v) => encodeURIComponent(v);

// Build a PostgREST query string from { select, order, limit, filters: {col: 'eq.x'} }
function qs({ select = '*', order, limit, offset, ...filters } = {}) {
  const parts = [`select=${enc(select)}`];
  for (const [k, v] of Object.entries(filters)) {
    if (v === undefined) continue;
    for (const one of Array.isArray(v) ? v : [v]) parts.push(`${enc(k)}=${enc(one)}`);
  }
  if (order) parts.push(`order=${enc(order)}`);
  if (limit) parts.push(`limit=${limit}`);
  if (offset) parts.push(`offset=${offset}`);
  return parts.join('&');
}

export const db = {
  select(table, query = {}) {
    return call('GET', `/rest/v1/${table}?${qs(query)}`);
  },
  async one(table, query = {}) {
    const rows = await this.select(table, { ...query, limit: 1 });
    return rows[0] ?? null;
  },
  async count(table, filters = {}) {
    const res = await call('HEAD', `/rest/v1/${table}?${qs({ select: 'id', ...filters })}`, {
      headers: { Prefer: 'count=exact', Range: '0-0' }, raw: true,
    });
    const range = res.headers.get('content-range') || '*/0';
    return Number(range.split('/')[1] || 0);
  },
  insert(table, rows, { onConflict, ignoreDuplicates = false, merge = false } = {}) {
    const prefer = ['return=representation'];
    if (onConflict || merge || ignoreDuplicates) prefer.push(ignoreDuplicates ? 'resolution=ignore-duplicates' : 'resolution=merge-duplicates');
    const q = onConflict ? `?on_conflict=${enc(onConflict)}` : '';
    return call('POST', `/rest/v1/${table}${q}`, { body: rows, headers: { Prefer: prefer.join(',') } });
  },
  async insertOne(table, row, opts) {
    const rows = await this.insert(table, [row], opts);
    return rows?.[0] ?? null;
  },
  update(table, filters, patch) {
    return call('PATCH', `/rest/v1/${table}?${qs({ select: '*', ...filters })}`, {
      body: patch, headers: { Prefer: 'return=representation' },
    });
  },
  delete(table, filters) {
    return call('DELETE', `/rest/v1/${table}?${qs({ select: '*', ...filters })}`, { headers: { Prefer: 'return=representation' } });
  },
  rpc(fn, args = {}) {
    return call('POST', `/rest/v1/rpc/${fn}`, { body: args });
  },
};

// Key/value settings (kv table).
export async function kvGet(key, fallback = null) {
  const row = await db.one('kv', { key: `eq.${key}` });
  return row && row.value !== null ? row.value : fallback;
}

export async function kvSet(key, value) {
  await db.insert('kv', [{ key, value, updated_at: new Date().toISOString() }], { onConflict: 'key', merge: true });
}
