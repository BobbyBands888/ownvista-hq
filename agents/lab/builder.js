// Builder — hourly 6am–11pm ET when there is work. For approved ideas/experiments it builds
// everything that needs no account and no payment: listing copy, briefs, landing page,
// outreach drafts (Gmail drafts, no recipient), pricing sheet, step plans. Never publishes.
import { db } from '../lib/db.js';
import { GMAIL_USER } from '../lib/env.js';
import { chat } from '../lib/llm.js';
import { systemPrompt } from '../lib/guard.js';
import { checkCopy } from '../lib/guard.js';
import { createDraft } from '../lib/gmail.js';
import { playbook, signoff } from '../lib/context.js';
import { truncate } from '../lib/text.js';

const KINDS = {
  growth: ['copy', 'outreach_draft', 'step_plan'],
  business: ['landing_page', 'outreach_draft', 'pricing_sheet', 'step_plan'],
  venture: ['listing_copy', 'design_brief', 'landing_page', 'outreach_draft', 'pricing_sheet'],
};

export async function run(ctx) {
  // Growth ideas are built by the Operator; the Builder handles business + venture ideas.
  const ideas = await db.select('ideas', {
    kind: 'in.(business,venture)', status: 'in.(approved,launched)', assets_built_at: 'is.null', order: 'decided_at.asc', limit: 1,
  });
  if (!ideas.length) return 'nothing approved to build';
  const n = await buildAssetsFor(ctx, ideas[0]);
  return `built ${n} asset(s) for "${truncate(ideas[0].title, 60)}"`;
}

export async function buildAssetsFor(ctx, idea) {
  const pb = await playbook();
  const kinds = KINDS[idea.kind] || KINDS.growth;
  const experiment = idea.kind === 'venture' ? await db.one('experiments', { idea_id: `eq.${idea.id}` }) : null;
  const villa = idea.business === 'villa-cinema';

  const system = systemPrompt('the Builder', `
${pb.text(['voice', 'guardrails', 'businesses', 'lab'])}

Build the assets for this approved idea. Asset kinds to produce: ${kinds.join(', ')}.
- landing_page: complete, self-contained HTML (inline CSS) Bobby can review; do not publish it.
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

  const { json } = await chat({ ctx, tier: 'smart', system, json: true, maxTokens: 4000, messages: [{ role: 'user', content: user }] });
  let made = 0;
  for (const a of (json.assets || []).slice(0, 8)) {
    if (!a.body) continue;
    let body = String(a.body);
    const problems = checkCopy(body, { business: idea.business, villa });
    let draftId = null;
    if (problems.length) {
      body = `> Guardrail flagged this asset: ${problems.join('; ')}. Review before using.\n\n${body}`;
    } else if (a.kind === 'outreach_draft' && !villa) {
      const m = /^subject:\s*(.+)$/im.exec(body);
      const subject = m ? m[1].trim() : a.title || idea.title;
      const text = body.replace(/^subject:.*$/im, '').trim();
      const from = idea.business === 'followup' ? 'hello@getownvista.com' : GMAIL_USER();
      ({ draftId } = await createDraft({ from, to: '', subject, body: `${text}\n\n${signoff(idea.business)}` }));
    }
    await db.insertOne('assets', {
      idea_id: idea.id, experiment_id: experiment?.id ?? null, kind: a.kind || 'copy',
      title: truncate(a.title || a.kind, 200), body, gmail_draft_id: draftId, created_by: ctx.agent,
    });
    made++;
  }
  await db.update('ideas', { id: `eq.${idea.id}` }, { assets_built_at: new Date().toISOString() });
  ctx.log('assets', `Built ${made} asset(s) for "${truncate(idea.title, 80)}"`, { table: 'ideas', id: idea.id });
  return made;
}
