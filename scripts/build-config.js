// Vercel build step: writes dashboard/config.js from environment variables so no keys live in the repo.
// The anon key is designed to be public; Row Level Security limits all data to Bobby's login.
import { writeFileSync } from 'node:fs';

const need = ['SUPABASE_URL', 'SUPABASE_ANON_KEY'];
const missing = need.filter((k) => !process.env[k]);
if (missing.length) {
  console.error(`Missing Vercel environment variables: ${missing.join(', ')}`);
  process.exit(1);
}
const cfg = {
  supabaseUrl: process.env.SUPABASE_URL.replace(/\/$/, ''),
  supabaseAnonKey: process.env.SUPABASE_ANON_KEY,
  gmailUser: process.env.GMAIL_USER || 'hello@nashvillebuys.com',
  allowedEmail: 'bobbybands888@gmail.com',
  githubRepo: process.env.GITHUB_REPO || 'BobbyBands888/ownvista-hq',
};
writeFileSync(new URL('../dashboard/config.js', import.meta.url), `window.HQ_CONFIG = ${JSON.stringify(cfg, null, 2)};\n`);
console.log('dashboard/config.js written');
