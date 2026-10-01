// KDP sales: lifetime totals copied from the KDP report become dated deltas the scoreboard and CEO Review read.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { salesUpdate } from '../agents/lib/books.js';
import { buildScore } from '../agents/lib/smartscore.js';

const ROOT = new URL('..', import.meta.url).pathname;
const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8');

test('Totals turn into dated deltas', () => {
  const book = { status: 'live', sales: 2, royalties: 6.3, sales_log: [{ day: '2026-10-04', sales: 2, royalties: 6.3 }] };
  const up = salesUpdate(book, { sales: '5', royalties: '15.75' }, '2026-10-06');
  assert.deepEqual(up.delta, { sales: 3, royalties: 9.45 });
  assert.equal(up.set.sales, 5);
  assert.equal(up.set.sales_log.length, 2);
});

test('Bad input and unpublished books are refused', () => {
  assert.ok(salesUpdate({ status: 'built' }, { sales: 1, royalties: 1 }).error);
  assert.ok(salesUpdate({ status: 'live' }, { sales: 1.5, royalties: 1 }).error);
  assert.ok(salesUpdate({ status: 'live' }, { sales: 1, royalties: -2 }).error);
  assert.ok(salesUpdate({ status: 'live', sales: 1, royalties: 3.15 }, { sales: 1, royalties: 3.15 }).error);
});

test('KDP royalties count as agent revenue on the scoreboard', () => {
  const s = buildScore({ books: [{ sales_log: [{ day: '2026-09-23', sales: 1, royalties: 3.15 }] }] }, new Date('2026-10-01T22:00:00Z'));
  const w = s.metrics.find((m) => m.id === 'revenue').weeks.find((x) => x.week === '2026-09-21');
  assert.equal(w.v, 3.15);
});

test('The API and Shop page wire it up', () => {
  assert.match(src('api/books.js'), /body\.action === 'sales'/);
  assert.match(src('dashboard/js/views/shop.js'), /data-booksales/);
});
