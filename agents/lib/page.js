// Turns a Builder landing page (model-written HTML) into a safe public page:
// no scripts, iframes, forms, event handlers, javascript: links or meta refresh; every
// {{BUY_URL}} placeholder points at the Stripe Payment Link; a fixed buy bar is always added.

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function sanitizeHtml(html = '') {
  let h = String(html);
  // Drop dangerous elements with their content, then any stray opening/closing tags.
  for (const t of ['script', 'iframe', 'object', 'embed', 'form', 'noscript', 'template', 'frame', 'frameset', 'applet']) {
    h = h.replace(new RegExp(`<${t}\\b[\\s\\S]*?<\\/${t}\\s*>`, 'gi'), '');
    h = h.replace(new RegExp(`<\\/?${t}\\b[^>]*>`, 'gi'), '');
  }
  h = h.replace(/<meta\b[^>]*http-equiv[^>]*>/gi, '');
  h = h.replace(/<base\b[^>]*>/gi, '');
  h = h.replace(/<link\b(?![^>]*fonts\.googleapis\.com)[^>]*>/gi, '');
  h = h.replace(/\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '');
  h = h.replace(/(href|src|action|formaction|xlink:href)\s*=\s*("|')?\s*(javascript|vbscript|data:text\/html)[^"'\s>]*("|')?/gi, '$1="#"');
  h = h.replace(/expression\s*\(/gi, '(');
  return h;
}

export function buildPublicPage({ html, title, priceUsd, buyUrl, status = 'live' }) {
  let h = sanitizeHtml(html);
  const live = status === 'live' && buyUrl;
  h = h.replace(/\{\{\s*BUY_URL\s*\}\}/g, live ? esc(buyUrl) : '#');
  if (!/<html[\s>]/i.test(h)) {
    h = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title></head><body>${h}</body></html>`;
  }
  if (!/<meta[^>]+viewport/i.test(h)) h = h.replace(/<head[^>]*>/i, (m) => `${m}<meta name="viewport" content="width=device-width,initial-scale=1">`);
  const price = priceUsd ? `$${Number(priceUsd).toFixed(Number(priceUsd) % 1 ? 2 : 0)}` : '';
  const bar = live
    ? `<div style="position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#111827;color:#fff;padding:12px 16px;display:flex;gap:12px;align-items:center;justify-content:center;font:600 15px/1.3 system-ui,sans-serif;box-shadow:0 -2px 12px rgba(0,0,0,.25)">
<span>${esc(title)}${price ? ` · ${price}` : ''}</span>
<a href="${esc(buyUrl)}" rel="noopener" style="background:#22c55e;color:#06210f;padding:10px 18px;border-radius:8px;text-decoration:none">Buy now</a></div><div style="height:64px"></div>`
    : `<div style="position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#374151;color:#fff;padding:12px 16px;text-align:center;font:600 15px/1.3 system-ui,sans-serif">This offer is no longer available.</div><div style="height:56px"></div>`;
  const footer = '<p style="text-align:center;font:13px system-ui,sans-serif;color:#6b7280;margin:24px 0">Secure checkout by Stripe · Ownvista</p>';
  return /<\/body>/i.test(h) ? h.replace(/<\/body>/i, `${footer}${bar}</body>`) : `${h}${footer}${bar}`;
}

export function slugify(title = '') {
  return String(title).toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'offer';
}
