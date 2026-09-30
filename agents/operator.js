// Operator — hourly, 24/7.
// Reads the Workspace inbox, drafts replies as Gmail drafts (never sends), flags what needs
// Bobby, records what Bobby actually sent, works agent tasks, builds assets for growth ideas.
import { db } from './lib/db.js';
import { GMAIL_USER } from './lib/env.js';
import { chat } from './lib/llm.js';
import { systemPrompt, untrusted, checkCopy, isAutomated } from './lib/guard.js';
import {
  gmail, simplifyMessage, bobbyAddresses, createDraft, ensureLabel, labelThread,
} from './lib/gmail.js';
import { playbook, knowledgeFor, formatKnowledge, signoff } from './lib/context.js';
import { editDistance, stripQuoted, truncate } from './lib/text.js';
import { buildAssetsFor } from './lab/builder.js';

const MAX_DRAFTS_PER_RUN = 6;

const FLAG_PATTERNS = {
  money: /\b(invoice|payment|paid|refund|charge[ds]?|wire|deposit|\$\s?\d)/i,
  contract: /\b(contract|agreement|terms and conditions|sign (the|an?) |signature|nda)\b/i,
  legal_tax: /\b(lawyer|attorney|legal|lawsuit|sue|subpoena|tax|irs|1099|w-?9)\b/i,
  complaint: /\b(complain|complaint|unhappy|disappointed|terrible|scam|fraud|bbb|refund)\b/i,
  press: /\b(reporter|journalist|press|interview|article|podcast|newsroom|editor at)\b/i,
  pricing: /\b(price|pricing|cost|how much|quote|rates?|fee)\b/i,
};

export async function run(ctx) {
  const pb = await playbook();
  const me = bobbyAddresses();
  const labels = {
    drafted: await ensureLabel('HQ/Drafted'),
    needs: await ensureLabel('HQ/Needs Bobby'),
  };

  const sent = await detectSends(ctx, me);
  const inbox = await processInbox(ctx, pb, labels, me);
  const tasks = ctx.outOfTime(120000) ? 0 : await workTasks(ctx, pb);
  const assets = ctx.outOfTime(120000) ? 0 : await growthAssets(ctx);

  return `drafts ${inbox.drafted}, flagged ${inbox.flagged}, skipped ${inbox.skipped}, Bobby sent ${sent}, tasks ${tasks}, assets ${assets}`;
}

// ---------------------------------------------------------------- sends → learning data

async function detectSends(ctx, me) {
  const open = await db.select('drafts', {
    status: 'eq.open', created_at: `gte.${new Date(Date.now() - 21 * 86400000).toISOString()}`,
    order: 'created_at.asc', limit: 40,
  });
  let found = 0;
  const byThread = new Map();
  for (const d of open) {
    if (!d.gmail_thread_id) continue;
    byThread.set(d.gmail_thread_id, [...(byThread.get(d.gmail_thread_id) || []), d]);
  }
  for (const [threadId, drafts] of byThread) {
    if (ctx.outOfTime(180000)) break;
    const thread = await gmail('GET', `/threads/${threadId}?format=full`);
    const msgs = (thread?.messages || []).map(simplifyMessage);
    for (const d of drafts) {
      const createdMs = Date.parse(d.created_at);
      const sentMsg = msgs.find((m) => m.labelIds.includes('SENT') && !m.labelIds.includes('DRAFT')
        && m.internalDate > createdMs - 60000 && me.has(m.from.email));
      if (sentMsg) {
        const body = stripQuoted(sentMsg.text);
        await db.update('drafts', { id: `eq.${d.id}` }, {
          status: 'sent', sent_body: body, sent_at: new Date(sentMsg.internalDate).toISOString(),
          edit_distance: +editDistance(d.body, body).toFixed(4),
        });
        await db.update('emails', { id: `eq.${d.email_id}` }, { status: 'handled', updated_at: new Date().toISOString() });
        found++;
      } else if (Date.now() - createdMs > 14 * 86400000) {
        const still = d.gmail_draft_id ? await gmail('GET', `/drafts/${d.gmail_draft_id}?format=minimal`) : null;
        if (!still || Date.now() - createdMs > 21 * 86400000) {
          await db.update('drafts', { id: `eq.${d.id}` }, { status: 'discarded' });
        }
      }
    }
  }
  if (found) ctx.log('sent_detected', `Recorded ${found} email(s) Bobby sent`);
  return found;
}

// ---------------------------------------------------------------- inbox

function businessFor(m) {
  const where = `${m.to} ${m.deliveredTo} ${m.headers.cc || ''}`.toLowerCase();
  return where.includes('getownvista.com') ? 'followup' : 'nashville-buys';
}

function ourAddressFor(m, me) {
  const where = `${m.to} ${m.headers.cc || ''} ${m.deliveredTo}`.toLowerCase();
  for (const a of me) if (where.includes(a)) return a;
  return GMAIL_USER();
}

async function processInbox(ctx, pb, labels, me) {
  const q = encodeURIComponent('in:inbox newer_than:3d -in:chats -category:promotions -category:social -category:forums');
  const list = await gmail('GET', `/threads?q=${q}&maxResults=30`);
  const stats = { drafted: 0, flagged: 0, skipped: 0 };
  for (const t of list?.threads || []) {
    if (stats.drafted >= MAX_DRAFTS_PER_RUN || ctx.outOfTime(150000)) break;
    try {
      await processThread(ctx, pb, labels, me, t, stats);
    } catch (e) {
      if (e.name === 'CapError') throw e;
      stats.errors = (stats.errors || 0) + 1;
      ctx.note(`thread ${t.id}: ${e.message.slice(0, 160)}`);
    }
  }
  return stats;
}

async function processThread(ctx, pb, labels, me, t, stats) {
  const existing = await db.one('emails', { gmail_thread_id: `eq.${t.id}` });
  const thread = await gmail('GET', `/threads/${t.id}?format=full`);
  const msgs = (thread?.messages || []).map(simplifyMessage).filter((m) => !m.labelIds.includes('DRAFT'));
  const last = msgs.at(-1);
  if (!last || existing?.last_message_id === last.id) return;

  const base = {
    gmail_thread_id: t.id, last_message_id: last.id, business: businessFor(last),
    to_address: ourAddressFor(last, me), from_address: last.from.email, from_name: last.from.name,
    subject: last.subject, snippet: truncate(last.text, 300), received_at: new Date(last.internalDate).toISOString(),
    updated_at: new Date().toISOString(),
  };

  if (me.has(last.from.email) || last.labelIds.includes('SENT')) {
    await upsertEmail(existing, { ...base, status: 'handled' });
    return;
  }
  const auto = isAutomated(last.headers, `${last.from.name} <${last.from.email}>`, last.subject);
  if (auto) {
    await upsertEmail(existing, { ...base, status: 'skipped', category: `automated: ${auto}` });
    stats.skipped++;
    return;
  }

  const result = await draftFor(ctx, pb, msgs, base);
  const email = await upsertEmail(existing, {
    ...base,
    status: result.draft ? 'drafted' : (result.needsBobby ? 'flagged' : 'skipped'),
    needs_bobby: result.needsBobby, flag_reason: result.reason || null, category: result.category,
  });

  if (result.draft) {
    // Older unused drafts for this thread are superseded.
    await db.update('drafts', { gmail_thread_id: `eq.${t.id}`, status: 'eq.open' }, { status: 'discarded' });
    const to = (last.replyTo?.email || last.from.email);
    const subject = /^re:/i.test(last.subject) ? last.subject : `Re: ${last.subject}`;
    const { draftId, messageId } = await createDraft({
      threadId: t.id, from: base.to_address, to, subject, body: result.draft,
      inReplyTo: last.messageId, references: last.references,
    });
    await db.insertOne('drafts', {
      email_id: email.id, gmail_thread_id: t.id, gmail_draft_id: draftId, gmail_draft_message_id: messageId,
      business: base.business, to_address: to, subject, body: result.draft, playbook_version: pb.version,
    });
    stats.drafted++;
  }
  await labelThread(t.id, [result.needsBobby ? labels.needs : labels.drafted].filter(Boolean));
  if (result.needsBobby) {
    stats.flagged++;
    ctx.log('flagged', `Needs Bobby: "${truncate(last.subject, 80)}" — ${result.reason}`, { table: 'emails', id: email.id });
  }
}

async function upsertEmail(existing, row) {
  if (existing) {
    const [u] = await db.update('emails', { id: `eq.${existing.id}` }, row);
    return u;
  }
  return db.insertOne('emails', row);
}

async function draftFor(ctx, pb, msgs, base) {
  const threadText = msgs.slice(-4).map((m) =>
    untrusted(`email from ${m.from.email} at ${new Date(m.internalDate).toISOString()}`, truncate(stripQuoted(m.text) || m.text, 2500))).join('\n\n');
  const knowledge = formatKnowledge(await knowledgeFor(`${base.subject} ${msgs.at(-1).text.slice(0, 300)}`, 3));

  const system = systemPrompt('the Operator, Bobby\'s email chief of staff', `
${pb.text()}

Your job for this thread:
1. Classify it. Flag "needs Bobby" for anything involving money, contracts, legal/tax, complaints, press, or pricing — with a one-sentence reason.
2. Unless it is spam or needs no reply, draft Bobby's reply in the playbook voice. Do NOT include a sign-off; it is added automatically.
   If it needs Bobby, still draft a short holding reply that commits to nothing (no numbers, no promises).
3. The business is "${base.business}". ${base.business === 'nashville-buys' ? 'Vendors list free; never quote prices to vendors.' : 'Follow-Up is $197 per 30-day run, invoiced only after the first ready-to-book customer. Only state that if they ask how pricing works.'}

Reply with JSON only:
{"category":"lead|customer|vendor|partner|press|support|personal|spam|other",
 "audience":"vendor|seller|buyer|contractor|customer|press|other",
 "flags":["money"|"contract"|"legal_tax"|"complaint"|"press"|"pricing"],
 "needs_bobby":true|false,
 "reason":"why Bobby must look, or empty",
 "should_draft":true|false,
 "draft":"reply body, plain text, no sign-off"}`);

  const user = `Our address on this thread: ${base.to_address}
Relevant knowledge (may be empty):
${knowledge || '(none)'}

Thread, oldest to newest:
${threadText}`;

  const { json } = await chat({ ctx, tier: 'smart', system, messages: [{ role: 'user', content: user }], json: true, maxTokens: 1400 });
  const allText = msgs.slice(-2).map((m) => `${m.subject}\n${m.text}`).join('\n');
  const flags = new Set(Array.isArray(json.flags) ? json.flags : []);
  for (const [k, re] of Object.entries(FLAG_PATTERNS)) if (re.test(allText)) flags.add(k);
  let needsBobby = Boolean(json.needs_bobby) || flags.size > 0;
  let reason = String(json.reason || '').trim() || (flags.size ? `Mentions ${[...flags].join(', ').replace('_', '/')}` : '');

  let draft = null;
  if (json.should_draft !== false && json.category !== 'spam' && String(json.draft || '').trim()) {
    const body = `${String(json.draft).trim()}\n\n${signoff(base.business)}`;
    const problems = checkCopy(body, { business: base.business, audience: json.audience });
    if (problems.length) {
      needsBobby = true;
      reason = `Draft blocked by guardrail (${problems.join('; ')}). ${reason}`.trim();
    } else {
      draft = body;
    }
  }
  return { draft, needsBobby, reason, category: json.category || 'other' };
}

// ---------------------------------------------------------------- agent tasks

async function workTasks(ctx, pb) {
  const tasks = await db.select('tasks', { assignee: 'eq.agent', status: 'eq.todo', order: 'created_at.asc', limit: 2 });
  let done = 0;
  for (const task of tasks) {
    if (ctx.outOfTime(120000)) break;
    await db.update('tasks', { id: `eq.${task.id}` }, { status: 'doing', updated_at: new Date().toISOString() });
    const knowledge = formatKnowledge(await knowledgeFor(`${task.title} ${task.detail || ''}`, 6));
    const system = systemPrompt('the Operator working an assigned task', `
${pb.text(['voice', 'guardrails', 'businesses', 'growth'])}

Do the task yourself as far as possible using only writing and the knowledge provided.
You cannot browse, send, sign up, pay or call. If the task needs any of those, do the prep work and say exactly what Bobby must do.
If an email would help, write it as "email_draft" (it becomes a Gmail draft with no recipient; Bobby decides whether to send).
JSON only: {"result":"markdown deliverable","email_draft":{"subject":"","body":""}|null,"status":"done"|"blocked","blocked_reason":""}`);
    try {
      const { json } = await chat({
        ctx, tier: 'smart', system, json: true, maxTokens: 2200,
        messages: [{ role: 'user', content: `Task: ${task.title}\nBusiness: ${task.business || 'any'}\nDetail: ${task.detail || '(none)'}\n\nKnowledge:\n${knowledge || '(none)'}` }],
      });
      let result = String(json.result || '').trim();
      if (json.email_draft?.body) {
        const body = `${json.email_draft.body.trim()}\n\n${signoff(task.business)}`;
        const problems = checkCopy(body, { business: task.business });
        if (problems.length) {
          result += `\n\n_Email draft withheld by guardrail: ${problems.join('; ')}_`;
        } else {
          const from = task.business === 'followup' ? 'hello@getownvista.com' : GMAIL_USER();
          const { draftId } = await createDraft({ from, to: '', subject: json.email_draft.subject || task.title, body });
          result += `\n\n_Gmail draft created (no recipient): ${json.email_draft.subject || task.title}_ [${draftId}]`;
        }
      }
      const status = json.status === 'blocked' ? 'blocked' : 'done';
      await db.update('tasks', { id: `eq.${task.id}` }, {
        status, result: `${result}${json.blocked_reason ? `\n\n**Blocked:** ${json.blocked_reason}` : ''}`,
        updated_at: new Date().toISOString(),
      });
      ctx.log('task', `${status === 'done' ? 'Finished' : 'Blocked on'} task "${task.title}"`, { table: 'tasks', id: task.id });
      done++;
    } catch (e) {
      await db.update('tasks', { id: `eq.${task.id}` }, { status: 'todo' });
      throw e;
    }
  }
  return done;
}

async function growthAssets(ctx) {
  const idea = await db.one('ideas', { kind: 'eq.growth', status: 'eq.approved', assets_built_at: 'is.null', order: 'decided_at.asc' });
  if (!idea) return 0;
  return buildAssetsFor(ctx, idea);
}
