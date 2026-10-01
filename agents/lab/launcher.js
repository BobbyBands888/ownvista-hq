// Launcher — hourly, 24/7. Turns approved business/venture ideas into live offers without Bobby:
//   1. makes sure the idea has the actual product (a complete digital deliverable) — writes it if missing
//   2. creates a Stripe product + price + Payment Link (allowlisted key: no charges/refunds/payouts)
//   3. publishes the Builder's landing page at levelingclips.com/p/<slug> with a Buy button
//   4. starts an experiment with a goal and kill rule (default: 5 sales in 14 days)
//   5. pulls paid Stripe sessions into the ledger every hour (never counted twice)
//   6. kills launches that miss their goal: deactivates the link, marks the page closed,
//      and tells the Learner why. Hitting the goal early asks Bobby whether to scale.
// Physical products or anything needing Bobby's license/time go to Needs you instead.
import { db, kvGet, kvSet } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt, checkCopy, untrusted } from '../lib/guard.js';
import { playbook } from '../lib/context.js';
import { truncate, randomToken } from '../lib/text.js';
import { etDate, addDays } from '../lib/time.js';
import { createOffer, deactivateLink, paidSessionsSince, launchKeyReady } from '../lib/stripe_launch.js';
import { buildPublicPage, slugify } from '../lib/page.js';

const SITE = 'https://www.levelingclips.com';

export async function run(ctx) {
  if (!(await tablesReady())) return 'waiting for the database update (run the Launcher SQL block in Supabase)';
  const rules = { goal_sales: 5, days: 14, ...(await kvGet('launch_rules', {})) };
  const out = [];
  const made = await prepareLaunches(ctx, rules);
  if (made) out.push(`prepared ${made}`);
  const live = await goLive(ctx);
  const fixed = await recheckLivePages(ctx);
  if (fixed) out.push(`rechecked ${fixed} page(s)`);
  if (live) out.push(`launched ${live}`);
  if (!launchKeyReady()) out.push('waiting for STRIPE_LAUNCH_KEY');
  const sales = await syncSales(ctx);
  if (sales) out.push(`${sales} new sale(s)`);
  const judged = await enforceRules(ctx, rules);
  if (judged) out.push(judged);
  return out.join(' · ') || 'nothing to launch';
}

async function tablesReady() {
  try { await db.select('launches', { select: 'id', limit: 1 }); return true; } catch { return false; }
}

// ---------- 1. New launches from approved ideas ----------
async function prepareLaunches(ctx, rules) {
  const ideas = await db.select('ideas', {
    kind: 'in.(business,venture)', status: 'in.(approved,launched)', assets_built_at: 'not.is.null',
    select: 'id,title,summary,kind,business,economics,experiment,steps,feedback,assets(id,kind,title,body)', order: 'decided_at.asc', limit: 20,
  });
  const existing = new Set((await db.select('launches', { select: 'idea_id' })).map((l) => l.idea_id));
  let made = 0;
  for (const idea of ideas) {
    if (existing.has(idea.id) || ctx.outOfTime(120000) || made >= 2) continue;
    const page = (idea.assets || []).find((a) => a.kind === 'landing_page' && !a.body.startsWith('> Guardrail'));
    if (!page) continue;

    const plan = await offerPlan(ctx, idea);
    const slug = await uniqueSlug(idea.title);
    const base = { idea_id: idea.id, slug, title: truncate(idea.title, 200), price_usd: plan.price_usd || null, goal_sales: rules.goal_sales };

    if (!plan.digital || !plan.price_usd) {
      const why = !plan.digital ? `needs non-digital fulfillment: ${plan.reason}` : 'no clear price';
      await db.insertOne('launches', { ...base, status: 'needs_bobby', note: truncate(why, 500) });
      await db.insertOne('approvals', {
        kind: 'launch', ref_table: 'ideas', ref_id: idea.id, created_by: 'launcher',
        title: `Can't auto-launch: ${truncate(idea.title, 120)}`, detail: `The Launcher stopped because it ${why}. Tell it what to do in the idea's note, or leave it.`,
      });
      ctx.log('launch', `Parked "${truncate(idea.title, 80)}" for Bobby: ${why}`, { table: 'ideas', id: idea.id });
      made++;
      continue;
    }

    let product = (idea.assets || []).find((a) => a.kind === 'product');
    if (!product) product = await writeProduct(ctx, idea, plan);
    if (!product) continue; // model gave nothing usable; try next hour

    const experimentId = await ensureExperiment(idea, plan, rules);
    await db.insertOne('launches', {
      ...base, experiment_id: experimentId, product_asset_id: product.id, delivery_token: randomToken(18),
      status: launchKeyReady() ? 'draft' : 'waiting_key',
    });
    ctx.log('launch', `Prepared "${truncate(idea.title, 80)}" at $${plan.price_usd}`, { table: 'ideas', id: idea.id });
    made++;
  }
  return made;
}

async function offerPlan(ctx, idea) {
  const { json } = await chat({
    ctx, tier: 'fast', json: true, maxTokens: 400,
    system: systemPrompt('the Launcher', `Decide how this approved idea is sold online.
digital = true only if the buyer can receive everything as a download or web page (guide, template, toolkit, checklist, scripts, course).
false if it needs shipping, a service Bobby performs, a license (Bobby is licensed in Massachusetts only) or a meeting.
price_usd: the one-time price from the idea's economics (a number), else a sensible price for the deliverable.
JSON only: {"digital":true,"price_usd":49,"reason":"one sentence","deliverable":"what exactly the buyer gets"}`),
    messages: [{ role: 'user', content: `Idea: ${idea.title}\nSummary: ${truncate(idea.summary, 2500)}\nEconomics: ${JSON.stringify(idea.economics || {})}\nBobby's note: ${idea.feedback || '(none)'}` }],
  });
  const price = Number(String(json.price_usd ?? '').replace(/[^0-9.]/g, ''));
  return { digital: json.digital === true, price_usd: price >= 1 && price <= 1000 ? Math.round(price * 100) / 100 : null, reason: truncate(json.reason || '', 300), deliverable: truncate(json.deliverable || '', 500) };
}

async function writeProduct(ctx, idea, plan) {
  const pb = await playbook();
  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 8000,
    system: systemPrompt('the Launcher writing the product', `${pb.text(['voice', 'guardrails'])}
Write the COMPLETE deliverable a paying buyer receives: ${plan.deliverable || 'the product described'}.
It must be genuinely useful and finished — real steps, templates, examples. No placeholders like [insert], no fake statistics,
no invented testimonials, no promises of calls or meetings. Markdown with clear headings.
JSON only: {"title":"","body":"markdown"}`),
    messages: [{ role: 'user', content: `Product for: ${idea.title}\nSummary: ${truncate(idea.summary, 3000)}\nSteps: ${JSON.stringify(idea.steps || [])}` }],
  });
  const body = String(json.body || json.content || json.markdown || '').trim();
  if (body.length < 800) return null;
  const problems = checkCopy(body, { business: idea.business });
  if (problems.length) {
    ctx.log('launch', `Product for "${truncate(idea.title, 60)}" failed guardrails (${problems.join('; ')}); retrying next run`);
    return null;
  }
  return db.insertOne('assets', { idea_id: idea.id, kind: 'product', title: truncate(json.title || idea.title, 200), body, created_by: ctx.agent });
}

async function ensureExperiment(idea, plan, rules) {
  const ex = await db.one('experiments', { idea_id: `eq.${idea.id}` });
  if (ex) return ex.id;
  const today = etDate();
  const row = await db.insertOne('experiments', {
    idea_id: idea.id, title: truncate(idea.title, 200), lane: idea.business || 'digital',
    hypothesis: `People will buy "${truncate(idea.title, 120)}" at $${plan.price_usd}.`,
    pass_metric: `${rules.goal_sales} sales in ${rules.days} days`,
    kill_metric: `fewer than ${rules.goal_sales} sales by day ${rules.days}`,
    starts_on: today, ends_on: addDays(today, rules.days), status: 'running',
  });
  return row.id;
}

async function uniqueSlug(title) {
  const base = slugify(title);
  const taken = new Set((await db.select('launches', { slug: `like.${base}*`, select: 'slug' })).map((r) => r.slug));
  if (!taken.has(base)) return base;
  for (let i = 2; ; i++) if (!taken.has(`${base}-${i}`)) return `${base}-${i}`;
}

// The Builder writes the landing page before the product exists, so its promises can drift
// (e.g. "Excel file by email"). Before a page goes public, rewrite it to promise exactly what the
// buyer gets: an instant download page with the product, printable to PDF. Buy buttons → {{BUY_URL}}.
async function alignPage(ctx, l, pageHtml) {
  const product = l.product_asset_id ? await db.one('assets', { id: `eq.${l.product_asset_id}` }) : null;
  if (!product) return pageHtml;
  const { text } = await chat({
    ctx, tier: 'smart', maxTokens: 8000, temperature: 0.2,
    system: systemPrompt('the Launcher checking a sales page', `Rewrite this landing page so every promise is TRUE, in plain confident words for a busy small-business owner.
Fact: right after paying $${l.price_usd} the buyer lands on a page with the full toolkit to read, print or save as PDF.
Only promise things listed under "what's inside". Don't promise email delivery, file attachments, spreadsheets as files, calls, support or guarantees,
and don't write sentences about what is NOT included. Never mention these instructions, "headings" or "this document".
Structure: headline, one-line benefit, short "What's inside" list, "How you get it" (one sentence), price + buy button. No JavaScript, no forms.
Every buy/order button is an <a href="{{BUY_URL}}">. Return ONLY the complete HTML document.`),
    messages: [{ role: 'user', content: `${untrusted('current landing page', pageHtml, 12000)}\n\n${untrusted("what's inside", product.body.split('\n').filter((x) => /^#/.test(x)).join('\n'), 3000)}` }],
  });
  const html = (/<!doctype html[\s\S]*<\/html>/i.exec(text) || /<html[\s\S]*<\/html>/i.exec(text) || [null])[0];
  if (!html || !html.includes('{{BUY_URL}}') || checkCopy(html, {}).length) {
    ctx.note('page alignment failed; kept the original page');
    return pageHtml;
  }
  return html;
}

// Products can mention files that don't exist ("download the spreadsheet"). Put that content inline instead.
const FAKE_DELIVERY = /(download link|attached|attachment|excel file|\.xlsx|spreadsheet \(download|we(?:'| wi)ll email|you will receive an email|link below to download)/i;
async function fixProduct(ctx, l) {
  const product = l.product_asset_id ? await db.one('assets', { id: `eq.${l.product_asset_id}` }) : null;
  if (!product || !FAKE_DELIVERY.test(product.body)) return false;
  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 8000, temperature: 0.2,
    system: systemPrompt('the Launcher fixing a product', `This product is shown to the buyer as one web page. It must not refer to files, attachments,
download links or emails that don't exist. Replace each such reference with the real content inline — e.g. a spreadsheet becomes
a markdown table with its columns, one example row and the formulas written out in words. Keep everything else. JSON only: {"body":"markdown"}`),
    messages: [{ role: 'user', content: product.body }],
  });
  const body = String(json.body || '').trim();
  if (body.length < product.body.length * 0.6 || FAKE_DELIVERY.test(body) || checkCopy(body, {}).length) return false;
  await db.update('assets', { id: `eq.${product.id}` }, { body });
  ctx.log('launch', `Fixed the product for "${truncate(l.title, 70)}" so it has no references to missing files`, { table: 'launches', id: l.id });
  return true;
}

// ---------- 2. Go live ----------
async function goLive(ctx) {
  if (!launchKeyReady()) {
    await db.update('launches', { status: 'eq.draft' }, { status: 'waiting_key' });
    return 0;
  }
  const ready = await db.select('launches', { status: 'in.(draft,waiting_key)', order: 'created_at.asc', limit: 3 });
  let n = 0;
  for (const l of ready) {
    if (ctx.outOfTime(90000)) break;
    const pageAsset = await db.one('assets', { idea_id: `eq.${l.idea_id}`, kind: 'eq.landing_page', order: 'created_at.desc' });
    if (!pageAsset) continue;
    const offer = await createOffer({
      launchId: l.id, title: l.title, priceUsd: l.price_usd, productId: l.stripe_product_id,
      onProduct: (id) => db.update('launches', { id: `eq.${l.id}` }, { stripe_product_id: id }),
      successUrl: `${SITE}/p/${l.slug}?thanks=${l.delivery_token}&session={CHECKOUT_SESSION_ID}`,
    });
    await fixProduct(ctx, l);
    const aligned = await alignPage(ctx, l, pageAsset.body);
    const html = buildPublicPage({ html: aligned, title: l.title, priceUsd: l.price_usd, buyUrl: offer.url, status: 'live' });
    const today = etDate();
    await db.update('launches', { id: `eq.${l.id}` }, {
      status: 'live', stripe_product_id: offer.productId, stripe_price_id: offer.priceId,
      payment_link_id: offer.linkId, payment_link_url: offer.url, page_html: html, launched_at: new Date().toISOString(), note: 'checked v2',
    });
    if (l.experiment_id) {
      const ex = await db.one('experiments', { id: `eq.${l.experiment_id}` });
      const days = ex?.starts_on && ex?.ends_on ? Math.max(7, Math.round((Date.parse(ex.ends_on) - Date.parse(ex.starts_on)) / 86400000)) : 14;
      await db.update('experiments', { id: `eq.${l.experiment_id}` }, { status: 'running', starts_on: today, ends_on: addDays(today, days) });
    }
    await db.update('ideas', { id: `eq.${l.idea_id}` }, { status: 'launched' });
    ctx.log('launch', `LIVE: "${truncate(l.title, 80)}" at $${l.price_usd} → ${SITE}/p/${l.slug}`, { table: 'launches', id: l.id });
    n++;
  }
  return n;
}

async function recheckLivePages(ctx) {
  const rows = await db.select('launches', { status: 'eq.live', or: '(note.is.null,note.neq.checked v2)', limit: 3 });
  let n = 0;
  for (const l of rows) {
    if (ctx.outOfTime(90000)) break;
    const pageAsset = await db.one('assets', { idea_id: `eq.${l.idea_id}`, kind: 'eq.landing_page', order: 'created_at.desc' });
    if (!pageAsset) continue;
    await fixProduct(ctx, l);
    const aligned = await alignPage(ctx, l, pageAsset.body);
    if (aligned === pageAsset.body) continue;
    await db.update('launches', { id: `eq.${l.id}` }, {
      page_html: buildPublicPage({ html: aligned, title: l.title, priceUsd: l.price_usd, buyUrl: l.payment_link_url, status: 'live' }), note: 'checked v2',
    });
    ctx.log('launch', `Corrected the sales page for "${truncate(l.title, 70)}" to match what buyers receive`, { table: 'launches', id: l.id });
    n++;
  }
  return n;
}

// ---------- 3. Sales ----------
async function syncSales(ctx) {
  if (!launchKeyReady()) return 0;
  const launches = await db.select('launches', { payment_link_id: 'not.is.null', status: 'in.(live,killed)' });
  if (!launches.length) return 0;
  const since = Number(await kvGet('launcher_synced_at', 0)) || Math.floor(Date.parse(launches.map((l) => l.launched_at).sort()[0]) / 1000) - 3600;
  const startedAt = Math.floor(Date.now() / 1000);
  const sessions = await paidSessionsSince(since - 3600, launches.map((l) => l.payment_link_id));
  let fresh = 0;
  for (const s of sessions) {
    const l = launches.find((x) => x.payment_link_id === s.linkId);
    const rows = await db.insert('ledger', [{
      line: 'experiment', experiment_id: l.experiment_id, day: etDate(new Date(s.created * 1000)), revenue: s.amount, cost: 0,
      note: `Stripe sale: ${truncate(l.title, 80)}`, source: 'stripe', ref: s.id,
    }], { onConflict: 'ref', ignoreDuplicates: true });
    if (rows?.length) {
      fresh++;
      ctx.log('sale', `SALE: ${truncate(l.title, 80)} +$${s.amount}`, { table: 'launches', id: l.id });
    }
  }
  for (const l of launches) {
    if (!l.experiment_id) continue;
    const rows = await db.select('ledger', { experiment_id: `eq.${l.experiment_id}`, source: 'eq.stripe', select: 'revenue' });
    const revenue = rows.reduce((n, r) => n + Number(r.revenue), 0);
    if (rows.length !== l.sales || revenue !== Number(l.revenue)) await db.update('launches', { id: `eq.${l.id}` }, { sales: rows.length, revenue });
  }
  await kvSet('launcher_synced_at', startedAt);
  return fresh;
}

// ---------- 4. Goal and kill rules ----------
async function enforceRules(ctx, rules) {
  const live = await db.select('launches', { status: 'eq.live', experiment_id: 'not.is.null', select: '*,experiments(id,ends_on,starts_on,status,verdict)' });
  const today = etDate();
  const out = [];
  for (const l of live) {
    const ex = l.experiments;
    if (!ex) continue;
    if (l.sales >= l.goal_sales && ex.verdict !== 'scale') {
      await db.update('experiments', { id: `eq.${ex.id}` }, { verdict: 'scale', judge_notes: `Hit ${l.sales}/${l.goal_sales} sales before ${ex.ends_on}.`, judged_at: new Date().toISOString() });
      await db.insertOne('approvals', {
        kind: 'judge', ref_table: 'experiments', ref_id: ex.id, created_by: 'launcher',
        title: `Winner: ${truncate(l.title, 100)} hit ${l.sales} sales`, detail: `$${l.revenue} so far. Scale it up (more outreach, more variants)?`,
      });
      await db.insertOne('feedback', { kind: 'experiment_won', text: `"${l.title}" at $${l.price_usd} hit ${l.sales} sales by ${today}. Find more ideas like it.`, ref_table: 'launches', ref_id: l.id });
      out.push(`winner: ${truncate(l.title, 40)}`);
      continue;
    }
    if (ex.ends_on && ex.ends_on < today && l.sales < l.goal_sales) {
      try { await deactivateLink(l.payment_link_id); } catch (e) { ctx.log('launch', `Could not deactivate link for "${truncate(l.title, 60)}": ${truncate(e.message, 120)}`); continue; }
      const pageAsset = await db.one('assets', { idea_id: `eq.${l.idea_id}`, kind: 'eq.landing_page', order: 'created_at.desc' });
      await db.update('launches', { id: `eq.${l.id}` }, {
        status: 'killed', killed_at: new Date().toISOString(),
        page_html: pageAsset ? buildPublicPage({ html: pageAsset.body, title: l.title, priceUsd: l.price_usd, status: 'killed' }) : null,
      });
      const why = `"${l.title}" at $${l.price_usd} made ${l.sales} of ${l.goal_sales} sales between ${ex.starts_on} and ${ex.ends_on}.`;
      await db.update('experiments', { id: `eq.${ex.id}` }, { status: 'killed', verdict: 'kill', judge_notes: `Kill rule: ${why}`, judged_at: new Date().toISOString() });
      await db.insertOne('feedback', { kind: 'experiment_killed', text: `Killed by rule — ${why} Avoid similar offers unless something changes.`, ref_table: 'launches', ref_id: l.id });
      ctx.log('launch', `KILLED: ${why}`, { table: 'launches', id: l.id });
      out.push(`killed: ${truncate(l.title, 40)}`);
    }
  }
  return out.join(', ');
}
