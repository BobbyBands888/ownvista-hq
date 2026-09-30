// films.villacinema.com/unsubscribe?t=<token>
// GET shows a confirm button (so link scanners can't unsubscribe people); POST unsubscribes instantly.
import { sb, html, page } from './_supabase.js';

const valid = (t) => /^[0-9a-f]{32}$/.test(String(t || ''));

async function prospectFor(t) {
  if (!valid(t)) return null;
  const rows = await sb('GET', `/rest/v1/vc_prospects?unsub_token=eq.${t}&select=id,contact_email`);
  return rows?.[0] || null;
}

export async function GET(request) {
  const t = new URL(request.url).searchParams.get('t');
  const p = await prospectFor(t).catch(() => null);
  if (!p) return html(page('Unsubscribe', '<h1>Link not recognized</h1><p>Reply "unsubscribe" to any of our emails and we will remove you right away.</p>'), 404);
  return html(page('Unsubscribe', `<h1>Unsubscribe</h1><p>Stop all emails from Villa Cinema to <strong>${p.contact_email.replace(/[<>&]/g, '')}</strong>?</p>
<form method="post" action="/api/unsubscribe?t=${t}"><button type="submit">Unsubscribe</button></form>`));
}

export async function POST(request) {
  const t = new URL(request.url).searchParams.get('t');
  const p = await prospectFor(t).catch(() => null);
  if (!p) return html(page('Unsubscribe', '<h1>Link not recognized</h1>'), 404);
  await sb('POST', '/rest/v1/vc_suppression?on_conflict=email', [{ email: p.contact_email, reason: 'unsub' }],
    { Prefer: 'resolution=ignore-duplicates,return=minimal' });
  await sb('PATCH', `/rest/v1/vc_prospects?id=eq.${p.id}`, { stage: 'unsubscribed', updated_at: new Date().toISOString() }, { Prefer: 'return=minimal' });
  await sb('POST', '/rest/v1/activity', { agent: 'villa_outreach', kind: 'vc_unsub', message: `${p.contact_email} unsubscribed via link` }, { Prefer: 'return=minimal' });
  return html(page('Unsubscribed', '<h1>You are unsubscribed</h1><p>You will not receive any more emails from Villa Cinema.</p>'));
}
