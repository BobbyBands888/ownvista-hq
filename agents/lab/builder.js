// Builder — hourly, 24/7, when there is work. For approved ideas/experiments it builds
// everything that needs no account and no payment: listing copy, briefs, landing page,
// outreach drafts (Gmail drafts, no recipient), pricing sheet, step plans. Never publishes.
import { db, kvGet, kvSet } from '../lib/db.js';
import { GMAIL_USER } from '../lib/env.js';
import { chat, CapError } from '../lib/llm.js';
import { systemPrompt } from '../lib/guard.js';
import { checkCopy } from '../lib/guard.js';
import { createDraft } from '../lib/gmail.js';
import { playbook, signoff } from '../lib/context.js';
import { truncate } from '../lib/text.js';
import { retireRealEstate } from '../lib/no_real_estate.js';

const KINDS = {
  growth: ['copy', 'outreach_draft', 'step_plan'],
  business: ['landing_page', 'outreach_draft', 'pricing_sheet', 'step_plan'],
  venture: ['listing_copy', 'design_brief', 'landing_page', 'outreach_draft', 'pricing_sheet'],
};

export async function run(ctx) {
  await retireRealEstate(ctx);
  // Growth ideas are built by the Operator; the Builder handles business + venture ideas.
  // Pick the oldest approved idea that has no assets yet. An idea marked built but holding
  // zero assets (an earlier empty build) counts as not built, so it gets retried.
  const approved = await db.select('ideas', {
    kind: 'in.(business,venture)', status: 'in.(approved,launched)', select: '*,assets(id)', order: 'decided_at.asc', limit: 20,
  });
  const pushed = await pushMissingDrafts(ctx);
  // One idea the model refuses (or keeps botching) must not block the whole queue: after MAX_FAILS
  // failed builds it is parked and the next idea gets built. (Oct 2: a short-term-rental guide the model
  // refused jammed the Builder for 12+ hours with 7 game-asset ideas waiting behind it.)
  const fails = (await kvGet('builder_failures', {})) || {};
  const todo = approved.filter((i) => (!i.assets_built_at || !(i.assets || []).length) && (fails[i.id]?.n || 0) < MAX_FAILS);
  const parked = approved.filter((i) => (fails[i.id]?.n || 0) >= MAX_FAILS && !(i.assets || []).length).length;
  if (!todo.length) return [pushed ? `pushed ${pushed} missing Gmail draft(s)` : 'nothing approved to build', parked ? `${parked} parked after failed builds` : ''].filter(Boolean).join(' · ');
  const { assets: _drop, ...idea } = todo[0];
  let n = 0, why = '';
  try {
    n = await buildAssetsFor(ctx, idea);
    if (!n) why = 'the model returned nothing usable';
  } catch (e) {
    if (e instanceof CapError) throw e;
    why = /can.?t help|cannot (create|proceed|help)|prohibited|not able to/i.test(e.message) ? `the model refused: ${truncate(e.message.replace(/^.*failed_generation":"/, ''), 140)}` : truncate(e.message, 160);
  }
  if (n) {
    if (fails[idea.id]) { delete fails[idea.id]; await kvSet('builder_failures', fails); }
    return `built ${n} asset(s) for "${truncate(idea.title, 60)}"`;
  }
  const f = { n: (fails[idea.id]?.n || 0) + 1, why, title: truncate(idea.title, 80), at: new Date().toISOString() };
  fails[idea.id] = f;
  await kvSet('builder_failures', fails);
  if (f.n >= MAX_FAILS) {
    ctx.log('builder_parked', `Parked "${truncate(idea.title, 80)}" after ${f.n} failed builds (${why}). Moving on to the next idea.`, { table: 'ideas', id: idea.id });
    return `parked "${truncate(idea.title, 60)}" after ${f.n} failed builds — next idea builds next run`;
  }
  throw new Error(`build ${f.n}/${MAX_FAILS} failed for "${truncate(idea.title, 60)}": ${why}`);
}

const MAX_FAILS = 2;

export async function buildAssetsFor(ctx, idea) {
  const pb = await playbook();
  const kinds = KINDS[idea.kind] || KINDS.growth;
  const experiment = idea.kind === 'venture' ? await db.one('experiments', { idea_id: `eq.${idea.id}` }) : null;
  const villa = idea.business === 'villa-cinema';

  const system = systemPrompt('the Builder', `
${pb.text(['voice', 'guardrails', 'businesses', 'lab'])}

Build the assets for this approved idea. Asset kinds to produce: ${kinds.join(', ')}.
- landing_page: complete, self-contained HTML (inline CSS, no JavaScript, no forms). Every buy/order button links to {{BUY_URL}} exactly. The Launcher publishes it with a Stripe checkout; state the price.
- outreach_draft: an email to a TYPE of recipient (no names/addresses); first line "Subject: …".
- pricing_sheet: a markdown table with the real numbers from the idea's economics.
- listing_copy: marketplace title, bullets and description that follow marketplace rules; no trademarks, no fake claims.
- design_brief / step_plan / copy: markdown.
No phone-call offers. No invented reviews, testimonials or statistics.
${villa ? 'This is Villa Cinema: never mention Ownvista, Nashville Buys or Follow-Up.' : ''}
JSON only: {"assets":[{"kind":"","title":"","body":""}]}`);

  const user = `Idea (${idea.kind}, ${idea.business || 'general'}): ${idea.title}
Summary: ${truncate(idea.summary, 3000)}
Steps: ${JSON.stringify(idea.steps || [])}
Economics: ${JSON.stringify(idea.economics || {})}
Experiment: ${JSON.stringify(experiment || idea.experiment || {})}
Bobby's note: ${idea.feedback || '(none)'}`;

  const { json } = await chat({ ctx, tier: 'smart', system, json: true, maxTokens: 8000, messages: [{ role: 'user', content: user }] });
  let made = 0;
  for (const a of assetList(json).slice(0, 8)) {
    const raw = assetBody(a);
    if (!raw) continue;
    let body = raw;
    const problems = checkCopy(body, { business: idea.business, villa });
    let draftId = null;
    if (problems.length) {
      body = `> Guardrail flagged this asset: ${problems.join('; ')}. Review before using.\n\n${body}`;
    } else if (a.kind === 'outreach_draft' && !villa) {
      const m = /^subject:\s*(.+)$/im.exec(body);
      const subject = m ? m[1].trim() : a.title || idea.title;
      const text = body.replace(/^subject:.*$/im, '').trim();
      const from = idea.business === 'followup' ? 'hello@getownvista.com' : GMAIL_USER();
      try {
        ({ draftId } = await createDraft({ from, to: '', subject, body: `${text}\n\n${signoff(idea.business)}` }));
      } catch (e) {
        // Keep the asset even when Gmail is down; the draft text is still in the dashboard.
        ctx.log('gmail_error', `Gmail draft skipped: ${truncate(e.message, 160)}`, { table: 'ideas', id: idea.id });
      }
    }
    await db.insertOne('assets', {
      idea_id: idea.id, experiment_id: experiment?.id ?? null, kind: a.kind || 'copy',
      title: truncate(a.title || a.kind, 200), body, gmail_draft_id: draftId, created_by: ctx.agent,
    });
    made++;
  }
  if (!made) return 0; // leave assets_built_at empty so the next run tries again
  await db.update('ideas', { id: `eq.${idea.id}` }, { assets_built_at: new Date().toISOString() });
  ctx.log('assets', `Built ${made} asset(s) for "${truncate(idea.title, 80)}"`, { table: 'ideas', id: idea.id });
  return made;
}

// Outreach drafts built while Gmail was down never reached Gmail. Push up to 3 per run.
async function pushMissingDrafts(ctx) {
  const rows = await db.select('assets', {
    kind: 'eq.outreach_draft', gmail_draft_id: 'is.null', select: 'id,title,body,ideas(business,title)', order: 'created_at.asc', limit: 10,
  });
  let n = 0;
  for (const a of rows) {
    if (n >= 3 || ctx.outOfTime(60000)) break;
    const business = a.ideas?.business;
    if (business === 'villa-cinema' || a.body.startsWith('> Guardrail')) continue;
    const m = /^subject:\s*(.+)$/im.exec(a.body);
    const subject = m ? m[1].trim() : a.title || a.ideas?.title || 'Draft';
    const text = a.body.replace(/^subject:.*$/im, '').trim();
    const from = business === 'followup' ? 'hello@getownvista.com' : GMAIL_USER();
    try {
      const { draftId } = await createDraft({ from, to: '', subject, body: `${text}\n\n${signoff(business)}` });
      await db.update('assets', { id: `eq.${a.id}` }, { gmail_draft_id: draftId });
      n++;
    } catch (e) {
      ctx.log('gmail_error', `Gmail draft push failed: ${truncate(e.message, 160)}`);
      break;
    }
  }
  if (n) ctx.log('assets', `Pushed ${n} missing outreach draft(s) to Gmail`);
  return n;
}

// Models don't always use the exact keys asked for. Accept the common variants.
export function assetList(json) {
  if (!json || typeof json !== 'object') return [];
  const list = json.assets ?? json.Assets ?? json.items ?? json.deliverables;
  if (Array.isArray(list)) return list.filter((a) => a && typeof a === 'object');
  if (list && typeof list === 'object') return Object.entries(list).map(([kind, v]) => (typeof v === 'string' ? { kind, body: v } : { kind, ...v }));
  return [];
}

export function assetBody(a) {
  const v = a.body ?? a.content ?? a.html ?? a.markdown ?? a.text;
  if (v == null) return '';
  return (typeof v === 'string' ? v : JSON.stringify(v, null, 2)).trim();
}
