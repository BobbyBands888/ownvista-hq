// Public offer pages: levelingclips.com/p/<slug>
//   GET /p/<slug>                         → the live landing page (Buy button → Stripe Payment Link)
//   GET /p/<slug>?thanks=<token>&session=… → after payment: the buyer's download page
// Pages are sanitized when the Launcher publishes them and served with a no-script CSP.
import { sb } from './_supabase.js';

const CSP = "default-src 'none'; img-src https: data:; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'";

const respond = (body, status = 200, cache = 'public, max-age=60') => new Response(body, {
  status,
  headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': cache, 'Content-Security-Policy': CSP, 'Referrer-Policy': 'no-referrer' },
});

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Small, safe Markdown → HTML (everything escaped first).
export function mdToHtml(md = '') {
  const lines = esc(md).split('\n');
  const out = [];
  let list = null, para = [], code = false;
  const inline = (s) => s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/(^|\W)\*(?!\s)(.+?)\*(?=\W|$)/g, '$1<em>$2</em>');
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
    if (list) { out.push(`</${list}>`); list = null; }
  };
  for (const line of lines) {
    if (/^```/.test(line)) { flush(); out.push(code ? '</pre>' : '<pre>'); code = !code; continue; }
    if (code) { out.push(line); continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    const li = /^\s*(?:[-*]|(\d+)[.)])\s+(.*)$/.exec(line);
    if (h) { flush(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); }
    else if (li) {
      if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
      const kind = li[1] ? 'ol' : 'ul';
      if (list !== kind) { if (list) out.push(`</${list}>`); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline(li[2])}</li>`);
    } else if (/^\s*\|/.test(line)) { flush(); if (!/^\s*\|[\s|:-]+\|\s*$/.test(line)) out.push(`<div class="row">${line.split('|').slice(1, -1).map((c) => `<span>${inline(c.trim())}</span>`).join('')}</div>`); }
    else if (!line.trim()) flush();
    else { if (list) { out.push(`</${list}>`); list = null; } para.push(line.trim()); }
  }
  flush();
  if (code) out.push('</pre>');
  return out.join('\n');
}

function deliveryPage(title, product) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>${esc(title)} — your download</title>
<style>body{font:17px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;color:#111827;background:#f9fafb;margin:0}main{max-width:760px;margin:0 auto;padding:32px 20px 80px}
.note{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:14px 16px;margin-bottom:28px}h1{line-height:1.2}pre{background:#111827;color:#f9fafb;padding:14px;border-radius:8px;overflow:auto}
code{background:#eef2ff;padding:1px 5px;border-radius:4px}.row{display:grid;grid-auto-flow:column;gap:12px;border-bottom:1px solid #e5e7eb;padding:6px 0}
@media print{.note{display:none}}</style></head><body><main>
<div class="note"><strong>Thank you for your purchase.</strong> Bookmark this page — it is your copy. Use your browser's Print → Save as PDF to keep an offline version.</div>
${mdToHtml(product)}
</main></body></html>`;
}

const notFound = () => respond('<!doctype html><meta charset="utf-8"><title>Not found</title><p style="font:16px system-ui;padding:40px;text-align:center">This page does not exist.</p>', 404, 'no-store');

export async function GET(request) {
  const url = new URL(request.url);
  const slug = String(url.searchParams.get('slug') || '').toLowerCase();
  if (!/^[a-z0-9-]{1,80}$/.test(slug)) return notFound();
  const rows = await sb('GET', `/rest/v1/launches?slug=eq.${slug}&select=id,title,status,page_html,delivery_token,product_asset_id&limit=1`).catch(() => null);
  const l = rows?.[0];
  if (!l || !['live', 'killed'].includes(l.status)) return notFound();

  const thanks = url.searchParams.get('thanks');
  if (thanks) {
    if (!l.delivery_token || thanks !== l.delivery_token || !l.product_asset_id) return notFound();
    const a = await sb('GET', `/rest/v1/assets?id=eq.${l.product_asset_id}&select=body&limit=1`).catch(() => null);
    if (!a?.[0]) return notFound();
    return respond(deliveryPage(l.title, a[0].body), 200, 'private, no-store');
  }
  if (!l.page_html) return notFound();
  return respond(l.page_html);
}
