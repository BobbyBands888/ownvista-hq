// Autopilot — Bobby's decision (Oct 1, 2026): new ideas go live without waiting for his OK.
// It approves proposed ideas on his behalf so the existing guarded pipeline takes them the rest of the way:
//   approved business/venture idea → Builder (assets) → Launcher (finished product, quality bar, Stripe link,
//   live page at levelingclips.com/p/<slug>, 14-day kill rule) ; approved growth idea → assets/Gmail drafts.
// What it still refuses (each is a code check, not a prompt):
//   - copy that fails checkCopy (phone offers, advice, cross-mentions)
//   - brand/character/celebrity names (selling those is IP infringement and gets listings and accounts pulled)
//   - Massachusetts real estate (license rules) and Villa Cinema (its email handling needs Bobby's OK)
//   - more than max_per_day approvals (Builder/Launcher work on Groq's free limits) or business ideas below min_score
// Pause it from the Radar page (kv autopilot.enabled = false). Approving never sends, spends or signs up.
import { db, kvGet } from './db.js';
import { checkCopy, realEstateRisk } from './guard.js';
import { truncate } from './text.js';
import { daysAgoIso, etToUtc, etDate } from './time.js';

// Hard pause set by Bobby (Oct 1, 2026, 9am) while the real-estate filter and daily cap were fixed.
// Overrides the kv switch. Set back to false only when Bobby says to unpause.
export const HARD_PAUSE = false; // unpaused by Bobby Oct 1, 9:22am, with the 3/day cap below

// Hard ceiling while Bobby reviews the first day after the fixes; kv can lower it, never raise it.
export const HARD_MAX_PER_DAY = 3;

export const DEFAULTS = { enabled: true, max_per_day: 3, min_score: 50, skip_businesses: ['ma-real-estate', 'nashville-buys', 'villa-cinema'] };

// Names of brands, characters and celebrities that must never be in a product we sell.
const IP = /\b(disney|marvel|pixar|star ?wars|pok[eé]mon|nintendo|mario|zelda|harry potter|hogwarts|barbie|lego|minecraft|roblox|fortnite|nfl|nba|mlb|nhl|fifa|taylor swift|beyonc[eé]|nike|adidas|gucci|louis vuitton|chanel|coca[- ]?cola|sanrio|hello kitty|bluey|peppa|paw patrol|sesame street|looney tunes|dr\.? seuss|grinch|snoopy|peanuts|hasbro|mattel|rolex|apple watch|iphone|stanley cup|yeti|labubu|squishmallow|sonic|spongebob|scooby|batman|superman|spider-?man|avengers|frozen|elsa|mickey|minnie|winnie the pooh|stitch|moana|encanto|wednesday addams|stranger things|game of thrones|lord of the rings|tolkien|anime character)\b/i;

export function ipRisk(text = '') {
  const m = IP.exec(String(text));
  return m ? m[0] : null;
}

// Pure: should this idea be auto-approved? Returns null (yes) or the reason it's skipped.
export function skipReason(idea, rules = DEFAULTS) {
  const text = [idea.title, idea.summary, ...(idea.steps || [])].filter(Boolean).join('\n');
  if ((rules.skip_businesses || []).includes(idea.business)) return `${idea.business} stays with Bobby`;
  const re = realEstateRisk(text);
  if (re) return `touches real estate ("${re}") — never auto-approved`;
  const ip = ipRisk(text);
  if (ip) return `uses a protected brand/character ("${ip}")`;
  const problems = checkCopy(text, { business: idea.business });
  if (problems.length) return problems.join('; ');
  if (idea.kind !== 'growth' && idea.score != null && idea.score < rules.min_score) return `score ${idea.score} < ${rules.min_score}`;
  return null;
}

export async function rules() {
  return { ...DEFAULTS, ...(await kvGet('autopilot', {})) };
}

export async function autoApprove(ctx) {
  const r = await rules();
  if (HARD_PAUSE) return 'paused (hard pause in code)';
  if (r.enabled === false) return 'paused (Radar page)';
  const dayStart = etToUtc(etDate(), 0, 0).toISOString();
  let today;
  try {
    today = await db.count('activity', { agent: 'eq.autopilot', kind: 'eq.autopilot', at: `gte.${dayStart}` });
  } catch (e) {
    return `could not count today's approvals (${truncate(e.message, 80)}) — approving nothing`;
  }
  const cap = Math.min(Number(r.max_per_day) || HARD_MAX_PER_DAY, HARD_MAX_PER_DAY);
  let left = Math.max(0, cap - today);
  if (!left) return `daily limit reached (${cap})`;
  const ideas = await db.select('ideas', {
    status: 'eq.proposed', created_at: `gte.${daysAgoIso(14)}`, order: 'score.desc.nullslast,created_at.asc', limit: 40,
    select: 'id,kind,business,title,summary,steps,score,created_by',
  });
  const approved = [], skipped = [];
  for (const idea of ideas) {
    if (!left) break;
    const why = skipReason(idea, r);
    if (why) { skipped.push(why); continue; }
    const now = new Date().toISOString();
    const rows = await db.update('ideas', { id: `eq.${idea.id}`, status: 'eq.proposed' }, { status: 'approved', decided_at: now });
    if (!rows?.length) continue;
    left--;
    approved.push(idea.title);
    await ctx.log('autopilot', `Auto-approved ${idea.kind} idea "${truncate(idea.title, 120)}" (from ${idea.created_by || 'an agent'}${idea.score != null ? `, score ${idea.score}` : ''}) → ${idea.kind === 'growth' ? 'assets' : 'Builder → Launcher'}`, { table: 'ideas', id: idea.id });
  }
  if (!approved.length && !skipped.length) return 'no new ideas';
  return `approved ${approved.length}${skipped.length ? `, skipped ${skipped.length} (${truncate([...new Set(skipped)].join('; '), 160)})` : ''}`;
}
