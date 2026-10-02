// Cloudflare Workers AI image generation (FLUX.1 schnell) on the FREE plan only.
// Free plan = a daily allowance with no card on file: when it runs out Cloudflare refuses the call
// instead of billing. On top of that we keep our own daily image cap (kv asset_rules.images_per_day)
// and stop for the day at the first "allowance used up" answer. Every image call goes through here.
import { requireEnv, hasEnv } from './env.js';
import { kvGet, kvSet } from './db.js';

export class ImageCapReached extends Error {
  constructor(msg) { super(msg); this.name = 'ImageCapReached'; }
}

export const cfReady = () => hasEnv('CF_ACCOUNT_ID', 'CF_API_TOKEN');
const MODEL = '@cf/black-forest-labs/flux-1-schnell';

// Cloudflare's free daily allowance resets at 00:00 UTC (8pm New York), so the counter keeps UTC days.
// (It used New York days before Oct 1: a late-night run used up the next UTC day and blocked the whole next ET day.)
const cfDay = (d = new Date()) => d.toISOString().slice(0, 10);

export async function imagesLeftToday(cap) {
  const day = cfDay();
  const st = await kvGet('cf_images', {});
  if (st.day !== day) return cap;
  if (st.exhausted) return 0;
  return Math.max(0, cap - (st.count || 0));
}

async function bump(extra = {}) {
  const day = cfDay();
  const st = await kvGet('cf_images', {});
  const cur = st.day === day ? st : { day, count: 0 };
  await kvSet('cf_images', { ...cur, count: (cur.count || 0) + (extra.exhausted ? 0 : 1), ...extra });
}

// Returns a JPEG Buffer (1024x1024).
// (FLUX.1 schnell on Workers AI accepts only prompt + steps; no seed.)
export async function generateImage(prompt, { cap, steps = 4 } = {}) {
  if (!cfReady()) throw new ImageCapReached('Cloudflare not connected yet (CF_ACCOUNT_ID / CF_API_TOKEN)');
  if ((await imagesLeftToday(cap)) <= 0) throw new ImageCapReached('daily free image allowance used');
  const res = await fetch(`https://api.cloudflare.com/client/v4/accounts/${requireEnv('CF_ACCOUNT_ID')}/ai/run/${MODEL}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${requireEnv('CF_API_TOKEN')}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prompt.slice(0, 2000), steps: Math.min(8, steps) }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.success) {
    const msg = (data.errors || []).map((e) => `${e.code}: ${e.message}`).join('; ') || `HTTP ${res.status}`;
    // Only the DAILY allowance stops images for the day; a per-minute rate limit just ends this run.
    if (/daily|allocation|neurons|quota|3036/i.test(msg)) {
      await bump({ exhausted: true, last_error: msg.slice(0, 200) });
      throw new ImageCapReached(`Cloudflare free allowance: ${msg}`);
    }
    if (res.status === 429 || /rate.?limit|too many|exceeded/i.test(msg)) {
      throw new ImageCapReached(`Cloudflare rate limit (try next run): ${msg}`);
    }
    const err = new Error(`Cloudflare image ${msg}`);
    // A content-filter refusal (8007 NSFW, often a false positive) is about this prompt only; skip the item, not the run.
    err.systemic = !/nsfw|8007/i.test(msg) && (res.status === 400 || res.status === 401 || res.status === 403 || /bad input|authentication|permission/i.test(msg));
    throw err;
  }
  await bump();
  return Buffer.from(data.result.image, 'base64');
}
