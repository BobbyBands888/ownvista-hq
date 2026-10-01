// Etsy Open API v3, read-only (public active listings). Off until Bobby adds the ETSY_API_KEY secret
// ("keystring:shared_secret" from https://www.etsy.com/developers/your-apps). Never scrapes etsy.com pages:
// Etsy's terms forbid scraping, and its robots.txt blocks search pages.
import { env } from './env.js';

export const etsyReady = () => Boolean(env('ETSY_API_KEY'));

export async function etsyListings(keywords, { limit = 25 } = {}) {
  if (!etsyReady()) return [];
  const url = `https://openapi.etsy.com/v3/application/listings/active?${new URLSearchParams({ keywords, limit: String(limit), sort_on: 'score' })}`;
  const res = await fetch(url, { headers: { 'x-api-key': env('ETSY_API_KEY'), accept: 'application/json' }, signal: AbortSignal.timeout(20000) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`Etsy ${res.status}: ${JSON.stringify(data).slice(0, 160)}`);
  return (data.results || []).map((l) => ({
    title: String(l.title || '').slice(0, 160),
    url: l.url || `https://www.etsy.com/listing/${l.listing_id}`,
    price: l.price?.amount != null ? Math.round((l.price.amount / (l.price.divisor || 100)) * 100) / 100 : null,
    favorers: l.num_favorers ?? null,
    views: l.views ?? null,
    digital: l.type === 'download' || l.is_digital === true,
  }));
}
