// "Nothing sends from Gmail" and "only sendgate.js can send Villa Cinema email" — proven here.
// Runs before every agent job; a failure stops the job before any agent starts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { assertAllowed } from '../agents/lib/gmail.js';

const ROOT = new URL('..', import.meta.url).pathname;

function files(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return f === 'node_modules' || f.startsWith('.') ? [] : files(p);
    return p.endsWith('.js') ? [p] : [];
  });
}
const code = [...files(join(ROOT, 'agents')), ...files(join(ROOT, 'api')), ...files(join(ROOT, 'dashboard')), ...files(join(ROOT, 'scripts'))]
  .map((p) => ({ path: relative(ROOT, p), text: readFileSync(p, 'utf8') }));

test('Gmail allowlist refuses every send-capable call', () => {
  for (const [m, p] of [
    ['POST', '/messages/send'], ['POST', '/drafts/send'], ['POST', '/messages'], ['POST', '/messages/import'],
    ['POST', '/messages/insert'], ['PUT', '/settings/forwardingAddresses'], ['POST', '/settings/filters'],
    ['POST', '/settings/sendAs'], ['DELETE', '/drafts/abc'], ['POST', '/threads/abc/trash'], ['POST', '/messages/abc/send'],
  ]) {
    assert.throws(() => assertAllowed(m, p), /refused/, `${m} ${p} must be refused`);
  }
});

test('Gmail allowlist permits the drafting calls agents need', () => {
  for (const [m, p] of [['POST', '/drafts'], ['PUT', '/drafts/r123'], ['GET', '/threads?q=in%3Ainbox'], ['GET', '/threads/abc?format=full'], ['POST', '/threads/abc/modify'], ['GET', '/labels']]) {
    assert.doesNotThrow(() => assertAllowed(m, p), `${m} ${p} should be allowed`);
  }
});

test('No code anywhere references a Gmail send endpoint or send scope', () => {
  const bad = /(messages\/send|drafts\/send|gmail\.send|auth\/gmail\.send|mail\.google\.com\/?["'`]|nodemailer|smtp\.gmail|sendmail)/i;
  const offenders = code.filter((f) => f.path !== 'agents/lib/gmail.js' && bad.test(f.text)).map((f) => f.path);
  assert.deepEqual(offenders, []);
});

test('gmail.js only talks to Gmail through the allowlisted helper', () => {
  const g = code.find((f) => f.path === 'agents/lib/gmail.js').text;
  const fetches = g.match(/fetch\(/g) || [];
  assert.equal(fetches.length, 2, 'exactly two fetch calls: token refresh + the guarded gmail() helper');
  assert.match(g, /assertAllowed\(method, path\);\s*\n\s*const res = await fetch/);
});

test('Only lib/sendgate.js can send email through Zoho', () => {
  const sendMarkers = /(mailFormat|fromAddress|action:\s*'reply'|zohoToken\(\))/;
  const offenders = code
    .filter((f) => !['agents/lib/sendgate.js', 'agents/lib/zoho.js'].includes(f.path) && sendMarkers.test(f.text))
    .map((f) => f.path);
  assert.deepEqual(offenders, []);
  const zoho = code.find((f) => f.path === 'agents/lib/zoho.js').text;
  assert.doesNotMatch(zoho, /mailFormat|toAddress|action: 'reply'/, 'zoho.js must stay read-only');
  assert.doesNotMatch(zoho.replace(/method: 'POST',\s*\n\s*headers: \{ 'Content-Type': 'application\/x-www-form-urlencoded' \}/, ''), /method:\s*'POST'/, 'only the token refresh may POST in zoho.js');
});

test('sendgate reserves in the database before it sends', () => {
  const s = code.find((f) => f.path === 'agents/lib/sendgate.js').text;
  const reserve = s.indexOf("db.rpc('vc_reserve_send'");
  const post = s.indexOf("method: 'POST'");
  assert.ok(reserve > 0 && post > reserve, 'vc_reserve_send must come before the POST');
  assert.match(s, /if \(!gate\?\.ok\) return/);
  assert.match(s, /endsWith\('@villacinema\.com'\)/);
});

test('MiniMax calls require a spend reservation', async () => {
  const mm = await import('../agents/lib/minimax.js');
  await assert.rejects(() => mm.createClip({ prompt: 'x', imageUrl: 'https://x' }), /spend reservation/);
  await assert.rejects(() => mm.createUpgrade({ prompt: 'x', imageUrl: 'https://x', baseVideoUrl: 'https://x' }), /spend reservation/);
  const users = code.filter((f) => /minimax\.create(Clip|Upgrade)\(/.test(f.text)).map((f) => f.path);
  assert.deepEqual(users, ['agents/villa/studio.js']);
  const studio = code.find((f) => f.path === 'agents/villa/studio.js').text;
  for (const m of studio.matchAll(/minimax\.create(Clip|Upgrade)\(\{ spendId/g)) assert.ok(m);
});

test('No other paid APIs are called', () => {
  const paid = /(api\.openai\.com|generativelanguage\.googleapis|api\.replicate|api\.runwayml|api\.stripe\.com\/v1\/(charges|payment_intents|refunds|transfers|payouts))/;
  assert.deepEqual(code.filter((f) => paid.test(f.text)).map((f) => f.path), []);
});
