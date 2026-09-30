// Cloudflare Workers AI image generation (FLUX.1 schnell) on the FREE plan only.
// Free plan = a daily allowance with no card on file: when it runs out Cloudflare refuses the call
// instead of billing. On top of that we keep our own daily image cap (kv asset_rules.images_per_day)
// and stop for the day at the first "allowance used up" answer. Every image call goes through here.
import { requireEnv, hasEnv } from './env.js';
import { kvGet, kvSet } from './db.js';
import { etDate } from './time.js';

export class ImageCapReached extends Error {
  constructor(msg) { super(msg); this.name = 'ImageCapReached'; }
}

export const cfReady = () => hasEnv('CF_ACCOUNT_ID', 'CF_API_TOKEN');
const MODEL = '@cf/black-forest-labs/flux-1-schnell';

export async function imagesLeftToday(cap) {
  const day = etDate();
  const st = await kvGet('cf_images', {});
  if (st.day !== day) return cap;
  if (st.exhausted) return 0;
  return Math.max(0, cap - (st.count || 0));
}

async function bump(extra = {}) {
  const day = etDate();
  const st = await kvGet('cf_images', {});
  const cur = st.day === day ? st : { day, count: 0 };
  await kvSet('cf_images', { ...cur, count: (cur.count || 0) + (extra.exhausted ? 0 : 1), ...extra });
}

// Returns a JPEG Buffer (1024x1024).
export async function generateImage(prompt, { cap, seed, steps = 4 } = {}) {
  if (!cfReady()) throw new ImageCapReached('Cloudflare not connected yet (CF_ACCOUNT_ID / CF_API_TOKEN)');
  if ((await imagesLeftToday(cap)) <= 0) throw new ImageCapReached('daily free image allowance used');
  const res = await fetch(`https://api.cloudflare.com/client/v4/accounts/${requireEnv('CF_ACCOUNT_ID')}/ai/run/${MODEL}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${requireEnv('CF_API_TOKEN')}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prompt.slice(0, 2000), steps: Math.min(8, steps), ...(seed != null ? { seed } : {}) }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.success) {
    const msg = (data.errors || []).map((e) => `${e.code}: ${e.message}`).join('; ') || `HTTP ${res.status}`;
    if (res.status === 429 || /allocation|neurons|limit|quota|exceeded/i.test(msg)) {
      await bump({ exhausted: true });
      throw new ImageCapReached(`Cloudflare free allowance: ${msg}`);
    }
    throw new Error(`Cloudflare image ${msg}`);
  }
  await bump();
  return Buffer.from(data.result.image, 'base64');
}
