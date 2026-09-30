// Zoho Mail REST — READ-ONLY helpers for hello@villacinema.com.
// Sending lives in sendgate.js only (tests enforce this).
import { requireEnv, env, VC_FROM } from './env.js';
import { kvGet, kvSet } from './db.js';

export const zohoBase = () => `https://mail.zoho.${env('ZOHO_DC', 'com')}`;
const accountsBase = () => `https://accounts.zoho.${env('ZOHO_DC', 'com')}`;

let token = null;
export async function zohoToken() {
  if (token && token.exp > Date.now() + 60000) return token.value;
  const res = await fetch(`${accountsBase()}/oauth/v2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      refresh_token: requireEnv('ZOHO_REFRESH_TOKEN'),
      client_id: requireEnv('ZOHO_CLIENT_ID'),
      client_secret: requireEnv('ZOHO_CLIENT_SECRET'),
      grant_type: 'refresh_token',
    }),
  });
  const data = await res.json();
  if (!res.ok || !data.access_token) throw new Error(`Zoho token refresh failed: ${JSON.stringify(data).slice(0, 200)}`);
  token = { value: data.access_token, exp: Date.now() + (data.expires_in || 3600) * 1000 };
  return token.value;
}

export async function zohoGet(path) {
  if (!/^\/api\/accounts/.test(path)) throw new Error('zohoGet: unexpected path');
  const res = await fetch(`${zohoBase()}${path}`, {
    headers: { Authorization: `Zoho-oauthtoken ${await zohoToken()}`, Accept: 'application/json' },
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`Zoho GET ${path.split('?')[0]} → ${res.status}: ${text.slice(0, 300)}`);
  return JSON.parse(text);
}

// accountId + inbox folderId, cached in kv.
export async function zohoAccount() {
  const cached = await kvGet('zoho_account', null);
  if (cached?.accountId && cached?.inboxId && cached.email === VC_FROM()) return cached;
  const { data: accounts } = await zohoGet('/api/accounts');
  const acct = accounts.find((a) => (a.primaryEmailAddress || '').toLowerCase() === VC_FROM()) || accounts[0];
  if (!acct) throw new Error('No Zoho mail account visible to this token');
  const { data: folders } = await zohoGet(`/api/accounts/${acct.accountId}/folders`);
  const inbox = folders.find((f) => (f.folderType || '').toLowerCase() === 'inbox' || f.folderName === 'Inbox');
  const info = { accountId: String(acct.accountId), inboxId: String(inbox.folderId), email: VC_FROM() };
  await kvSet('zoho_account', info);
  return info;
}

export async function listInbox(limit = 50) {
  const { accountId, inboxId } = await zohoAccount();
  const { data } = await zohoGet(`/api/accounts/${accountId}/messages/view?folderId=${inboxId}&limit=${limit}&sortorder=false`);
  return (data || []).map((m) => ({
    messageId: String(m.messageId),
    folderId: String(m.folderId),
    threadId: m.threadId ? String(m.threadId) : null,
    from: String(m.fromAddress || '').toLowerCase().replace(/^.*<([^>]+)>.*$/, '$1'),
    sender: m.sender || '',
    subject: m.subject || '',
    summary: m.summary || '',
    receivedTime: Number(m.receivedTime),
  }));
}

export async function messageContent(folderId, messageId) {
  const { accountId } = await zohoAccount();
  const { data } = await zohoGet(`/api/accounts/${accountId}/folders/${folderId}/messages/${messageId}/content`);
  return data?.content || '';
}
