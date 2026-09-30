// films.villacinema.com/upload → signed upload URLs for one order's photos.
// POST { order, token, files:[{ name, size, type }] } → { uploads:[{ name, url }] }
// POST { order, token, action:'complete' } → marks the order photos_received
import { sb, SB, sha256, isUuid, json } from './_supabase.js';

const MAX_FILES = 30;
const MAX_BYTES = 20 * 1024 * 1024;
const TYPES = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp' };

async function loadOrder(id, token) {
  if (!isUuid(id) || typeof token !== 'string' || token.length < 20) return null;
  const rows = await sb('GET', `/rest/v1/vc_orders?id=eq.${id}&select=id,status,upload_token_hash,prospect_id,photos_prefix`);
  const o = rows?.[0];
  if (!o || o.upload_token_hash !== sha256(token) || o.photos_prefix) return null;
  return o;
}

async function listPhotos(orderId) {
  return sb('POST', '/storage/v1/object/list/vc-photos', { prefix: orderId, limit: 100, offset: 0 }).then((r) => r.filter((x) => x.id));
}

export async function POST(request) {
  let body;
  try { body = await request.json(); } catch { return json({ error: 'Bad request' }, 400); }
  const order = await loadOrder(body.order, body.token).catch(() => null);
  if (!order) return json({ error: 'This upload link is not valid. Reply to our email and we will send a fresh one.' }, 403);
  if (order.status !== 'awaiting_photos') return json({ error: 'Photos for this order are already in. Thank you!' }, 409);

  const existing = await listPhotos(order.id);

  if (body.action === 'complete') {
    if (existing.length < 8) return json({ error: `Please upload at least 8 photos (you have ${existing.length}).` }, 400);
    const now = new Date().toISOString();
    await sb('PATCH', `/rest/v1/vc_orders?id=eq.${order.id}`, { status: 'photos_received', photos_submitted_at: now, updated_at: now }, { Prefer: 'return=minimal' });
    if (order.prospect_id) {
      await sb('PATCH', `/rest/v1/vc_prospects?id=eq.${order.prospect_id}`, { stage: 'photos_received', updated_at: now }, { Prefer: 'return=minimal' });
    }
    return json({ ok: true, count: existing.length });
  }

  const files = Array.isArray(body.files) ? body.files.slice(0, 12) : [];
  if (!files.length) return json({ error: 'No files' }, 400);
  if (existing.length + files.length > MAX_FILES) return json({ error: `Up to ${MAX_FILES} photos per order.` }, 400);
  const uploads = [];
  for (const [i, f] of files.entries()) {
    const ext = TYPES[f.type];
    if (!ext) return json({ error: `${f.name}: please use JPG, PNG or WEBP.` }, 400);
    if (!(f.size > 0 && f.size <= MAX_BYTES)) return json({ error: `${f.name}: each photo must be under 20 MB.` }, 400);
    const path = `${order.id}/${Date.now()}-${existing.length + i}.${ext}`;
    const signed = await sb('POST', `/storage/v1/object/upload/sign/vc-photos/${path}`, {});
    uploads.push({ name: f.name, url: `${SB()}/storage/v1${signed.url}` });
  }
  return json({ uploads });
}
