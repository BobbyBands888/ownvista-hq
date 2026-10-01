// levelingclips.com/api/books — the Shop page's Amazon (KDP) section. Bobby's dashboard login only.
//   GET                                   → books (kv amazon_books) + short-lived signed links to their PDFs
//   POST { slug, status, kdp_title_id?, list_price? } → records a step Bobby/Claude did on KDP (allowed moves only)
// Records what happened on Amazon; it never talks to Amazon, publishes or changes a price there.
import { sb, SB, json } from './_supabase.js';
import { KV_KEY, BUCKET, canMove, applyPatches, uploadPack, priceAdvice } from '../agents/lib/books.js';

const ALLOWED = 'bobbybands888@gmail.com';

async function isBobby(request) {
  const auth = request.headers.get('authorization') || '';
  if (!/^Bearer\s+\S+/.test(auth)) return false;
  const key = process.env.SUPABASE_ANON_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY || '';
  const res = await fetch(`${SB()}/auth/v1/user`, { headers: { apikey: key, Authorization: auth } }).catch(() => null);
  if (!res?.ok) return false;
  const user = await res.json().catch(() => null);
  return String(user?.email || '').toLowerCase() === ALLOWED;
}

async function loadBooks() {
  const rows = await sb('GET', `/rest/v1/kv?key=eq.${KV_KEY}&select=value`);
  const v = rows?.[0]?.value;
  return Array.isArray(v) ? v : [];
}

async function sign(path) {
  if (!path) return null;
  try {
    const r = await sb('POST', `/storage/v1/object/sign/${BUCKET}/${path.split('/').map(encodeURIComponent).join('/')}`, { expiresIn: 3600 });
    return r?.signedURL ? `${SB()}/storage/v1${r.signedURL}` : null;
  } catch { return null; }
}

export async function GET(request) {
  if (!(await isBobby(request))) return json({ error: 'unauthorized' }, 401);
  const books = await loadBooks();
  const out = await Promise.all(books.map(async (b) => ({
    ...b,
    links: { interior: await sign(b.files?.interior), cover: await sign(b.files?.cover), thumb: await sign(b.files?.thumb) },
    pack: b.files?.interior && ['built', 'needs_upload', 'uploaded_draft'].includes(b.status) ? uploadPack(b) : null,
    price: priceAdvice(b),
  })));
  return json({ books: out });
}

export async function POST(request) {
  if (!(await isBobby(request))) return json({ error: 'unauthorized' }, 401);
  let body;
  try { body = await request.json(); } catch { return json({ error: 'Bad request' }, 400); }
  const books = await loadBooks();
  const book = books.find((b) => b.slug === body.slug);
  if (!book) return json({ error: 'No such book' }, 404);
  if (!canMove(book.status, body.status, 'human')) return json({ error: `Can't move a book from ${book.status} to ${body.status}` }, 400);
  const set = { status: body.status };
  const today = new Date().toISOString().slice(0, 10);
  if (body.kdp_title_id != null && body.kdp_title_id !== '') {
    const id = String(body.kdp_title_id).trim().toUpperCase();
    if (!/^[A-Z0-9]{8,14}$/.test(id)) return json({ error: 'KDP title ID looks wrong (letters and digits, like EHB1H1HFNNN)' }, 400);
    set.kdp_title_id = id;
  }
  if (body.list_price != null && body.list_price !== '') {
    const p = Number(body.list_price);
    if (!(p >= 0.99 && p <= 250)) return json({ error: 'Price must be between $0.99 and $250' }, 400);
    set.list_price = Math.round(p * 100) / 100; // what Bobby set on KDP (recorded, not changed by us)
  }
  if (body.status === 'uploaded_draft') {
    if (!set.kdp_title_id && !book.kdp_title_id) return json({ error: 'Add the KDP title ID first' }, 400);
    if (!book.kdp_created_at) set.kdp_created_at = today; // counts toward KDP's weekly title limit
  }
  if (body.status === 'in_review' && !book.submitted_at) set.submitted_at = today;
  if (body.status === 'live' && !book.live_at) set.live_at = today;
  const { books: next } = applyPatches(books, [{ slug: book.slug, expect: book.status, set, by: 'bobby' }]);
  await sb('POST', '/rest/v1/kv?on_conflict=key', [{ key: KV_KEY, value: next, updated_at: new Date().toISOString() }], { Prefer: 'resolution=merge-duplicates,return=minimal' });
  await sb('POST', '/rest/v1/activity', [{ agent: 'book_studio', kind: 'books', message: `KDP: "${book.title.slice(0, 80)}" marked ${body.status.replace('_', ' ')}${set.kdp_title_id ? ` (${set.kdp_title_id})` : ''}` }], { Prefer: 'return=minimal' }).catch(() => {});
  return json({ ok: true });
}
