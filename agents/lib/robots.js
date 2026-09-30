// robots.txt check (RFC 9309). 4xx = no rules (allowed); 5xx / network error = disallowed.
export const USER_AGENT = 'OwnvistaHQ-Researcher/1.0 (+https://levelingclips.com)';
const TOKEN = 'ownvistahq-researcher';
const cache = new Map();

export function parseRobots(text) {
  const groups = [];
  let cur = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/#.*/, '').trim();
    if (!line) continue;
    const i = line.indexOf(':');
    if (i < 0) continue;
    const key = line.slice(0, i).trim().toLowerCase();
    const val = line.slice(i + 1).trim();
    if (key === 'user-agent') {
      if (!cur || cur.rules.length) { cur = { agents: [], rules: [] }; groups.push(cur); }
      cur.agents.push(val.toLowerCase());
    } else if ((key === 'allow' || key === 'disallow') && cur) {
      cur.rules.push({ allow: key === 'allow', path: val });
    }
  }
  return groups;
}

export function isAllowed(groups, pathAndQuery) {
  const mine = groups.filter((g) => g.agents.some((a) => a !== '*' && TOKEN.startsWith(a)));
  const group = mine.length ? mine : groups.filter((g) => g.agents.includes('*'));
  const rules = group.flatMap((g) => g.rules);
  let best = null;
  for (const r of rules) {
    if (!r.path) continue;
    const re = new RegExp('^' + r.path.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\\\$$/, '$'));
    if (re.test(pathAndQuery) && (!best || r.path.length > best.path.length || (r.path.length === best.path.length && r.allow))) best = r;
  }
  return !best || best.allow;
}

export async function robotsAllowed(url) {
  const u = new URL(url);
  let groups = cache.get(u.origin);
  if (groups === undefined) {
    try {
      const res = await fetch(`${u.origin}/robots.txt`, { headers: { 'user-agent': USER_AGENT }, signal: AbortSignal.timeout(10000) });
      if (res.ok) groups = parseRobots(await res.text());
      else if (res.status >= 400 && res.status < 500) groups = [];
      else groups = null;
    } catch {
      groups = null;
    }
    cache.set(u.origin, groups);
  }
  if (groups === null) return false;
  return isAllowed(groups, u.pathname + u.search);
}

// Polite fetch of a public page: robots check, identified user agent, timeout, size cap.
export async function politeFetch(url, { headers = {}, maxBytes = 2_000_000 } = {}) {
  if (!/^https?:\/\//i.test(url)) throw new Error('only http(s) URLs');
  if (!(await robotsAllowed(url))) {
    const e = new Error(`robots.txt disallows ${url}`);
    e.robots = true;
    throw e;
  }
  const res = await fetch(url, { headers: { 'user-agent': USER_AGENT, ...headers }, redirect: 'follow', signal: AbortSignal.timeout(20000) });
  const buf = Buffer.from(await res.arrayBuffer());
  return { res, text: buf.subarray(0, maxBytes).toString('utf8') };
}
