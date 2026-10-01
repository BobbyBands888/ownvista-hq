// One LLM entry point for every agent. LLM_PROVIDER=groq|anthropic switches providers.
// Enforces: per-model and per-agent daily token caps (stored in Supabase), requests/day,
// tokens-per-minute pacing, and 429 backoff. Stops gracefully with CapError.
import { env, requireEnv } from './env.js';
import { db, kvGet } from './db.js';
import { etDate, sleep } from './time.js';

export class CapError extends Error {
  constructor(msg) { super(msg); this.name = 'CapError'; }
}

const PROVIDER = () => env('LLM_PROVIDER', 'groq');

const MODELS = {
  groq: {
    smart: env('LLM_MODEL_SMART', 'openai/gpt-oss-120b'),
    fast: env('LLM_MODEL_FAST', 'openai/gpt-oss-20b'),
    vision: env('LLM_MODEL_VISION', 'qwen/qwen3.8-27b'),
  },
  anthropic: {
    smart: env('LLM_MODEL_SMART', 'claude-sonnet-5-5'),
    fast: env('LLM_MODEL_FAST', 'claude-haiku-4-5-20251001'),
    vision: env('LLM_MODEL_VISION', 'claude-sonnet-5-5'),
  },
};

// Groq free tier: 30 RPM / 8K TPM per model. Keep headroom.
const PACE = { groq: { tpm: 7000, rpm: 26 }, anthropic: { tpm: 200000, rpm: 200 } };

const DEFAULT_CAPS = {
  smart: { tokens: 150000, requests: 800 },
  fast: { tokens: 150000, requests: 800 },
  vision: { tokens: 150000, requests: 800 },
  agents: {},
};

const state = { caps: null, day: null, usage: new Map(), windows: new Map() };

async function loadUsage() {
  const day = etDate();
  if (state.caps && state.day === day) return;
  state.day = day;
  state.caps = { ...DEFAULT_CAPS, ...(await kvGet('llm_caps', {})) };
  state.usage.clear();
  const rows = await db.select('llm_usage', { day: `eq.${day}` });
  for (const r of rows) bump(r.model, r.agent, r.requests, r.tokens_in + r.tokens_out);
}

function bump(model, agent, requests, tokens) {
  for (const k of [`m:${model}`, `a:${agent}`]) {
    const u = state.usage.get(k) || { requests: 0, tokens: 0 };
    u.requests += requests;
    u.tokens += tokens;
    state.usage.set(k, u);
  }
}

// Long-lived processes (the Vercel tick) re-read caps and usage from the database at the start of each shift,
// so usage by the GitHub job and other ticks counts against the same daily caps.
export function resetUsageCache() {
  state.caps = null;
  state.day = null;
}

export async function usageToday() {
  await loadUsage();
  return Object.fromEntries(state.usage);
}

const estimateTokens = (messages) =>
  Math.ceil(JSON.stringify(messages).replace(/data:[^"]+/g, '').length / 3.5) +
  messages.reduce((n, m) => n + (Array.isArray(m.content) ? m.content.filter((c) => c.type === 'image').length * 2048 : 0), 0);

async function checkCaps(tier, model, agent, est) {
  await loadUsage();
  const capM = state.caps[tier] || DEFAULT_CAPS[tier];
  const um = state.usage.get(`m:${model}`) || { requests: 0, tokens: 0 };
  if (um.requests + 1 > capM.requests) throw new CapError(`Daily request cap reached for ${model} (${capM.requests})`);
  if (um.tokens + est > capM.tokens) throw new CapError(`Daily token cap reached for ${model} (${um.tokens}/${capM.tokens})`);
  const capA = state.caps.agents?.[agent];
  const ua = state.usage.get(`a:${agent}`) || { requests: 0, tokens: 0 };
  if (capA && ua.tokens + est > capA) throw new CapError(`Daily token share used up for ${agent} (${ua.tokens}/${capA})`);
}

// Sliding one-minute window per model so we never trip TPM/RPM limits.
async function pace(model, est) {
  const base = PACE[PROVIDER()] || PACE.groq;
  const tpm = Number(env('LLM_TPM', base.tpm));
  const rpm = Number(env('LLM_RPM', base.rpm));
  const w = state.windows.get(model) || [];
  state.windows.set(model, w);
  for (;;) {
    const now = Date.now();
    while (w.length && now - w[0].t > 60000) w.shift();
    const used = w.reduce((n, x) => n + x.tokens, 0);
    if ((used + est <= tpm || w.length === 0) && w.length < rpm) break;
    await sleep(Math.max(1000, 60000 - (now - w[0].t) + 250));
  }
  w.push({ t: Date.now(), tokens: est });
}

/**
 * chat({ ctx, tier: 'smart'|'fast'|'vision', system, messages, json, maxTokens, temperature })
 * messages: [{ role, content }] where content is a string or
 *   [{ type:'text', text }, { type:'image', url }]  (url may be https or data:image/...;base64,…)
 * Returns { text, json, usage }.
 */
export async function chat({ ctx, tier = 'smart', system, messages, json = false, maxTokens = 1500, temperature = 0.4 }) {
  const provider = PROVIDER();
  const model = MODELS[provider][tier];
  const agent = ctx?.agent ?? 'unknown';
  // Every agent gets its latest Researcher briefs (wrapped as untrusted data) on every call.
  if (ctx?.agent) {
    try { system = `${system}${await (await import('./briefs.js')).briefsFor(ctx.agent)}`; } catch { /* briefs are optional */ }
  }
  const est = estimateTokens([{ content: system }, ...messages]) + Math.min(maxTokens, 1200);
  await checkCaps(tier, model, agent, est);
  if (ctx?.outOfTime?.(45000)) throw new CapError('Out of time for this run');
  await pace(model, est);

  const call = provider === 'anthropic' ? callAnthropic : callGroq;
  let lastErr;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const out = await call({ model, system, messages, json, maxTokens, temperature });
      const tokensIn = out.usage.in ?? 0;
      const tokensOut = out.usage.out ?? 0;
      bump(model, agent, 1, tokensIn + tokensOut);
      if (ctx) { ctx.llmCalls++; ctx.tokens += tokensIn + tokensOut; }
      const win = state.windows.get(model);
      if (win?.length) win[win.length - 1].tokens = Math.max(est, tokensIn + tokensOut);
      await db.rpc('llm_log', { p_model: model, p_agent: agent, p_in: tokensIn, p_out: tokensOut }).catch((e) => console.error(e.message));
      let parsed = null;
      if (json) parsed = parseJson(out.text);
      return { text: out.text, json: parsed, usage: out.usage };
    } catch (e) {
      lastErr = e;
      if (e instanceof CapError) throw e;
      if (e.status === 429) {
        if (/per day|daily|TPD|RPD/i.test(e.body || '')) throw new CapError(`Provider daily limit: ${String(e.body).slice(0, 200)}`);
        const wait = Math.min(60, Number(e.retryAfter) || 5 * 2 ** attempt);
        if (ctx?.outOfTime?.(wait * 1000 + 45000)) throw new CapError('Rate limited and out of time');
        await sleep(wait * 1000);
        continue;
      }
      if (e.status >= 500 && attempt < 2) { await sleep(3000 * (attempt + 1)); continue; }
      if (e.jsonFailed && attempt < 1) continue;
      throw e;
    }
  }
  throw lastErr;
}

export function parseJson(text) {
  const t = String(text || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/```$/, '');
  try { return JSON.parse(t); } catch {}
  const start = t.search(/[[{]/);
  if (start >= 0) {
    const open = t[start], close = open === '{' ? '}' : ']';
    const end = t.lastIndexOf(close);
    if (end > start) { try { return JSON.parse(t.slice(start, end + 1)); } catch {} }
  }
  const err = new Error(`Model did not return valid JSON: ${t.slice(0, 200)}`);
  err.jsonFailed = true;
  throw err;
}

function httpError(res, body) {
  const e = new Error(`LLM HTTP ${res.status}: ${body.slice(0, 300)}`);
  e.status = res.status;
  e.body = body;
  e.retryAfter = res.headers.get('retry-after');
  return e;
}

async function callGroq({ model, system, messages, json, maxTokens, temperature }) {
  const msgs = [{ role: 'system', content: system }, ...messages.map(toOpenAI)];
  const body = { model, messages: msgs, temperature, max_completion_tokens: maxTokens };
  if (json) body.response_format = { type: 'json_object' };
  if (model.startsWith('openai/gpt-oss')) {
    body.reasoning_effort = 'low';
    body.include_reasoning = false;
  }
  const res = await fetch('https://api.groq.com/openai/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${requireEnv('GROQ_API_KEY')}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw httpError(res, text);
  const data = JSON.parse(text);
  return {
    text: (data.choices?.[0]?.message?.content ?? '').replace(/<think>[\s\S]*?<\/think>/gi, '').trim(),
    usage: { in: data.usage?.prompt_tokens, out: data.usage?.completion_tokens },
  };
}

function toOpenAI(m) {
  if (typeof m.content === 'string') return m;
  return {
    role: m.role,
    content: m.content.map((c) => (c.type === 'image' ? { type: 'image_url', image_url: { url: c.url } } : { type: 'text', text: c.text })),
  };
}

async function callAnthropic({ model, system, messages, json, maxTokens, temperature }) {
  const msgs = messages.map((m) => ({
    role: m.role,
    content: typeof m.content === 'string' ? m.content : m.content.map((c) => {
      if (c.type !== 'image') return { type: 'text', text: c.text };
      const d = /^data:([^;]+);base64,(.*)$/.exec(c.url);
      return d
        ? { type: 'image', source: { type: 'base64', media_type: d[1], data: d[2] } }
        : { type: 'image', source: { type: 'url', url: c.url } };
    }),
  }));
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': requireEnv('ANTHROPIC_API_KEY'),
      'anthropic-version': '2023-06-01',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model, max_tokens: maxTokens, temperature,
      system: json ? `${system}\n\nRespond with a single JSON object and nothing else.` : system,
      messages: msgs,
    }),
  });
  const text = await res.text();
  if (!res.ok) throw httpError(res, text);
  const data = JSON.parse(text);
  return {
    text: (data.content || []).filter((b) => b.type === 'text').map((b) => b.text).join(''),
    usage: { in: data.usage?.input_tokens, out: data.usage?.output_tokens },
  };
}
