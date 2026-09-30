// Strategist — daily 7am ET. Up to 3 growth ideas with concrete steps, up to 3 agent tasks,
// up to 3 new research sources (search queries) to fill gaps.
import { db } from './lib/db.js';
import { chat } from './lib/llm.js';
import { systemPrompt, untrusted } from './lib/guard.js';
import { playbook, BUSINESSES } from './lib/context.js';
import { similarTitle, truncate } from './lib/text.js';
import { daysAgoIso } from './lib/time.js';
import { searchAvailable } from './lib/search.js';

export async function run(ctx) {
  const pb = await playbook();
  const [knowledge, tasks, decided, recentIdeas, sources, ledger] = await Promise.all([
    db.select('knowledge', { created_at: `gte.${daysAgoIso(7)}`, order: 'usefulness.desc,created_at.desc', limit: 25 }),
    db.select('tasks', { status: 'in.(todo,doing,blocked)', order: 'created_at.desc', limit: 20 }),
    db.select('ideas', { status: 'in.(approved,rejected,launched)', kind: 'eq.growth', order: 'decided_at.desc', limit: 15 }),
    db.select('ideas', { created_at: `gte.${daysAgoIso(30)}`, select: 'title', limit: 200 }),
    db.select('sources', { status: 'eq.active', select: 'name,business,kind,query', limit: 200 }),
    db.select('ledger', { day: `gte.${daysAgoIso(30).slice(0, 10)}`, limit: 500 }),
  ]);
  const byLine = {};
  for (const l of ledger) {
    const x = (byLine[l.line] ||= { revenue: 0, cost: 0, hours: 0 });
    x.revenue += +l.revenue; x.cost += +l.cost; x.hours += +l.bobby_hours;
  }
  const coverage = Object.fromEntries(BUSINESSES.map((b) => [b, sources.filter((s) => s.business === b).length]));
  const canSearch = await searchAvailable();

  const system = systemPrompt('the Strategist', `
${pb.text(['growth', 'businesses', 'guardrails', 'lab'])}

Propose up to 3 growth ideas for Bobby's CURRENT businesses. Each needs: which business, the idea, why now (cite knowledge URLs you were given — never invent links), and 3–6 concrete steps that can be done by email and the web.
Learn from past decisions: do not repeat rejected ideas; lean toward what Bobby approved or launched.
Create up to 3 tasks YOU (the agents) can execute with writing alone (research summaries, copy, outreach drafts, step plans). No tasks that need sending, paying, signing up, calls or publishing.
Suggest up to 3 new research search queries to fill gaps in coverage (short, specific web-search phrasing).
JSON only:
{"ideas":[{"business":"${BUSINESSES.slice(0, 5).join('|')}","title":"","summary":"","why_now":"","steps":["..."],"source_urls":["..."]}],
 "tasks":[{"title":"","detail":"","business":""}],
 "sources":[{"name":"","query":"","business":""}]}`);

  const user = [
    `Recent knowledge (last 7 days):\n${knowledge.map((k) => untrusted(k.url, `[${k.businesses.join(',')}] u${k.usefulness} ${k.title}: ${k.summary}`, 500)).join('\n') || '(none yet)'}`,
    `Open tasks:\n${tasks.map((t) => `- [${t.assignee}/${t.status}] ${t.title}`).join('\n') || '(none)'}`,
    `Past growth-idea decisions:\n${decided.map((i) => `- ${i.status.toUpperCase()}: ${i.title}${i.feedback ? ` — Bobby: "${truncate(i.feedback, 200)}"` : ''}`).join('\n') || '(none yet)'}`,
    `Profit ledger, last 30 days: ${JSON.stringify(byLine)}`,
    `Source coverage by business: ${JSON.stringify(coverage)}`,
  ].join('\n\n');

  const { json } = await chat({ ctx, tier: 'smart', system, json: true, maxTokens: 2600, messages: [{ role: 'user', content: user }] });

  const knownUrls = new Set(knowledge.map((k) => k.url));
  let ideas = 0, newTasks = 0, newSources = 0;
  for (const idea of (json.ideas || []).slice(0, 3)) {
    if (!idea.title || recentIdeas.some((r) => similarTitle(r.title, idea.title))) continue;
    const urls = (idea.source_urls || []).filter((u) => knownUrls.has(u));
    await db.insertOne('ideas', {
      kind: 'growth', business: BUSINESSES.includes(idea.business) ? idea.business : null,
      title: truncate(idea.title, 200), summary: `${idea.summary || ''}${idea.why_now ? `\n\nWhy now: ${idea.why_now}` : ''}`.trim(),
      steps: (idea.steps || []).slice(0, 8), source_urls: urls, created_by: 'strategist',
    });
    ideas++;
  }
  const openTitles = tasks.map((t) => t.title);
  for (const t of (json.tasks || []).slice(0, 3)) {
    if (!t.title || openTitles.some((o) => similarTitle(o, t.title))) continue;
    await db.insertOne('tasks', {
      title: truncate(t.title, 200), detail: truncate(t.detail || '', 2000),
      business: BUSINESSES.includes(t.business) ? t.business : null, assignee: 'agent', created_by: 'strategist',
    });
    newTasks++;
  }
  for (const s of (json.sources || []).slice(0, 3)) {
    const query = String(s.query || '').trim();
    if (!query || sources.some((x) => x.query && similarTitle(x.query, query))) continue;
    await db.insert('sources', [{
      name: truncate(s.name || query, 120), kind: 'search', query, url: `search:${query.toLowerCase()}`,
      business: BUSINESSES.includes(s.business) ? s.business : null,
      status: canSearch ? 'active' : 'paused', added_by: 'strategist',
    }], { onConflict: 'url', ignoreDuplicates: true });
    newSources++;
  }
  ctx.log('strategy', `Proposed ${ideas} idea(s), ${newTasks} agent task(s), ${newSources} new source(s)${canSearch ? '' : ' (search sources wait paused until search is approved)'}`);
  return `ideas ${ideas}, tasks ${newTasks}, sources ${newSources}`;
}
