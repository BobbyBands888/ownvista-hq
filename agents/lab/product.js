// Product builder for the Launcher. A paid product must be COMPLETE before anything goes public:
//   - written section by section across hourly runs (fits Groq's free per-minute limits),
//   - every template, table, script and checklist written out inline (buyers get one web page, no files),
//   - checked against a hard quality bar (productProblems) before it can be used.
// Draft progress is stored as an asset of kind 'product_draft' (JSON), so a run that runs out of time resumes next hour.
import { db } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt, checkCopy } from '../lib/guard.js';
import { playbook } from '../lib/context.js';
import { truncate } from '../lib/text.js';

export const BAR = { minChars: 12000, minSections: 6, maxAttempts: 2 };

// References to things the buyer will never receive (they only get one web page).
export const FAKE_DELIVERY = /(download link|attached|attachment|excel file|google sheets? link|\.xlsx|\.csv\b|spreadsheet \(download|we(?:'| wi)ll email|you will receive an email|link below to download|downloadable (?:file|template|spreadsheet)|separate file|included file)/i;
const PLACEHOLDER = /(\[insert|\binsert (?:here|your)\b|\bTBD\b|\bTODO\b|lorem ipsum|coming soon|to be added|\(add [a-z ]+ here\)|xx%|\$xx)/i;
const NEEDS_TABLE = /\b(template|spreadsheet|tracker|worksheet|calculator|log sheet|scorecard)\b/i;

// Returns a list of reasons the product isn't sellable yet. Empty list = passes.
export function productProblems(body = '') {
  const text = String(body || '');
  const out = [];
  if (text.length < BAR.minChars) out.push(`too short (${text.length} chars, need ${BAR.minChars})`);
  const sections = (text.match(/^##\s+\S/gm) || []).length;
  if (sections < BAR.minSections) out.push(`only ${sections} main sections (need ${BAR.minSections})`);
  const fake = FAKE_DELIVERY.exec(text);
  if (fake) out.push(`refers to something buyers don't get ("${fake[0]}")`);
  const ph = PLACEHOLDER.exec(text);
  if (ph) out.push(`unfinished placeholder ("${ph[0]}")`);
  if (NEEDS_TABLE.test(text) && !/^\s*\|.*\|\s*$\n^\s*\|\s*:?-{3,}/m.test(text)) out.push('mentions a template/tracker but has no table written out');
  return out;
}

// The newest product asset for an idea that passes the bar, or null.
export async function finishedProduct(ideaId) {
  const rows = await db.select('assets', { idea_id: `eq.${ideaId}`, kind: 'eq.product', order: 'created_at.desc', limit: 5 });
  return rows.find((r) => !productProblems(r.body).length) || null;
}

// Advance (or finish) the product for an idea. Returns { product } when done,
// { pending: 'reason' } while still writing, or { failed: 'reason' } after too many bad attempts.
export async function advanceProduct(ctx, idea, plan) {
  const done = await finishedProduct(idea.id);
  if (done) return { product: done };

  let draftRow = await db.one('assets', { idea_id: `eq.${idea.id}`, kind: 'eq.product_draft', order: 'created_at.desc' });
  let draft = draftRow ? safeJson(draftRow.body) : null;
  if (draft?.failed) return { failed: draft.failed };

  if (!draft?.outline) {
    const outline = await writeOutline(ctx, idea, plan, draft?.lastProblems);
    if (!outline) return { pending: 'outline not ready' };
    draft = { outline, sections: [], attempts: draft?.attempts || 0, deliverable: plan.deliverable, price_usd: plan.price_usd };
    draftRow = draftRow
      ? (await db.update('assets', { id: `eq.${draftRow.id}` }, { body: JSON.stringify(draft) }), draftRow)
      : await db.insertOne('assets', { idea_id: idea.id, kind: 'product_draft', title: truncate(outline.title, 200), body: JSON.stringify(draft), created_by: ctx.agent });
    ctx.log('launch', `Outlined the product for "${truncate(idea.title, 70)}" (${outline.sections.length} sections)`, { table: 'ideas', id: idea.id });
  }

  const save = () => db.update('assets', { id: `eq.${draftRow.id}` }, { body: JSON.stringify(draft) });
  while (draft.sections.length < draft.outline.sections.length) {
    if (ctx.outOfTime(75000)) return { pending: `${draft.sections.length}/${draft.outline.sections.length} sections written` };
    const md = await writeSection(ctx, idea, draft, draft.sections.length);
    if (!md) return { pending: `section ${draft.sections.length + 1} failed; retrying next run` };
    draft.sections.push(md);
    await save();
  }

  const body = assemble(draft.outline, draft.sections);
  const problems = [...productProblems(body), ...checkCopy(body, { business: idea.business })];
  if (problems.length) {
    draft.attempts = (draft.attempts || 0) + 1;
    if (draft.attempts >= BAR.maxAttempts) {
      draft.failed = `product failed the quality bar twice: ${problems.join('; ')}`;
      await save();
      return { failed: draft.failed };
    }
    ctx.log('launch', `Product for "${truncate(idea.title, 60)}" missed the bar (${truncate(problems.join('; '), 200)}); rewriting`, { table: 'ideas', id: idea.id });
    draft = { attempts: draft.attempts, lastProblems: problems, deliverable: draft.deliverable, price_usd: draft.price_usd };
    await save();
    return { pending: 'rewriting after quality check' };
  }

  const product = await db.insertOne('assets', { idea_id: idea.id, kind: 'product', title: truncate(draft.outline.title, 200), body, created_by: ctx.agent });
  await db.delete('assets', { id: `eq.${draftRow.id}` });
  ctx.log('launch', `Finished the product for "${truncate(idea.title, 70)}" (${body.length.toLocaleString()} chars, passed the quality bar)`, { table: 'ideas', id: idea.id });
  return { product };
}

async function writeOutline(ctx, idea, plan, lastProblems) {
  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 1500, temperature: 0.3,
    system: systemPrompt('the Launcher planning a paid product', `Plan the COMPLETE digital product a buyer receives: ${plan.deliverable || 'the product described'}.
The buyer gets ONE web page they can read, print or save as PDF — no files, downloads, emails, calls or support.
So every template, spreadsheet, tracker, script or checklist must be WRITTEN OUT inside a section (as markdown tables, numbered steps, word-for-word scripts).
Plan 7-9 sections. Each section is substantial (1,500-2,500 characters) and concrete for the target buyer.
JSON only: {"title":"product title","promise":"one sentence: what the buyer can do after using it","sections":[{"heading":"","contains":"exactly what this section includes, naming each table/script/checklist"}]}`),
    messages: [{ role: 'user', content: `Idea: ${idea.title}\nSummary: ${truncate(idea.summary, 2500)}\nSteps: ${truncate(JSON.stringify(idea.steps || []), 1500)}\nBobby's note: ${idea.feedback || '(none)'}${lastProblems ? `\nThe last version was rejected because: ${lastProblems.join('; ')}. Fix that.` : ''}` }],
  });
  const sections = (Array.isArray(json.sections) ? json.sections : [])
    .map((s) => ({ heading: truncate(String(s.heading || '').replace(/^#+\s*/, ''), 120), contains: truncate(String(s.contains || ''), 500) }))
    .filter((s) => s.heading && s.contains);
  if (sections.length < BAR.minSections || !json.title) return null;
  return { title: truncate(String(json.title), 200), promise: truncate(String(json.promise || ''), 300), sections: sections.slice(0, 10) };
}

async function writeSection(ctx, idea, draft, i) {
  const pb = await playbook();
  const { outline } = draft;
  const s = outline.sections[i];
  const { text } = await chat({
    ctx, tier: 'smart', maxTokens: 3500, temperature: 0.4,
    system: systemPrompt('the Launcher writing one section of a paid product', `${pb.text(['voice', 'guardrails'])}
You are writing section ${i + 1} of ${outline.sections.length} of "${outline.title}". Write ONLY this section, in markdown, starting with "## ${s.heading}".
Length: 1,500-2,500 characters. Concrete and finished: real steps, real examples, word-for-word scripts where useful.
Any template, tracker or spreadsheet is written out as a markdown table (header row, separator row, at least 2 example rows); explain formulas in words.
Never refer to files, downloads, attachments, links, emails, calls, support or other sections "in the appendix". No placeholders like [insert]; buyer fill-in blanks like "[Customer name]" are fine.
No invented statistics, no testimonials, no guarantees. Output the markdown only.`),
    messages: [{ role: 'user', content: `Product promise: ${outline.promise}\nAll sections: ${outline.sections.map((x, n) => `${n + 1}. ${x.heading}`).join(' | ')}\n\nWrite section ${i + 1}: ${s.heading}\nIt must contain: ${s.contains}\n\nBuyer context: ${truncate(idea.summary, 1200)}` }],
  });
  let md = String(text || '').trim().replace(/^```(?:markdown|md)?\s*/i, '').replace(/```\s*$/, '').trim();
  if (!md.startsWith('## ')) md = `## ${s.heading}\n\n${md.replace(/^#+\s*.*\n/, '')}`;
  md = md.replace(/^# (?!#)/gm, '### ');
  if (md.length < 900 || FAKE_DELIVERY.test(md) || PLACEHOLDER.test(md)) return null;
  return md;
}

export function assemble(outline, sections) {
  const toc = outline.sections.map((s, i) => `${i + 1}. ${s.heading}`).join('\n');
  return `# ${outline.title}\n\n${outline.promise}\n\n**What's inside**\n\n${toc}\n\n${sections.join('\n\n')}\n`;
}

function safeJson(s) { try { return JSON.parse(s); } catch { return null; } }
