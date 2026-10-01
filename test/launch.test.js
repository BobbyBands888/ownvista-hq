// Launcher + Asset Studio guardrails: Stripe can only create offers and read sales; pages can't run script;
// images only come from Cloudflare's free plan through one capped helper.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { assertStripeAllowed } from '../agents/lib/stripe_launch.js';
import { sanitizeHtml, buildPublicPage, slugify } from '../agents/lib/page.js';
import { mdToHtml } from '../api/p.js';

const ROOT = new URL('..', import.meta.url).pathname;
const files = (dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? files(p) : p.endsWith('.js') ? [p] : [];
});
const code = ['agents', 'api', 'dashboard', 'scripts'].flatMap((d) => files(join(ROOT, d))).map((p) => ({ path: relative(ROOT, p), text: readFileSync(p, 'utf8') }));

test('Launcher Stripe key can only create offers, deactivate links and read sessions', () => {
  for (const [m, p] of [['POST', '/v1/products'], ['POST', '/v1/prices'], ['POST', '/v1/payment_links'], ['POST', '/v1/payment_links/plink_abc123'], ['GET', '/v1/checkout/sessions']]) {
    assert.doesNotThrow(() => assertStripeAllowed(m, p), `${m} ${p}`);
  }
  for (const [m, p] of [
    ['POST', '/v1/charges'], ['POST', '/v1/refunds'], ['POST', '/v1/transfers'], ['POST', '/v1/payouts'], ['POST', '/v1/payment_intents'],
    ['POST', '/v1/customers'], ['DELETE', '/v1/products/prod_1'], ['POST', '/v1/checkout/sessions'], ['POST', '/v1/payment_links/plink_1/line_items'],
    ['GET', '/v1/customers'], ['POST', '/v1/accounts'],
  ]) {
    assert.throws(() => assertStripeAllowed(m, p), /refused/, `${m} ${p} must be refused`);
  }
});

test('Only the two Stripe helpers talk to Stripe; only cfimage.js talks to Cloudflare AI', () => {
  const stripe = code.filter((f) => /api\.stripe\.com/.test(f.text)).map((f) => f.path).sort();
  assert.deepEqual(stripe, ['agents/lib/stripe.js', 'agents/lib/stripe_launch.js']);
  const cf = code.filter((f) => /api\.cloudflare\.com/.test(f.text)).map((f) => f.path);
  assert.deepEqual(cf, ['agents/lib/cfimage.js']);
  assert.ok(!code.some((f) => /(requireEnv|hasEnv|env)\(['"]STRIPE_LAUNCH_KEY/.test(f.text) && f.path !== 'agents/lib/stripe_launch.js'), 'launch key used only in stripe_launch.js');
});

test('Published pages cannot run script', () => {
  const dirty = `<html><head><script>alert(1)</script><meta http-equiv="refresh" content="0;url=https://evil"></head>
<body><a href="javascript:alert(1)" onclick="x()">x</a><iframe src="https://evil"></iframe><form action="https://evil"><input></form>
<img src=x onerror=alert(1)><a href="{{BUY_URL}}">Buy</a></body></html>`;
  const clean = sanitizeHtml(dirty);
  for (const bad of [/<script/i, /onclick/i, /onerror/i, /javascript:/i, /<iframe/i, /<form/i, /http-equiv/i]) assert.ok(!bad.test(clean), `${bad} removed`);
  const page = buildPublicPage({ html: dirty, title: 'Kit', priceUsd: 49, buyUrl: 'https://buy.stripe.com/test_123', status: 'live' });
  assert.ok(page.includes('href="https://buy.stripe.com/test_123">Buy</a>'), 'placeholder replaced');
  assert.ok(/Buy now/.test(page) && /\$49/.test(page));
  const killed = buildPublicPage({ html: dirty, title: 'Kit', priceUsd: 49, buyUrl: 'https://buy.stripe.com/test_123', status: 'killed' });
  assert.ok(!killed.includes('buy.stripe.com') && /no longer available/.test(killed));
});

test('Delivery markdown is escaped', () => {
  const h = mdToHtml('# Title\n<script>alert(1)</script>\n- **one**\n- two');
  assert.ok(!/<script/.test(h) && /<h1>Title<\/h1>/.test(h) && /<li><strong>one<\/strong><\/li>/.test(h));
  assert.equal(slugify('HVAC Contractor Workflow — Toolkit!'), 'hvac-contractor-workflow-toolkit');
});

test('Launcher product quality bar: thin, file-referencing or unfinished products cannot launch', async () => {
  const { productProblems, assemble } = await import('../agents/lab/product.js');
  const section = (h, extra = '') => `## ${h}\n\n${'Concrete step with a real example for the contractor. '.repeat(34)}\n${extra}`;
  const table = '| Job | Price | Margin |\n|---|---|---|\n| AC tune-up | $129 | 40% |\n| Furnace check | $99 | 35% |';
  const good = assemble({ title: 'Kit', promise: 'Run your week.', sections: Array.from({ length: 7 }, (_, i) => ({ heading: `Part ${i + 1}` })) },
    Array.from({ length: 7 }, (_, i) => section(`Part ${i + 1}`, i === 2 ? `Pricing template:\n\n${table}` : '')));
  assert.deepEqual(productProblems(good), [], 'complete product passes');
  assert.ok(productProblems('# Kit\n\n## One\nshort').some((p) => /too short/.test(p)));
  assert.ok(productProblems(good.replace('Pricing template', 'Download the Excel file for the pricing template')).some((p) => /buyers don't get/.test(p)));
  assert.ok(productProblems(good + '\n[Insert your logo here]').some((p) => /placeholder/.test(p)));
  assert.ok(productProblems(good.replace(table, 'Fill in the spreadsheet tracker.')).some((p) => /no table/.test(p)));
  assert.deepEqual(productProblems(good + '\nDear [Customer name],'), [], 'buyer fill-in blanks are fine');
});

test('Delivery page renders markdown tables as real tables', () => {
  const h = mdToHtml('| A | B |\n|---|---|\n| 1 | 2 |');
  assert.ok(/<table>/.test(h) && /<th>A<\/th>/.test(h) && /<td>2<\/td>/.test(h) && !/---/.test(h));
});
