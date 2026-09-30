// Villa Outreach / Inbox — hourly 6am–11pm ET.
// Inbox (bounces, unsubscribes, complaints, replies) → payments → follow-ups → first emails
// → prospect discovery. All sending goes through lib/sendgate.js (database-enforced caps).
import { db, kvGet, kvSet } from '../lib/db.js';
import { env, hasEnv, FILMS_BASE_URL, VC_FROM } from '../lib/env.js';
import { chat } from '../lib/llm.js';
import { systemPrompt, untrusted } from '../lib/guard.js';
import { listInbox, messageContent, zohoAccount } from '../lib/zoho.js';
import { send } from '../lib/sendgate.js';
import { completedSessionsSince, paymentLinkFor } from '../lib/stripe.js';
import { webSearch, searchAvailable } from '../lib/search.js';
import { politeFetch } from '../lib/robots.js';
import { playbook, signoff } from '../lib/context.js';
import { plan } from '../lib/pricing.js';
import { et, etDate, etToUtc } from '../lib/time.js';
import { htmlToText, stripQuoted, extractEmails, truncate, sha256, randomToken } from '../lib/text.js';

const SIGN = signoff('villa-cinema');
const ROLE = /^(info|hello|contact|contactus|reservations?|bookings?|book|stay|stays|rentals?|vacations?|concierge|sales|office|team|inquir(y|ies)|enquir(y|ies)|guests?|guestservices|admin|villas?|homes|management|marketing|owners?|frontdesk|help|support|welcome|reserve)$/;
const UNSUB = /\b(unsubscribe|remove me|opt[ -]?out|stop (emailing|contacting|sending)|take me off|do not (email|contact))\b/i;
const COMPLAINT = /\b(spam|reported (you|this)|harass|how did you get (my|this|our)|gdpr|ccpa|lawyer|attorney|legal action|cease and desist|blacklist)\b/i;
const UNUSUAL = /\b(discount|custom (price|pricing|quote)|refund|chargeback|contract|invoice|lawyer|legal|complain|cheaper|negotiat|bulk|agency|white[- ]?label|exclusive|nda|partnership|commission|affiliate)\b/i;
const BOUNCE_FROM = /(mailer-daemon|postmaster|mail delivery|mailerdaemon)/i;
const BOUNCE_SUBJECT = /(undeliver|delivery status|returned mail|failure notice|delivery fail|could not be delivered|not delivered|address rejected)/i;

const DISCOVERY_QUERIES = [
  ['luxury villa rental management company Maui', 'US-HI', 'Maui'],
  ['luxury vacation home management Kauai', 'US-HI', 'Kauai'],
  ['luxury villa rentals Big Island Hawaii management company', 'US-HI', 'Big Island'],
  ['luxury vacation rental management Florida Keys', 'US-FL', 'Florida Keys'],
  ['luxury villa rental management Naples Florida', 'US-FL', 'Naples'],
  ['luxury villa rentals management St. John USVI', 'US-VI', 'St. John'],
  ['luxury villa rental management St. Thomas USVI', 'US-VI', 'St. Thomas'],
  ['luxury villa rental management Dorado Puerto Rico', 'US-PR', 'Dorado'],
  ['luxury vacation rental management Aspen', 'US-MTN', 'Aspen'],
  ['luxury vacation home management Vail', 'US-MTN', 'Vail'],
  ['luxury vacation rental management Park City', 'US-MTN', 'Park City'],
  ['luxury vacation rental management Jackson Hole', 'US-MTN', 'Jackson Hole'],
];

export function configured() {
  return hasEnv('ZOHO_CLIENT_ID', 'ZOHO_CLIENT_SECRET', 'ZOHO_REFRESH_TOKEN');
}

export async function run(ctx) {
  if (!configured()) return 'Zoho is not configured yet — skipped';
  const out = [];
  out.push(`inbox: ${await inbox(ctx)}`);
  if (hasEnv('STRIPE_RESTRICTED_KEY')) out.push(`payments: ${await payments(ctx)}`);

  const enabled = (await kvGet('vc_enabled', false)) === true;
  const paused = (await kvGet('vc_paused', false)) === true;
  if (!enabled || paused) {
    out.push(paused ? `sending paused (${await kvGet('vc_pause_reason', '')})` : 'outreach off (dashboard → Villa → enable)');
    return out.join(' · ');
  }
  const pre = await ensurePreflight(ctx);
  if (!pre.ok) {
    out.push(`preflight failed: ${pre.problems.join('; ')}`);
    return out.join(' · ');
  }
  if (!ctx.outOfTime(120000)) out.push(`follow-ups: ${await followups(ctx)}`);
  if (!ctx.outOfTime(120000)) out.push(`first emails: ${await firstTouches(ctx)}`);
  if (!ctx.outOfTime(150000)) out.push(`discovery: ${await discovery(ctx)}`);
  return out.join(' · ');
}

// ---------------------------------------------------------------- preflight

export async function preflight(ctx) {
  const problems = [];
  const checks = {};
  for (const k of ['ZOHO_CLIENT_ID', 'ZOHO_CLIENT_SECRET', 'ZOHO_REFRESH_TOKEN', 'VC_PAYMENT_LINK', 'STRIPE_RESTRICTED_KEY', 'MINIMAX_API_KEY']) {
    checks[k] = hasEnv(k);
    if (!checks[k]) problems.push(`secret ${k} missing`);
  }
  try {
    const acct = await zohoAccount();
    await listInbox(1);
    checks.zoho = `ok (account ${acct.accountId})`;
  } catch (e) {
    checks.zoho = e.message;
    problems.push(`Zoho API: ${truncate(e.message, 160)} (the mailbox plan must include API/IMAP access)`);
  }
  const domain = VC_FROM().split('@')[1];
  const txt = async (name) => {
    const r = await fetch(`https://dns.google/resolve?name=${encodeURIComponent(name)}&type=TXT`);
    const j = await r.json();
    return (j.Answer || []).map((a) => String(a.data).replace(/^"|"$/g, '').replace(/"\s*"/g, ''));
  };
  const spf = (await txt(domain)).find((t) => /^v=spf1/i.test(t));
  const dmarc = (await txt(`_dmarc.${domain}`)).find((t) => /^v=DMARC1/i.test(t));
  const selectors = (env('VC_DKIM_SELECTORS', 'zmail,zoho,default')).split(',');
  let dkim = null;
  for (const s of selectors) {
    const rec = (await txt(`${s.trim()}._domainkey.${domain}`)).find((t) => /p=/.test(t));
    if (rec) { dkim = s.trim(); break; }
  }
  checks.spf = spf || null;
  checks.dmarc = dmarc || null;
  checks.dkim_selector = dkim;
  if (!spf || !/zoho/i.test(spf)) problems.push('SPF missing or does not include Zoho');
  if (!dmarc) problems.push('DMARC record missing');
  if (!dkim) problems.push(`DKIM not found (checked selectors: ${selectors.join(', ')})`);
  const footerAddress = await kvGet('vc_footer_address', '');
  checks.footer_address = Boolean(String(footerAddress).trim());
  if (!checks.footer_address) problems.push('footer mailing address not set');
  const result = { ok: problems.length === 0, problems, checks, at: new Date().toISOString() };
  await kvSet('vc_preflight', result);
  ctx?.log?.('preflight', result.ok ? 'Villa Cinema preflight passed' : `Villa Cinema preflight: ${problems.join('; ')}`);
  return result.ok ? 'preflight passed' : `preflight problems: ${problems.join('; ')}`;
}

async function ensurePreflight(ctx) {
  const last = await kvGet('vc_preflight', null);
  if (last && Date.now() - Date.parse(last.at) < 24 * 3600000) return last;
  await preflight(ctx);
  return kvGet('vc_preflight', { ok: false, problems: ['preflight did not run'] });
}

// ---------------------------------------------------------------- test email (manual)

export async function testEmail(ctx) {
  const to = await kvGet('bobby_email', '');
  const pb = await playbook();
  const fake = { company: 'Test Villas (sample prospect)', site_summary: '12 oceanfront villas on Maui with a strong photo library.', markets: ['Maui'] };
  const { subject, body } = await writeFirst(ctx, pb, fake);
  const r = await send({ kind: 'test', to, subject: `[TEST] ${subject}`, body });
  if (!r.ok) throw new Error(`Test send refused: ${r.reason}`);
  ctx.log('vc_test', `Sent test first-touch email to ${to}`);
  return `test email sent to ${to}`;
}

// ---------------------------------------------------------------- inbox

async function inbox(ctx) {
  const cursor = Number(await kvGet('vc_inbox_cursor', 0));
  const msgs = (await listInbox(50)).filter((m) => m.receivedTime > cursor - 15 * 60000).sort((a, b) => a.receivedTime - b.receivedTime);
  let handled = 0, maxTime = cursor;
  for (const m of msgs) {
    if (ctx.outOfTime(120000)) break;
    maxTime = Math.max(maxTime, m.receivedTime);
    if (m.from === VC_FROM()) continue;
    const seen = await db.one('vc_messages', { zoho_message_id: `eq.${m.messageId}`, direction: 'eq.in' });
    if (seen) continue;
    await handleInbound(ctx, m);
    handled++;
  }
  if (maxTime > cursor) await kvSet('vc_inbox_cursor', maxTime);
  return `${handled} new`;
}

async function handleInbound(ctx, m) {
  const html = await messageContent(m.folderId, m.messageId).catch(() => m.summary);
  const text = stripQuoted(htmlToText(html)) || m.summary;

  if (BOUNCE_FROM.test(m.from) || BOUNCE_SUBJECT.test(m.subject)) {
    const addrs = extractEmails(htmlToText(html)).filter((e) => e !== VC_FROM() && !BOUNCE_FROM.test(e));
    let matched = 0;
    for (const a of addrs) {
      const known = await db.one('vc_messages', { to_email: `eq.${a}`, direction: 'eq.out' });
      if (!known) continue;
      await db.rpc('vc_record_bounce', { p_email: a, p_zoho_id: m.messageId });
      matched++;
    }
    if (!matched) await recordIn(null, null, m, text, 'bounce_unmatched');
    ctx.log('vc_bounce', `Bounce received (${matched} address(es) suppressed)`);
    return;
  }

  let prospect = await db.one('vc_prospects', { contact_email: `eq.${m.from}` });
  const order = prospect ? null : await db.one('vc_orders', { customer_email: `eq.${m.from}`, order: 'created_at.desc' });
  if (!prospect && order?.prospect_id) prospect = await db.one('vc_prospects', { id: `eq.${order.prospect_id}` });
  if (!prospect) {
    await recordIn(null, order?.id, m, text, 'unknown');
    await needsBobby('vc_reply', `New email to ${VC_FROM()} from ${m.from}`, `Subject: ${m.subject}\n\n${truncate(text, 1500)}`, null);
    return;
  }

  await recordIn(prospect.id, order?.id, m, text, 'reply');
  const stageUpdate = ['prospect', 'contacted'].includes(prospect.stage) ? { stage: 'replied' } : {};
  await db.update('vc_prospects', { id: `eq.${prospect.id}` }, { last_reply_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...stageUpdate });

  if (UNSUB.test(`${m.subject}\n${text}`)) {
    await db.insert('vc_suppression', [{ email: m.from, reason: 'unsub' }], { onConflict: 'email', ignoreDuplicates: true });
    await db.update('vc_prospects', { id: `eq.${prospect.id}` }, { stage: 'unsubscribed' });
    ctx.log('vc_unsub', `${m.from} unsubscribed by reply`);
    return;
  }
  if (COMPLAINT.test(`${m.subject}\n${text}`)) {
    await db.insert('vc_suppression', [{ email: m.from, reason: 'complaint' }], { onConflict: 'email', ignoreDuplicates: true });
    await db.update('vc_prospects', { id: `eq.${prospect.id}` }, { stage: 'lost' });
    await db.rpc('vc_pause', { p_reason: `Possible spam complaint from ${m.from}: "${truncate(text, 200)}"` });
    return;
  }

  const pb = await playbook();
  const openOrder = await db.one('vc_orders', { prospect_id: `eq.${prospect.id}`, status: 'eq.awaiting_photos', order: 'created_at.desc' });
  const system = systemPrompt('the Villa Cinema reply writer', `
${pb.text(['villa'])}

Classify the prospect's latest message and, if it is a normal question or interest, answer it.
Facts you may use: films are cinematic walkthroughs made from the property photos they already have (8–12 photos), delivered as a download link, every film carries a small "AI-generated from photos" note. Price and checkout are on the Payment Link. No calls — everything by email.
"unusual" = custom pricing, discounts, refunds, legal, contracts, complaints, partnerships, anything you are not sure about. Unusual messages get NO reply from you.
Do not include links or a sign-off in "answer" — the next step link and sign-off are added automatically.
JSON only: {"intent":"question|interested|wants_sample|ready_to_buy|photos_sent|not_interested|out_of_office|unusual","unusual_reason":"","answer":"reply body, under 120 words","property_name":""}`);
  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 900,
    system, messages: [{ role: 'user', content: `Prospect: ${prospect.company} (${prospect.markets.join(', ')})\n${untrusted(`email from ${m.from}`, `Subject: ${m.subject}\n\n${truncate(text, 3000)}`)}` }],
  });
  let intent = String(json.intent || 'unusual');
  if (UNUSUAL.test(text) && intent !== 'out_of_office') intent = 'unusual';

  if (intent === 'out_of_office') return;
  if (intent === 'not_interested') {
    await db.update('vc_prospects', { id: `eq.${prospect.id}` }, { stage: 'lost' });
    return;
  }
  if (intent === 'unusual' || !String(json.answer || '').trim()) {
    await needsBobby('vc_reply', `Villa Cinema reply needs you: ${prospect.company}`,
      `From ${m.from}: "${truncate(text, 1200)}"\n\nWhy: ${json.unusual_reason || 'unusual request'}\nSuggested answer (not sent): ${json.answer || '-'}`, prospect.id);
    return;
  }
  if (['interested', 'wants_sample', 'ready_to_buy'].includes(intent)) {
    await db.update('vc_prospects', { id: `eq.${prospect.id}` }, { hot: true });
  }

  let nextStep;
  if (openOrder) {
    nextStep = `Upload 8–12 of your best photos here: ${await freshUploadLink(openOrder.id)}`;
  } else if (['interested', 'wants_sample', 'photos_sent'].includes(intent) && await canOfferSample(prospect)) {
    const { link } = await createOrder({ kind: 'sample', prospect, propertyName: json.property_name });
    nextStep = `We'd be glad to make a short free sample first. Upload 8–12 photos of one property here: ${link}`;
  } else {
    nextStep = `You can order here: ${paymentLinkFor(prospect)} — after checkout you'll get a link to upload your photos.`;
  }
  const body = `${String(json.answer).trim()}\n\n${nextStep}\n\n${SIGN}`;
  const r = await send({
    kind: 'reply', to: m.from, subject: /^re:/i.test(m.subject) ? m.subject : `Re: ${m.subject}`,
    body, prospect, replyTo: { messageId: m.messageId },
  });
  ctx.log(r.ok ? 'vc_reply' : 'vc_reply_refused', r.ok ? `Replied to ${prospect.company} (${intent})` : `Reply to ${prospect.company} not sent: ${r.reason}`, { table: 'vc_prospects', id: prospect.id });
}

async function recordIn(prospectId, orderId, m, text, kind) {
  await db.insertOne('vc_messages', {
    prospect_id: prospectId, order_id: orderId ?? null, direction: 'in', kind, status: 'received',
    from_email: m.from, subject: m.subject, body: truncate(text, 8000), zoho_message_id: m.messageId, zoho_thread_id: m.threadId,
  }).catch(() => {}); // duplicate message id → already recorded
}

async function needsBobby(kind, title, detail, prospectId) {
  await db.insertOne('approvals', { kind, title, detail, ref_table: prospectId ? 'vc_prospects' : null, ref_id: prospectId, created_by: 'villa_outreach' });
}

async function canOfferSample(prospect) {
  if ((await kvGet('vc_sample_mode', 'auto')) !== 'auto') return false;
  const prior = await db.count('vc_orders', { prospect_id: `eq.${prospect.id}`, kind: 'eq.sample' });
  if (prior > 0) return false;
  const weekStart = new Date(Date.now() - ((et().weekday + 6) % 7) * 86400000);
  const used = await db.select('spend', { kind: 'eq.sample', status: 'in.(reserved,charged)', at: `gte.${weekStart.toISOString().slice(0, 10)}`, select: 'amount_usd' });
  const openSamples = await db.count('vc_orders', { kind: 'eq.sample', status: 'in.(awaiting_photos,photos_received,generating,qa,stitching)' });
  const committed = used.reduce((n, s) => n + +s.amount_usd, 0) + openSamples * plan('sample').total * 1.5;
  return committed + plan('sample').total * 1.5 <= 25;
}

export async function createOrder({ kind, prospect, propertyName, stripeSessionId = null, amount = null, email = null }) {
  const token = randomToken();
  const order = await db.insertOne('vc_orders', {
    kind, prospect_id: prospect?.id ?? null, status: 'awaiting_photos', stripe_session_id: stripeSessionId,
    amount_usd: amount, customer_email: email || prospect?.contact_email || null,
    property_name: propertyName || null, upload_token_hash: sha256(token),
  });
  return { order, link: `${FILMS_BASE_URL()}/upload?o=${order.id}&t=${token}` };
}

async function freshUploadLink(orderId) {
  const token = randomToken();
  await db.update('vc_orders', { id: `eq.${orderId}` }, { upload_token_hash: sha256(token), updated_at: new Date().toISOString() });
  return `${FILMS_BASE_URL()}/upload?o=${orderId}&t=${token}`;
}

// ---------------------------------------------------------------- payments

async function payments(ctx) {
  const since = Number(await kvGet('vc_stripe_cursor', Math.floor(Date.now() / 1000) - 7 * 86400));
  const sessions = await completedSessionsSince(since);
  let created = 0, maxCreated = since;
  const uuid = /^[0-9a-f-]{36}$/i;
  for (const s of sessions) {
    maxCreated = Math.max(maxCreated, s.created);
    if (await db.one('vc_orders', { stripe_session_id: `eq.${s.id}` })) continue;
    let prospect = s.clientReferenceId && uuid.test(s.clientReferenceId)
      ? await db.one('vc_prospects', { id: `eq.${s.clientReferenceId}` }) : null;
    if (!prospect && s.email) prospect = await db.one('vc_prospects', { contact_email: `eq.${s.email}` });
    const { order, link } = await createOrder({ kind: 'paid', prospect, stripeSessionId: s.id, amount: s.amount, email: s.email || prospect?.contact_email });
    await db.insertOne('ledger', { line: 'villa-cinema', revenue: s.amount, note: `Stripe ${s.id}`, source: 'stripe' });
    if (prospect) {
      await db.update('vc_prospects', { id: `eq.${prospect.id}` }, { stage: 'paid', hot: true, updated_at: new Date().toISOString() });
      // A paid order replaces any free sample still waiting for photos.
      await db.update('vc_orders', { prospect_id: `eq.${prospect.id}`, kind: 'eq.sample', status: 'eq.awaiting_photos' }, { status: 'cancelled', notes: 'Superseded by paid order', updated_at: new Date().toISOString() });
    }
    const to = s.email || prospect?.contact_email;
    if (to) {
      const r = await send({
        kind: 'order', to, orderId: order.id, prospect,
        subject: 'Your Villa Cinema film — upload your photos',
        body: `Thank you — your order is confirmed.\n\nNext step: upload 8–12 of your best photos of the property (wide shots of living areas, bedrooms, pool and views work best): ${link}\n\nWe'll email your film as soon as it's ready.\n\n${SIGN}`,
      });
      if (!r.ok) await needsBobby('vc_order', 'Paid order: upload email not sent', `${to}: ${r.reason}`, prospect?.id);
    } else {
      await needsBobby('vc_order', 'Paid order without an email address', `Stripe session ${s.id}`, null);
    }
    ctx.log('vc_paid', `New paid order $${s.amount} from ${to || 'unknown'}`, { table: 'vc_orders', id: order.id });
    created++;
  }
  if (maxCreated > since) await kvSet('vc_stripe_cursor', maxCreated);
  return `${created} new order(s)`;
}

// ---------------------------------------------------------------- follow-ups and first emails

function inSendWindow() {
  const t = et();
  return t.weekday >= 1 && t.weekday <= 5 && t.hour >= 9 && t.hour <= 16;
}

async function followups(ctx) {
  if (!inSendWindow()) return 'outside send window';
  const due = await db.select('vc_prospects', {
    stage: 'eq.contacted', followup_sent_at: 'is.null', last_reply_at: 'is.null',
    first_sent_at: `lte.${new Date(Date.now() - 4 * 86400000).toISOString()}`, order: 'first_sent_at.asc', limit: 5,
  });
  let sent = 0;
  for (const p of due) {
    const first = await db.one('vc_messages', { prospect_id: `eq.${p.id}`, kind: 'eq.first', status: 'eq.sent' });
    const body = `Following up once on my note about a walkthrough film for ${p.company}. If it's useful, I can make a short sample from photos you already have.\n\n${SIGN}`;
    const r = await send({ kind: 'followup', to: p.contact_email, subject: `Re: ${first?.subject || 'A film for your villas'}`, body, prospect: p });
    if (r.ok) sent++;
    else if (/cap|paused|switched off/.test(r.reason)) break;
  }
  return `${sent} sent`;
}

async function writeFirst(ctx, pb, p) {
  const { json } = await chat({
    ctx, tier: 'smart', json: true, maxTokens: 700,
    system: systemPrompt('the Villa Cinema outreach writer', `${pb.text(['villa'])}
Write the first cold email. Under 110 words. One specific, true observation from the site summary (no flattery, no invented facts), the offer in one sentence, and one question.
No links, no sign-off, no phone numbers, no mention of any other business.
JSON only: {"subject":"under 7 words","body":""}`),
    messages: [{ role: 'user', content: untrusted(`${p.company} website summary`, `Company: ${p.company}\nMarkets: ${(p.markets || []).join(', ')}\nSummary: ${p.site_summary || '(none)'}`, 1500) }],
  });
  return { subject: String(json.subject || 'A film for your villas').slice(0, 80), body: `${String(json.body || '').trim()}\n\n${SIGN}` };
}

async function firstTouches(ctx) {
  if (!inSendWindow()) return 'outside send window';
  const start = await kvGet('vc_warmup_start', '');
  const dayN = start ? Math.floor((Date.parse(etDate()) - Date.parse(start)) / 86400000) : 0;
  const cap = Math.min(20, 5 + Math.floor(dayN * 15 / 14));
  const dayStart = etToUtc(etDate(), 0, 0).toISOString();
  const sentToday = await db.count('vc_messages', { direction: 'eq.out', kind: 'eq.first', status: 'in.(reserved,sent)', created_at: `gte.${dayStart}` });
  const hoursLeft = Math.max(1, 17 - et().hour);
  const quota = Math.min(cap - sentToday, Math.ceil((cap - sentToday) / hoursLeft));
  if (quota <= 0) return `cap reached (${cap} today)`;

  const countries = await kvGet('vc_countries', {});
  const regions = await kvGet('vc_us_regions', {});
  const pb = await playbook();
  const candidates = await db.select('vc_prospects', { stage: 'eq.prospect', order: 'created_at.asc', limit: quota * 3 });
  let sent = 0;
  for (const p of candidates) {
    if (sent >= quota || ctx.outOfTime(90000)) break;
    if (!countries[p.country] || (p.country === 'US' && !regions[p.region])) continue;
    if (!ROLE.test(p.contact_email.split('@')[0])) continue;
    const { subject, body } = await writeFirst(ctx, pb, p);
    const r = await send({ kind: 'first', to: p.contact_email, subject, body, prospect: p });
    if (r.ok) sent++;
    else {
      ctx.note(`first to ${p.contact_email} refused: ${r.reason}`);
      if (/cap|paused|switched off|footer/.test(r.reason)) break;
      if (/guard/.test(r.reason)) continue;
    }
  }
  return `${sent} sent (cap ${cap}/day, warm-up day ${dayN})`;
}

// ---------------------------------------------------------------- discovery

async function discovery(ctx) {
  const today = etDate();
  if ((await kvGet('vc_discovery_day', '')) === today || et().hour < 10) return 'not due';
  const backlog = await db.count('vc_prospects', { stage: 'eq.prospect' });
  if (backlog >= 30) return `backlog ${backlog}, skipped`;

  const candidates = [];
  if (await searchAvailable()) {
    const i = (await kvGet('vc_discovery_idx', 0)) % DISCOVERY_QUERIES.length;
    for (const [q, region, market] of [DISCOVERY_QUERIES[i], DISCOVERY_QUERIES[(i + 1) % DISCOVERY_QUERIES.length]]) {
      const r = await webSearch(q, { purpose: 'discovery', maxResults: 8 });
      for (const x of r.results || []) candidates.push({ url: x.url, region, market, via: q });
    }
    await kvSet('vc_discovery_idx', i + 2);
  }
  const directories = await db.select('sources', { kind: 'eq.directory', status: 'eq.active', limit: 3 });
  for (const d of directories) {
    try {
      const { text } = await politeFetch(d.url);
      const links = [...text.matchAll(/href=["'](https?:\/\/[^"'#]+)["']/gi)].map((x) => x[1]);
      const host = new URL(d.url).host;
      for (const l of [...new Set(links)].filter((l) => !l.includes(host)).slice(0, 15)) {
        candidates.push({ url: l, region: d.query || null, market: d.name, via: d.url });
      }
    } catch (e) {
      ctx.note(`directory ${d.name}: ${e.message}`);
    }
  }
  await kvSet('vc_discovery_day', today);

  const seenHosts = new Set();
  let added = 0;
  for (const c of candidates) {
    if (added >= 8 || ctx.outOfTime(90000)) break;
    let site;
    try { site = new URL(c.url); } catch { continue; }
    const host = site.host.replace(/^www\./, '');
    if (seenHosts.has(host) || /(airbnb|vrbo|booking|expedia|tripadvisor|facebook|instagram|yelp|linkedin|google|youtube|wikipedia|reddit)\./i.test(host)) continue;
    seenHosts.add(host);
    if (await db.one('vc_prospects', { website: `ilike.*${host}*` })) continue;
    try {
      const home = await politeFetch(`${site.protocol}//${site.host}/`);
      const contactHref = /href=["']([^"']*contact[^"']*)["']/i.exec(home.text)?.[1];
      let contactText = '';
      if (contactHref) {
        const url = new URL(contactHref, `${site.protocol}//${site.host}/`).toString();
        if (new URL(url).host === site.host) contactText = (await politeFetch(url)).text;
      }
      const emails = extractEmails(`${home.text}\n${contactText}`)
        .filter((e) => e.endsWith(`@${host}`) && ROLE.test(e.split('@')[0]));
      if (!emails.length) continue;
      const { json } = await chat({
        ctx, tier: 'fast', json: true, maxTokens: 500, temperature: 0.1,
        system: systemPrompt('the Villa Cinema prospect qualifier', `Decide from the website text whether this company manages luxury villa or high-end vacation home rentals.
JSON only: {"is_luxury_villa_manager":true,"company":"","markets":[""],"portfolio_size":null,"summary":"1–2 factual sentences about their portfolio for personalization"}`),
        messages: [{ role: 'user', content: untrusted(host, htmlToText(home.text).slice(0, 5000), 5200) }],
      });
      if (!json.is_luxury_villa_manager) continue;
      const email = emails.sort((a, b) => ROLE_PRIORITY(a) - ROLE_PRIORITY(b))[0];
      await db.insert('vc_prospects', [{
        company: truncate(json.company || host, 120), website: `${site.protocol}//${site.host}`, contact_email: email,
        markets: (json.markets || [c.market]).filter(Boolean).slice(0, 5), country: 'US', region: c.region,
        portfolio_size: Number.isFinite(+json.portfolio_size) && json.portfolio_size !== null ? +json.portfolio_size : null,
        source_url: c.via, site_summary: truncate(json.summary || '', 500),
      }], { onConflict: 'contact_email', ignoreDuplicates: true });
      added++;
    } catch (e) {
      if (e.name === 'CapError') throw e;
    }
  }
  if (added) ctx.log('vc_prospects', `Found ${added} new prospect(s)`);
  if (!candidates.length) return 'no discovery source (approve search or add a directory source)';
  return `${added} new prospect(s) from ${candidates.length} candidate(s)`;
}

const ROLE_PRIORITY = (e) => {
  const local = e.split('@')[0];
  return ['reservations', 'info', 'hello', 'contact', 'stay', 'concierge', 'sales'].indexOf(local) >>> 0;
};
