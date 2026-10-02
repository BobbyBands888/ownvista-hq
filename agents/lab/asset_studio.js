// Asset Studio — hourly, 24/7, $0. Makes game asset packs for itch.io on Cloudflare's free image allowance:
//   research  → reads itch.io's best-selling game assets feed + what our own packs sold
//   plan      → one pack at a time: theme, consistent style, 16 items, tags, price, page copy (AI disclosed)
//   generate  → FLUX.1 schnell on the free plan (stops for the day when the allowance is used; never bills)
//   clean     → sprites/icons get a flat magenta background keyed out to transparent PNG (512 + 128 px)
//   QA        → the vision model grades each image; weak ones are redone once, then dropped
//   package   → preview sheet + zip (PNGs, LICENSE, README) in private storage → Needs you: "publish on itch.io"
//   learn     → itch.io stats (views, downloads, sales) flow back into the plan and the ledger
// Bobby creates the itch.io page and clicks Publish; agents never create accounts or publish.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { db, kvGet, kvSet } from '../lib/db.js';
import { env, hasEnv } from '../lib/env.js';
import { chat, CapError } from '../lib/llm.js';
import { systemPrompt, checkCopy, untrusted } from '../lib/guard.js';
import { playbook } from '../lib/context.js';
import { fetchFeed } from '../lib/feeds.js';
import { truncate } from '../lib/text.js';
import { etDate, addDays } from '../lib/time.js';
import { run as sh, hasFfmpeg, workdir } from '../lib/ffmpeg.js';
import { upload, download } from '../lib/storage.js';
import { generateImage, imagesLeftToday, cfReady, ImageCapReached } from '../lib/cfimage.js';

const BUCKET = 'asset-packs';
const KEYED = new Set(['sprites', 'icons', 'items', 'characters', 'props']);
const TREND_FEEDS = ['https://itch.io/game-assets/top-sellers.xml', 'https://itch.io/game-assets/new-and-popular.xml'];

const MAX_TRIES = 4; // the vision grader is noisy; Oct 1 a bad duplicate check also burned tries on good images
const RULES = async () => ({ images_per_day: 100, items_per_pack: 16, max_waiting: 3, goal_sales: 5, days: 30, ...(await kvGet('asset_rules', {})) });
const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'item';

export async function hasWork() {
  if (!cfReady()) return false;
  try { await db.select('asset_packs', { select: 'id', limit: 1 }); } catch { return false; }
  // A finished pack still needs ffmpeg to be packaged even after the day's image allowance is used.
  if ((await db.count('asset_packs', { status: 'eq.packaging' }).catch(() => 0)) > 0) return true;
  const rules = await RULES();
  return (await imagesLeftToday(rules.images_per_day)) > 0;
}

export async function run(ctx) {
  try { await db.select('asset_packs', { select: 'id', limit: 1 }); } catch { return 'waiting for the database update (run the Asset Studio SQL block in Supabase)'; }
  const rules = await RULES();
  const out = [];
  const synced = await syncItch(ctx);
  if (synced) out.push(synced);
  const killed = await enforceKillRule(ctx, rules);
  if (killed) return killed;

  if (!cfReady()) { out.push('waiting for Cloudflare (CF_ACCOUNT_ID, CF_API_TOKEN)'); return out.join(' · '); }
  if (!(await hasFfmpeg())) {
    // The job installs ffmpeg only when hasWork() says yes, so say the real reason (usually: allowance used today).
    const left = await imagesLeftToday(rules.images_per_day);
    out.push(left <= 0 ? 'free image allowance used for today (ffmpeg skipped)' : 'no ffmpeg on this run');
    return out.join(' · ');
  }

  // Finish what's in progress before starting anything new.
  let pack = await db.one('asset_packs', { status: 'in.(generating,packaging)', order: 'created_at.asc' });
  if (!pack) {
    const waiting = await db.count('asset_packs', { status: 'eq.ready' });
    if (waiting >= rules.max_waiting) { out.push(`${waiting} pack(s) waiting for Bobby to publish — not starting more`); return out.join(' · '); }
    if ((await imagesLeftToday(rules.images_per_day)) <= 0) { out.push('free image allowance used for today'); return out.join(' · '); }
    pack = await planPack(ctx, rules);
    if (!pack) { out.push('could not plan a pack this run'); return out.join(' · '); }
    out.push(`planned "${truncate(pack.title, 50)}"`);
  }

  if (pack.status === 'generating') {
    const r = await generateItems(ctx, pack, rules);
    out.push(r.msg);
    pack = r.pack;
  }
  if (pack.status === 'packaging' && !ctx.outOfTime(90000)) out.push(await packagePack(ctx, pack));
  return out.join(' · ');
}

// ---------- Plan ----------
async function planPack(ctx, rules) {
  const pb = await playbook();
  const trends = [];
  for (const url of TREND_FEEDS) {
    try { trends.push(...(await fetchFeed({ url })).items.slice(0, 25).map((i) => i.title)); } catch (e) { ctx.note(`feed ${url}: ${e.message}`); }
  }
  const past = await db.select('asset_packs', { select: 'title,kind:theme,style,status,views,downloads,sales,revenue,price_usd,feedback', order: 'created_at.desc', limit: 15 });
  const hints = ((await kvGet('asset_pack_ideas', [])) || []).slice(0, 6);
  const lessons = await db.select('playbook_rules', { active: 'eq.true', category: 'in.(lab,guardrails)', select: 'rule', limit: 30 });

  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 3500, temperature: 0.7,
    system: systemPrompt('the Asset Studio planning an itch.io game asset pack', `${pb.text(['guardrails', 'results'])}
Lessons learned so far:
${lessons.map((l) => `- ${l.rule}`).join('\n') || '- (none yet)'}

You make packs with an AI image model that draws ONE square 1024px image per prompt. It is good at: single objects (weapons,
potions, food, gems, tools), icons, character portraits, props, seamless textures, painted backgrounds. It is BAD at: tilesets that
must line up, animation frames/sprite sheets, consistent characters across poses, text, UI with words, and exact pixel grids.
Pick a niche with buyer demand (use the best-seller titles as a signal, don't copy them) that plays to those strengths.
Rules: no trademarks, franchises, real brands or living artists' names; no "in the style of <artist>". Distinct from our past packs.
kind: one of sprites | icons | items | characters | props (these get transparent backgrounds) or portraits | textures | backgrounds (full frame).
style: one short visual style clause appended to every prompt so the pack looks consistent (e.g. "painted fantasy game icon, bold outline, soft shading").
items: exactly ${rules.items_per_pack}, each {"name":"Short name","prompt":"what to draw, one subject"}.
price_usd: 2–8 (itch.io asset buyers pay little; low price + volume). tags: up to 10 itch.io tags.
page_copy: markdown for the itch.io page — hook, what's included (${rules.items_per_pack} PNGs, 512px + 128px${'${transparent}'}), suggested uses,
license summary (use in commercial and non-commercial games; do not resell or redistribute the files as-is), and the line
"Made with AI image generation (FLUX.1 schnell), then checked and cleaned up." Never call the images hand-painted or hand-drawn. No fake reviews, no download counts.
JSON only: {"title":"","theme":"","kind":"icons","style":"","items":[{"name":"","prompt":""}],"tags":[],"price_usd":3,"page_copy":""}`),
    messages: [{ role: 'user', content: `${untrusted('itch.io best sellers right now', trends.join('\n') || '(feed unavailable)', 4000)}

Our past packs (learn from what sold and what didn't):
${past.map((p) => `- ${p.title} [${p.status}] $${p.price_usd} · views ${p.views} · downloads ${p.downloads} · sales ${p.sales} · $${p.revenue}${p.feedback ? ` · Bobby: ${p.feedback}` : ''}`).join('\n') || '(none yet — this is the first pack)'}

${hints.length ? untrusted('pack niches the Product Scout found demand for (pick one if it fits the model\'s strengths, or ignore)', hints.map((h) => `- ${h.niche}: ${h.why}`).join('\n'), 2000) : ''}` }],
  });

  const items = (json.items || []).filter((i) => i?.name && i?.prompt).slice(0, rules.items_per_pack);
  if (!json.title || items.length < Math.min(12, rules.items_per_pack)) return null;
  const kind = String(json.kind || 'icons').toLowerCase();
  const keyed = KEYED.has(kind);
  const copy = String(json.page_copy || '').replace('${transparent}', keyed ? ', transparent background' : '');
  const problems = checkCopy(`${json.title}\n${copy}\n${items.map((i) => i.prompt).join('\n')}`, {});
  if (problems.length) { ctx.note(`plan failed guardrails: ${problems.join('; ')}`); return null; }
  const price = Math.min(8, Math.max(2, Number(json.price_usd) || 3));
  return db.insertOne('asset_packs', {
    title: truncate(json.title, 120), theme: truncate(json.theme || '', 300), style: truncate(json.style || '', 300),
    status: 'generating', price_usd: price, tags: (json.tags || []).map((t) => truncate(String(t), 40)).slice(0, 10),
    page_copy: truncate(copy, 6000),
    items: items.map((i, n) => ({ n: n + 1, name: truncate(i.name, 60), prompt: truncate(i.prompt, 400), kind, keyed, attempts: 0, grade: null, done: false, path: null })),
  });
}

// ---------- Generate + clean + QA ----------
// FLUX tends to draw sprite sheets when it hears "game asset" or "icons", so ask for ONE object, fully in frame.
function promptFor(pack, item) {
  const style = String(pack.style || '').replace(/\b(icons?|sprites?|sheet|set|pack|collection)\b/gi, '').replace(/\s+,/g, ',').trim();
  if (!item.keyed) return `${item.prompt}. ${style}. Full-frame illustration, no text, no letters, no watermark, no border.`;
  // Oct 1 QA data: "small with lots of empty space" gave tiny subjects (keyed away) and FLUX filled the space with
  // extra copies or collages. Ask for one medium-sized object with a clear margin instead.
  return `One single ${item.name.toLowerCase()} (${item.prompt}), centered, shown whole, filling about half of the image, with a clear margin on every side. `
    + `Only one object: not a set, not a collage, not a pattern, no duplicates. `
    + `${style}. Plain flat solid pure magenta #FF00FF background filling the whole image, no floor, no cast shadow, no text, no letters.`;
}

// Raw pixels from ffmpeg (small sizes only).
async function rawPixels(file, w, h, vf = '') {
  const out = await new Promise((resolve, reject) => {
    const p = spawn('ffmpeg', ['-loglevel', 'error', '-i', file, '-vf', `${vf}${vf ? ',' : ''}scale=${w}:${h}`, '-f', 'rawvideo', '-pix_fmt', 'rgba', '-']);
    const chunks = [];
    p.stdout.on('data', (d) => chunks.push(d));
    p.on('error', reject);
    p.on('close', (code) => (code === 0 ? resolve(Buffer.concat(chunks)) : reject(new Error(`ffmpeg raw exited ${code}`))));
  });
  return out;
}

// The model rarely paints pure #FF00FF, so key out whatever flat color it actually used: sample the four corners.
async function backgroundColor(file) {
  const px = await rawPixels(file, 32, 32);
  const at = (x, y) => { const i = (y * 32 + x) * 4; return [px[i], px[i + 1], px[i + 2]]; };
  const samples = [];
  for (const [x0, y0] of [[0, 0], [28, 0], [0, 28], [28, 28]]) for (let dx = 0; dx < 4; dx++) for (let dy = 0; dy < 4; dy++) samples.push(at(x0 + dx, y0 + dy));
  const avg = [0, 1, 2].map((c) => Math.round(samples.reduce((n, s) => n + s[c], 0) / samples.length));
  const spread = Math.max(...samples.map((s) => Math.abs(s[0] - avg[0]) + Math.abs(s[1] - avg[1]) + Math.abs(s[2] - avg[2])));
  return { hex: avg.map((v) => v.toString(16).padStart(2, '0')).join(''), flat: spread < 60 };
}

async function keyOut(jpg, dir, item) {
  const inFile = join(dir, `${item.n}.jpg`);
  await writeFile(inFile, jpg);
  const big = join(dir, `${item.n}-512.png`), small = join(dir, `${item.n}-128.png`);
  let bg = null;
  if (item.keyed) bg = await backgroundColor(inFile);
  const vf = item.keyed
    ? `colorkey=0x${bg.hex}:0.16:0.10,format=rgba,scale=512:512:flags=lanczos`
    : 'scale=512:512:flags=lanczos';
  await sh('ffmpeg', ['-y', '-loglevel', 'error', '-i', inFile, '-vf', vf, big]);
  await sh('ffmpeg', ['-y', '-loglevel', 'error', '-i', big, '-vf', 'scale=128:128:flags=lanczos', small]);
  const qaFile = join(dir, `${item.n}-qa.jpg`);
  await sh('ffmpeg', ['-y', '-loglevel', 'error', '-i', inFile, '-vf', 'scale=384:384', '-q:v', '5', qaFile]);

  // Deterministic checks on the keyed image: flat background, subject fully inside the frame, sensible size.
  let checks = { ok: true, issue: '' };
  if (item.keyed) {
    const a = await rawPixels(big, 64, 64);
    let opaque = 0, edge = 0;
    for (let y = 0; y < 64; y++) for (let x = 0; x < 64; x++) {
      if (a[(y * 64 + x) * 4 + 3] > 128) { opaque++; if (x < 2 || y < 2 || x > 61 || y > 61) edge++; }
    }
    const cover = opaque / 4096;
    if (!bg.flat) checks = { ok: false, issue: 'background not flat' };
    else if (edge > 6) checks = { ok: false, issue: 'subject touches the edge' };
    else if (cover < 0.02) checks = { ok: false, issue: 'subject too small or keyed away' };
    else if (cover > 0.75) checks = { ok: false, issue: 'background not removed' };
  }
  return { big, small, checks, qa: `data:image/jpeg;base64,${(await readFile(qaFile)).toString('base64')}` };
}

// Vision check answers narrow yes/no questions; the pixel checks above handle framing and background.
async function grade(ctx, pack, item, qaUri) {
  const { json } = await chat({
    ctx, tier: 'vision', json: true, maxTokens: 200, temperature: 0.1,
    system: systemPrompt('the Asset Studio QA checker', `Look at the picture and answer honestly.
matches: does it clearly show a ${item.name} (${item.prompt})?
has_text: are there readable letters, words or a watermark anywhere?
brand: does it look like a famous trademarked character or logo?
quality: 1–5, how good would it look as a video game item image (5 = polished, 1 = garbled/broken).
JSON only: {"matches":true,"has_text":false,"brand":false,"quality":4,"issue":"short or empty"}`),
    messages: [{ role: 'user', content: [{ type: 'text', text: `Item: ${item.name}` }, { type: 'image', url: qaUri }] }],
  });
  const quality = Math.max(1, Math.min(5, Number(json.quality) || 3));
  // (Oct 1: a "how many copies?" question was tried and removed: this vision model reported 2+ copies on clean
  // single-object images and failed good items. Framing is handled by the pixel checks instead.)
  const bad = json.matches === false ? 'does not match the item' : json.has_text === true ? 'text in image' : json.brand === true ? 'looks like a brand' : '';
  return { grade: bad ? Math.min(2, quality) : quality, issue: truncate(bad || json.issue || '', 120) };
}

async function generateItems(ctx, pack, rules) {
  const dir = await workdir();
  const items = pack.items.map((i) => ({ ...i }));
  let made = 0, stop = '';
  for (const item of items) {
    if (item.done || item.attempts >= MAX_TRIES) continue;
    if (ctx.outOfTime(100000)) { stop = 'out of time'; break; }
    try {
      const jpg = await generateImage(promptFor(pack, item), { cap: rules.images_per_day });
      item.attempts++;
      made++;
      const f = await keyOut(jpg, dir, item);
      const g = f.checks.ok ? await grade(ctx, pack, item, f.qa) : { grade: 1, issue: f.checks.issue };
      item.grade = g.grade;
      item.issue = g.issue;
      if (g.grade < 3) {
        // Keep rejects so prompts can be tuned by looking at what went wrong.
        await upload(BUCKET, `${pack.id}/rejects/${String(item.n).padStart(2, '0')}-try${item.attempts}.jpg`, Buffer.from(f.qa.split(',')[1], 'base64'), 'image/jpeg').catch(() => {});
      }
      if (g.grade >= 3) {
        const base = `${pack.id}/items/${String(item.n).padStart(2, '0')}-${slug(item.name)}`;
        await upload(BUCKET, `${base}.png`, await readFile(f.big), 'image/png');
        await upload(BUCKET, `${base}-128.png`, await readFile(f.small), 'image/png');
        item.done = true;
        item.path = `${base}.png`;
      }
    } catch (e) {
      if (e instanceof ImageCapReached) { stop = e.message; break; }
      if (e instanceof CapError) { stop = `LLM cap: ${e.message}`; break; }
      // A setup problem (bad request, auth) is not the item's fault: don't burn its attempt, stop and report.
      if (e.systemic) { stop = truncate(e.message, 160); ctx.log('assets', `Asset Studio stopped: ${stop}`); break; }
      item.attempts++;
      item.issue = truncate(e.message, 120);
      ctx.note(`item ${item.n}: ${truncate(e.message, 100)}`);
    }
    await db.update('asset_packs', { id: `eq.${pack.id}` }, { items, images_made: (pack.images_made || 0) + made });
  }
  const done = items.filter((i) => i.done).length;
  const open = items.filter((i) => !i.done && i.attempts < MAX_TRIES).length;
  let status = pack.status;
  if (!open) status = done >= Math.min(12, items.length) ? 'packaging' : 'rejected';
  const patch = { items, images_made: (pack.images_made || 0) + made, status };
  if (status === 'rejected') {
    patch.feedback = `Only ${done}/${items.length} images passed QA.`;
    await db.insertOne('feedback', { kind: 'asset_pack_failed', text: `Asset pack "${pack.title}" (${items[0]?.kind}, style: ${pack.style}) failed: only ${done}/${items.length} images passed QA. Common issues: ${[...new Set(items.map((i) => i.issue).filter(Boolean))].slice(0, 4).join('; ')}. Choose subjects the model draws well.`, ref_table: 'asset_packs', ref_id: pack.id });
  }
  const [updated] = await db.update('asset_packs', { id: `eq.${pack.id}` }, patch);
  if (made) ctx.log('assets', `Asset Studio: ${made} image(s) for "${truncate(pack.title, 60)}" (${done}/${items.length} passed)`, { table: 'asset_packs', id: pack.id });
  return { pack: updated || { ...pack, ...patch }, msg: `made ${made} image(s), ${done}/${items.length} passed${stop ? ` · stopped: ${truncate(stop, 80)}` : ''}` };
}

// ---------- Package ----------
async function packagePack(ctx, pack) {
  const dir = await workdir();
  const files = join(dir, 'pack');
  await mkdir(files, { recursive: true });
  await mkdir(join(files, '128px'), { recursive: true });
  const good = pack.items.filter((i) => i.done && i.path);
  let k = 0;
  for (const it of good) {
    const name = `${String(it.n).padStart(2, '0')}-${slug(it.name)}`;
    await writeFile(join(files, `${name}.png`), await download(BUCKET, it.path));
    await writeFile(join(files, '128px', `${name}.png`), await download(BUCKET, it.path.replace(/\.png$/, '-128.png')));
    await writeFile(join(dir, `seq-${String(++k).padStart(2, '0')}.png`), await download(BUCKET, it.path));
  }
  const cols = Math.ceil(Math.sqrt(k));
  const rows = Math.ceil(k / cols);
  const preview = join(dir, 'preview.png');
  await sh('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', '1', '-i', join(dir, 'seq-%02d.png'),
    '-filter_complex', `color=c=0x1f2937:s=256x256:r=1[bg];[0:v]scale=256:256[fg];[bg][fg]overlay=shortest=1,tile=${cols}x${rows}:padding=10:margin=16:color=0x111827`,
    '-frames:v', '1', preview]);
  const license = `${pack.title} — license

You may use these images in commercial and non-commercial games, apps and videos, and modify them.
You may not resell, redistribute or share the image files themselves (on their own or in another asset pack).
Made with AI image generation (FLUX.1 schnell) and checked before release.
`;
  await writeFile(join(files, 'LICENSE.txt'), license);
  await writeFile(join(files, 'README.txt'), `${pack.title}\n\n${good.length} PNG images at 512x512 (plus 128x128 in /128px)${good[0]?.keyed ? ' with transparent backgrounds' : ''}.\n\nItems:\n${good.map((i) => `- ${i.name}`).join('\n')}\n`);
  await sh('cp', [preview, join(files, 'preview.png')]);
  const zip = join(dir, 'pack.zip');
  await sh('bash', ['-c', `cd "${files}" && zip -q -r "${zip}" .`]);
  const prefix = `${pack.id}`;
  await upload(BUCKET, `${prefix}/preview.png`, await readFile(preview), 'image/png');
  await upload(BUCKET, `${prefix}/${slug(pack.title)}.zip`, await readFile(zip), 'application/zip');
  await db.update('asset_packs', { id: `eq.${pack.id}` }, {
    status: 'ready', preview_path: `${prefix}/preview.png`, zip_path: `${prefix}/${slug(pack.title)}.zip`, ready_at: new Date().toISOString(),
    page_copy: packCopy(pack, good), tags: honestTags(pack.tags),
  });
  await db.insertOne('approvals', {
    kind: 'asset_pack', ref_table: 'asset_packs', ref_id: pack.id, created_by: 'asset_studio',
    title: `Publish on itch.io: ${truncate(pack.title, 100)} ($${pack.price_usd})`,
    detail: 'Open the Shop page: download the zip, copy the page text, create the itch.io page, then paste the itch.io link back so the crew can track sales.',
  });
  ctx.log('assets', `Pack ready to publish: "${truncate(pack.title, 70)}" (${good.length} images)`, { table: 'asset_packs', id: pack.id });
  return `packaged "${truncate(pack.title, 50)}" (${good.length} images) — ready for Bobby`;
}

// ---------- itch.io stats (optional ITCH_API_KEY) ----------
async function syncItch(ctx) {
  if (!hasEnv('ITCH_API_KEY')) return '';
  const res = await fetch('https://api.itch.io/profile/games', { headers: { Authorization: `Bearer ${env('ITCH_API_KEY')}` } });
  if (!res.ok) { ctx.note(`itch.io API ${res.status}`); return ''; }
  const games = (await res.json()).games || [];
  const packs = await db.select('asset_packs', { status: 'in.(ready,published,killed)', itch_url: 'not.is.null' });
  const exp = await ensureExperiment();
  let sales = 0;
  const norm = (u) => String(u || '').toLowerCase().replace(/^https?:\/\//, '').replace(/\/+$/, '');
  for (const p of packs) {
    const g = games.find((x) => norm(x.url) === norm(p.itch_url));
    if (!g) continue;
    const revenue = (g.earnings || []).filter((e) => e.currency === 'USD').reduce((n, e) => n + Number(e.amount || 0) / 100, 0);
    const purchases = g.purchases_count || 0;
    if (purchases > p.sales) {
      const perSale = purchases ? (revenue - Number(p.revenue)) / (purchases - p.sales) : 0;
      for (let n = p.sales + 1; n <= purchases; n++) {
        await db.insert('ledger', [{ line: 'experiment', experiment_id: exp, revenue: +perSale.toFixed(2), cost: 0, source: 'itchio', ref: `itch:${g.id}:${n}`, note: `itch.io sale: ${truncate(p.title, 80)}` }], { onConflict: 'ref', ignoreDuplicates: true });
      }
      sales += purchases - p.sales;
      ctx.log('sale', `SALE on itch.io: ${truncate(p.title, 70)} (${purchases} total)`, { table: 'asset_packs', id: p.id });
    }
    await db.update('asset_packs', { id: `eq.${p.id}` }, {
      itch_game_id: g.id, views: g.views_count || 0, downloads: g.downloads_count || 0, sales: purchases, revenue: +revenue.toFixed(2),
      ...(g.published && p.status === 'ready' ? { status: 'published', published_at: g.published_at || new Date().toISOString() } : {}),
    });
  }
  return sales ? `${sales} new itch.io sale(s)` : `itch.io stats synced (${packs.length} pack(s))`;
}

// One experiment for the whole lane; the clock starts when the first pack is published.
async function ensureExperiment() {
  const id = await kvGet('asset_experiment_id', null);
  if (id) return id;
  const rules = await RULES();
  const today = etDate();
  const row = await db.insertOne('experiments', {
    title: 'Asset Studio: AI game asset packs on itch.io', lane: 'digital',
    hypothesis: 'AI-made, QA-checked asset packs sell on itch.io at $2–8 with $0 spend.',
    pass_metric: `${rules.goal_sales} sales in ${rules.days} days from first publish`, kill_metric: `fewer than ${rules.goal_sales} sales by day ${rules.days}`,
    starts_on: today, ends_on: addDays(today, rules.days), status: 'running', budget_usd: 0,
  });
  await kvSet('asset_experiment_id', row.id);
  return row.id;
}

async function enforceKillRule(ctx, rules) {
  const first = await db.one('asset_packs', { published_at: 'not.is.null', order: 'published_at.asc' });
  if (!first) return '';
  const days = (Date.now() - Date.parse(first.published_at)) / 86400000;
  if (days < rules.days) return '';
  const sold = (await db.select('asset_packs', { select: 'sales' })).reduce((n, p) => n + p.sales, 0);
  if (sold >= rules.goal_sales) return '';
  if (await kvGet('asset_studio_killed', false)) return 'lane killed by rule';
  const why = `Asset Studio sold ${sold} of ${rules.goal_sales} packs in ${Math.round(days)} days since the first publish.`;
  await kvSet('asset_studio_killed', true);
  await db.update('agents', { id: 'eq.asset_studio' }, { enabled: false });
  const exp = await kvGet('asset_experiment_id', null);
  if (exp) await db.update('experiments', { id: `eq.${exp}` }, { status: 'killed', verdict: 'kill', judge_notes: `Kill rule: ${why}`, judged_at: new Date().toISOString() });
  await db.insertOne('feedback', { kind: 'experiment_killed', text: `Killed by rule — ${why}`, ref_table: 'experiments', ref_id: exp });
  await db.insertOne('approvals', { kind: 'judge', ref_table: 'experiments', ref_id: exp, created_by: 'asset_studio', title: 'Asset Studio paused by its kill rule', detail: `${why} Turn it back on from the Shop page if you want another round.` });
  ctx.log('launch', `KILLED: ${why}`);
  return `paused by kill rule: ${why}`;
}
export const _test = { keyOut, backgroundColor };

// The itch.io text is rebuilt from what actually made it into the zip (the plan's count and wording can drift),
// and never calls AI images "hand-painted" / "hand-drawn".
const HAND = /\bhand[\s\u2010-\u2015-]*(painted|drawn|made|crafted)\b/gi;
export function honestTags(tags = []) {
  return [...new Set((tags || []).map((t) => String(t).replace(HAND, (_, w) => (w.toLowerCase() === 'drawn' ? 'drawn' : 'painted')).trim()).filter(Boolean))].slice(0, 10);
}
export function packCopy(pack, good) {
  const n = good.length;
  const transparent = good[0]?.keyed ? ' with transparent backgrounds' : '';
  const kind = pack.kind || 'icons';
  return `${n} ${String(pack.theme || pack.title).replace(HAND, '').trim()} ${kind} in one consistent style for your game.

What's included
- ${n} PNG files${transparent}
- Each at 512 px and 128 px
- Items: ${good.map((i) => i.name).join(', ')}

License
Use in commercial and non-commercial games. Don't resell or redistribute the files as-is.

Made with AI image generation (FLUX.1 schnell), then checked and cleaned up.`;
}
