// Gmail REST client — DRAFTS ONLY.
// The gmail.modify scope technically allows sending, so this module is the guarantee:
// every request passes an allowlist, and any path that could send is refused before fetch.
// test/no-send.test.js fails the build if send-capable code appears anywhere.
import { requireEnv, GMAIL_USER } from './env.js';
import { GMAIL_FORBIDDEN } from './guard.js';
import { fromB64url, htmlToText } from './text.js';

const API = 'https://gmail.googleapis.com/gmail/v1/users/me';

// [method, path regex] — the complete list of Gmail calls agents may make.
const ALLOW = [
  ['GET', /^\/profile$/],
  ['GET', /^\/labels$/],
  ['POST', /^\/labels$/],
  ['GET', /^\/threads(\?.*)?$/],
  ['GET', /^\/threads\/[\w-]+(\?.*)?$/],
  ['POST', /^\/threads\/[\w-]+\/modify$/],
  ['GET', /^\/messages\/[\w-]+(\?.*)?$/],
  ['GET', /^\/drafts(\?.*)?$/],
  ['GET', /^\/drafts\/[\w-]+(\?.*)?$/],
  ['POST', /^\/drafts$/],
  ['PUT', /^\/drafts\/[\w-]+$/],
];

export function assertAllowed(method, path) {
  if (GMAIL_FORBIDDEN.test(path)) throw new Error(`Gmail call refused (send-capable path): ${method} ${path}`);
  if (!ALLOW.some(([m, re]) => m === method && re.test(path))) throw new Error(`Gmail call refused (not allowlisted): ${method} ${path}`);
}

let token = null;
async function accessToken() {
  if (token && token.exp > Date.now() + 60000) return token.value;
  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: requireEnv('GMAIL_CLIENT_ID'),
      client_secret: requireEnv('GMAIL_CLIENT_SECRET'),
      refresh_token: requireEnv('GMAIL_REFRESH_TOKEN'),
      grant_type: 'refresh_token',
    }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(`Gmail token refresh failed: ${data.error} ${data.error_description || ''}`);
  token = { value: data.access_token, exp: Date.now() + data.expires_in * 1000 };
  return token.value;
}

export async function gmail(method, path, body) {
  assertAllowed(method, path);
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${await accessToken()}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 404) return null;
  const text = await res.text();
  if (!res.ok) throw new Error(`Gmail ${method} ${path.split('?')[0]} → ${res.status}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

// ---------- parsing ----------

export function headerMap(payload) {
  const h = {};
  for (const { name, value } of payload?.headers || []) h[name.toLowerCase()] = value;
  return h;
}

export function messageText(payload) {
  let plain = '', html = '';
  const walk = (p) => {
    if (!p) return;
    if (p.mimeType === 'text/plain' && p.body?.data && !plain) plain = fromB64url(p.body.data);
    else if (p.mimeType === 'text/html' && p.body?.data && !html) html = fromB64url(p.body.data);
    (p.parts || []).forEach(walk);
  };
  walk(payload);
  return (plain || htmlToText(html)).replace(/\r/g, '').trim();
}

export function parseAddress(s = '') {
  const m = /^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/.exec(s);
  return m ? { name: m[1].trim(), email: m[2].trim().toLowerCase() } : { name: '', email: s.trim().toLowerCase() };
}

// Addresses that count as "Bobby" (the Workspace user and the aliases routed into it).
export function bobbyAddresses() {
  const extra = (process.env.GMAIL_ALIASES || 'hello@getownvista.com,quotes@getownvista.com').split(',');
  return new Set([GMAIL_USER(), ...extra.map((s) => s.trim().toLowerCase()).filter(Boolean)]);
}

export function simplifyMessage(m) {
  const h = headerMap(m.payload);
  return {
    id: m.id,
    threadId: m.threadId,
    labelIds: m.labelIds || [],
    internalDate: Number(m.internalDate),
    headers: h,
    from: parseAddress(h.from || ''),
    replyTo: h['reply-to'] ? parseAddress(h['reply-to']) : null,
    to: h.to || '',
    deliveredTo: h['delivered-to'] || h['x-original-to'] || '',
    subject: h.subject || '',
    messageId: h['message-id'] || '',
    references: h.references || '',
    text: messageText(m.payload),
  };
}

// ---------- drafts ----------

function encodeHeader(v) {
  return /^[\x20-\x7e]*$/.test(v) ? v : `=?UTF-8?B?${Buffer.from(v).toString('base64')}?=`;
}

export function buildRaw({ from, to, subject, body, inReplyTo, references }) {
  const lines = [
    `From: ${from}`,
    to ? `To: ${to}` : null,
    `Subject: ${encodeHeader(subject)}`,
    inReplyTo ? `In-Reply-To: ${inReplyTo}` : null,
    inReplyTo ? `References: ${[references, inReplyTo].filter(Boolean).join(' ')}` : null,
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset="UTF-8"',
    'Content-Transfer-Encoding: base64',
    '',
    Buffer.from(body).toString('base64').replace(/.{76}/g, '$&\r\n'),
  ].filter((l) => l !== null);
  return Buffer.from(lines.join('\r\n')).toString('base64url');
}

export async function createDraft({ threadId, ...msg }) {
  const draft = await gmail('POST', '/drafts', { message: { raw: buildRaw(msg), ...(threadId ? { threadId } : {}) } });
  return { draftId: draft.id, messageId: draft.message?.id };
}

export async function ensureLabel(name) {
  const { labels = [] } = (await gmail('GET', '/labels')) || {};
  const found = labels.find((l) => l.name === name);
  if (found) return found.id;
  const made = await gmail('POST', '/labels', { name, labelListVisibility: 'labelShow', messageListVisibility: 'show' });
  return made.id;
}

export async function labelThread(threadId, labelIds) {
  return gmail('POST', `/threads/${threadId}/modify`, { addLabelIds: labelIds });
}

export function gmailThreadLink(threadId) {
  return `https://mail.google.com/mail/?authuser=${encodeURIComponent(GMAIL_USER())}#all/${threadId}`;
}
