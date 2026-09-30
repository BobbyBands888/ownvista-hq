// THE ONLY CODE IN THIS REPO THAT CAN SEND EMAIL.
// Sends only from hello@villacinema.com via Zoho Mail REST, and only after the database
// send gate (vc_reserve_send) approves: caps, warm-up, suppression, countries, role
// addresses, no third touch, pause switch. Guard checks run here first as a second layer.
import { requireEnv, VC_FROM, FILMS_BASE_URL, VC_PRICE_USD } from './env.js';
import { db, kvGet } from './db.js';
import { checkCopy } from './guard.js';
import { zohoBase, zohoToken, zohoAccount } from './zoho.js';

export const VILLA_LINK_PREFIXES = () => [
  FILMS_BASE_URL(),
  'https://villacinema.com',
  'https://www.villacinema.com',
  'https://buy.stripe.com/',
  `${requireEnv('SUPABASE_URL').replace(/\/$/, '')}/storage/v1/object/sign/vc-films/`,
];

export async function footer(prospect) {
  const address = await kvGet('vc_footer_address', '');
  if (!address || !String(address).trim()) throw new Error('Footer address is not set (dashboard → Villa → Settings). Nothing can send without it.');
  const unsub = prospect?.unsub_token
    ? `${FILMS_BASE_URL()}/unsubscribe?t=${prospect.unsub_token}`
    : null;
  return [
    '',
    '—',
    'Villa Cinema · villacinema.com',
    String(address).trim(),
    unsub ? `Not interested? Unsubscribe: ${unsub} (or reply "unsubscribe").` : 'To unsubscribe, reply "unsubscribe".',
  ].join('\n');
}

/**
 * send({ kind, to, subject, body, prospect, orderId, replyTo: { messageId } })
 * kind: first | followup | reply | order | delivery | test
 * Returns { ok, id, reason }.
 */
export async function send({ kind, to, subject, body, prospect = null, orderId = null, replyTo = null }) {
  const fromAddr = VC_FROM();
  if (!fromAddr.endsWith('@villacinema.com')) return { ok: false, reason: 'sender must be @villacinema.com' };

  const full = `${body.trim()}\n${await footer(prospect)}`;
  const problems = checkCopy(`${subject}\n${full}`, { villa: true, allowLinks: VILLA_LINK_PREFIXES(), prices: [VC_PRICE_USD()] });
  if (problems.length) return { ok: false, reason: `guard: ${problems.join('; ')}` };

  const gate = await db.rpc('vc_reserve_send', {
    p_kind: kind, p_to: to, p_prospect: prospect?.id ?? null, p_order: orderId,
    p_subject: subject, p_body: full, p_in_reply_to: replyTo?.messageId ?? null,
  });
  if (!gate?.ok) return { ok: false, reason: gate?.reason || 'send gate refused' };

  try {
    const { accountId } = await zohoAccount();
    const path = replyTo?.messageId
      ? `/api/accounts/${accountId}/messages/${replyTo.messageId}`
      : `/api/accounts/${accountId}/messages`;
    const payload = {
      fromAddress: fromAddr,
      toAddress: to,
      subject,
      content: full,
      mailFormat: 'plaintext',
      ...(replyTo?.messageId ? { action: 'reply' } : {}),
    };
    const res = await fetch(`${zohoBase()}${path}`, {
      method: 'POST',
      headers: { Authorization: `Zoho-oauthtoken ${await zohoToken()}`, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`Zoho send ${res.status}: ${text.slice(0, 300)}`);
    const data = JSON.parse(text).data || {};
    await db.rpc('vc_confirm_send', { p_id: gate.id, p_zoho_id: String(data.messageId ?? ''), p_thread_id: data.threadId ? String(data.threadId) : null });
    return { ok: true, id: gate.id };
  } catch (e) {
    await db.rpc('vc_fail_send', { p_id: gate.id, p_error: e.message });
    return { ok: false, reason: e.message };
  }
}
