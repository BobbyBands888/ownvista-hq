// Stripe, read-only: list completed Checkout Sessions (restricted key with Checkout Sessions: Read).
import { requireEnv, env } from './env.js';

export async function completedSessionsSince(unixSeconds) {
  const out = [];
  let startingAfter = null;
  for (let page = 0; page < 5; page++) {
    const q = new URLSearchParams({ limit: '100', status: 'complete', 'created[gte]': String(unixSeconds) });
    if (startingAfter) q.set('starting_after', startingAfter);
    const res = await fetch(`https://api.stripe.com/v1/checkout/sessions?${q}`, {
      headers: { Authorization: `Bearer ${requireEnv('STRIPE_RESTRICTED_KEY')}` },
    });
    const data = await res.json();
    if (!res.ok) throw new Error(`Stripe ${res.status}: ${data.error?.message || ''}`);
    out.push(...data.data);
    if (!data.has_more) break;
    startingAfter = data.data.at(-1).id;
  }
  const linkId = env('VC_PAYMENT_LINK_ID');
  return out
    .filter((s) => s.payment_status === 'paid' && (!linkId || s.payment_link === linkId))
    .map((s) => ({
      id: s.id,
      clientReferenceId: s.client_reference_id,
      email: (s.customer_details?.email || s.customer_email || '').toLowerCase(),
      amount: (s.amount_total ?? 0) / 100,
      currency: s.currency,
      created: s.created,
    }));
}

// Payment Link URL tagged with the prospect id so the payment maps back to them.
export function paymentLinkFor(prospect) {
  const u = new URL(requireEnv('VC_PAYMENT_LINK'));
  u.searchParams.set('client_reference_id', prospect.id);
  if (prospect.contact_email) u.searchParams.set('prefilled_email', prospect.contact_email);
  return u.toString();
}
