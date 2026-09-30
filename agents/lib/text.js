import { createHash, randomBytes } from 'node:crypto';

export const sha256 = (s) => createHash('sha256').update(s).digest('hex');
export const randomToken = (n = 24) => randomBytes(n).toString('base64url');

const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', '#39': "'", hellip: '…', mdash: '—', ndash: '–', rsquo: '’', lsquo: '‘', rdquo: '”', ldquo: '“' };

export function decodeEntities(s = '') {
  return s
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(+d))
    .replace(/&([a-z0-9#]+);/gi, (m, n) => ENTITIES[n.toLowerCase()] ?? m);
}

export function htmlToText(html = '') {
  return decodeEntities(
    html
      .replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, ' ')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/(p|div|li|tr|h[1-6])>/gi, '\n')
      .replace(/<[^>]+>/g, ' '),
  )
    .replace(/[ \t\f\v]+/g, ' ')
    .replace(/\n\s*\n\s*\n+/g, '\n\n')
    .trim();
}

// Remove quoted history from a reply ("On … wrote:", "> …", Outlook headers).
export function stripQuoted(text = '') {
  const lines = text.replace(/\r/g, '').split('\n');
  const out = [];
  for (const line of lines) {
    if (/^\s*>/.test(line)) break;
    if (/^On .+wrote:\s*$/i.test(line.trim())) break;
    if (/^-{2,}\s*Original Message\s*-{2,}/i.test(line.trim())) break;
    if (/^From:\s.+/i.test(line.trim()) && out.length > 2) break;
    out.push(line);
  }
  return out.join('\n').trim();
}

export function truncate(s = '', n = 2000) {
  s = String(s ?? '');
  return s.length > n ? s.slice(0, n) + '…' : s;
}

// Normalized word-level edit distance: 0 = identical, 1 = completely rewritten.
export function editDistance(a = '', b = '') {
  const wa = norm(a).split(' ').filter(Boolean).slice(0, 600);
  const wb = norm(b).split(' ').filter(Boolean).slice(0, 600);
  if (!wa.length && !wb.length) return 0;
  let prev = Array.from({ length: wb.length + 1 }, (_, j) => j);
  for (let i = 1; i <= wa.length; i++) {
    const cur = [i];
    for (let j = 1; j <= wb.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa[i - 1] === wb[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[wb.length] / Math.max(wa.length, wb.length);
}

function norm(s) {
  return String(s).toLowerCase().replace(/[^\p{L}\p{N}@.'$ ]+/gu, ' ').replace(/\s+/g, ' ').trim();
}

export function similarTitle(a = '', b = '') {
  const A = new Set(norm(a).split(' ').filter((w) => w.length > 3));
  const B = new Set(norm(b).split(' ').filter((w) => w.length > 3));
  if (!A.size || !B.size) return false;
  let both = 0;
  for (const w of A) if (B.has(w)) both++;
  return both / Math.min(A.size, B.size) >= 0.7;
}

export function extractEmails(text = '') {
  const found = String(text).match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi) || [];
  return [...new Set(found.map((e) => e.toLowerCase().replace(/\.$/, '')))];
}

export function b64url(buf) {
  return Buffer.from(buf).toString('base64url');
}

export function fromB64url(s = '') {
  return Buffer.from(s, 'base64url').toString('utf8');
}

export function money(n) {
  return `$${Number(n || 0).toFixed(2)}`;
}
