// Supabase Storage over fetch (private buckets: vc-photos, vc-films, vc-music).
import { requireEnv } from './env.js';
import { authHeaders } from './db.js';

const base = () => `${requireEnv('SUPABASE_URL').replace(/\/$/, '')}/storage/v1`;
const p = (path) => path.split('/').map(encodeURIComponent).join('/');

async function ok(res, what) {
  if (!res.ok) throw new Error(`Storage ${what} → ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res;
}

export async function upload(bucket, path, data, contentType) {
  await ok(await fetch(`${base()}/object/${bucket}/${p(path)}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': contentType, 'x-upsert': 'true' }),
    body: data,
  }), `upload ${bucket}/${path}`);
  return path;
}

export async function download(bucket, path) {
  const res = await ok(await fetch(`${base()}/object/${bucket}/${p(path)}`, { headers: authHeaders() }), `download ${bucket}/${path}`);
  return Buffer.from(await res.arrayBuffer());
}

export async function list(bucket, prefix = '', limit = 200) {
  const res = await ok(await fetch(`${base()}/object/list/${bucket}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ prefix, limit, offset: 0, sortBy: { column: 'name', order: 'asc' } }),
  }), `list ${bucket}/${prefix}`);
  const rows = await res.json();
  return rows.filter((r) => r.id); // folders have no id
}

export async function signedUrl(bucket, path, expiresIn = 3600) {
  const res = await ok(await fetch(`${base()}/object/sign/${bucket}/${p(path)}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ expiresIn }),
  }), `sign ${bucket}/${path}`);
  const { signedURL } = await res.json();
  return `${base()}${signedURL}`;
}

export async function remove(bucket, paths) {
  if (!paths.length) return;
  await ok(await fetch(`${base()}/object/${bucket}`, {
    method: 'DELETE',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ prefixes: paths }),
  }), `remove ${bucket}`);
}
