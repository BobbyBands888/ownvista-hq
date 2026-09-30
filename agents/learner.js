// Learner — nightly 11pm ET. Compares drafts with what Bobby sent, turns edits, rejected
// ideas and feedback into playbook rules (dedupe; consolidate past 40), keeps version
// history, grades today's drafts, writes a self-review and the daily metrics row.
import { db, kvGet, kvSet } from './lib/db.js';
import { chat } from './lib/llm.js';
import { systemPrompt, untrusted } from './lib/guard.js';
import { playbook, resetPlaybookCache } from './lib/context.js';
import { similarTitle, truncate } from './lib/text.js';
import { etDate, etToUtc, daysAgoIso } from './lib/time.js';

const CATEGORIES = ['voice', 'growth', 'scout', 'lab', 'villa', 'guardrails'];

export async function run(ctx) {
  const pb = await playbook();
  const learned = await learnRules(ctx, pb);
  resetPlaybookCache();
  const graded = ctx.outOfTime(90000) ? 0 : await gradeAndReview(ctx);
  await writeMetrics();
  return `new rules ${learned.added}${learned.consolidated ? `, consolidated to ${learned.consolidated}` : ''}, graded ${graded}`;
}

async function learnRules(ctx, pb) {
  const [pairs, feedback, rejected] = await Promise.all([
    db.select('drafts', { status: 'eq.sent', learned_at: 'is.null', order: 'sent_at.asc', limit: 12 }),
    db.select('feedback', { consumed_at: 'is.null', order: 'created_at.asc', limit: 30 }),
    db.select('ideas', { status: 'eq.rejected', decided_at: `gte.${daysAgoIso(2)}`, limit: 15 }),
  ]);
  const edited = pairs.filter((p) => (p.edit_distance ?? 1) >= 0.05);
  const now = new Date().toISOString();
  let added = 0, consolidated = 0;

  if (edited.length || feedback.length || rejected.length) {
    const system = systemPrompt('the Learner', `
Current playbook and rules:
${pb.text(['voice', 'signoffs', 'growth', 'scout', 'lab', 'villa'])}

Study how Bobby changed the agents' drafts, and his feedback. Write NEW rules that would have made the drafts match what he sent.
Rules are short imperatives (max 25 words), specific and testable ("Answer the question in the first sentence"), never vague ("be better").
Do not restate an existing rule. Ignore one-off facts (names, dates). Categories: ${CATEGORIES.join(', ')}.
JSON only: {"rules":[{"rule":"","category":"voice","evidence":"what in the data shows this"}]}`);
    const user = [
      edited.length ? `Draft vs what Bobby sent:\n${edited.map((p, i) => `#${i} (edit distance ${p.edit_distance})\n${untrusted('agent draft', truncate(p.body, 1200))}\n${untrusted('bobby sent', truncate(p.sent_body, 1200))}`).join('\n\n')}` : '',
      feedback.length ? `Bobby's feedback:\n${feedback.map((f) => `- [${f.kind}] ${truncate(f.text, 400)}`).join('\n')}` : '',
      rejected.length ? `Ideas Bobby rejected:\n${rejected.map((r) => `- ${r.title}${r.feedback ? ` — "${truncate(r.feedback, 200)}"` : ''}`).join('\n')}` : '',
    ].filter(Boolean).join('\n\n');
    const { json } = await chat({ ctx, tier: 'smart', system, json: true, maxTokens: 1500, messages: [{ role: 'user', content: user }] });
    const existing = await db.select('playbook_rules', { active: 'eq.true', select: 'rule' });
    for (const r of (json.rules || []).slice(0, 6)) {
      const rule = truncate(String(r.rule || '').trim(), 240);
      if (!rule || existing.some((e) => similarTitle(e.rule, rule))) continue;
      await db.insertOne('playbook_rules', {
        rule, category: CATEGORIES.includes(r.category) ? r.category : 'voice', origin: 'learned', evidence: truncate(r.evidence || '', 500),
      });
      existing.push({ rule });
      added++;
    }
  }
  if (pairs.length) await db.update('drafts', { id: `in.(${pairs.map((p) => p.id).join(',')})` }, { learned_at: now });
  if (feedback.length) await db.update('feedback', { id: `in.(${feedback.map((f) => f.id).join(',')})` }, { consumed_at: now });

  const active = await db.select('playbook_rules', { active: 'eq.true', origin: 'neq.manual', order: 'created_at.asc' });
  if (active.length > 40 && !ctx.outOfTime(120000)) {
    const { json } = await chat({
      ctx, tier: 'smart', json: true, maxTokens: 2500,
      system: systemPrompt('the Learner consolidating rules', `Merge duplicates and overlapping rules into at most 30 clear rules. Keep every distinct instruction Bobby gave; drop none of his corrections' meaning.
JSON only: {"rules":[{"rule":"","category":"${CATEGORIES.join('|')}"}]}`),
      messages: [{ role: 'user', content: active.map((r) => `- [${r.category}/${r.origin}] ${r.rule}`).join('\n') }],
    });
    const merged = (json.rules || []).filter((r) => r.rule).slice(0, 30);
    if (merged.length >= 10) {
      await db.update('playbook_rules', { id: `in.(${active.map((r) => r.id).join(',')})` }, { active: false });
      await db.insert('playbook_rules', merged.map((r) => ({
        rule: truncate(r.rule, 240), category: CATEGORIES.includes(r.category) ? r.category : 'voice', origin: 'consolidated',
      })));
      consolidated = merged.length;
    }
  }

  if (added || consolidated) {
    const version = Number(await kvGet('playbook_version', 1)) + 1;
    const [sections, rules] = await Promise.all([
      db.select('playbook', {}), db.select('playbook_rules', { active: 'eq.true', select: 'rule,category,origin' }),
    ]);
    await db.insertOne('playbook_versions', {
      version, reason: `Learner: +${added} rule(s)${consolidated ? `, consolidated to ${consolidated}` : ''}`,
      snapshot: { sections: Object.fromEntries(sections.map((s) => [s.section, s.content])), rules },
    });
    await kvSet('playbook_version', version);
    ctx.log('learned', `Playbook v${version}: +${added} rule(s)${consolidated ? `, consolidated to ${consolidated}` : ''}`);
  }
  return { added, consolidated };
}

async function gradeAndReview(ctx) {
  const pb = await playbook();
  const dayStart = etToUtc(etDate(), 0, 0).toISOString();
  const drafts = await db.select('drafts', { created_at: `gte.${dayStart}`, order: 'created_at.asc', limit: 12 });
  const sentToday = await db.select('drafts', { sent_at: `gte.${dayStart}`, select: 'edit_distance' });
  const system = systemPrompt('the Learner grading the day', `${pb.text(['voice', 'signoffs', 'guardrails'])}
Grade each draft 1–5 against the playbook (5 = Bobby could send it unedited). Then write a self-review (max 150 words) the other agents will read tomorrow:
what went well, the most common mistake, and one concrete thing to do differently. Use the edit data: low edit distance = good.
JSON only: {"grades":[{"i":0,"grade":4,"note":"short"}],"self_review":""}`);
  const user = `Drafts today:\n${drafts.map((d, i) => `#${i} [${d.business}]\n${untrusted('agent draft', truncate(d.body, 1000))}`).join('\n\n') || '(no drafts today)'}
Edit distance of emails Bobby sent today: ${sentToday.map((s) => s.edit_distance).join(', ') || 'none'}`;
  const { json } = await chat({ ctx, tier: 'smart', system, json: true, maxTokens: 1500, messages: [{ role: 'user', content: user }] });
  let graded = 0;
  for (const g of json.grades || []) {
    const d = drafts[g.i];
    if (!d) continue;
    await db.update('drafts', { id: `eq.${d.id}` }, { grade: Math.max(1, Math.min(5, Number(g.grade) || 3)), grade_notes: truncate(g.note || '', 300) });
    graded++;
  }
  if (json.self_review) {
    await db.insert('self_reviews', [{ day: etDate(), text: truncate(json.self_review, 1500) }], { onConflict: 'day', merge: true });
  }
  return graded;
}

export async function writeMetrics(day = etDate()) {
  const start = etToUtc(day, 0, 0).toISOString();
  const end = new Date(Date.parse(start) + 86400000).toISOString();
  const range = [`gte.${start}`, `lt.${end}`];
  const [drafts, sent, proposed, approved, knowledge, usage, vc, spend, existing] = await Promise.all([
    db.select('drafts', { created_at: range, select: 'grade' }),
    db.select('drafts', { sent_at: range, select: 'edit_distance' }),
    db.count('ideas', { created_at: range }),
    db.count('ideas', { decided_at: range, status: 'in.(approved,launched)' }),
    db.count('knowledge', { created_at: range }),
    db.select('llm_usage', { day: `eq.${day}` }),
    db.count('vc_messages', { direction: 'eq.out', status: 'eq.sent', sent_at: range }),
    db.select('spend', { at: range, status: 'eq.charged', select: 'amount_usd' }),
    db.one('metrics_daily', { day: `eq.${day}` }),
  ]);
  const dists = sent.map((s) => s.edit_distance).filter((x) => x != null);
  const grades = drafts.map((d) => d.grade).filter((x) => x != null);
  const row = {
    day,
    drafts: drafts.length,
    sent: sent.length,
    sent_unedited: dists.filter((x) => x < 0.05).length,
    avg_edit_distance: dists.length ? +(dists.reduce((a, b) => a + b, 0) / dists.length).toFixed(4) : null,
    avg_grade: grades.length ? +(grades.reduce((a, b) => a + b, 0) / grades.length).toFixed(2) : null,
    ideas_proposed: proposed,
    ideas_approved: approved,
    knowledge_added: knowledge,
    llm_calls: usage.reduce((n, u) => n + u.requests, 0),
    tokens: usage.reduce((n, u) => n + u.tokens_in + u.tokens_out, 0),
    vc_sent: vc,
    spend_usd: +spend.reduce((n, s) => n + +s.amount_usd, 0).toFixed(2),
    actions_minutes: existing?.actions_minutes ?? 0,
  };
  await db.insert('metrics_daily', [row], { onConflict: 'day', merge: true });
  return row;
}
