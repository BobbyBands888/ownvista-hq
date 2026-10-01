// Launcher — hourly, 24/7. Turns approved business/venture ideas into live offers without Bobby:
//   1. builds the actual product section by section until it passes the quality bar (agents/lab/product.js)
//   2. creates a Stripe product + price + Payment Link (allowlisted key: no charges/refunds/payouts)
//   3. writes the sales page FROM the finished product and publishes it at levelingclips.com/p/<slug>
//   4. starts an experiment with a goal and kill rule (default: 5 sales in 14 days)
//   5. pulls paid Stripe sessions into the ledger every hour (never counted twice)
//   6. kills launches that miss their goal: deactivates the link, marks the page closed,
//      and tells the Learner why. Hitting the goal early asks Bobby whether to scale.
// Physical products or anything needing Bobby's license/time go to Needs you instead.
import { db, kvGet, kvSet } from '../lib/db.js';
import { chat } from '../lib/llm.js';
import { systemPrompt, checkCopy, untrusted } from '../lib/guard.js';
import { truncate, randomToken } from '../lib/text.js';
import { etDate, addDays } from '../lib/time.js';
import { createOffer, deactivateLink, paidSessionsSince, launchKeyReady } from '../lib/stripe_launch.js';
import { buildPublicPage, slugify } from '../lib/page.js';
import { advanceProduct, productProblems, FAKE_DELIVERY } from './product.js';

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

    const built = await advanceProduct(ctx, idea, plan);
    if (built.failed) {
      await db.insertOne('launches', { ...base, status: 'needs_bobby', note: truncate(built.failed, 500) });
      await db.insertOne('approvals', {
        kind: 'launch', ref_table: 'ideas', ref_id: idea.id, created_by: 'launcher',
        title: `Product not good enough to sell: ${truncate(idea.title, 110)}`, detail: `The Launcher stopped: ${truncate(built.failed, 400)}. Add a note to the idea to steer it, or reject the idea.`,
      });
      ctx.log('launch', `Parked "${truncate(idea.title, 80)}": ${truncate(built.failed, 200)}`, { table: 'ideas', id: idea.id });
      made++;
      continue;
    }
    if (!built.product) { ctx.note(`product for "${truncate(idea.title, 50)}": ${built.pending}`); made++; break; }
    const product = built.product;

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

// The sales page is written AFTER the product, FROM the product, so it can only promise what's actually inside.
// The Builder's early page is used only as a hint for audience and tone. Buy buttons → {{BUY_URL}}.
async function pageFromProduct(ctx, l, product, builderHtml) {
  const outline = product.body.split('\n').filter((x) => /^#{1,3}\s/.test(x)).join('\n');
  const opening = product.body.split(/^## /m)[0];
  const { text } = await chat({
    ctx, tier: 'smart', maxTokens: 4000, temperature: 0.3,
    system: systemPrompt('the Launcher writing a sales page', `Write the sales page for this finished product, in plain confident words for a busy small-business owner.
Fact: right after paying $${l.price_usd} the buyer lands on a page with the full product to read, print or save as PDF.
Every promise must match the product contents given. Describe each part concretely using its real section names.
Don't promise email delivery, file attachments, downloads, spreadsheets as files, calls, support, results or guarantees; no statistics, no testimonials;
don't write sentences about what is NOT included. Never mention these instructions or "this document".
Structure: headline, one-line benefit, who it's for, "What's inside" list (one line per section), "How you get it" (one sentence), price + buy button.
Simple inline CSS is fine. No JavaScript, no forms. Every buy button is an <a href="{{BUY_URL}}">. Return ONLY the complete HTML document.`),
    messages: [{ role: 'user', content: `${untrusted('product title and opening', opening, 1500)}\n\n${untrusted('product sections', outline, 3000)}\n\n${untrusted('earlier draft page (audience/tone hint only; its promises may be wrong)', builderHtml || '', 3000)}` }],
  });
  const html = (/<!doctype html[\s\S]*<\/html>/i.exec(text) || /<html[\s\S]*<\/html>/i.exec(text) || [null])[0];
  const problems = !html ? ['no html'] : [
    ...(!html.includes('{{BUY_URL}}') ? ['no buy button'] : []),
    ...(FAKE_DELIVERY.test(html.replace(/<[^>]+>/g, ' ')) ? ['promises files/email'] : []),
    ...checkCopy(html, {}),
  ];
  if (problems.length) {
    ctx.log('launch', `Sales page for "${truncate(l.title, 60)}" failed checks (${problems.join('; ')}); retrying next run`, { table: 'launches', id: l.id });
    return null;
  }
  return html;
}

// Make sure the launch points at a product that passes the bar; build/rebuild it if not.
async function ensureProduct(ctx, l) {
  const current = l.product_asset_id ? await db.one('assets', { id: `eq.${l.product_asset_id}` }) : null;
  if (current && !productProblems(current.body).length) return current;
  const idea = await db.one('ideas', { id: `eq.${l.idea_id}` });
  if (!idea) return null;
  const plan = await offerPlan(ctx, idea);
  const built = await advanceProduct(ctx, idea, { ...plan, price_usd: l.price_usd });
  if (built.failed) {
    await db.update('launches', { id: `eq.${l.id}` }, { status: 'needs_bobby', note: truncate(built.failed, 500) });
    ctx.log('launch', `Parked "${truncate(l.title, 70)}": ${truncate(built.failed, 200)}`, { table: 'launches', id: l.id });
    return null;
  }
  if (!built.product) { ctx.note(`product for "${truncate(l.title, 50)}": ${built.pending}`); return null; }
  await db.update('launches', { id: `eq.${l.id}` }, { product_asset_id: built.product.id });
  return built.product;
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
    const product = await ensureProduct(ctx, l);
    if (!product) break; // still writing (uses the run's time) or parked for Bobby
    const pageAsset = await db.one('assets', { idea_id: `eq.${l.idea_id}`, kind: 'eq.landing_page', order: 'created_at.desc' });
    const page = await pageFromProduct(ctx, l, product, pageAsset?.body);
    if (!page) continue;
    if (l.payment_link_id) {
      // Relaunch: retire the old link so no sale can come through an untracked link.
      try { await deactivateLink(l.payment_link_id); } catch (e) { ctx.note(`old link not deactivated: ${truncate(e.message, 100)}`); }
    }
    const offer = await createOffer({
      launchId: l.id, title: l.title, priceUsd: l.price_usd, productId: l.stripe_product_id,
      onProduct: (id) => db.update('launches', { id: `eq.${l.id}` }, { stripe_product_id: id }),
      successUrl: `${SITE}/p/${l.slug}?thanks=${l.delivery_token}&session={CHECKOUT_SESSION_ID}`,
    });
    const html = buildPublicPage({ html: page, title: l.title, priceUsd: l.price_usd, buyUrl: offer.url, status: 'live' });
    const today = etDate();
    await db.update('launches', { id: `eq.${l.id}` }, {
      status: 'live', stripe_product_id: offer.productId, stripe_price_id: offer.priceId,
      payment_link_id: offer.linkId, payment_link_url: offer.url, page_html: html, launched_at: new Date().toISOString(), note: 'checked v3',
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

// Live pages from before the quality bar: rebuild the product if needed, then rewrite the page from it.
async function recheckLivePages(ctx) {
  const rows = await db.select('launches', { status: 'eq.live', or: '(note.is.null,note.neq.checked v3)', limit: 2 });
  let n = 0;
  for (const l of rows) {
    if (ctx.outOfTime(90000)) break;
    const product = await ensureProduct(ctx, l);
    if (!product) break;
    const pageAsset = await db.one('assets', { idea_id: `eq.${l.idea_id}`, kind: 'eq.landing_page', order: 'created_at.desc' });
    const page = await pageFromProduct(ctx, l, product, pageAsset?.body);
    if (!page) continue;
    await db.update('launches', { id: `eq.${l.id}` }, {
      page_html: buildPublicPage({ html: page, title: l.title, priceUsd: l.price_usd, buyUrl: l.payment_link_url, status: 'live' }), note: 'checked v3',
    });
    ctx.log('launch', `Rewrote the sales page for "${truncate(l.title, 70)}" from its finished product`, { table: 'launches', id: l.id });
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
