#!/usr/bin/env node
// One-time helper: exchanges a Zoho Self Client grant code for a refresh token.
// Run it on your own computer:  node scripts/zoho-token.js
// It asks for the values (nothing is saved or sent anywhere except Zoho's token endpoint),
// then prints the refresh token for you to paste into the GitHub secret ZOHO_REFRESH_TOKEN.
import { createInterface } from 'node:readline/promises';
import { stdin, stdout } from 'node:process';

const rl = createInterface({ input: stdin, output: stdout });
const dc = (await rl.question('Zoho data center (com, eu, in, com.au, jp, ca) [com]: ')).trim() || 'com';
const clientId = (await rl.question('Client ID: ')).trim();
const clientSecret = (await rl.question('Client Secret: ')).trim();
const code = (await rl.question('Grant code (from "Generate Code", valid 10 minutes): ')).trim();
rl.close();

const res = await fetch(`https://accounts.zoho.${dc}/oauth/v2/token`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ grant_type: 'authorization_code', client_id: clientId, client_secret: clientSecret, code }),
});
const data = await res.json();
if (!data.refresh_token) {
  console.error('\nZoho did not return a refresh token:', data.error || JSON.stringify(data));
  console.error('Generate a fresh code (they expire after 10 minutes and work once) and try again.');
  process.exit(1);
}
console.log('\nRefresh token (paste into GitHub → Settings → Secrets and variables → Actions → ZOHO_REFRESH_TOKEN):\n');
console.log(data.refresh_token);
console.log('\nThen clear your terminal (Cmd+K).');
