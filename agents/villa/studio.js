// Villa Studio — hourly, only when an order is in production.
// photos_received → pick 8–12 hero photos (vision) → generate 768P clips (MiniMax-H3)
// → vision QA (max 2 retries per clip) → paid/test: upgrade passing clips to 2K via regeneration
// → stitch (ffmpeg, title card, licensed music, "AI-generated from photos" end card)
// → review (first 3 films, or when review mode is on) → deliver by email (signed link).
// Every paid call is reserved first in the database; caps are enforced there.
import { writeFile, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { db, kvGet } from '../lib/db.js';
import { hasEnv } from '../lib/env.js';
import { chat } from '../lib/llm.js';
import { systemPrompt } from '../lib/guard.js';
import * as storage from '../lib/storage.js';
import * as minimax from '../lib/minimax.js';
import * as spend from '../lib/spend.js';
import { plan, clipCost, upgradeCost, PRICES, CLIP_SECONDS, priceLine } from '../lib/pricing.js';
import { hasFfmpeg, workdir, framesAsDataUris, stitchFilm } from '../lib/ffmpeg.js';
import { send } from '../lib/sendgate.js';
import { paymentLinkFor } from '../lib/stripe.js';
import { signoff } from '../lib/context.js';
import { sleep } from '../lib/time.js';
import { truncate } from '../lib/text.js';

const ACTIVE = 'in.(photos_received,generating,qa,upgrading,stitching,approved)';
const IMAGE = /\.(jpe?g|png|webp)$/i;
const ROOM_ORDER = ['exterior', 'entrance', 'living', 'kitchen', 'dining', 'bedroom', 'bathroom', 'pool', 'view', 'other'];
const WEEK = 7 * 24 * 3600;

export async function run(ctx) {
  if (!hasEnv('MINIMAX_API_KEY')) return 'MiniMax is not configured yet — skipped';
  const orders = await db.select('vc_orders', { status: ACTIVE, order: 'created_at.asc', limit: 3 });
  const out = [];
  for (const o of orders) {
    if (ctx.outOfTime(90000)) break;
    try {
      out.push(`${o.id.slice(0, 8)} ${await advance(ctx, o)}`);
    } catch (e) {
      if (e instanceof spend.SpendRefused) {
        await setOrder(o.id, { status: 'failed', notes: e.message });
        out.push(`${o.id.slice(0, 8)} stopped: ${e.reason}`);
        continue;
      }
      throw e;
    }
  }
  if (!ctx.outOfTime(60000)) await cleanup();
  return out.length ? out.join(' · ') : 'no orders in production';
}

// Advance one order as far as time allows.
async function advance(ctx, order) {
  for (let step = 0; step < 8 && !ctx.outOfTime(90000); step++) {
    const o = await db.one('vc_orders', { id: `eq.${order.id}` });
    const before = o.status;
    if (o.status === 'photos_received') await selectPhotos(ctx, o);
    else if (o.status === 'generating') await generate(ctx, o);
    else if (o.status === 'qa') await qa(ctx, o);
    else if (o.status === 'upgrading') await upgrade(ctx, o);
    else if (o.status === 'stitching') await stitch(ctx, o);
    else if (o.status === 'approved') await deliver(ctx, o);
    else return o.status;
    const after = (await db.one('vc_orders', { id: `eq.${order.id}`, select: 'status' })).status;
    if (after === before) return `${after} (waiting)`;
  }
  return (await db.one('vc_orders', { id: `eq.${order.id}`, select: 'status' })).status;
}

const setOrder = (id, patch) => db.update('vc_orders', { id: `eq.${id}` }, { ...patch, updated_at: new Date().toISOString() });
const setClip = (id, patch) => db.update('vc_clips', { id: `eq.${id}` }, { ...patch, updated_at: new Date().toISOString() });
const isPaidPath = (o) => o.kind === 'paid' || o.kind === 'test';

async function flag(order, title, detail) {
  await db.insertOne('approvals', { kind: 'vc_order', ref_table: 'vc_orders', ref_id: order.id, title, detail, created_by: 'villa_studio' });
}

// ---------------------------------------------------------------- 1. photo selection

async function selectPhotos(ctx, o) {
  const prefix = o.photos_prefix || o.id;
  const files = (await storage.list('vc-photos', prefix)).filter((f) => IMAGE.test(f.name)).slice(0, 24);
  const p = plan(o.kind === 'sample' ? 'sample' : 'paid');
  if (files.length < 6) {
    await setOrder(o.id, { status: 'failed', notes: `Only ${files.length} photos uploaded` });
    await flag(o, 'Order has too few photos', `${files.length} photo(s) in ${prefix}. Ask the customer for 8–12.`);
    return;
  }
  const photos = [];
  for (const f of files) {
    const path = `${prefix}/${f.name}`;
    photos.push({ path, url: await storage.signedUrl('vc-photos', path, WEEK) });
  }

  // Rate photos three at a time with the vision model.
  const rated = [];
  for (let i = 0; i < photos.length; i += 3) {
    const group = photos.slice(i, i + 3);
    const { json } = await chat({
      ctx, tier: 'vision', json: true, maxTokens: 900, temperature: 0.1,
      system: systemPrompt('the Villa Cinema photo editor', `Rate each property photo for a cinematic walkthrough film.
score 1–10: sharp, well-lit, well-composed, shows the property at its best. people/text: true if any person, face, logo or watermark is visible.
room: one of ${ROOM_ORDER.join(', ')}. move: one slow camera move that suits the shot (e.g. "slow push-in", "gentle pan left", "slow crane up").
description: 8–15 words describing only what is visible.
JSON only: {"photos":[{"i":0,"score":7,"room":"living","people":false,"text":false,"landscape":true,"move":"","description":""}]}`),
      messages: [{ role: 'user', content: [{ type: 'text', text: `Photos 0–${group.length - 1}, in order:` }, ...group.map((g) => ({ type: 'image', url: g.url }))] }],
    });
    for (const r of json.photos || []) {
      const g = group[r.i];
      if (g) rated.push({ ...g, ...r, score: Number(r.score) || 0, room: ROOM_ORDER.includes(r.room) ? r.room : 'other' });
    }
  }
  const usable = rated.filter((r) => !r.people && !r.text && r.score >= 4).sort((a, b) => b.score - a.score);
  const perRoom = {};
  const picked = [];
  for (const r of usable) {
    const limit = ['bedroom', 'bathroom'].includes(r.room) ? 3 : 2;
    if ((perRoom[r.room] || 0) >= limit) continue;
    perRoom[r.room] = (perRoom[r.room] || 0) + 1;
    picked.push(r);
    if (picked.length >= p.clips) break;
  }
  for (const r of usable) { if (picked.length >= Math.min(p.clips, 8)) break; if (!picked.includes(r)) picked.push(r); }
  if (picked.length < 6) {
    await setOrder(o.id, { status: 'failed', notes: `Only ${picked.length} usable photos` });
    await flag(o, 'Not enough usable photos', `Vision review kept ${picked.length} of ${files.length}. Ask for more wide, well-lit shots without people.`);
    return;
  }
  picked.sort((a, b) => ROOM_ORDER.indexOf(a.room) - ROOM_ORDER.indexOf(b.room));

  // Reserve the whole 2K upgrade budget up front so retries can never eat it.
  if (isPaidPath(o) && !o.upgrade_spend_id) {
    const id = await spend.reserve({ orderId: o.id, purpose: 'upgrade_reserve', amount: +(picked.length * upgradeCost()).toFixed(2), note: `2K upgrade for ${picked.length} clips` });
    await setOrder(o.id, { upgrade_spend_id: id });
  }
  await db.insert('vc_clips', picked.map((r, i) => ({
    order_id: o.id, photo_path: r.path, photo_url: r.url, rank: i, status: 'pending',
    prompt: clipPrompt(r),
  })));
  await setOrder(o.id, { status: 'generating' });
  ctx.log('vc_studio', `Order ${o.id.slice(0, 8)}: picked ${picked.length} photos`, { table: 'vc_orders', id: o.id });
}

const RETRY_NOTE = 'Use minimal camera movement; walls must stay perfectly straight; do not change any object.';

function clipPrompt(r) {
  return [
    `Cinematic luxury real-estate walkthrough shot: ${r.description || r.room}.`,
    `${r.move || 'Slow, smooth push-in'}.`,
    'Slow, stable, gimbal-smooth camera. Architecture, walls and furniture stay perfectly rigid and straight.',
    'Keep every object exactly as in the photo. No people, no text, no new objects. Natural light.',
  ].filter(Boolean).join(' ');
}

// ---------------------------------------------------------------- 2. generation

async function generate(ctx, o) {
  const clips = await db.select('vc_clips', { order_id: `eq.${o.id}`, order: 'rank.asc' });
  for (const c of clips.filter((c) => c.status === 'pending')) {
    const spendId = await spend.reserve({ orderId: o.id, clipId: c.id, purpose: c.attempt > 1 ? 'regenerate' : 'generate', amount: clipCost(), note: `clip ${c.rank} attempt ${c.attempt}` });
    try {
      const taskId = await minimax.createClip({ spendId, prompt: c.prompt, imageUrl: c.photo_url, duration: CLIP_SECONDS });
      await setClip(c.id, { status: 'generating', minimax_task_id: taskId, spend_id: spendId });
    } catch (e) {
      await spend.release(spendId);
      throw e;
    }
  }
  await pollTasks(ctx, o, 'generating', async (c, t) => {
    const path = `${o.id}/clips/${c.rank}-a${c.attempt}-768.mp4`;
    await storage.upload('vc-films', path, await fetchBytes(t.url), 'video/mp4');
    await spend.settle(c.spend_id, (t.usage.output_seconds || CLIP_SECONDS) * PRICES.h3_768p_per_sec, c.minimax_task_id);
    await setClip(c.id, { status: 'generated', video_path_768: path });
  }, async (c, t) => {
    await spend.release(c.spend_id);
    if (c.attempt < 3) await setClip(c.id, { status: 'pending', attempt: c.attempt + 1, qa: { generation_error: t.error } });
    else await setClip(c.id, { status: 'dropped', qa: { generation_error: t.error } });
  });
  const left = await db.count('vc_clips', { order_id: `eq.${o.id}`, status: 'in.(pending,generating)' });
  if (!left) await setOrder(o.id, { status: 'qa' });
}

async function pollTasks(ctx, o, status, onDone, onFail, taskField = 'minimax_task_id') {
  for (let round = 0; round < 40; round++) {
    const waiting = await db.select('vc_clips', { order_id: `eq.${o.id}`, status: `eq.${status}` });
    if (!waiting.length) return;
    for (const c of waiting) {
      const t = await minimax.queryTask(c[taskField]);
      if (t.status === 'succeeded' && t.url) await onDone(c, t);
      else if (t.status === 'failed' || t.status === 'cancelled') await onFail(c, t);
    }
    if (ctx.outOfTime(150000)) return;
    await sleep(20000);
  }
}

async function fetchBytes(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`download ${res.status}`);
  return Buffer.from(await res.arrayBuffer());
}

// ---------------------------------------------------------------- 3. QA

async function qa(ctx, o) {
  if (!(await hasFfmpeg())) throw new Error('ffmpeg is not installed on this runner');
  const clips = await db.select('vc_clips', { order_id: `eq.${o.id}`, status: 'eq.generated', order: 'rank.asc' });
  const dir = await workdir();
  let retried = 0;
  for (const c of clips) {
    if (ctx.outOfTime(120000)) return;
    const file = join(dir, `${c.id}.mp4`);
    await writeFile(file, await storage.download('vc-films', c.video_path_768));
    const frames = await framesAsDataUris(file, 2);
    const { json } = await chat({
      ctx, tier: 'vision', json: true, maxTokens: 600, temperature: 0,
      system: systemPrompt('the Villa Cinema QA inspector', `Image 1 is the original property photo. Images 2–3 are frames from the generated video clip.
Fail the clip for ANY of: warped or bending walls, door frames or straight lines; melted, stretched or deformed furniture; people or faces that appear; objects added or removed vs the photo; heavy blur or visual artifacts; text or watermarks.
JSON only: {"pass":true,"issues":["warped_walls"|"warped_furniture"|"people"|"added_or_removed_objects"|"artifacts"|"text"],"notes":"short"}`),
      messages: [{ role: 'user', content: [{ type: 'text', text: 'Inspect this clip.' }, { type: 'image', url: c.photo_url }, ...frames.map((f) => ({ type: 'image', url: f }))] }],
    });
    const pass = json.pass === true && !(json.issues || []).length;
    if (pass) {
      await setClip(c.id, { status: 'qa_passed', qa: json });
    } else if (c.attempt < 3) {
      await setClip(c.id, { status: 'pending', attempt: c.attempt + 1, qa: json, prompt: `${c.prompt.replace(RETRY_NOTE, '').trim()} ${RETRY_NOTE}` });
      retried++;
    } else {
      await setClip(c.id, { status: 'dropped', qa: json });
    }
  }
  if (retried) { await setOrder(o.id, { status: 'generating' }); return; }
  const passed = await db.count('vc_clips', { order_id: `eq.${o.id}`, status: 'eq.qa_passed' });
  const min = o.kind === 'sample' ? 6 : 7;
  if (passed < min) {
    await setOrder(o.id, { status: 'failed', qa_passed: false, notes: `Only ${passed} clips passed QA` });
    await flag(o, 'Film failed QA', `Only ${passed} clip(s) passed QA after retries. Review the clips in the Villa view.`);
    return;
  }
  if (isPaidPath(o)) {
    await setOrder(o.id, { status: 'upgrading', qa_passed: true });
  } else {
    await db.update('vc_clips', { order_id: `eq.${o.id}`, status: 'eq.qa_passed' }, { status: 'final' });
    await setOrder(o.id, { status: 'stitching', qa_passed: true });
  }
}

// ---------------------------------------------------------------- 4. 2K upgrade (paid + test)

async function upgrade(ctx, o) {
  const ready = await db.select('vc_clips', { order_id: `eq.${o.id}`, status: 'eq.qa_passed', order: 'rank.asc' });
  for (const c of ready) {
    let spendId;
    try {
      spendId = await spend.split({ reservationId: o.upgrade_spend_id, amount: upgradeCost(), purpose: 'upgrade', clipId: c.id, note: `2K clip ${c.rank}` });
    } catch {
      await setClip(c.id, { status: 'final' }); // budget gone → keep the 768P clip
      continue;
    }
    try {
      const baseVideoUrl = await storage.signedUrl('vc-films', c.video_path_768, 24 * 3600);
      const taskId = await minimax.createUpgrade({ spendId, prompt: c.prompt, imageUrl: c.photo_url, baseVideoUrl });
      await setClip(c.id, { status: 'upgrading', regen_task_id: taskId, spend_id: spendId });
    } catch (e) {
      await spend.release(spendId);
      await setClip(c.id, { status: 'final', qa: { ...(c.qa || {}), upgrade_error: truncate(e.message, 300) } });
    }
  }
  await pollTasks(ctx, o, 'upgrading', async (c, t) => {
    const path = `${o.id}/clips/${c.rank}-2k.mp4`;
    await storage.upload('vc-films', path, await fetchBytes(t.url), 'video/mp4');
    const secs = t.usage.output_seconds || CLIP_SECONDS;
    await spend.settle(c.spend_id, secs * (PRICES.regen_output_per_sec + PRICES.regen_input_video_per_sec), c.regen_task_id);
    await setClip(c.id, { status: 'final', video_path_2k: path });
  }, async (c) => {
    await spend.release(c.spend_id);
    await setClip(c.id, { status: 'final' });
  }, 'regen_task_id');
  const left = await db.count('vc_clips', { order_id: `eq.${o.id}`, status: 'in.(qa_passed,upgrading)' });
  if (!left) {
    if (o.upgrade_spend_id) await spend.release(o.upgrade_spend_id); // unused remainder
    await setOrder(o.id, { status: 'stitching' });
  }
}

// ---------------------------------------------------------------- 5. stitching

async function stitch(ctx, o) {
  if (!(await hasFfmpeg())) throw new Error('ffmpeg is not installed on this runner');
  const music = (await storage.list('vc-music', '')).filter((f) => /\.(mp3|wav|m4a|aac)$/i.test(f.name));
  if (!music.length) {
    if (!(await db.one('approvals', { kind: 'eq.vc_music', status: 'eq.pending' }))) {
      await db.insertOne('approvals', { kind: 'vc_music', title: 'Upload licensed music to finish films', detail: 'Add royalty-free/CC0 tracks (with license notes) to the vc-music bucket from the Villa view. Films wait until then.', created_by: 'villa_studio' });
    }
    return;
  }
  const dir = await workdir();
  const track = music[Math.floor(Math.random() * music.length)];
  const musicFile = join(dir, track.name);
  await writeFile(musicFile, await storage.download('vc-music', track.name));

  const clips = await db.select('vc_clips', { order_id: `eq.${o.id}`, status: 'eq.final', order: 'rank.asc' });
  const files = [];
  for (const c of clips) {
    const f = join(dir, `${c.rank}.mp4`);
    await writeFile(f, await storage.download('vc-films', c.video_path_2k || c.video_path_768));
    files.push(f);
  }
  const hd = isPaidPath(o) && clips.some((c) => c.video_path_2k);
  const film = await stitchFilm({
    clips: files,
    title: o.property_name || 'A Villa Cinema film',
    subtitle: 'Villa Cinema',
    endLines: ['villacinema.com', 'AI-generated from photos'],
    musicFile,
    w: hd ? 2560 : 1280, h: hd ? 1440 : 720,
  });
  const path = `${o.id}/film.mp4`;
  await storage.upload('vc-films', path, await readFile(film.path), 'video/mp4');

  const mode = await kvGet('vc_review_mode', 'auto');
  const approvedFilms = Number(await kvGet('vc_approved_films', 0));
  const needsReview = o.kind === 'test' || mode === 'always' || approvedFilms < 3;
  await setOrder(o.id, { status: needsReview ? 'review' : 'approved', film_path: path, film_bytes: film.bytes });
  if (needsReview) {
    await db.insertOne('approvals', {
      kind: 'film', ref_table: 'vc_orders', ref_id: o.id, created_by: 'villa_studio',
      title: `Approve film before delivery: ${o.property_name || o.id.slice(0, 8)} (${o.kind})`,
      detail: `${clips.length} clips, ${film.duration.toFixed(0)}s, ${(film.bytes / 1048576).toFixed(1)} MB, music: ${track.name}. Preview it in the Villa view.`,
    });
  }
  ctx.log('vc_studio', `Film stitched for ${o.id.slice(0, 8)} (${needsReview ? 'waiting for Bobby' : 'auto-approved'})`, { table: 'vc_orders', id: o.id });
}

// ---------------------------------------------------------------- 6. delivery

async function deliver(ctx, o) {
  const prospect = o.prospect_id ? await db.one('vc_prospects', { id: `eq.${o.prospect_id}` }) : null;
  const to = o.customer_email || prospect?.contact_email;
  if (!to) { await flag(o, 'Approved film has no recipient', 'Add a customer email to the order.'); return; }
  const link = await storage.signedUrl('vc-films', o.film_path, WEEK);
  const sample = o.kind === 'sample';
  const lines = [
    sample
      ? `Your free sample film for ${o.property_name || 'your property'} is ready: ${link}`
      : `Your Villa Cinema film for ${o.property_name || 'your property'} is ready: ${link}`,
    'The link works for 7 days — please download the file. The film carries a small "AI-generated from photos" note.',
    sample && prospect ? `If you'd like the full-length 2K film (${priceLine()}), you can order here: ${paymentLinkFor(prospect)}` : null,
    'If you have a moment, a sentence or two on how it turned out would mean a lot — just reply to this email.',
    signoff('villa-cinema'),
  ].filter(Boolean);
  const r = await send({ kind: 'delivery', to, orderId: o.id, prospect, subject: sample ? 'Your sample film is ready' : 'Your film is ready', body: lines.join('\n\n') });
  if (!r.ok) {
    await flag(o, 'Delivery email not sent', r.reason);
    await setOrder(o.id, { status: 'review', notes: `Delivery refused: ${r.reason}` });
    return;
  }
  await setOrder(o.id, { status: 'delivered', delivered_at: new Date().toISOString() });
  if (prospect && !sample) await db.update('vc_prospects', { id: `eq.${prospect.id}` }, { stage: 'delivered' });
  if (!o.photos_prefix) {
    const photos = await storage.list('vc-photos', o.id);
    await storage.remove('vc-photos', photos.map((p) => `${o.id}/${p.name}`));
  }
  ctx.log('vc_delivered', `Delivered ${o.kind} film to ${to}`, { table: 'vc_orders', id: o.id });
}

// Films are kept 30 days after delivery, then removed from storage.
async function cleanup() {
  const old = await db.select('vc_orders', {
    status: 'eq.delivered', delivered_at: `lt.${new Date(Date.now() - 30 * 86400000).toISOString()}`, film_path: 'not.is.null', limit: 5,
  });
  for (const o of old) {
    const files = await storage.list('vc-films', o.id);
    const clips = await storage.list('vc-films', `${o.id}/clips`);
    await storage.remove('vc-films', [...files.map((f) => `${o.id}/${f.name}`), ...clips.map((f) => `${o.id}/clips/${f.name}`)]);
    await setOrder(o.id, { film_path: null });
  }
}

// ---------------------------------------------------------------- manual: test order

export async function createTestOrder(ctx) {
  const samples = (await storage.list('vc-photos', '_samples')).filter((f) => IMAGE.test(f.name));
  if (samples.length < 8) throw new Error(`Upload 8–12 sample photos in the Villa view first (found ${samples.length} in vc-photos/_samples)`);
  const to = await kvGet('bobby_email', '');
  const order = await db.insertOne('vc_orders', {
    kind: 'test', status: 'photos_received', customer_email: to, property_name: 'Test Villa',
    photos_prefix: '_samples', photos_submitted_at: new Date().toISOString(),
  });
  ctx.log('vc_test', `Created test order ${order.id.slice(0, 8)} from ${samples.length} sample photos (est. spend ${plan('paid').total} USD, per-order cap 20 USD)`, { table: 'vc_orders', id: order.id });
  return `test order ${order.id} created — Villa Studio will produce it on its next runs`;
}

