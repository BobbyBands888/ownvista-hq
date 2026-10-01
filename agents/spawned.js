// Runtime for crew members the Architect designed (kind 'new').
// The spec is data: a mission, a lane, a list of building blocks and what it may read.
// This file is the ONLY code those crew members run, and every block below writes a proposal row
// (idea, task, paused search source, draft asset, one Needs-you note). Nothing here sends, spends,
// publishes, signs up, trades or calls an outside service other than the capped LLM.
import { db } from './lib/db.js';
import { chat } from './lib/llm.js';
import { systemPrompt, checkCopy, untrusted } from './lib/guard.js';
import { playbook, BUSINESSES } from './lib/context.js';
import { truncate, similarTitle } from './lib/text.js';
import { daysAgoIso } from './lib/time.js';
import { BLOCKS, READS, ASSET_KINDS } from './lib/crew.js';

export async function run(ctx) {
  const spec = ctx.spec || await db.one('crew_specs', { id: `eq.${ctx.agent}` });
  if (!spec || !['probation', 'active'].includes(spec.status)) return 'not on the crew';
  const blocks = (spec.blocks || []).filter((b) => BLOCKS[b]);
  const used = await usedThisWeek(spec.id);
  const open = blocks.filter((b) => used[b] < BLOCKS[b].perWeek);
  if (!open.length) return 'weekly output limit reached';

  const pb = await playbook();
  const context = await readContext(spec.reads || []);
  const menu = open.map((b) => `- ${b}: ${BLOCKS[b].label} (max ${Math.min(BLOCKS[b].perRun, BLOCKS[b].perWeek - used[b])} this run)`).join('\n');
  const system = systemPrompt(`${spec.name}, a crew member on probation`, `
${pb.text(['voice', 'guardrails', 'businesses'])}

Your mission: ${spec.mission}
Lane: ${spec.lane}. You keep your job only if your outputs get approved or used, so quality over quantity. Zero actions is fine.
You can ONLY produce these outputs (everything is a proposal; nothing is sent or published by you):
${menu}
Field rules:
- propose_idea: {"block":"propose_idea","kind":"growth|venture","business":"${BUSINESSES.join('|')}","title":"","summary":"","steps":["..."],"price_usd":null}
  (kind "venture" = a product we can sell as one web page of written content, with a one-time price_usd; Autopilot approves ideas and the Launcher builds and publishes them)
- agent_task: {"block":"agent_task","title":"","detail":"","business":""} (writing work only: no sending, paying, signing up, calls or publishing)
- research_query: {"block":"research_query","name":"","query":"","business":""}
- draft_asset: {"block":"draft_asset","idea_title":"exact title of an approved/launched idea from the context","kind":"${ASSET_KINDS.join('|')}","title":"","body":"markdown"}
- note_to_bobby: {"block":"note_to_bobby","title":"","detail":"two sentences max"}
No invented facts, numbers, testimonials or links. No phone calls.
JSON only: {"actions":[ ... ]}`);
  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 2200, system,
    messages: [{ role: 'user', content: context || '(no context available yet)' }],
  });

  const done = { ...Object.fromEntries(open.map((b) => [b, 0])) };
  const results = [];
  for (const a of (json.actions || []).slice(0, 8)) {
    const b = a?.block;
    if (!open.includes(b)) continue;
    if (done[b] >= Math.min(BLOCKS[b].perRun, BLOCKS[b].perWeek - used[b])) continue;
    const text = [a.title, a.summary, a.detail, a.body, ...(a.steps || [])].filter(Boolean).join('\n');
    const problems = checkCopy(text, { business: a.business });
    if (problems.length) { ctx.note(`skipped ${b}: ${problems.join('; ')}`); continue; }
    const ok = await HANDLERS[b](spec, a);
    if (ok) { done[b]++; results.push(`${b}: ${truncate(a.title || a.query || '', 60)}`); }
  }
  if (results.length) ctx.log('crew', `${spec.name}: ${results.join(' · ')}`, { table: 'crew_specs', id: spec.id });
  return results.length ? `${results.length} output(s)` : 'nothing worth proposing this run';
}

const HANDLERS = {
  async propose_idea(spec, a) {
    if (!a.title) return false;
    const recent = await db.select('ideas', { created_at: `gte.${daysAgoIso(30)}`, select: 'title', limit: 300 });
    if (recent.some((r) => similarTitle(r.title, a.title))) return false;
    const price = Number(a.price_usd);
    const venture = a.kind === 'venture' && price >= 5 && price <= 300;
    await db.insertOne('ideas', {
      kind: venture ? 'venture' : 'growth', business: venture ? 'venture-lab' : BUSINESSES.includes(a.business) ? a.business : null, title: truncate(a.title, 200),
      summary: truncate(a.summary || '', 3000), steps: (a.steps || []).slice(0, 8).map((s) => truncate(String(s), 300)), created_by: spec.id,
      ...(venture ? { economics: { price_usd: price, cost_usd: 0 } } : {}),
    });
    return true;
  },
  async agent_task(spec, a) {
    if (!a.title || /\b(send|publish|post|sign ?up|pay|buy|call)\b/i.test(`${a.title} ${a.detail}`)) return false;
    const open = await db.select('tasks', { status: 'in.(todo,doing,blocked)', select: 'title', limit: 100 });
    if (open.some((t) => similarTitle(t.title, a.title))) return false;
    await db.insertOne('tasks', {
      title: truncate(a.title, 200), detail: truncate(a.detail || '', 2000),
      business: BUSINESSES.includes(a.business) ? a.business : null, assignee: 'agent', created_by: spec.id,
    });
    return true;
  },
  async research_query(spec, a) {
    const query = String(a.query || '').trim();
    if (!query) return false;
    // Always paused: turning a search source on stays Bobby's (or the Researcher's existing rules') call.
    await db.insert('sources', [{
      name: truncate(a.name || query, 120), kind: 'search', query, url: `search:${query.toLowerCase()}`,
      business: BUSINESSES.includes(a.business) ? a.business : null, status: 'paused', added_by: spec.id,
    }], { onConflict: 'url', ignoreDuplicates: true });
    return true;
  },
  async draft_asset(spec, a) {
    if (!a.body || !ASSET_KINDS.includes(a.kind)) return false;
    const ideas = await db.select('ideas', { status: 'in.(approved,launched)', select: 'id,title', order: 'decided_at.desc', limit: 40 });
    const idea = ideas.find((i) => i.title === a.idea_title) || ideas.find((i) => similarTitle(i.title, a.idea_title || ''));
    if (!idea) return false;
    const asset = await db.insertOne('assets', { idea_id: idea.id, kind: a.kind, title: truncate(a.title || a.kind, 200), body: truncate(a.body, 12000), created_by: spec.id });
    // Bobby's Approve is how a draft counts as "used" for the kill metric. Approving never publishes it.
    await db.insertOne('approvals', {
      kind: 'crew_draft', ref_table: 'assets', ref_id: asset?.id ?? null, created_by: spec.id,
      title: `${truncate(spec.name, 40)} drafted: ${truncate(a.title || a.kind, 110)}`,
      detail: `For "${truncate(idea.title, 120)}". Approve if it's worth using (nothing is published automatically).\n\n${truncate(a.body, 1500)}`,
    });
    return true;
  },
  async note_to_bobby(spec, a) {
    if (!a.title) return false;
    await db.insertOne('approvals', {
      kind: 'crew', ref_table: 'crew_specs', ref_id: spec.id, created_by: spec.id,
      title: `${truncate(spec.name, 40)}: ${truncate(a.title, 120)}`, detail: truncate(a.detail || '', 400),
    });
    return true;
  },
};

async function usedThisWeek(id) {
  const since = daysAgoIso(7);
  const [ideas, tasks, sources, assets, notes] = await Promise.all([
    db.count('ideas', { created_by: `eq.${id}`, created_at: `gte.${since}` }),
    db.count('tasks', { created_by: `eq.${id}`, created_at: `gte.${since}` }),
    db.count('sources', { added_by: `eq.${id}`, created_at: `gte.${since}` }).catch(() => 0),
    db.count('assets', { created_by: `eq.${id}`, created_at: `gte.${since}` }),
    db.count('approvals', { created_by: `eq.${id}`, kind: 'eq.crew', created_at: `gte.${since}` }),
  ]);
  return { propose_idea: ideas, agent_task: tasks, research_query: sources, draft_asset: assets, note_to_bobby: notes };
}

async function readContext(reads) {
  const parts = [];
  const want = reads.filter((r) => READS.includes(r));
  for (const r of want) {
    try {
      if (r === 'ledger') {
        const rows = await db.select('ledger', { day: `gte.${daysAgoIso(30).slice(0, 10)}`, select: 'line,source,revenue,note', limit: 100 });
        parts.push(`Revenue, last 30 days: ${rows.length ? rows.map((x) => `${x.line}/${x.source} $${x.revenue}`).join('; ') : '$0 — no sales yet'}`);
      } else if (r === 'launches') {
        const rows = await db.select('launches', { select: 'title,status,price_usd,sales,slug', order: 'created_at.desc', limit: 10 });
        parts.push(`Offers: ${rows.map((x) => `"${x.title}" ${x.status} $${x.price_usd} sales ${x.sales}${x.status === 'live' ? ` https://www.levelingclips.com/p/${x.slug}` : ''}`).join('; ') || 'none'}`);
      } else if (r === 'asset_packs') {
        const rows = await db.select('asset_packs', { select: 'title,status,price_usd,views,downloads,sales', order: 'created_at.desc', limit: 10 });
        parts.push(`itch.io packs: ${rows.map((x) => `"${x.title}" ${x.status} $${x.price_usd} views ${x.views} sales ${x.sales}`).join('; ') || 'none'}`);
      } else if (r === 'knowledge') {
        const rows = await db.select('knowledge', { created_at: `gte.${daysAgoIso(7)}`, order: 'usefulness.desc', select: 'title,url,summary', limit: 10 });
        parts.push(`Recent research:\n${rows.map((k) => untrusted(k.url, `${k.title}: ${truncate(k.summary, 300)}`, 500)).join('\n')}`);
      } else if (r === 'ideas') {
        const rows = await db.select('ideas', { status: 'in.(approved,launched,rejected)', select: 'title,status,feedback', order: 'decided_at.desc', limit: 15 });
        parts.push(`Idea decisions: ${rows.map((i) => `${i.status}: ${i.title}${i.feedback ? ` (Bobby: ${truncate(i.feedback, 120)})` : ''}`).join('; ')}`);
      } else if (r === 'activity') {
        const rows = await db.select('activity', { select: 'agent,message', order: 'created_at.desc', limit: 20 });
        parts.push(`Recent activity:\n${rows.map((x) => `- ${x.agent}: ${truncate(x.message, 160)}`).join('\n')}`);
      } else if (r === 'signals') {
        const rows = await db.select('signals', { order: 'created_at.desc', limit: 10 });
        parts.push(`Demand signals:\n${rows.map((s) => untrusted(s.url || 'signal', truncate(`[${s.lane}] ${s.title}: ${s.evidence || ''}`, 300), 400)).join('\n')}`);
      } else if (r === 'villa_counts') {
        const [prospects, orders] = await Promise.all([db.count('vc_prospects'), db.count('vc_orders', { kind: 'eq.paid' })]);
        parts.push(`Villa Cinema: ${prospects} prospects, ${orders} paid orders (outreach can't send yet).`);
      }
    } catch (e) {
      parts.push(`(${r} unavailable: ${truncate(e.message, 80)})`);
    }
  }
  return parts.join('\n\n');
}
