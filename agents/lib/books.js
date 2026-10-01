// Book Studio rules (pure; tested in test/books.test.js). Amazon KDP has no publishing API, so nothing here
// talks to Amazon: these functions plan books, do the price and cover math, vet listing copy and lay out the
// upload pack that Claude follows in Chrome. Bobby clicks Publish on KDP himself.
import { checkCopy, realEstateRisk } from './guard.js';
import { ipRisk } from './autopilot.js';

export const KV_KEY = 'amazon_books';
export const BUCKET = 'kdp-books';

// ---------- Status ----------
export const STATUSES = ['planned', 'built', 'needs_upload', 'uploaded_draft', 'in_review', 'live', 'paused'];
// Steps the agent takes on its own (files and listing only).
export const AGENT_NEXT = { planned: ['built'], built: ['needs_upload', 'planned'] };
// Steps Bobby or Claude record from the Shop page after doing them on KDP.
export const HUMAN_NEXT = {
  needs_upload: ['uploaded_draft', 'paused'],
  uploaded_draft: ['in_review', 'needs_upload', 'paused'],
  in_review: ['live', 'uploaded_draft', 'paused'],
  live: ['paused'],
  paused: ['needs_upload', 'live'],
};
export function canMove(from, to, who = 'human') {
  const map = who === 'agent' ? AGENT_NEXT : HUMAN_NEXT;
  return STATUSES.includes(to) && (map[from] || []).includes(to);
}

// ---------- Weekly cap ----------
// KDP limits how many titles an account can create per week; its week resets Sunday 00:00 UTC.
export const WEEKLY_CAP = 2;
export function weekStart(at = new Date()) {
  const d = new Date(at);
  const day = d.getUTCDay();
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day));
}
export const weekKey = (at) => weekStart(at).toISOString().slice(0, 10);
const PENDING = ['planned', 'built', 'needs_upload'];
const when = (v) => new Date(/T/.test(String(v)) ? v : `${v}T12:00:00Z`);
const createdIn = (books, wk) => books.filter((b) => b.kdp_created_at && weekKey(when(b.kdp_created_at)) === wk).length;
// Titles created on KDP this week + books still waiting to be created. New books are planned only while
// this stays under the cap, so the upload queue can never ask KDP for a third title in one week.
export function slotsLeft(books, now = new Date(), cap = WEEKLY_CAP) {
  const created = createdIn(books, weekKey(now));
  const pending = books.filter((b) => PENDING.includes(b.status)).length;
  return Math.max(0, cap - created - pending);
}
// Earliest day Claude may create this title on KDP (next week when this week's titles are used up).
export function uploadAfter(books, now = new Date(), cap = WEEKLY_CAP) {
  const created = createdIn(books, weekKey(now));
  if (created < cap) return now.toISOString().slice(0, 10);
  return new Date(weekStart(now).getTime() + 7 * 86400000).toISOString().slice(0, 10);
}

// ---------- Price and royalty ----------
// Amazon.com paperbacks: list price under $9.99 earns 50%, $9.99 and up earns 60%. royalty = price x rate - print cost.
export const DEFAULT_PRICE = 9.99;
export const royaltyRate = (price) => (Number(price) >= 9.99 ? 0.6 : 0.5);
const cents = (n) => Math.round((Number(n) + 1e-9) * 100) / 100;
// KDP printing cost, B&W interior on white paper, 8.5 x 11 in (large trim): $2.84 flat for 24-108 pages,
// then $1.00 + $0.012 per page. A known cost stored on the book always wins.
export function printCost(pages) {
  const n = Number(pages) || 0;
  if (n <= 108) return 2.84;
  return cents(1 + 0.012 * n);
}
export function royalty(price, cost) {
  const p = Number(price);
  const rate = royaltyRate(p);
  return { price: cents(p), rate, print_cost: cents(cost), per_sale: cents(p * rate - cost) };
}
export function priceAdvice(book) {
  const cost = Number(book.print_cost) || printCost(book.pages);
  const rec = Number(book.recommended_price) || DEFAULT_PRICE;
  return {
    recommended: royalty(rec, cost),
    current: book.list_price ? royalty(book.list_price, cost) : null,
  };
}

// ---------- Cover math ----------
export const TRIM = { w: 8.5, h: 11 };
export const BLEED = 0.125;
export const SPINE_PER_PAGE = 0.002252; // white paper, B&W
export function coverSize(pages) {
  const spine = Number(pages) * SPINE_PER_PAGE;
  return { spine: +spine.toFixed(6), width: +(2 * BLEED + 2 * TRIM.w + spine).toFixed(4), height: TRIM.h + 2 * BLEED };
}

// ---------- Copy checks ----------
// Trademarked characters/brands and words KDP rejects in titles, subtitles and keywords.
const TRADEMARK = /\b(grinch|rudolph|frosty|charlie brown|snoopy|peanuts|elf on the shelf|hallmark|nutcracker suite|disney|pixar|marvel|pok[eé]mon|pikachu|hello kitty|sanrio|bluey|peppa|paw patrol|barbie|lego|minecraft|roblox|harry potter|star wars|sesame street|dr\.? seuss|cat in the hat|care bears|my little pony|garfield|scooby|spongebob|crayola|prismacolor|sharpie|copic|faber[- ]castell|zentangle|johanna basford|coca[- ]?cola|peeps|cadbury|hershey|reese'?s|m&m'?s|skittles|starbucks|squishmallows?|labubu)\b/i;
const KDP_BANNED = /#\s?1\b|\b(amazon|kindle|kdp|audible|best[- ]?sell(er|ing)|number one|free|on sale|sale|discount|cheap|new release|kindle unlimited|limited time|award[- ]winning|top[- ]rated|5[- ]star|five[- ]star)\b/i;
const OFF_LIMITS = /\b(airbnb|vrbo|short[- ]term rentals?|vacation rentals?|str hosts?|landlords?|tenants?|property managers?|real estate|realtors?|mortgages?)\b/i;
export function bannedWords(text = '') {
  const t = String(text).normalize('NFKC');
  const hits = [];
  for (const re of [TRADEMARK, KDP_BANNED, OFF_LIMITS]) { const m = re.exec(t); if (m) hits.push(m[0]); }
  const ip = ipRisk(t); if (ip && !hits.some((h) => h.toLowerCase() === ip.toLowerCase())) hits.push(ip);
  const re = realEstateRisk(t); if (re && !hits.some((h) => h.toLowerCase() === re.toLowerCase())) hits.push(re);
  return hits;
}

// Subjects a listing may name only when the book actually draws them.
const SUBJECTS = /\b(hearts?|pumpkins?|shamrocks?|clovers?|leprechauns?|eggs?|bunn(y|ies)|rabbits?|chicks?|turkeys?|leaves|leaf|acorns?|ghosts?|witch(es)?|bats?|skulls?|spiders?|santas?|reindeer|snowm[ae]n|elves|elf|gingerbread|candy canes?|butterfl(y|ies)|animals?|birds?|owls?|cats?|dogs?|fish|ocean|mermaids?|unicorns?|dinosaurs?|mushrooms?|apples?|pencils?|school ?bus|snowflakes?|poinsettias?|holly|ornaments?|wreaths?|christmas trees?|bells)\b/i;
const CHRISTMAS_DRAWN = /^(snowflakes?|poinsettias?|holly|ornaments?|wreaths?|christmas trees?|bells)$/i;
export function motifRisk(text = '', motifs = 'generic') {
  const re = new RegExp(SUBJECTS.source, 'gi');
  for (const m of String(text).matchAll(re)) {
    if (motifs === 'christmas' && CHRISTMAS_DRAWN.test(m[0])) continue;
    return m[0];
  }
  return null;
}

export function vetText(text, { motifs = 'generic', prices } = {}) {
  const problems = [...checkCopy(text, { allowLinks: [], ...(prices ? { prices } : {}) })];
  const banned = bannedWords(text);
  if (banned.length) problems.push(`banned word(s): ${banned.join(', ')}`);
  const m = motifRisk(text, motifs);
  if (m) problems.push(`names "${m}", which the book does not draw`);
  if (/\b(hand[- ]?(drawn|painted|illustrated|made)|handmade|by a human)\b/i.test(text)) problems.push('calls AI-made art hand-made');
  return problems;
}

// KDP description: only <b>, <ul>, <li>, <br>, <p>. Everything else is stripped; text is escaped.
export function cleanHtml(html = '') {
  const allowed = /^<\/?(b|ul|li|br|p)\s*\/?>$/i;
  return String(html)
    .replace(/<\/?(strong)>/gi, (t) => t.replace(/strong/i, 'b'))
    .split(/(<[^>]*>)/)
    .map((part) => (part.startsWith('<') ? (allowed.test(part) ? part.toLowerCase().replace(/\s+/g, '') : '') : part.replace(/&(?!(amp|lt|gt|quot|#39);)/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')))
    .join('')
    .slice(0, 3900);
}
export const htmlText = (html = '') => String(html).replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();

// Keywords: exactly 7 boxes, each 50 characters or fewer, no banned words, no duplicates.
export function cleanKeywords(list = [], { motifs = 'generic' } = {}) {
  const out = [], dropped = [];
  for (const raw of list) {
    const k = String(raw || '').replace(/["“”]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
    if (!k) continue;
    if (k.length > 50) { dropped.push(`${k} (over 50 chars)`); continue; }
    const p = vetText(k, { motifs });
    if (p.length) { dropped.push(`${k} (${p[0]})`); continue; }
    if (!out.includes(k)) out.push(k);
  }
  return { keywords: out.slice(0, 7), dropped };
}

// ---------- Listing ----------
export const AI_DISCLOSURE = {
  texts: { answer: 'AI-generated', detail: 'Entire work', editing: 'Minimal or no editing', tool: 'Claude' },
  images: { answer: 'AI-generated', detail: 'Many AI-generated images', editing: 'Minimal or no editing', tool: 'Claude' },
  translations: { answer: 'None' },
};

export const CATEGORIES = {
  adult_mandala: [
    'Books › Crafts, Hobbies & Home › Crafts & Hobbies › Coloring Books for Grown-Ups › Mandalas',
    'Books › Crafts, Hobbies & Home › Crafts & Hobbies › Coloring Books for Grown-Ups › Patterns',
    'Books › Self-Help › Stress Management',
  ],
  adult_mandala_christmas: [
    'Books › Crafts, Hobbies & Home › Crafts & Hobbies › Coloring Books for Grown-Ups › Mandalas',
    'Books › Crafts, Hobbies & Home › Crafts & Hobbies › Coloring Books for Grown-Ups › Holidays',
    'Books › Self-Help › Stress Management',
  ],
  kids_coloring: [
    "Books › Children's Books › Activities, Crafts & Games › Activity Books › Coloring",
    "Books › Children's Books › Holidays & Celebrations",
  ],
};
export const categoriesFor = (book) => CATEGORIES[book.kind === 'adult_mandala' && book.motifs === 'christmas' ? 'adult_mandala_christmas' : book.kind] || CATEGORIES.kids_coloring;
export const readingAgeFor = (book) => (book.kind === 'adult_mandala' ? 'Leave blank (adult book)' : book.kind === 'toddler_coloring' ? '2 to 5' : '4 to 8');

// The deterministic listing every book gets; the LLM may only replace the description and keywords, after checks.
export function defaultListing(book) {
  const n = book.designs || 40;
  const motifLine = book.motifs === 'christmas'
    ? 'snowflakes, poinsettias, holly, heirloom ornaments, wreaths and evergreen trees woven into intricate mandalas'
    : 'flowing petals, delicate lace, beads, stars and geometric bands woven into intricate mandalas';
  const description = cleanHtml(`<p><b>${book.title}</b>: ${n} original designs for adults who want a calm, absorbing coloring project.</p>`
    + `<p>Inside you will find ${motifLine}. Every design sits on its own page with the back left blank, so markers and gel pens will not ruin the next picture.</p>`
    + `<ul><li>${n} single-sided designs on large 8.5 x 11 in pages</li><li>A color test page to try your pencils and markers first</li>`
    + `<li>Fine, detailed line work made for colored pencils, gel pens and fine-tip markers</li>`
    + `<li>${book.gift_line || 'A thoughtful gift for friends, family and coworkers'}</li></ul>`
    + '<p>Pick a page, pour something warm and take your time.</p>');
  const base = book.motifs === 'christmas'
    ? ['christmas coloring book for adults', 'holiday mandala coloring book', 'christmas gifts for women', 'stress relief coloring book adults', 'winter coloring book for adults', 'adult coloring book christmas designs', 'stocking stuffers for adults']
    : ['mandala coloring book for adults', 'adult coloring book stress relief', 'relaxing coloring book for women', 'intricate mandala designs to color', 'mindfulness coloring book adults', 'pattern coloring book for adults', 'gift for women who love coloring'];
  return {
    title: book.title, subtitle: book.subtitle, author: book.author,
    description, keywords: [...(book.keyword_hints || []), ...base].slice(0, 7),
    categories: categoriesFor(book), reading_age: readingAgeFor(book), ai: AI_DISCLOSURE,
  };
}

// Vet an LLM listing against the book: title/subtitle are fixed (they are printed on the cover);
// a description or keyword that fails a check falls back to the default. Returns { listing, dropped }.
export function vetListing(raw = {}, book) {
  const base = defaultListing(book);
  const dropped = [];
  const titleProblems = vetText(`${book.title}\n${book.subtitle}`, { motifs: book.motifs || 'generic' });
  if (titleProblems.length) dropped.push(`title/subtitle: ${titleProblems.join('; ')}`);
  let description = base.description;
  if (raw.description) {
    const html = cleanHtml(raw.description);
    const p = vetText(htmlText(html), { motifs: book.motifs || 'generic' });
    if (p.length) dropped.push(`description: ${p.join('; ')}`);
    else if (htmlText(html).length >= 200) description = html;
  }
  const { keywords, dropped: kd } = cleanKeywords([...(raw.keywords || []), ...base.keywords], { motifs: book.motifs || 'generic' });
  dropped.push(...kd.map((k) => `keyword ${k}`));
  return { listing: { ...base, description, keywords }, dropped, ok: !titleProblems.length };
}

// ---------- Planning ----------
function easter(y) {
  const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31), day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(Date.UTC(y, month - 1, day));
}
const nth = (y, month, weekday, n) => { const first = new Date(Date.UTC(y, month - 1, 1)); return new Date(Date.UTC(y, month - 1, 1 + ((weekday - first.getUTCDay() + 7) % 7) + 7 * (n - 1))); };
const iso = (d) => d.toISOString().slice(0, 10);

// Each occasion: when it is, and an honest book for it. Generic-motif books never promise hearts, eggs, pumpkins...
// Halloween and St Patrick's need new drawings (pumpkins, shamrocks) the v1 engines don't have: tracked, never planned.
export const OCCASIONS = [
  { key: 'valentines', name: "Valentine's Day", date: (y) => new Date(Date.UTC(y, 1, 14)), motifs: 'generic', palette: 'rose',
    title: 'Love & Lace Mandalas', subtitle: "An Adult Coloring Book with 40 Romantic Floral and Lace Designs for Relaxation - A Valentine's Day Gift",
    gift_line: "A thoughtful Valentine's Day gift for anyone who loves to color", keyword_hints: ["valentines day gifts for her", 'romantic coloring book for adults'] },
  { key: 'st_patricks', name: "St Patrick's Day", date: (y) => new Date(Date.UTC(y, 2, 17)), supported: false, why: 'needs shamrock drawings (not in v1)' },
  { key: 'easter', name: 'Easter', date: easter, motifs: 'generic', palette: 'spring',
    title: 'Spring Bloom Mandalas', subtitle: 'An Adult Coloring Book with 40 Floral Designs for Relaxation - An Easter Basket Gift for Adults',
    gift_line: 'A calm Easter basket gift for grown-ups', keyword_hints: ['easter basket stuffers for adults', 'spring coloring book for adults'] },
  { key: 'mothers_day', name: "Mother's Day", date: (y) => nth(y, 5, 0, 2), motifs: 'generic', palette: 'lavender',
    title: 'Mandalas for Mom', subtitle: "An Adult Coloring Book with 40 Relaxing Floral Designs - A Mother's Day Gift",
    gift_line: "A thoughtful Mother's Day gift", keyword_hints: ['mothers day gifts for mom', 'coloring book for moms'] },
  { key: 'back_to_school', name: 'Back to school', date: (y) => new Date(Date.UTC(y, 7, 15)), motifs: 'generic', palette: 'teal',
    title: 'Mandalas for Teachers', subtitle: 'An Adult Coloring Book with 40 Calming Designs for Stress Relief - A Teacher Appreciation Gift',
    gift_line: 'A thank-you gift for teachers at the start of the school year', keyword_hints: ['teacher appreciation gifts', 'back to school gifts for teachers'] },
  { key: 'halloween', name: 'Halloween', date: (y) => new Date(Date.UTC(y, 9, 31)), supported: false, why: 'needs pumpkin/witch drawings (not in v1)' },
  { key: 'thanksgiving', name: 'Thanksgiving', date: (y) => nth(y, 11, 4, 4), motifs: 'generic', palette: 'amber',
    title: 'Gratitude Mandalas', subtitle: 'An Adult Coloring Book with 40 Calming Designs for Thanksgiving and Cozy Fall Evenings',
    gift_line: 'A cozy hostess gift for Thanksgiving', keyword_hints: ['thanksgiving gifts for adults', 'fall coloring book for adults'] },
  { key: 'christmas', name: 'Christmas', date: (y) => new Date(Date.UTC(y, 11, 25)), motifs: 'christmas', palette: 'evergreen',
    title: 'Christmas Mandalas Volume 2', subtitle: 'An Adult Coloring Book with 40 New Intricate Holiday Designs for Relaxation & Stress Relief',
    gift_line: 'A thoughtful Christmas gift for friends, family and coworkers', keyword_hints: [] },
];
// Live 4-6 weeks before the date: plan from 12 weeks out, never later than 5 weeks out (a week for upload + review).
export const PLAN_FROM_DAYS = 84;
export const PLAN_UNTIL_DAYS = 35;

export const EVERGREEN = [
  { key: 'floral', title: 'Floral Mandalas', subtitle: 'An Adult Coloring Book with 40 Petal and Flower Designs for Relaxation & Stress Relief', palette: 'rose', keyword_hints: ['flower mandala coloring book'] },
  { key: 'geometric', title: 'Geometric Pattern Mandalas', subtitle: 'An Adult Coloring Book with 40 Intricate Bands, Stars and Medallions for Mindful Relaxation', palette: 'teal', keyword_hints: ['geometric coloring book for adults'] },
  { key: 'lace', title: 'Lace Mandalas', subtitle: 'An Adult Coloring Book with 40 Delicate Lace and Petal Designs for Calm and Focus', palette: 'lavender', keyword_hints: ['lace pattern coloring book'] },
  { key: 'starlight', title: 'Starlight Mandalas', subtitle: 'An Adult Coloring Book with 40 Star and Medallion Designs for Evening Relaxation', palette: 'night', keyword_hints: ['star mandala coloring book'] },
  { key: 'mindful', title: 'Mindful Mandalas', subtitle: 'An Adult Coloring Book with 40 Calming Patterns for Stress Relief and Focus', palette: 'amber', keyword_hints: ['mindfulness gifts for women'] },
];

export const slugify = (s) => String(s).toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);

// Pure: the next book to plan today, or null. Seasonal first (earliest date in its window), then evergreen.
export function pickNext(books, today = new Date().toISOString().slice(0, 10)) {
  const t = new Date(`${today}T12:00:00Z`);
  const y = t.getUTCFullYear();
  const covered = (key, year) => books.some((b) => b.occasion === key && Number(b.occasion_year) === year && b.kind === 'adult_mandala');
  const seasonal = [];
  for (const yr of [y, y + 1]) {
    for (const o of OCCASIONS) {
      if (o.supported === false) continue;
      const d = o.date(yr);
      const days = Math.round((d - t) / 86400000);
      if (days > PLAN_FROM_DAYS || days < PLAN_UNTIL_DAYS) continue;
      if (covered(o.key, yr)) continue;
      seasonal.push({ o, yr, d, days });
    }
  }
  seasonal.sort((a, b) => a.d - b.d);
  if (seasonal.length) {
    const { o, yr, d } = seasonal[0];
    return {
      slug: slugify(`${o.title}-${yr}`), title: o.title, subtitle: o.subtitle, author: 'Evergreen Atelier', kind: 'adult_mandala',
      motifs: o.motifs, palette: o.palette, occasion: o.key, occasion_year: yr, occasion_date: iso(d),
      live_by: iso(new Date(d.getTime() - 28 * 86400000)), gift_line: o.gift_line, keyword_hints: o.keyword_hints,
    };
  }
  const used = new Set(books.map((b) => b.evergreen).filter(Boolean));
  const e = EVERGREEN.find((x) => !used.has(x.key));
  if (!e) return null;
  return {
    slug: slugify(e.title), title: e.title, subtitle: e.subtitle, author: 'Evergreen Atelier', kind: 'adult_mandala',
    motifs: 'generic', palette: e.palette, evergreen: e.key, keyword_hints: e.keyword_hints,
  };
}

// ---------- Mandala config (drives agents/books/engines/mandala) ----------
const PALETTES = {
  evergreen: { bg: '#123A27', bg2: '#1C4A33', accent: '#D9AE4A', text: '#F5EBD3', ink: '#2A1914', palette: ['#F3E6C8', '#B42335', '#D6A739', '#2E6B47', '#6E1A2B', '#8DB39A', '#C9DDE3', '#FBF4E6'] },
  rose: { bg: '#5A1A2B', bg2: '#6B2537', accent: '#E8B86A', text: '#FBEFE6', ink: '#2A1418', palette: ['#F7E3DA', '#C2405A', '#E8B86A', '#8E2C48', '#F2A7A0', '#6B8F71', '#F6D0C4', '#FFF6EE'] },
  spring: { bg: '#2F5D50', bg2: '#3A6B5D', accent: '#F2C66D', text: '#FAF6EC', ink: '#1E2B26', palette: ['#FCEFD8', '#E58FA6', '#F2C66D', '#7FB685', '#B9A7D8', '#9FD3D8', '#F6D6E0', '#FFFBEF'] },
  lavender: { bg: '#3E2F5B', bg2: '#4B3B6B', accent: '#E9C46A', text: '#F7F1FA', ink: '#221A30', palette: ['#EFE6F6', '#9D7BC9', '#E9C46A', '#5E8C7A', '#D98FA6', '#B8D8E0', '#F4DCE4', '#FFFAF3'] },
  teal: { bg: '#123F4A', bg2: '#1B4E5A', accent: '#E6B54A', text: '#F2F1E8', ink: '#13252A', palette: ['#E7F0EE', '#2E8B8B', '#E6B54A', '#D9644C', '#7FB3C8', '#A6C48A', '#F3D9B1', '#FFFDF6'] },
  amber: { bg: '#4A2A12', bg2: '#5A3519', accent: '#E3A63A', text: '#FBF0DF', ink: '#2B1A0C', palette: ['#F8E8CC', '#C0592B', '#E3A63A', '#7A8B3A', '#9C3B22', '#D9B98A', '#EED7B0', '#FFF8EC'] },
  night: { bg: '#141B3C', bg2: '#1E2850', accent: '#E8C468', text: '#F1F0FA', ink: '#11142A', palette: ['#E9ECF8', '#4C5FA8', '#E8C468', '#7A6FB5', '#2E8B9A', '#B6C2E6', '#F2E2B3', '#FDFCF7'] },
};
const ADJ = ['Quiet', 'Golden', 'Velvet', 'Morning', 'Silver', 'Gentle', 'Twilight', 'Garden', 'Crystal', 'Amber', 'Still', 'Bright', 'Soft', 'Evening', 'Rising', 'Hidden', 'Woven', 'Moonlit', 'Sunlit', 'Calm'];
const NOUN = { classic: ['Medallion', 'Rose Window', 'Star Compass', 'Lace Circle', 'Petal Wheel', 'Bloom', 'Rosette'], bands: ['Tapestry', 'Ribbon Bands', 'Woven Circle'], trio: ['Trio', 'Three Rosettes'], quilt: ['Quilt', 'Patchwork'] };
const XMAS_NOUN = { classic: ['Medallion', 'Star', 'Rose Window', 'Frost Circle'], snow: ['Snowfall', 'Frost Lace'], tree: ['Evergreen', 'Fir'], orn3: ['Ornaments'], wreath: ['Wreath'], quilt: ['Quilt'], bauble: ['Bauble'] };
export const GENERIC_KINDS = ['classic', 'bands', 'classic', 'trio', 'classic', 'quilt'];
export const GENERIC_BGS = ['corners', 'rays', 'lattice', 'scatter'];
export const GENERIC_CENTERS = ['rose', 'star'];
const XMAS_KINDS = ['classic', 'snow', 'classic', 'tree', 'classic', 'orn3', 'classic', 'wreath', 'quilt', 'bauble'];
const XMAS_CENTERS = ['poinsettia', 'star', 'holly', 'rose', 'snowflake'];

const hash = (s) => { let h = 2166136261; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
function splitTitle(title) {
  const w = title.split(' ');
  if (title.length <= 16 || w.length < 2) return [title];
  let best = 1, diff = Infinity;
  for (let i = 1; i < w.length; i++) { const d = Math.abs(w.slice(0, i).join(' ').length - w.slice(i).join(' ').length); if (d < diff) { diff = d; best = i; } }
  return [w.slice(0, best).join(' '), w.slice(best).join(' ')];
}

export function mandalaConfig(book, designs = 40) {
  const xmas = book.motifs === 'christmas';
  const base = 1000 + (hash(book.slug) % 8000);
  const kinds = xmas ? XMAS_KINDS : GENERIC_KINDS;
  const bgs = xmas ? ['corners', 'snow', 'rays', 'lattice', 'scatter'] : GENERIC_BGS;
  const centers = xmas ? XMAS_CENTERS : GENERIC_CENTERS;
  const nouns = xmas ? XMAS_NOUN : NOUN;
  const used = new Set();
  const plan = [];
  for (let i = 0; i < designs; i++) {
    const kind = kinds[i % kinds.length];
    const p = { kind, seed: base + i, bg: bgs[(i + Math.floor(i / kinds.length)) % bgs.length] };
    if (kind === 'classic') { p.center = centers[i % centers.length]; p.k = [8, 10, 12, 16][(i >> 1) % 4]; }
    if (kind === 'wreath') { p.center = 'mandala'; }
    let name;
    for (let j = 0; ; j++) {
      const list = nouns[kind];
      name = `${ADJ[(i * 7 + j) % ADJ.length]} ${list[(i + j) % list.length]}`;
      if (!used.has(name)) break;
    }
    used.add(name);
    p.name = name;
    plan.push(p);
  }
  const col = PALETTES[book.palette] || PALETTES.evergreen;
  const tagline = `${designs} intricate designs for calm, creativity and joy`;
  return {
    slug: book.slug, title: book.title, subtitle: book.subtitle, author: book.author, motifs: xmas ? 'christmas' : 'generic',
    year: Number(book.occasion_year) || new Date().getUTCFullYear(), pages: 4 + 2 * designs,
    title_page: { kicker: 'AN ADULT COLORING BOOK', tagline, mandala: { rng: base % 97, spec_r: 118, k: 12, center: xmas ? 'poinsettia' : 'rose', outer: 'lace' } },
    cover: {
      kicker: 'AN ADULT COLORING BOOK', title_lines: splitTitle(book.title), title_size: 62,
      subtitle: `${designs} Intricate Designs for Relaxation & Stress Relief`,
      mandala: { seed: base + 500, k: 12, center: xmas ? 'poinsettia' : 'rose', outer: 'petals', themes: xmas ? ['holly', 'stars', 'flakes', 'ornaments'] : ['stars', 'bract'] },
      back_headline: 'Slow down and color.',
      back_body: `${xmas ? 'Snowflakes, poinsettias, holly, ornaments and evergreen trees' : 'Flowing petals, delicate lace, beads, stars and geometric bands'}, woven into ${designs} original designs. Every page is drawn in fine, detailed line work made for adults who love a coloring project they can sink into.`,
      bullets: [`${designs} original designs, from classic mandalas to layered medallions`, 'Single-sided pages, so markers never ruin the next design', 'Large 8.5 x 11 in pages with a color test page', book.gift_line || 'A thoughtful gift for friends, family and coworkers'].map((b) => b.slice(0, 64)),
      thumbs: [{ seed: base + 601, k: 12, center: 'star', outer: 'lace' }, { seed: base + 602, k: 12, center: xmas ? 'snowflake' : 'rose', outer: 'petals' }, { seed: base + 603, k: 16, center: 'rose', outer: 'lace' }],
      colors: col,
    },
    plan,
  };
}

// ---------- Seed (Bobby's books as of Oct 1, 2026) ----------
export const SEED = [
  {
    slug: 'cute-halloween-coloring-book-for-kids', title: 'Cute Halloween Coloring Book for Kids',
    subtitle: '40 Big and Easy Pages of Little Witches, Smiling Pumpkins and Friendly Haunted Houses - Ages 4-8',
    author: 'Little Pumpkin Press', kind: 'kids_coloring', status: 'in_review', kdp_title_id: 'GH7JB8TCVT6',
    kdp_created_at: '2026-10-01', submitted_at: '2026-10-01', list_price: 6.99, recommended_price: 9.99, print_cost: 2.84,
    occasion: 'halloween', occasion_year: 2026, notes: 'Print cost assumed $2.84 (8.5x11 B&W). Recommend $9.99 once live (60% royalty).',
    raise_to: 9.99,
  },
  {
    slug: 'christmas-coloring-book-for-toddlers', title: 'Christmas Coloring Book for Toddlers',
    subtitle: '50 Big & Easy Pictures of Santa, Reindeer, Snowmen, Penguins and More for Kids Ages 2-5 | Christmas Stocking Stuffer',
    author: 'Little Pumpkin Press', kind: 'toddler_coloring', engine: 'toddler', status: 'in_review', kdp_title_id: 'EHB1H1HFNNN',
    kdp_created_at: '2026-10-01', submitted_at: '2026-10-01', list_price: 9.99, recommended_price: 9.99, print_cost: 2.84, pages: 102,
    occasion: 'christmas', occasion_year: 2026, check_on: '2026-11-15', check_note: 'price test: if no sales by now, drop to $7.99',
    notes: 'Price test at $9.99. Check sales around Nov 15; drop to $7.99 if none.',
  },
  {
    slug: 'christmas-mandalas', title: 'Christmas Mandalas',
    subtitle: 'An Adult Coloring Book with 40 Intricate Holiday Designs for Relaxation & Stress Relief',
    author: 'Evergreen Atelier', kind: 'adult_mandala', engine: 'mandala', motifs: 'christmas', status: 'needs_upload',
    pages: 84, designs: 40, print_cost: 2.84, recommended_price: 9.99, occasion: 'christmas', occasion_year: 2026,
    config_path: 'agents/books/engines/mandala/configs/christmas-mandalas.json', upload_after: '2026-10-04',
    notes: 'Upload scheduled Sun Oct 4 (KDP weekly title limit resets Sunday 00:00 UTC).',
  },
];

// Pure + idempotent: adds seed books that are missing (matched by slug or KDP title id). Never edits existing ones.
export function seedBooks(books = [], seed = SEED, now = new Date().toISOString()) {
  const out = [...books];
  let added = 0;
  for (const s of seed) {
    if (out.some((b) => b.slug === s.slug || (s.kdp_title_id && b.kdp_title_id === s.kdp_title_id))) continue;
    out.push({ ...s, created_at: now, updated_at: now, history: [{ at: now, status: s.status, by: 'seed' }] });
    added++;
  }
  return { books: out, added };
}

// Pure: apply this run's changes onto a freshly read list, so a status Bobby set meanwhile is never overwritten.
// patch = { slug, set: {...}, expect: 'status the agent saw' (optional), add: bool }
export function applyPatches(fresh = [], patches = [], now = new Date().toISOString()) {
  const out = fresh.map((b) => ({ ...b }));
  const skipped = [];
  for (const p of patches) {
    const i = out.findIndex((b) => b.slug === p.slug);
    if (i < 0) { if (p.add) out.push({ ...p.set, updated_at: now }); else skipped.push(p.slug); continue; }
    if (p.add) { skipped.push(p.slug); continue; }
    if (p.expect && out[i].status !== p.expect) { skipped.push(p.slug); continue; }
    const history = p.set.status && p.set.status !== out[i].status ? [...(out[i].history || []), { at: now, status: p.set.status, by: p.by || 'book_studio' }].slice(-30) : out[i].history;
    out[i] = { ...out[i], ...p.set, history, updated_at: now };
  }
  return { books: out, skipped };
}

// ---------- Upload pack (what Claude fills in on KDP, in order) ----------
export function uploadPack(book) {
  const L = book.listing || defaultListing(book);
  const price = priceAdvice(book).recommended;
  const [first, ...rest] = String(book.author).split(' ');
  const glossy = book.kind !== 'adult_mandala';
  const kw = [...L.keywords]; while (kw.length < 7) kw.push('');
  return {
    files: { interior: book.files?.interior || null, cover: book.files?.cover || null },
    upload_after: book.upload_after || null,
    sections: [
      { name: 'Paperback Details', fields: [
        ['Language', 'English'],
        ['Book Title', book.title],
        ['Subtitle', book.subtitle],
        ['Series', '(leave blank)'],
        ['Edition Number', '(leave blank)'],
        ['Primary Author or Contributor (pen name) - First name', first],
        ['Primary Author or Contributor (pen name) - Last name', rest.join(' ')],
        ['Description (paste in the HTML / source box)', L.description],
        ['Publishing Rights', 'I own the copyright and I hold the necessary publishing rights'],
        ['Primary Audience: sexually explicit images or title', 'No'],
        ['Reading age', L.reading_age],
        ['Primary marketplace', 'Amazon.com'],
        ...L.categories.map((c, i) => [`Category ${i + 1}`, c]),
        ...kw.map((k, i) => [`Keyword ${i + 1}`, k || '(leave blank)']),
        ['Publication date', '(leave blank)'],
      ] },
      { name: 'Paperback Content', fields: [
        ['Print ISBN', 'Get a free KDP ISBN'],
        ['Ink and paper type', 'Black & white interior with white paper'],
        ['Trim size', '8.5 x 11 in (21.59 x 27.94 cm)'],
        ['Bleed settings', 'No bleed'],
        ['Paperback cover finish', glossy ? 'Glossy' : 'Matte'],
        ['Reading direction', 'Left to right'],
        ['Manuscript', 'Upload interior.pdf'],
        ['Book cover', `Upload a cover you already have (print-ready PDF only): cover.pdf (${coverSize(book.pages || 84).width} x 11.25 in)`],
        ['AI-generated content', 'Yes'],
        ['Texts', `${L.ai.texts.detail} · ${L.ai.texts.editing} · tool: ${L.ai.texts.tool}`],
        ['Images', `${L.ai.images.detail} · ${L.ai.images.editing} · tool: ${L.ai.images.tool}`],
        ['Translations', L.ai.translations.answer],
        ['Book Preview', 'Launch Previewer → check pages and cover → Approve'],
      ] },
      { name: 'Paperback Rights & Pricing', fields: [
        ['Territories', 'All territories (worldwide rights)'],
        ['Primary marketplace', 'Amazon.com'],
        ['List price (USD)', `${price.price.toFixed(2)} (recommended; Bobby confirms before Publish)`],
        ['Royalty at that price', `${Math.round(price.rate * 100)}% x $${price.price.toFixed(2)} - $${price.print_cost.toFixed(2)} print = $${price.per_sale.toFixed(2)} per sale`],
        ['Other marketplaces', 'Leave auto-calculated from the USD price'],
        ['Expanded Distribution', 'Off'],
      ] },
    ],
    checklist: [
      book.upload_after ? `Do not create the title before ${book.upload_after} (KDP weekly title limit; week resets Sunday 00:00 UTC).` : 'Check the KDP weekly title limit has room (max 2 new titles per week).',
      'Download interior.pdf and cover.pdf from the Shop page.',
      'KDP Bookshelf → + Create → Paperback. Fill Details exactly as listed, then Save and Continue.',
      'Content: upload both PDFs, answer the AI questions as listed, Launch Previewer, Approve.',
      'Rights & Pricing: enter the recommended price, check the royalty matches.',
      'Stop before "Publish Your Paperback Book": save as draft and mark "Uploaded as draft" on the Shop page with the KDP title ID.',
      'Bobby reviews and clicks Publish, then marks "In review".',
    ],
  };
}

// ---------- Weekly review ----------
export function weeklyReview(books, today = new Date().toISOString().slice(0, 10)) {
  const by = Object.fromEntries(STATUSES.map((s) => [s, books.filter((b) => b.status === s)]));
  const short = (b) => `"${b.title.length > 40 ? `${b.title.slice(0, 39)}…` : b.title}"`;
  const bobby = [], claude = [];
  for (const b of by.needs_upload) {
    if (!b.files?.interior) continue;
    if (!b.upload_after || b.upload_after <= today) claude.push(`upload ${short(b)} as a draft`);
    else claude.push(`upload ${short(b)} on/after ${b.upload_after}`);
  }
  for (const b of by.uploaded_draft) bobby.push(`review and click Publish for ${short(b)}`);
  for (const b of by.in_review) claude.push(`check KDP status of ${short(b)} and mark it live when it is`);
  for (const b of by.live) {
    if (b.raise_to && Number(b.list_price) < b.raise_to) bobby.push(`raise ${short(b)} to $${b.raise_to} on KDP`);
  }
  for (const b of books) if (b.check_on && b.check_on <= today && b.status !== 'paused') bobby.push(`${short(b)}: ${b.check_note || 'check sales'}`);
  const counts = STATUSES.filter((s) => by[s].length).map((s) => `${s.replace('_', ' ')} ${by[s].length}`).join(' · ') || 'no books';
  return {
    line: `Amazon review: ${counts}. Needs Bobby: ${bobby.join('; ') || 'nothing'}. Needs Claude: ${claude.join('; ') || 'nothing'}.`,
    bobby, claude,
  };
}
