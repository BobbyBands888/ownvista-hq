// MiniMax H3 video API (verified 2026-09-30):
//   POST /v2/video_generation        { model:'MiniMax-H3', content:[text, image first_frame], duration, resolution:'768P', ratio:'adaptive' }
//   POST /v2/video_regeneration      { model:'MiniMax-H3', content:[same inputs…, video_url role base_video], resolution:'2K' }
//   GET  /v2/query/video_generation/{task_id} → { task: { status, content:{url}, usage, error } }
// Every create call requires a spend reservation id — no reservation, no call.
import { requireEnv } from './env.js';

const BASE = 'https://api.minimax.io';

async function call(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${requireEnv('MINIMAX_API_KEY')}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch {}
  if (!res.ok || data?.type === 'error' || (data?.base_resp && data.base_resp.status_code !== 0)) {
    const e = new Error(`MiniMax ${method} ${path} → ${res.status}: ${text.slice(0, 300)}`);
    e.status = res.status;
    throw e;
  }
  return data;
}

function requireReservation(spendId) {
  if (!spendId || typeof spendId !== 'string') throw new Error('MiniMax call without a spend reservation is not allowed');
}

export function clipContent({ prompt, imageUrl }) {
  return [
    { type: 'text', text: prompt },
    { type: 'image_url', image_url: { url: imageUrl }, role: 'first_frame' },
  ];
}

export async function createClip({ spendId, prompt, imageUrl, duration = 5 }) {
  requireReservation(spendId);
  const data = await call('POST', '/v2/video_generation', {
    model: 'MiniMax-H3',
    content: clipContent({ prompt, imageUrl }),
    duration,
    resolution: '768P',
    ratio: 'adaptive',
  });
  return data.task_id;
}

export async function createUpgrade({ spendId, prompt, imageUrl, baseVideoUrl }) {
  requireReservation(spendId);
  const data = await call('POST', '/v2/video_regeneration', {
    model: 'MiniMax-H3',
    content: [
      ...clipContent({ prompt, imageUrl }),
      { type: 'video_url', video_url: { url: baseVideoUrl }, role: 'base_video' },
    ],
    resolution: '2K',
  });
  return data.task_id;
}

// → { status: 'queued'|'running'|'succeeded'|'failed'|'cancelled', url, usage, error }
export async function queryTask(taskId) {
  const { task } = await call('GET', `/v2/query/video_generation/${taskId}`);
  return { status: task.status, url: task.content?.url ?? null, usage: task.usage ?? {}, error: task.error ?? null };
}
