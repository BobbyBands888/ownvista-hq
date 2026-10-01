// CEO Review — Sundays 8pm ET (after the Judge and the Architect). The results half of learning:
// the Learner learns from Bobby's edits and feedback; the CEO Review learns from what actually sold.
//   1. Scores every selling lane on real numbers (sales, views, revenue, days live, kills) → kv lane_scores.
//      Strategist, Scout, Analyst, Asset Studio and Product Scout read that scoreboard before proposing.
//   2. When there is real evidence (an earning lane, or items live 14+ days with no sales), writes up to 3
//      results lessons into the Playbook (category lab/growth/scout), vetted so they can never loosen a guardrail.
// It moves no money and no budgets (the Economist owns effort) and never sends, publishes or approves anything.
import { db, kvGet, kvSet } from './lib/db.js';
import { chat } from './lib/llm.js';
import { systemPrompt, untrusted } from './lib/guard.js';
import { playbook, resetPlaybookCache } from './lib/context.js';
import { similarTitle, truncate } from './lib/text.js';
import { daysAgoIso } from './lib/time.js';
import { KV_KEY as BOOKS_KEY } from './lib/books.js';
import { KV_KEY, MAX_LESSONS, laneScoreboard, hasEvidence, resultsText, vetLesson } from './lib/review.js';

export async function run(ctx) {
  const now = new Date();
  const [launches, packs, booksRaw, ledger] = await Promise.all([
    db.select('launches', { select: 'title,status,sales,revenue,price_usd,launched_at,created_at,killed_at', limit: 300 }),
    db.select('asset_packs', { select: 'title,theme,status,views,downloads,sales,revenue,price_usd,published_at,created_at', limit: 300 }),
    kvGet(BOOKS_KEY, []),
    db.select('ledger', { day: `gte.${daysAgoIso(30).slice(0, 10)}`, limit: 1000 }),
  ]);
  const books = Array.isArray(booksRaw) ? booksRaw : [];
  const board = laneScoreboard({ launches, packs, books, ledger, now });
  const at = now.toISOString();
  await kvSet(KV_KEY, { at, board, text: resultsText(board, at) });
  resetPlaybookCache();

  const summary = board.map((l) => `${l.lane} ${l.verdict}`).join(' · ');
  if (!hasEvidence(board)) {
    ctx.log('ceo_review', `Scoreboard: ${summary}. Nothing mature enough to learn from yet.`);
    return `scoreboard saved; no lessons yet (${summary})`;
  }

  const pb = await playbook();
  const existing = await db.select('playbook_rules', { active: 'eq.true', select: 'rule' });
  const killed = launches.filter((l) => l.status === 'killed').map((l) => l.title).slice(0, 10);
  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 1200,
    system: systemPrompt('the CEO Review', `${pb.text(['lab', 'guardrails'])}

You review REAL sales results across Bobby's lanes and write at most ${MAX_LESSONS} short lessons the product agents follow when
choosing what to make next. Base every lesson on the numbers given; cite them in "evidence". No lesson when the data is too thin.
Lessons only steer WHAT to make (niche, format, price band, theme, which lane to favor). Never write lessons about sending,
posting, publishing, approving, spending, ads, accounts, trading, real estate or rentals.
Rules are short imperatives (max 25 words), specific and testable. Do not restate an existing rule.
JSON only: {"lessons":[{"rule":"","category":"lab|growth|scout","evidence":"the numbers behind it"}]}`),
    messages: [{
      role: 'user',
      content: [
        untrusted('scoreboard', JSON.stringify(board), 4000),
        killed.length ? untrusted('killed offers', killed.join('; '), 1000) : '',
        `Existing rules:\n${existing.map((e) => `- ${truncate(e.rule, 160)}`).join('\n') || '(none)'}`,
      ].filter(Boolean).join('\n\n'),
    }],
  });

  let added = 0;
  for (const raw of (json.lessons || []).slice(0, MAX_LESSONS)) {
    const lesson = vetLesson(raw);
    if (!lesson || existing.some((e) => similarTitle(e.rule, lesson.rule))) continue;
    await db.insertOne('playbook_rules', { ...lesson, origin: 'learned' });
    existing.push({ rule: lesson.rule });
    added++;
  }
  if (added) {
    const version = Number(await kvGet('playbook_version', 1)) + 1;
    const [sections, rules] = await Promise.all([
      db.select('playbook', {}), db.select('playbook_rules', { active: 'eq.true', select: 'rule,category,origin' }),
    ]);
    await db.insertOne('playbook_versions', {
      version, reason: `CEO Review: +${added} results lesson(s)`,
      snapshot: { sections: Object.fromEntries(sections.map((s) => [s.section, s.content])), rules },
    });
    await kvSet('playbook_version', version);
    resetPlaybookCache();
  }
  ctx.log('ceo_review', `Scoreboard: ${summary}. ${added} new results lesson(s) in the Playbook.`);
  return `scoreboard saved, ${added} lesson(s) (${summary})`;
}
