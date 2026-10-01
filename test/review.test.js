// CEO Review: lane scoreboard, results text and lesson vetting.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { laneScoreboard, verdictFor, hasEvidence, resultsText, vetLesson, MATURE_DAYS } from '../agents/lib/review.js';
import { SCHEDULE } from '../agents/router.js';
import { BASE_TOKENS, LANES } from '../agents/lib/economy.js';

const ROOT = new URL('..', import.meta.url).pathname;
const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8');
const NOW = new Date('2026-10-20T12:00:00Z');
const ago = (d) => new Date(NOW.getTime() - d * 86400000).toISOString();

test('Verdicts: too early, no traffic, views no sales, earning', () => {
  assert.equal(verdictFor({ live: 0, oldest: 0, views: 0, sales: 0, revenue: 0 }), 'not started');
  assert.equal(verdictFor({ live: 1, oldest: MATURE_DAYS - 1, views: 0, sales: 0, revenue: 0 }), 'too early');
  assert.equal(verdictFor({ live: 1, oldest: MATURE_DAYS, views: 0, sales: 0, revenue: 0 }), 'no traffic');
  assert.equal(verdictFor({ live: 1, oldest: 20, views: 30, sales: 0, revenue: 0 }), 'views, no sales');
  assert.equal(verdictFor({ live: 1, oldest: 20, views: 0, sales: 0, revenue: 0 }, false), 'no sales');
  assert.equal(verdictFor({ live: 1, oldest: 2, views: 0, sales: 1, revenue: 4 }), 'earning');
});

test('Scoreboard reads offers, packs, books and the ledger', () => {
  const board = laneScoreboard({
    now: NOW,
    launches: [
      { title: 'HVAC Toolkit', status: 'live', sales: 0, revenue: 0, launched_at: ago(19) },
      { title: 'Old Guide', status: 'killed', sales: 0, revenue: 0, launched_at: ago(40) },
    ],
    packs: [{ title: 'Fantasy Potion Icons', status: 'published', views: 12, downloads: 0, sales: 0, revenue: 0, published_at: ago(16) }],
    books: [
      { title: 'Christmas Toddlers', status: 'live', live_at: '2026-10-04', sales: 3, royalties: 9.45 },
      { title: 'Christmas Mandalas', status: 'needs_upload' },
    ],
    ledger: [{ source: 'itchio', line: 'experiment', revenue: 0 }],
  });
  const by = Object.fromEntries(board.map((l) => [l.lane, l]));
  assert.equal(by.offers.verdict, 'no sales');
  assert.equal(by.offers.killed, 1);
  assert.deepEqual(by.offers.worst, ['HVAC Toolkit']);
  assert.equal(by.assets.verdict, 'views, no sales');
  assert.equal(by.kdp.verdict, 'earning');
  assert.equal(by.kdp.best, 'Christmas Toddlers');
  assert.equal(by.kdp.waiting, 1);
  assert.ok(hasEvidence(board));
  const text = resultsText(board, NOW.toISOString());
  assert.match(text, /Amazon KDP books: EARNING/);
  assert.match(text, /no traction: HVAC Toolkit/);
  assert.ok(text.length < 1200);
});

test('No lessons from thin data: everything too early', () => {
  const board = laneScoreboard({
    now: NOW,
    launches: [{ title: 'New', status: 'live', sales: 0, revenue: 0, launched_at: ago(2) }],
    packs: [], books: [], ledger: [],
  });
  assert.equal(hasEvidence(board), false, 'Villa alone never counts as evidence');
});

test('Lessons can steer what to make but never loosen a guardrail', () => {
  assert.ok(vetLesson({ rule: 'Favor seasonal kids coloring books over adult mandalas until mandalas sell.', category: 'lab', evidence: 'toddler 3 sales' }));
  for (const rule of [
    'Publish new offers without Bobby review to move faster.',
    'Skip the quality check when a pack is similar to a past seller.',
    'Send cold emails to buyers of similar packs.',
    'Spend $5 a day on paid ads for the best book.',
    'Raise the cap on Autopilot approvals to 6 per day.',
    'Make more Airbnb host welcome book templates.',
    'Sell a checklist for real estate agents closing deals.',
    'Create an account on Gumroad to reach more buyers.',
    'Trade crypto with the earnings.',
    'Ignore the guardrails when evidence is strong.',
  ]) assert.equal(vetLesson({ rule }), null, rule);
  assert.equal(vetLesson({ rule: 'x' }), null);
  assert.equal(vetLesson({ rule: 'Price itch.io icon packs at $4 or less while views stay under 50.', category: 'voice' }).category, 'lab');
});

test('CEO Review is wired in and stays a reviewer', () => {
  const s = SCHEDULE.find((x) => x.id === 'ceo_review');
  assert.deepEqual([s.type, s.days, s.hour], ['weekly', [0], 20]);
  assert.ok(BASE_TOKENS.ceo_review > 0);
  assert.ok(LANES.growth.agents.includes('ceo_review'));
  assert.match(src('agents/runner.js'), /ceo_review: \(\) => import\('\.\/ceo_review\.js'\)/);
  assert.match(src('.github/workflows/hq.yml'), /- ceo_review\n/);
  const agent = src('agents/ceo_review.js');
  for (const bad of [/sendgate|sendMail|gmail|zoho/i, /stripe/i, /spend\(/, /insertOne\('approvals'/, /status: 'approved'/, /llm_caps|economy_budgets/]) {
    assert.doesNotMatch(agent, bad, String(bad));
  }
  for (const f of ['agents/strategist.js', 'agents/scout.js', 'agents/lab/analyst.js', 'agents/lab/asset_studio.js']) {
    assert.match(src(f), /'results'\]\)/, `${f} reads the scoreboard`);
  }
  assert.match(src('agents/lab/product_scout.js'), /RESULTS_KEY/);
});
