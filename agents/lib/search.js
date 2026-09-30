// Web search via Tavily (free: 1,000 credits/month, no card). OFF until Bobby approves:
// requires kv search_enabled = true AND the TAVILY_API_KEY secret. Daily caps in kv.
import { env } from './env.js';
import { kvGet, kvSet } from './db.js';
import { etDate } from './time.js';

export async function searchAvailable() {
  return Boolean(env('TAVILY_API_KEY')) && (await kvGet('search_enabled', false)) === true;
}

export async function webSearch(query, { purpose = 'research', maxResults = 8 } = {}) {
  if (!(await searchAvailable())) return { disabled: true, results: [] };
  const caps = await kvGet('search_daily_cap', { research: 15, discovery: 10 });
  const day = etDate();
  const usage = await kvGet('search_usage', {});
  const today = usage.day === day ? usage : { day, research: 0, discovery: 0 };
  if ((today[purpose] || 0) >= (caps[purpose] ?? 0)) return { capped: true, results: [] };
  today[purpose] = (today[purpose] || 0) + 1;
  await kvSet('search_usage', today);

  const res = await fetch('https://api.tavily.com/search', {
    method: 'POST',
    headers: { Authorization: `Bearer ${env('TAVILY_API_KEY')}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, search_depth: 'basic', max_results: maxResults, include_answer: false }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(`Search ${res.status}: ${JSON.stringify(data).slice(0, 200)}`);
  return {
    results: (data.results || []).map((r) => ({ title: r.title, url: r.url, snippet: String(r.content || '').slice(0, 600) })),
  };
}
