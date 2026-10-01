// Book Studio — daily, off-peak, $0. Does Bobby's Amazon KDP work except the parts Amazon keeps for a human:
//   seed      → Bobby's existing books go into kv amazon_books once (idempotent)
//   plan      → next book from the seasonal calendar (live 4-6 weeks before the date) or the evergreen list;
//               never more than 2 new KDP titles per week (KDP's week resets Sunday 00:00 UTC)
//   build     → interior.pdf + cover.pdf with the vendored Python engines (agents/books/engines), checked with pypdf
//   listing   → description + 7 keywords (Groq), checked for trademarks, banned words and things the book doesn't draw
//   pack      → every KDP field in order + checklist on the Shop page; Claude uploads in Chrome, Bobby clicks Publish
//   review    → weekly live-feed line: books by status, what needs Bobby, what needs Claude
// KDP has no publishing API. This agent never logs into Amazon, uploads, publishes, changes prices or spends money.
import { readFile, writeFile, mkdtemp } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { kvGet, kvSet, authHeaders } from '../lib/db.js';
import { requireEnv } from '../lib/env.js';
import { chat, CapError } from '../lib/llm.js';
import { systemPrompt } from '../lib/guard.js';
import { truncate } from '../lib/text.js';
import { etDate } from '../lib/time.js';
import { upload } from '../lib/storage.js';
import {
  KV_KEY, BUCKET, seedBooks, applyPatches, slotsLeft, uploadAfter, pickNext, mandalaConfig, vetText, vetListing,
  defaultListing, weeklyReview, weekKey, printCost, DEFAULT_PRICE,
} from '../lib/books.js';

const ENGINES = fileURLToPath(new URL('../books/engines/', import.meta.url));
const STATE_KEY = 'book_studio_state';

const needsBuild = (b) => ['planned', 'needs_upload'].includes(b.status) && b.engine && !b.files?.interior;

async function load() {
  const books = (await kvGet(KV_KEY, [])) || [];
  return Array.isArray(books) ? books : [];
}

// Read fresh and apply only this run's changes, so a status Bobby set from the Shop page meanwhile is kept.
async function save(patches) {
  if (!patches.length) return;
  const { books } = applyPatches(await load(), patches);
  await kvSet(KV_KEY, books);
}

// Cheap check for the hourly job's plan step: is there a book to build (and so Python to install)?
export async function hasWork() {
  const books = seedBooks(await load()).books;
  if (books.some(needsBuild)) return true;
  return slotsLeft(books) > 0 && !!pickNext(books, etDate());
}
export async function needsToddler() {
  return (await load()).some((b) => needsBuild(b) && b.engine === 'toddler');
}

export async function run(ctx) {
  const out = [];
  let books = await load();

  // 1. Seed Bobby's books (only those missing).
  const seeded = seedBooks(books);
  if (seeded.added) {
    await save(seeded.books.slice(books.length).map((b) => ({ slug: b.slug, set: b, add: true })));
    books = await load();
    out.push(`seeded ${seeded.added} book(s)`);
  }

  // 2. Weekly Amazon review (first run of each KDP week).
  const state = (await kvGet(STATE_KEY, {})) || {};
  const wk = weekKey(new Date());
  if (state.review_week !== wk) {
    const r = weeklyReview(books, etDate());
    ctx.log('books', r.line);
    await kvSet(STATE_KEY, { ...state, review_week: wk, last_review: r.line, at: new Date().toISOString() });
    out.push('weekly review posted');
  }

  // 3. Plan one new book if the weekly KDP title cap allows it.
  const left = slotsLeft(books);
  if (left > 0) {
    const pick = pickNext(books, etDate());
    if (pick) {
      const problems = vetText(`${pick.title}\n${pick.subtitle}`, { motifs: pick.motifs });
      if (problems.length) {
        ctx.note(`skipped plan "${pick.title}": ${problems.join('; ')}`);
      } else {
        const book = {
          ...pick, status: 'planned', engine: 'mandala', designs: 40, pages: 84,
          print_cost: printCost(84), recommended_price: DEFAULT_PRICE, created_at: new Date().toISOString(),
          history: [{ at: new Date().toISOString(), status: 'planned', by: 'book_studio' }],
          notes: pick.occasion ? `For ${pick.occasion.replace('_', ' ')} ${pick.occasion_year}: live by ${pick.live_by}.` : 'Evergreen title.',
        };
        await save([{ slug: book.slug, set: book, add: true }]);
        books = await load();
        ctx.log('books', `Book Studio planned "${truncate(book.title, 70)}" (${pick.occasion ? `${pick.occasion.replace('_', ' ')} ${pick.occasion_year}` : 'evergreen'})`);
        out.push(`planned "${truncate(book.title, 40)}"`);
      }
    }
  } else out.push('weekly KDP title cap reached — no new book planned');

  // 4. Build one book per run.
  const todo = books.find(needsBuild);
  if (todo) {
    if (ctx.outOfTime(150000)) out.push('no time left to build');
    else out.push(await buildBook(ctx, todo, books));
  }
  return out.join(' · ') || 'nothing to do';
}

// Runs a command; resolves { code, out, err } (stdout is kept on failure: build.py prints its verdict there).
function py(args, timeoutMs) {
  return new Promise((resolve) => {
    const p = spawn('python3', ['-B', ...args], { stdio: ['ignore', 'pipe', 'pipe'], cwd: tmpdir() });
    let out = '', err = '';
    const timer = setTimeout(() => p.kill('SIGKILL'), timeoutMs);
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { err = (err + d).slice(-20000); });
    p.on('error', (e) => { clearTimeout(timer); resolve({ code: -1, out, err: String(e.message) }); });
    p.on('close', (code) => { clearTimeout(timer); resolve({ code, out, err }); });
  });
}

async function pythonReady(engine) {
  const mods = engine === 'toddler' ? 'reportlab, pypdf, numpy, scipy, PIL' : 'reportlab, pypdf';
  return (await py(['-c', `import ${mods}`], 60000)).code === 0;
}

async function ensureBucket() {
  const base = `${requireEnv('SUPABASE_URL').replace(/\/$/, '')}/storage/v1`;
  const have = await fetch(`${base}/bucket/${BUCKET}`, { headers: authHeaders() });
  if (have.ok) return;
  const res = await fetch(`${base}/bucket`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ id: BUCKET, name: BUCKET, public: false, file_size_limit: 52428800, allowed_mime_types: ['application/pdf', 'image/png', 'application/json'] }),
  });
  if (!res.ok && res.status !== 409) throw new Error(`could not create storage bucket ${BUCKET}: ${res.status} ${(await res.text()).slice(0, 200)}`);
}

async function buildBook(ctx, book, books) {
  if (!(await pythonReady(book.engine))) return `"${truncate(book.title, 40)}" waits: Python packages not installed on this run`;
  const dir = await mkdtemp(join(tmpdir(), 'book-'));
  const args = [join(ENGINES, 'build.py'), '--engine', book.engine, '--out', dir];
  let config = null;
  if (book.engine === 'mandala') {
    config = book.config_path
      ? JSON.parse(await readFile(fileURLToPath(new URL(`../../${book.config_path}`, import.meta.url)), 'utf8'))
      : mandalaConfig(book, book.designs || 40);
    const cfgFile = join(dir, 'config.json');
    await writeFile(cfgFile, JSON.stringify(config, null, 1));
    args.push('--config', cfgFile, '--pages', String(config.pages));
  } else if (book.pages) args.push('--pages', String(book.pages));

  const r = await py(args, 8 * 60000);
  let res;
  try { res = JSON.parse(r.out.trim().split('\n').filter((l) => l.trim().startsWith('{')).pop()); }
  catch { res = { ok: false, problems: [`builder exited ${r.code}: ${truncate(r.err.trim().split('\n').slice(-3).join(' '), 300)}`] }; }
  if (r.code !== 0) res.ok = false;
  if (!res?.ok) {
    const why = (res?.problems || ['unknown error']).join('; ');
    await save([{ slug: book.slug, set: { build_error: truncate(why, 500), build_failed_at: new Date().toISOString() } }]);
    ctx.log('books', `Book Studio build FAILED for "${truncate(book.title, 60)}": ${truncate(why, 200)}`);
    throw new Error(`build failed for ${book.slug}: ${why}`);
  }

  await ensureBucket();
  const prefix = `${book.slug}`;
  const files = {
    interior: await upload(BUCKET, `${prefix}/interior.pdf`, await readFile(join(dir, 'interior.pdf')), 'application/pdf'),
    cover: await upload(BUCKET, `${prefix}/cover.pdf`, await readFile(join(dir, 'cover.pdf')), 'application/pdf'),
  };
  if (res.thumb) files.thumb = await upload(BUCKET, `${prefix}/cover-thumb.png`, await readFile(res.thumb), 'image/png').catch(() => undefined);
  if (config) files.config = await upload(BUCKET, `${prefix}/config.json`, Buffer.from(JSON.stringify(config, null, 1)), 'application/json').catch(() => undefined);

  const built = { ...book, pages: res.pages, designs: config?.plan?.length || book.designs };
  const { listing, dropped } = await writeListing(ctx, built);
  const now = new Date().toISOString();
  const set = {
    files, pages: res.pages, designs: built.designs, cover_in: res.cover_in, spine_in: res.spine_in, built_at: now, build_error: null,
    print_cost: Number(book.print_cost) || printCost(res.pages), listing, listing_dropped: dropped,
    upload_after: book.upload_after || uploadAfter(books),
  };
  const patches = [];
  if (book.status === 'planned') {
    patches.push({ slug: book.slug, expect: 'planned', set: { ...set, status: 'built' } });
    patches.push({ slug: book.slug, expect: 'built', set: { status: 'needs_upload' } });
  } else patches.push({ slug: book.slug, expect: book.status, set });
  await save(patches);
  ctx.log('books', `Book ready for KDP: "${truncate(book.title, 60)}" (${res.pages} pages, cover ${res.cover_in.join(' x ')} in). Upload pack on the Shop page; Claude uploads${set.upload_after > etDate() ? ` on/after ${set.upload_after}` : ''}, Bobby clicks Publish.`);
  return `built "${truncate(book.title, 40)}" (${res.pages} pages)`;
}

// Description + keywords from the LLM, vetted; anything that fails falls back to the safe default.
async function writeListing(ctx, book) {
  const motifs = book.motifs === 'christmas'
    ? 'snowflakes, poinsettias, holly, ornaments, wreaths, evergreen trees, stars, petals, lace'
    : 'petals, flowers in general terms, lace, beads, stars, geometric bands (nothing else is drawn)';
  try {
    const { json } = await chat({
      ctx, tier: 'smart', json: true, maxTokens: 1800, temperature: 0.5,
      system: systemPrompt('the Book Studio writing an Amazon KDP paperback listing', `
Write the Amazon description and 7 search keywords for one adult coloring book. Bobby reviews before anything is published.
Honest only: describe exactly what is printed. The pages show only: ${motifs}. Never name anything else as a subject.
No brand, character, author or artist names. No "free", "sale", "bestseller", "#1", "Amazon", "Kindle", rankings, reviews or awards.
Never call the art hand-drawn or handmade. No links, no prices, no phone numbers.
description: 120-250 words of HTML using only <p>, <b>, <ul>, <li>, <br>. Mention single-sided pages, 8.5 x 11 in, the color test page and the design count.
keywords: exactly 7 lowercase phrases a buyer types, each under 50 characters, not repeating title words verbatim.
JSON only: {"description":"","keywords":["",""]}`),
      messages: [{ role: 'user', content: `Title: ${book.title}\nSubtitle: ${book.subtitle}\nAuthor (pen name): ${book.author}\nDesigns: ${book.designs || 40}\nPages: ${book.pages}\n${book.occasion ? `Occasion: ${book.occasion.replace('_', ' ')}` : 'Evergreen (any time of year)'}` }],
    });
    const { listing, dropped } = vetListing(json || {}, book);
    return { listing, dropped };
  } catch (e) {
    if (!(e instanceof CapError)) ctx.note(`listing: ${truncate(e.message, 100)}`);
    return { listing: defaultListing(book), dropped: [`LLM listing not used (${truncate(e.message, 80)}); default listing kept`] };
  }
}
