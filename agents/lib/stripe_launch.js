// Stripe for the Launcher. Key: STRIPE_LAUNCH_KEY, a restricted key with WRITE on Products, Prices and
// Payment Links and READ on Checkout Sessions — nothing else. On top of that, every call is checked
// against this allowlist, so no code path here can charge, refund, transfer or pay out.
import { requireEnv, hasEnv } from './env.js';

const ALLOWED = [
  ['POST', /^\/v1\/products$/],
  ['POST', /^\/v1\/prices$/],
  ['POST', /^\/v1\/payment_links$/],
  ['POST', /^\/v1\/payment_links\/plink_[A-Za-z0-9]+$/], // update (used only to deactivate a killed launch)
  ['GET', /^\/v1\/checkout\/sessions$/],
];

export function assertStripeAllowed(method, path) {
  if (!ALLOWED.some(([m, re]) => m === method && re.test(path))) throw new Error(`Stripe call refused by allowlist: ${method} ${path}`);
}

export const launchKeyReady = () => hasEnv('STRIPE_LAUNCH_KEY');

async function call(method, path, params = {}) {
  assertStripeAllowed(method, path);
  const body = new URLSearchParams();
  const add = (k, v) => {
    if (v === undefined || v === null) return;
    if (typeof v === 'object') for (const [kk, vv] of Object.entries(v)) add(`${k}[${kk}]`, vv);
    else body.append(k, String(v));
  };
  for (const [k, v] of Object.entries(params)) add(k, v);
  const url = `https://api.stripe.com${path}${method === 'GET' && body.toString() ? `?${body}` : ''}`;
  const res = await fetch(url, {
    method,
    headers: { Authorization: `Bearer ${requireEnv('STRIPE_LAUNCH_KEY')}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: method === 'GET' ? undefined : body,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(`Stripe ${res.status}: ${data.error?.message || ''}`);
  return data;
}

// Product + one-time price + Payment Link. Metadata ties everything back to the launch.
export async function createOffer({ launchId, title, description, priceUsd, successUrl }) {
  const cents = Math.round(Number(priceUsd) * 100);
  if (!(cents >= 100 && cents <= 100000)) throw new Error(`price out of range: ${priceUsd}`);
  const product = await call('POST', '/v1/products', {
    name: title.slice(0, 250), description: description ? description.slice(0, 500) : undefined, metadata: { launch_id: launchId, source: 'ownvista-hq' },
  });
  const price = await call('POST', '/v1/prices', { product: product.id, unit_amount: cents, currency: 'usd', metadata: { launch_id: launchId } });
  const link = await call('POST', '/v1/payment_links', {
    'line_items[0][price]': price.id, 'line_items[0][quantity]': 1,
    metadata: { launch_id: launchId },
    ...(successUrl ? { 'after_completion[type]': 'redirect', 'after_completion[redirect][url]': successUrl } : {}),
  });
  return { productId: product.id, priceId: price.id, linkId: link.id, url: link.url };
}

export const deactivateLink = (linkId) => call('POST', `/v1/payment_links/${linkId}`, { active: false });

// Paid Checkout Sessions since a time, for our payment links only.
export async function paidSessionsSince(unixSeconds, linkIds) {
  const want = new Set(linkIds);
  if (!want.size) return [];
  const out = [];
  let startingAfter;
  for (let page = 0; page < 5; page++) {
    const data = await call('GET', '/v1/checkout/sessions', {
      limit: 100, status: 'complete', 'created[gte]': unixSeconds, ...(startingAfter ? { starting_after: startingAfter } : {}),
    });
    out.push(...data.data);
    if (!data.has_more) break;
    startingAfter = data.data.at(-1).id;
  }
  return out.filter((s) => s.payment_status === 'paid' && want.has(s.payment_link))
    .map((s) => ({ id: s.id, linkId: s.payment_link, amount: (s.amount_total ?? 0) / 100, created: s.created }));
}
