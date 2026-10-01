// CEO Review rules (pure; tested in test/review.test.js).
// Scores every selling lane on real results (sales, views, revenue, days live) and vets the lessons the
// CEO Review writes into the Playbook. Lessons can only steer WHAT agents make next; they can never loosen
// a guardrail (sending, publishing, spending, accounts, trading, real estate, rentals).
import { realEstateRisk } from './guard.js';
import { ledgerLane } from './economy.js';
import { truncate } from './text.js';

export const KV_KEY = 'lane_scores';
// An item needs this many days live before "no sales" counts as a result rather than "too early".
export const MATURE_DAYS = 14;
export const MAX_LESSONS = 3;

const days = (from, now) => (from ? Math.max(0, Math.floor((now - new Date(from)) / 86400000)) : 0);
const sum = (xs, f) => xs.reduce((n, x) => n + (Number(f(x)) || 0), 0);
const r2 = (n) => Math.round(n * 100) / 100;

// verdict for one lane: not started | too early | no traffic | views, no sales | earning
export function verdictFor({ live, oldest, views, sales, revenue }, hasViews = true) {
  if (revenue > 0 || sales > 0) return 'earning';
  if (!live) return 'not started';
  if (oldest < MATURE_DAYS) return 'too early';
  if (hasViews && views > 0) return 'views, no sales';
  return hasViews ? 'no traffic' : 'no sales';
}

// launches: Launcher offers. packs: itch.io asset packs. books: kv amazon_books. ledger: rows from the last 30 days.
export function laneScoreboard({ launches = [], packs = [], books = [], ledger = [], now = new Date() }) {
  const rev30 = {};
  for (const row of ledger) {
    const lane = ledgerLane(row);
    rev30[lane] = (rev30[lane] || 0) + (Number(row.revenue) || 0);
  }
  const lanes = [];

  const liveOffers = launches.filter((l) => l.status === 'live');
  const offers = {
    lane: 'offers', name: 'Launcher offers (levelingclips.com/p)',
    live: liveOffers.length,
    killed: launches.filter((l) => l.status === 'killed').length,
    oldest: Math.max(0, ...liveOffers.map((l) => days(l.launched_at || l.created_at, now))),
    views: 0,
    sales: sum(launches, (l) => l.sales),
    revenue: r2(Math.max(sum(launches, (l) => l.revenue), rev30.offers || 0)),
    best: bestOf(launches, (l) => l.revenue, (l) => l.sales),
    worst: liveOffers.filter((l) => !Number(l.sales)).map((l) => l.title).slice(0, 3),
  };
  offers.verdict = verdictFor(offers, false);
  lanes.push(offers);

  const published = packs.filter((p) => p.status === 'published');
  const assets = {
    lane: 'assets', name: 'itch.io asset packs',
    live: published.length,
    killed: packs.filter((p) => p.status === 'killed' || p.status === 'rejected').length,
    oldest: Math.max(0, ...published.map((p) => days(p.published_at || p.created_at, now))),
    views: sum(packs, (p) => p.views),
    downloads: sum(packs, (p) => p.downloads),
    sales: sum(packs, (p) => p.sales),
    revenue: r2(Math.max(sum(packs, (p) => p.revenue), rev30.assets || 0)),
    best: bestOf(published, (p) => p.revenue, (p) => p.views),
    worst: published.filter((p) => !Number(p.views)).map((p) => p.title).slice(0, 3),
  };
  assets.verdict = verdictFor(assets, true);
  lanes.push(assets);

  const liveBooks = books.filter((b) => b.status === 'live');
  const kdp = {
    lane: 'kdp', name: 'Amazon KDP books',
    live: liveBooks.length,
    in_review: books.filter((b) => b.status === 'in_review').length,
    waiting: books.filter((b) => ['planned', 'built', 'needs_upload', 'uploaded_draft'].includes(b.status)).length,
    oldest: Math.max(0, ...liveBooks.map((b) => days(b.live_at || b.submitted_at, now))),
    views: 0,
    sales: sum(books, (b) => b.sales),
    revenue: r2(sum(books, (b) => b.royalties)),
    best: bestOf(liveBooks, (b) => b.royalties, (b) => b.sales),
    worst: liveBooks.filter((b) => !Number(b.sales)).map((b) => b.title).slice(0, 3),
    note: 'KDP sales are entered by hand from the KDP report',
  };
  kdp.verdict = verdictFor(kdp, false);
  lanes.push(kdp);

  const villa = {
    lane: 'villa', name: 'Villa Cinema', live: 1, oldest: MATURE_DAYS, views: 0, sales: 0,
    revenue: r2(rev30.villa || 0),
  };
  villa.verdict = villa.revenue > 0 ? 'earning' : 'no sales';
  lanes.push(villa);

  return lanes;
}

function bestOf(items, primary, secondary) {
  const top = [...items].sort((a, b) => (Number(primary(b)) || 0) - (Number(primary(a)) || 0)
    || (Number(secondary(b)) || 0) - (Number(secondary(a)) || 0))[0];
  return top && ((Number(primary(top)) || 0) > 0 || (Number(secondary(top)) || 0) > 0) ? top.title : null;
}

// Is there anything real to learn from? (an earning lane, or a lane with mature items and no sales)
export function hasEvidence(board) {
  return board.some((l) => l.lane !== 'villa' && ['earning', 'views, no sales', 'no traffic', 'no sales'].includes(l.verdict));
}

// Compact block for agent prompts (Strategist, Scout, Analyst, Asset Studio, Product Scout).
export function resultsText(board, at) {
  if (!Array.isArray(board) || !board.length) return '';
  const total = r2(sum(board, (l) => l.revenue));
  const lines = board.map((l) => {
    const bits = [`${l.live} live`];
    if (l.in_review) bits.push(`${l.in_review} in review`);
    if (l.killed) bits.push(`${l.killed} killed`);
    if (l.views) bits.push(`${l.views} views`);
    bits.push(`${l.sales} sales`, `$${l.revenue}`);
    const extra = [l.best && `best: ${l.best}`, l.worst?.length && l.verdict !== 'too early' && `no traction: ${l.worst.join(', ')}`].filter(Boolean).join('; ');
    return `- ${l.name}: ${l.verdict.toUpperCase()} (${bits.join(', ')})${extra ? ` — ${truncate(extra, 160)}` : ''}`;
  });
  return `Real results so far${at ? ` (CEO Review ${String(at).slice(0, 10)})` : ''}, total revenue $${total}:\n${lines.join('\n')}\n`
    + 'Lean toward lanes that earn or get traffic. Do not repeat what got killed or had no traction.';
}

// Lessons may steer what to make; they may never loosen what agents are allowed to do.
const LOOSENING = /\b(without (bobby|review|approval|checks?)|skip(ping)? (the )?(review|approval|check|quality)|auto[- ]?(send|publish|post|approve)|send(ing|s)?|e-?mails?|e-?mailing|outreach|dms?|cold[- ]emails?|post (it |them )?(to|on)|publish (directly|automatically|without)|raise the (cap|limit)|increase the (cap|limit|budget)|spend|paid ads?|buy|purchase|ad budget|credit card|sign[- ]?up|create (an? )?account|crypto|trade|trading|stocks?|wallet|airbnb|short[- ]term rental|landlord|property manag|real estate|realtor|listing agent|ignore (the |all )?(rules?|guardrails?|playbook|limits?|caps?))\b/i;
export function vetLesson(raw) {
  const rule = truncate(String(raw?.rule || '').replace(/\s+/g, ' ').trim(), 240);
  if (rule.length < 12) return null;
  if (LOOSENING.test(rule) || realEstateRisk(rule)) return null;
  const category = ['lab', 'growth', 'scout'].includes(raw?.category) ? raw.category : 'lab';
  return { rule, category, evidence: truncate(`CEO Review: ${String(raw?.evidence || '').trim()}`, 500) };
}
