// Book Studio (Amazon KDP): royalty rule, weekly title cap, banned words, cover math, seed, status moves,
// and proof that nothing in the lane can log into Amazon, publish or change a price.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import {
  royaltyRate, royalty, printCost, priceAdvice, DEFAULT_PRICE, weekStart, weekKey, slotsLeft, uploadAfter, WEEKLY_CAP,
  bannedWords, vetText, cleanKeywords, cleanHtml, vetListing, coverSize, seedBooks, SEED, applyPatches, canMove, STATUSES,
  pickNext, mandalaConfig, uploadPack, weeklyReview, OCCASIONS, EVERGREEN,
} from '../agents/lib/books.js';
import { SCHEDULE, isDue } from '../agents/router.js';

const src = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8').split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n');

test('Royalty rule: under $9.99 earns 50%, $9.99 and up earns 60%, minus print cost', () => {
  assert.equal(royaltyRate(9.98), 0.5);
  assert.equal(royaltyRate(9.99), 0.6);
  assert.equal(royaltyRate(12), 0.6);
  assert.equal(royaltyRate(6.99), 0.5);
  assert.deepEqual(royalty(6.99, 2.84), { price: 6.99, rate: 0.5, print_cost: 2.84, per_sale: 0.66 });
  assert.deepEqual(royalty(9.99, 2.84), { price: 9.99, rate: 0.6, print_cost: 2.84, per_sale: 3.15 });
  assert.equal(royalty(7.99, 2.84).per_sale, 1.16);
  assert.equal(DEFAULT_PRICE, 9.99);
  assert.equal(printCost(84), 2.84);
  assert.equal(printCost(102), 2.84);
  const halloween = SEED.find((b) => b.kdp_title_id === 'GH7JB8TCVT6');
  const a = priceAdvice(halloween);
  assert.equal(a.current.per_sale, 0.66);
  assert.equal(a.recommended.price, 9.99);
  assert.equal(priceAdvice({ pages: 84 }).recommended.per_sale, 3.15, 'stored print cost or $2.84 default');
  assert.equal(priceAdvice({ pages: 84, print_cost: 3.1 }).recommended.print_cost, 3.1, 'known print cost wins');
});

test('Weekly cap: KDP week starts Sunday 00:00 UTC; max 2 new titles counting created + waiting', () => {
  assert.equal(WEEKLY_CAP, 2);
  assert.equal(weekKey(new Date('2026-10-03T23:59:59Z')), '2026-09-27'); // Saturday night UTC
  assert.equal(weekKey(new Date('2026-10-04T00:00:00Z')), '2026-10-04'); // Sunday 00:00 UTC
  assert.equal(weekKey(new Date('2026-10-03T21:00:00-04:00')), '2026-10-04', 'Sat 9pm New York is already Sunday UTC');
  assert.equal(weekStart(new Date('2026-10-01T12:00:00Z')).toISOString(), '2026-09-27T00:00:00.000Z');
  const seeded = seedBooks([]).books;
  // Oct 1: two titles created this week, one waiting → no room.
  assert.equal(slotsLeft(seeded, new Date('2026-10-03T23:59:00Z')), 0);
  // Sunday: the two creations are last week's; Christmas Mandalas still waits → one slot.
  assert.equal(slotsLeft(seeded, new Date('2026-10-04T00:00:00Z')), 1);
  assert.equal(uploadAfter(seeded, new Date('2026-10-01T12:00:00Z')), '2026-10-04');
  assert.equal(uploadAfter(seeded, new Date('2026-10-05T12:00:00Z')), '2026-10-05');
  const full = [...seeded.filter((b) => b.status !== 'needs_upload'), { slug: 'a', status: 'planned' }, { slug: 'b', status: 'built' }];
  assert.equal(slotsLeft(full, new Date('2026-10-05T12:00:00Z')), 0, 'two waiting books fill the week');
  assert.equal(slotsLeft([{ status: 'live', kdp_created_at: '2026-10-04T00:30:00Z' }], new Date('2026-10-05T00:00:00Z')), 1);
});

test('Banned-word filter: trademarks, KDP-banned words, off-limits themes', () => {
  for (const w of ['Grinch Coloring Book', 'Rudolph and friends', 'Disney princess', 'Pokemon pages', 'Pokémon', 'Bluey', 'Hello Kitty',
    'Amazon bestseller', '#1 coloring book', 'free bonus pages', 'Kindle edition', 'Airbnb host gift', 'landlord gifts', 'real estate agent', 'Elf on the Shelf']) {
    assert.ok(bannedWords(w).length, w);
  }
  for (const w of ['Christmas Mandalas', 'mandala coloring book for adults', 'stress relief coloring book adults', 'stocking stuffers for adults', "valentines day gifts for her"]) {
    assert.deepEqual(bannedWords(w), [], w);
  }
  assert.ok(vetText('Love & Lace Mandalas with hearts').some((p) => /hearts/.test(p)), 'generic books never promise hearts');
  assert.deepEqual(vetText('Christmas Mandalas with snowflakes and poinsettias', { motifs: 'christmas' }), []);
  assert.ok(vetText('Hand-drawn mandalas').length);
  assert.ok(vetText('call me at 617-555-1212').length);
  const { keywords, dropped } = cleanKeywords(['Grinch coloring', 'x'.repeat(51), 'mandala coloring book', 'MANDALA coloring book', 'free coloring pages', 'gift for women']);
  assert.deepEqual(keywords, ['mandala coloring book', 'gift for women']);
  assert.equal(dropped.length, 3);
  assert.equal(cleanHtml('<p><strong>Hi</strong> <a href="x">there</a><script>bad()</script> & <ul><li>one</li></ul></p>'), '<p><b>Hi</b> therebad() &amp; <ul><li>one</li></ul></p>');
});

test('Every planned title and subtitle on the calendar passes the filter', () => {
  for (const o of [...OCCASIONS.filter((x) => x.supported !== false), ...EVERGREEN]) {
    assert.deepEqual(vetText(`${o.title}\n${o.subtitle}`, { motifs: o.motifs || 'generic' }), [], o.title);
    assert.ok(o.subtitle.length <= 200 && `${o.title}${o.subtitle}`.length < 200, `${o.title}: KDP title+subtitle under 200 chars`);
  }
  for (const s of SEED) assert.deepEqual(bannedWords(`${s.title}\n${s.subtitle}`), [], s.title);
});

test('Listing vetting keeps 7 clean keywords and falls back on a bad description', () => {
  const book = { slug: 'love-and-lace-mandalas-2027', title: 'Love & Lace Mandalas', subtitle: 'An Adult Coloring Book', author: 'Evergreen Atelier', kind: 'adult_mandala', motifs: 'generic', pages: 84, designs: 40 };
  const good = vetListing({ description: `<p>${'Calm lace and petal designs. '.repeat(10)}</p><ul><li>40 designs</li></ul>`, keywords: ['lace mandala coloring book', 'Disney coloring'] }, book);
  assert.ok(good.ok);
  assert.equal(good.listing.keywords.length, 7);
  assert.ok(good.listing.keywords.every((k) => k.length <= 50 && !bannedWords(k).length));
  assert.ok(good.dropped.some((d) => /Disney/i.test(d)));
  assert.match(good.listing.description, /Calm lace/);
  const bad = vetListing({ description: `<p>${'Hearts and bunnies everywhere, a bestseller! '.repeat(6)}</p>` }, book);
  assert.doesNotMatch(bad.listing.description, /bestseller|Hearts/);
  assert.ok(bad.listing.categories.length >= 2 && bad.listing.categories.length <= 3);
  assert.equal(bad.listing.ai.texts.detail, 'Entire work');
  assert.equal(bad.listing.ai.images.detail, 'Many AI-generated images');
  assert.equal(bad.listing.ai.texts.tool, 'Claude');
  assert.equal(bad.listing.ai.translations.answer, 'None');
});

test('Spine and cover math: pages x 0.002252 in, 2 x 0.125 bleed + 2 x 8.5 trim + spine', () => {
  assert.deepEqual(coverSize(84), { spine: 0.189168, width: 17.4392, height: 11.25 });
  assert.equal(coverSize(102).width, 17.4797);
  assert.equal(coverSize(24).spine, 0.054048);
  // The Python builder uses the same constants.
  const py = readFileSync(new URL('../agents/books/engines/build.py', import.meta.url), 'utf8');
  assert.match(py, /TRIM_W, TRIM_H, BLEED_IN, SPINE_PER_PAGE = 8\.5, 11\.0, 0\.125, 0\.002252/);
  assert.match(py, /sys\.exit\(0 if res\['ok'\] else 1\)/, 'builder fails when pypdf checks fail');
});

test('Mandala configs: Christmas reproduces the original; others use only generic motifs', () => {
  const xmas = JSON.parse(readFileSync(new URL('../agents/books/engines/mandala/configs/christmas-mandalas.json', import.meta.url), 'utf8'));
  assert.equal(xmas.pages, 84);
  assert.equal(xmas.plan.length, 40);
  assert.equal(4 + 2 * xmas.plan.length, 84);
  const seasonalOnly = /^(holly|pine|flakes|ornaments|bells|poinsettia|snowflake)$/;
  for (const today of ['2026-10-01', '2026-12-01', '2027-03-01', '2027-06-20']) {
    const b = pickNext([], today);
    const cfg = mandalaConfig(b);
    assert.equal(cfg.motifs, 'generic', today);
    assert.equal(cfg.pages, 84);
    assert.equal(new Set(cfg.plan.map((p) => p.name)).size, 40, 'unique design names');
    for (const p of cfg.plan) {
      assert.ok(['classic', 'quilt', 'bands', 'trio'].includes(p.kind), p.kind);
      assert.ok(!seasonalOnly.test(p.center || ''), p.center);
      assert.notEqual(p.bg, 'snow');
    }
    assert.ok(!cfg.cover.mandala.themes.some((t) => seasonalOnly.test(t)));
    for (const t of cfg.cover.thumbs) assert.ok(!seasonalOnly.test(t.center));
  }
});

test('Planner: seasonal books 5-12 weeks ahead, skips covered and unsupported occasions, then evergreen', () => {
  assert.equal(pickNext([], '2026-10-01').occasion, 'thanksgiving');
  assert.equal(pickNext([], '2026-10-01').occasion_date, '2026-11-26');
  assert.equal(pickNext([], '2026-10-01').live_by, '2026-10-29', 'live 4 weeks before');
  // Christmas 2026 is 85 days out on Oct 1 (outside the window); Christmas is covered by the seed anyway.
  const seeded = seedBooks([]).books;
  const withThanks = [...seeded, { slug: 't', kind: 'adult_mandala', occasion: 'thanksgiving', occasion_year: 2026 }];
  assert.equal(pickNext(withThanks, '2026-11-01').evergreen, 'floral', 'Christmas 2026 already has a mandala book');
  assert.notEqual(pickNext([], '2027-09-01').occasion, 'halloween', 'Halloween needs drawings v1 does not have');
  assert.notEqual(pickNext([], '2027-01-25').occasion, 'st_patricks');
  const all = EVERGREEN.map((e) => ({ evergreen: e.key }));
  assert.equal(pickNext(all, '2026-05-20'), null, 'no occasion in its window and every evergreen title used');
  for (const o of OCCASIONS.filter((x) => x.supported !== false)) {
    const b = pickNext([], new Date(o.date(2027) - 50 * 86400000).toISOString().slice(0, 10));
    assert.equal(b.occasion, o.key, o.key);
    assert.ok(b.live_by < b.occasion_date);
  }
});

test('Seed is idempotent and matches Bobby\'s books', () => {
  const now = '2026-10-01T12:00:00Z';
  const first = seedBooks([], SEED, now);
  assert.equal(first.added, 3);
  const again = seedBooks(first.books, SEED, now);
  assert.equal(again.added, 0);
  assert.deepEqual(again.books, first.books);
  // An edited existing book (matched by KDP id even if the slug differs) is never overwritten.
  const edited = [{ slug: 'my-halloween', kdp_title_id: 'GH7JB8TCVT6', status: 'live', list_price: 9.99 }];
  const merged = seedBooks(edited, SEED, now);
  assert.equal(merged.added, 2);
  assert.equal(merged.books[0].status, 'live');
  const by = Object.fromEntries(first.books.map((b) => [b.slug, b]));
  const h = by['cute-halloween-coloring-book-for-kids'];
  assert.equal(h.status, 'in_review'); assert.equal(h.list_price, 6.99); assert.equal(h.author, 'Little Pumpkin Press');
  const t = by['christmas-coloring-book-for-toddlers'];
  assert.equal(t.kdp_title_id, 'EHB1H1HFNNN'); assert.equal(t.pages, 102); assert.equal(t.print_cost, 2.84); assert.equal(t.check_on, '2026-11-15');
  const m = by['christmas-mandalas'];
  assert.equal(m.status, 'needs_upload'); assert.equal(m.author, 'Evergreen Atelier'); assert.equal(m.pages, 84); assert.equal(m.upload_after, '2026-10-04');
  assert.ok(existsSync(new URL(`../${m.config_path}`, import.meta.url)));
});

test('Status transitions: agent only reaches needs_upload; humans record KDP steps in order', () => {
  assert.deepEqual(STATUSES, ['planned', 'built', 'needs_upload', 'uploaded_draft', 'in_review', 'live', 'paused']);
  assert.ok(canMove('planned', 'built', 'agent'));
  assert.ok(canMove('built', 'needs_upload', 'agent'));
  for (const to of ['uploaded_draft', 'in_review', 'live']) assert.ok(!canMove('needs_upload', to, 'agent'), `agent can't reach ${to}`);
  assert.ok(canMove('needs_upload', 'uploaded_draft'));
  assert.ok(canMove('uploaded_draft', 'in_review'));
  assert.ok(canMove('in_review', 'live'));
  assert.ok(canMove('live', 'paused'));
  assert.ok(!canMove('needs_upload', 'live'), 'no skipping review');
  assert.ok(!canMove('planned', 'live'));
  assert.ok(!canMove('live', 'bogus'));
  // A change made on the Shop page meanwhile is never overwritten by an agent patch that saw an older status.
  const fresh = [{ slug: 'a', status: 'uploaded_draft', history: [] }];
  const { books, skipped } = applyPatches(fresh, [{ slug: 'a', expect: 'needs_upload', set: { status: 'needs_upload', listing: {} } }]);
  assert.equal(books[0].status, 'uploaded_draft');
  assert.deepEqual(skipped, ['a']);
  const moved = applyPatches(fresh, [{ slug: 'a', expect: 'uploaded_draft', set: { status: 'in_review' }, by: 'bobby' }], '2026-10-02T00:00:00Z');
  assert.equal(moved.books[0].status, 'in_review');
  assert.equal(moved.books[0].history.at(-1).by, 'bobby');
});

test('Upload pack lists every KDP field in order and the weekly review says who does what', () => {
  const m = seedBooks([]).books.find((b) => b.slug === 'christmas-mandalas');
  const pack = uploadPack({ ...m, files: { interior: 'christmas-mandalas/interior.pdf', cover: 'christmas-mandalas/cover.pdf' } });
  assert.deepEqual(pack.sections.map((s) => s.name), ['Paperback Details', 'Paperback Content', 'Paperback Rights & Pricing']);
  const f = Object.fromEntries(pack.sections.flatMap((s) => s.fields));
  assert.equal(f['Book Title'], 'Christmas Mandalas');
  assert.equal(f['Primary Author or Contributor (pen name) - First name'], 'Evergreen');
  assert.match(f['Book cover'], /17\.4392/);
  assert.match(f['List price (USD)'], /^9\.99/);
  assert.match(f['Royalty at that price'], /\$3\.15/);
  assert.equal(pack.sections[0].fields.filter(([k]) => /^Keyword/.test(k)).length, 7);
  assert.ok(pack.checklist.some((c) => /Stop before "Publish/.test(c)), 'Claude never clicks Publish');
  assert.equal(pack.upload_after, '2026-10-04');
  const r = weeklyReview([...seedBooks([]).books.map((b) => (b.slug === 'christmas-mandalas' ? { ...b, files: { interior: 'x' } } : b))], '2026-10-01');
  assert.match(r.line, /^Amazon review: needs upload 1 · in review 2\./);
  assert.ok(r.claude.some((c) => /Christmas Mandalas.*2026-10-04/.test(c)));
  const later = weeklyReview(seedBooks([]).books.map((b) => (b.kdp_title_id === 'GH7JB8TCVT6' ? { ...b, status: 'live' } : b)), '2026-11-16');
  assert.ok(later.bobby.some((x) => /raise .*Halloween.* \$9\.99/.test(x)));
  assert.ok(later.bobby.some((x) => /7\.99/.test(x)));
});

test('Book Studio never touches Amazon, publishes, spends or sends; it is wired and scheduled once a day off-peak', () => {
  const forbidden = /(https?:\/\/[^\s'"`]*amazon|kdp\.amazon\.com|sellercentral|sendgate|gmail\.js|zoho\.js|minimax|spend\.js|stripe(_launch)?\.js|cfimage|createDraft|puppeteer|playwright|selenium)/i;
  for (const f of ['agents/lab/book_studio.js', 'agents/lib/books.js', 'api/books.js']) assert.doesNotMatch(src(f), forbidden, f);
  assert.doesNotMatch(src('agents/lab/book_studio.js'), /\blist_price\s*:/, 'agent never sets a price');
  assert.match(src('agents/runner.js'), /book_studio: \(\) => import\('\.\/lab\/book_studio\.js'\)/);
  assert.match(src('agents/runner.js'), /book_studio: \{ name: 'Book Studio'/);
  assert.match(readFileSync(new URL('../.github/workflows/hq.yml', import.meta.url), 'utf8'), /- book_studio\n[\s\S]*pip install --quiet --disable-pip-version-check reportlab pypdf/);
  const s = SCHEDULE.find((x) => x.id === 'book_studio');
  assert.equal(s.type, 'daily');
  assert.ok(s.hour >= 1 && s.hour <= 5, 'off-peak');
  assert.ok(isDue(s, new Date('2026-10-02T07:07:00Z'), []), 'due 3:07am EDT');
  assert.ok(!isDue(s, new Date('2026-10-02T07:07:00Z'), [{ status: 'ok', started_at: '2026-10-02T07:07:30Z' }]));
  assert.ok(!isDue(s, new Date('2026-10-02T16:07:00Z'), [{ status: 'ok', started_at: '2026-10-02T07:07:30Z' }]), 'once a day');
  // The dashboard goes through the API route, never straight to the books kv row.
  const shop = src('dashboard/js/views/shop.js');
  assert.match(shop, /fetch\('\/api\/books'/);
  assert.doesNotMatch(shop, /amazon_books/);
  assert.match(src('api/books.js'), /canMove\(book\.status, body\.status, 'human'\)/);
});
