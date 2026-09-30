// Judge — Sundays 6pm ET. Reviews every running experiment against its kill metric and
// recommends scale / continue / kill with the numbers. Recommendations go to Needs you.
import { db } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt } from '../lib/guard.js';
import { playbook } from '../lib/context.js';
import { money } from '../lib/text.js';

export async function run(ctx) {
  const pb = await playbook();
  const running = await db.select('experiments', { status: 'eq.running', order: 'starts_on.asc' });
  if (!running.length) return 'no running experiments';
  let judged = 0;
  for (const x of running) {
    if (ctx.outOfTime(60000)) break;
    const rows = await db.select('ledger', { experiment_id: `eq.${x.id}` });
    const revenue = rows.reduce((n, r) => n + +r.revenue, 0);
    const cost = rows.reduce((n, r) => n + +r.cost, 0);
    const hours = rows.reduce((n, r) => n + +r.bobby_hours, 0);
    const profit = revenue - cost;
    const today = new Date().toISOString().slice(0, 10);
    const daysIn = Math.round((Date.parse(today) - Date.parse(x.starts_on)) / 86400000);
    const daysLeft = Math.round((Date.parse(x.ends_on) - Date.parse(today)) / 86400000);

    const { json } = await chat({
      ctx, tier: 'smart', json: true, maxTokens: 900,
      system: systemPrompt('the Judge in the Venture Lab', `${pb.text(['lab'])}
Judge strictly against the metrics set in advance. No attachment. If the end date passed and the pass metric is not met, recommend kill.
JSON only: {"verdict":"scale|continue|kill","reason":"2–3 sentences with the numbers"}`),
      messages: [{ role: 'user', content: `Experiment: ${x.title}
Hypothesis: ${x.hypothesis || '-'}
Pass metric: ${x.pass_metric || '-'}
Kill metric: ${x.kill_metric || '-'}
Day ${daysIn}, ${daysLeft} day(s) left (ends ${x.ends_on})
Ledger: revenue ${money(revenue)}, cost ${money(cost)}, profit ${money(profit)}, Bobby's hours ${hours}, profit/hour ${hours ? money(profit / hours) : 'n/a'}
Expected profit/hour at approval: ${x.expected_profit_per_hour ?? '?'}
Ledger notes: ${rows.map((r) => r.note).filter(Boolean).join(' | ') || '(none — Bobby has not logged results yet)'}` }],
    });
    const verdict = ['scale', 'continue', 'kill'].includes(json.verdict) ? json.verdict : 'continue';
    await db.update('experiments', { id: `eq.${x.id}` }, { verdict, judge_notes: json.reason, judged_at: new Date().toISOString() });
    if (verdict !== 'continue') {
      await db.insertOne('approvals', {
        kind: 'judge', ref_table: 'experiments', ref_id: x.id, created_by: 'judge',
        title: `Judge recommends ${verdict.toUpperCase()}: ${x.title}`, detail: json.reason,
      });
    }
    judged++;
  }
  ctx.log('judge', `Judged ${judged} experiment(s)`);
  return `judged ${judged}`;
}
