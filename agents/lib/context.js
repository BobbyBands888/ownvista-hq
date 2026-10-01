// Shared context every agent reads: playbook, learned rules, latest self-review, knowledge.
import { db, kvGet } from './db.js';
import { truncate } from './text.js';
import { KV_KEY as RESULTS_KEY } from './review.js';

export const BUSINESSES = ['nashville-buys', 'followup', 'ma-real-estate', 'clearance', 'villa-cinema', 'venture-lab'];
export const LANES = ['reselling', 'pod', 'dropshipping', 'local-services', 'b2b', 'digital'];

let cache = null;

export async function playbook() {
  if (cache) return cache;
  const [sections, rules, review, version, results] = await Promise.all([
    db.select('playbook', { order: 'sort.asc' }),
    db.select('playbook_rules', { active: 'eq.true', order: 'created_at.asc', limit: 60 }),
    db.one('self_reviews', { order: 'day.desc' }),
    kvGet('playbook_version', 1),
    kvGet(RESULTS_KEY, null).catch(() => null),
  ]);
  const by = Object.fromEntries(sections.map((s) => [s.section, s.content]));
  const rulesText = rules.map((r, i) => `${i + 1}. [${r.category}] ${r.rule}`).join('\n');
  cache = {
    by,
    rules,
    version: Number(version) || 1,
    review: review?.text || '',
    // CEO Review's weekly scoreboard of real sales by lane ('' until its first run).
    results: typeof results?.text === 'string' ? truncate(results.text, 1200) : '',
    // Compact text block for prompts. Ask for 'results' to include the scoreboard.
    text(sectionsWanted = ['voice', 'signoffs', 'guardrails', 'businesses']) {
      const parts = sectionsWanted.filter((s) => by[s]).map((s) => `## ${s}\n${by[s]}`);
      if (rulesText) parts.push(`## Learned rules (from Bobby's edits and feedback)\n${rulesText}`);
      if (sectionsWanted.includes('results') && this.results) parts.push(`## Results so far\n${this.results}`);
      if (this.review) parts.push(`## Yesterday's self-review\n${truncate(this.review, 800)}`);
      return parts.join('\n\n');
    },
  };
  return cache;
}

export function resetPlaybookCache() {
  cache = null;
}

// Top knowledge items for a query (full-text search), formatted for a prompt.
export async function knowledgeFor(query, limit = 5) {
  const q = String(query || '').replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/).filter((w) => w.length > 3).slice(0, 8).join(' or ');
  if (!q) return [];
  try {
    return await db.rpc('search_knowledge', { q, lim: limit });
  } catch {
    return [];
  }
}

export function formatKnowledge(items) {
  return items.map((k) => `- ${k.title} (${k.url}) — ${truncate(k.summary, 300)}`).join('\n');
}

export function signoff(business) {
  if (business === 'followup') return 'Bobby\nFounder & CEO, Ownvista';
  if (business === 'villa-cinema') return 'Bobby\nVilla Cinema';
  if (business === 'nashville-buys') return 'Bobby\nFounder, Nashville Buys';
  return 'Bobby\nOwnvista';
}
