// Environment access. Secrets live in GitHub Actions secrets, never in code.

export function env(name, fallback = undefined) {
  const v = process.env[name];
  return v === undefined || v === '' ? fallback : v;
}

export function requireEnv(name) {
  const v = env(name);
  if (v === undefined) throw new Error(`Missing environment variable ${name}`);
  return v;
}

export function hasEnv(...names) {
  return names.every((n) => env(n) !== undefined);
}

export const GMAIL_USER = () => env('GMAIL_USER', 'hello@nashvillebuys.com').toLowerCase();
export const VC_FROM = () => env('ZOHO_FROM', 'hello@villacinema.com').toLowerCase();
export const FILMS_BASE_URL = () => env('VC_FILMS_BASE_URL', 'https://films.villacinema.com').replace(/\/$/, '');
