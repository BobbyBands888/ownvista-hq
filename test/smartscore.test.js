// Smart Score: "are the agents getting smarter?" math. Pure, no network.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildScore, weekOf, ruleBreak, trendOf, METRICS, WEEKS } from '../agents/lib/smartscore.js';
import { SCHEDULE } from '../agents/router.js';
import { LANES, PROTECTED } from '../agents/lib/economy.js';

const ROOT = new URL('..', import.meta.url).pathname;
const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8');
const NOW = new Date('2026-10-01T22:00:00Z'); // Thu Oct 1, 6pm ET
const at = (day, h = 15) => `${day}T${String(h).padStart(2, '0')}:00:00Z`;

test('Weeks start on Monday, New York time', () => {
  assert.equal(weekOf(NOW), '2026-09-28');
  assert.equal(weekOf('2026-09-28T03:00:00Z'), '2026-09-21'); // Sun 11pm ET still belongs to the week before
});

test('Rule breaks use the same checks as Autopilot', () => {
  assert.match(ruleBreak({ title: 'FSBO seller checklist' }), /real estate/);
  assert.match(ruleBreak({ title: 'Pokemon sticker pack' }), /brand/);
  assert.equal(ruleBreak({ title: 'Pixel potion icons', summary: '16 icons for game devs', steps: ['make icons'] }), null);
});

test('Not enough data gives no verdict instead of a fake trend', () => {
  const s = buildScore({ ideas: [{ title: 'Icons', status: 'rejected', created_at: at('2026-09-22'), decided_at: at('2026-09-23') }] }, NOW);
  assert.equal(s.weeks.length, WEEKS);
  assert.match(s.verdict, /Not enough data/);
  const reject = s.metrics.find((m) => m.id === 'idea_reject');
  assert.equal(reject.trend.verdict, 'none');
});

test('Fewer rejections and fewer edits read as smarter', () => {
  const ideas = [], drafts = [];
  // Week of Sep 14: 6 of 6 rejected. Week of Sep 21 (last full week): 1 of 6 rejected.
  for (let i = 0; i < 6; i++) ideas.push({ title: `Icon set ${i}`, status: 'rejected', created_at: at('2026-09-15'), decided_at: at('2026-09-16') });
  for (let i = 0; i < 6; i++) ideas.push({ title: `Icon set B${i}`, status: i ? 'approved' : 'rejected', created_at: at('2026-09-22'), decided_at: at('2026-09-23') });
  for (let i = 0; i < 6; i++) drafts.push({ sent_at: at('2026-09-16'), edit_distance: 0.4 });
  for (let i = 0; i < 6; i++) drafts.push({ sent_at: at('2026-09-23'), edit_distance: 0.01 });
  const s = buildScore({ ideas, drafts }, NOW);
  const v = Object.fromEntries(s.metrics.map((m) => [m.id, m.trend.verdict]));
  assert.equal(v.idea_reject, 'better');
  assert.equal(v.email_edited, 'better');
  assert.equal(v.email_edit_size, 'better');
  assert.match(s.verdict, /^Smarter/);
});

test('Quality bar: a finish after a miss is not a first-try pass', () => {
  const productLogs = [
    { at: at('2026-09-22', 10), ref_id: 'a', message: 'Product for "A" missed the bar (thin); rewriting' },
    { at: at('2026-09-22', 11), ref_id: 'a', message: 'Finished the product for "A" (900 chars, passed the quality bar)' },
    { at: at('2026-09-23', 11), ref_id: 'b', message: 'Finished the product for "B" (900 chars, passed the quality bar)' },
  ];
  const s = buildScore({ productLogs }, NOW);
  const w = s.metrics.find((m) => m.id === 'product_first_pass').weeks.find((x) => x.week === '2026-09-21');
  assert.deepEqual([w.v, w.n], [50, 2]);
});

test('Manual ledger lines never count as agent revenue', () => {
  const s = buildScore({ ledger: [{ day: '2026-09-23', revenue: 197, source: 'manual' }, { day: '2026-09-23', revenue: 4, source: 'itch' }] }, NOW);
  const w = s.metrics.find((m) => m.id === 'revenue').weeks.find((x) => x.week === '2026-09-21');
  assert.equal(w.v, 4);
});

test('Info-only metrics never vote', () => {
  for (const m of METRICS.filter((x) => x.better === 'info')) assert.equal(trendOf(m, []).verdict, 'info');
});

test('Smart Score is wired in, protected, and makes no AI calls', () => {
  assert.ok(SCHEDULE.find((x) => x.id === 'smart_score'));
  assert.ok(LANES.growth.agents.includes('smart_score'));
  assert.ok(PROTECTED.includes('smart_score'));
  assert.match(src('agents/runner.js'), /smart_score: \(\) => import\('\.\/smart_score\.js'\)/);
  assert.match(src('.github/workflows/hq.yml'), /- smart_score\n/);
  const agent = src('agents/smart_score.js') + src('agents/lib/smartscore.js');
  assert.doesNotMatch(agent, /llm|groq|chat\(/i);
});
