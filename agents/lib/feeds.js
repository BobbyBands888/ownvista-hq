// RSS 2.0 / Atom parsing with conditional GET. Public feeds only.
import { politeFetch } from './robots.js';
import { decodeEntities, htmlToText } from './text.js';

function tag(block, name) {
  const re = new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${name}>`, 'i');
  const m = re.exec(block);
  if (!m) return '';
  return m[1].replace(/^\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*$/, '$1').trim();
}

export function parseFeed(xml) {
  const items = [];
  const blocks = xml.match(/<item[\s>][\s\S]*?<\/item>/gi) || xml.match(/<entry[\s>][\s\S]*?<\/entry>/gi) || [];
  for (const b of blocks) {
    let link = tag(b, 'link');
    if (!link || link.startsWith('<')) {
      const alt = /<link[^>]*rel=["']alternate["'][^>]*href=["']([^"']+)["']/i.exec(b) || /<link[^>]*href=["']([^"']+)["']/i.exec(b);
      link = alt ? alt[1] : '';
    }
    const title = htmlToText(decodeEntities(tag(b, 'title')));
    const desc = tag(b, 'description') || tag(b, 'summary') || tag(b, 'content:encoded') || tag(b, 'content');
    const date = tag(b, 'pubDate') || tag(b, 'published') || tag(b, 'updated') || tag(b, 'dc:date');
    if (!title || !link) continue;
    items.push({
      title: title.slice(0, 300),
      url: decodeEntities(link.trim()),
      snippet: htmlToText(decodeEntities(desc)).slice(0, 700),
      publishedAt: date && !isNaN(Date.parse(date)) ? new Date(date).toISOString() : null,
    });
  }
  return items;
}

export async function fetchFeed(source) {
  const headers = { accept: 'application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5' };
  if (source.etag) headers['if-none-match'] = source.etag;
  if (source.last_modified) headers['if-modified-since'] = source.last_modified;
  const { res, text } = await politeFetch(source.url, { headers });
  if (res.status === 304) return { notModified: true, items: [] };
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const items = parseFeed(text);
  if (!items.length && !/<(rss|feed|rdf)/i.test(text)) throw new Error('not a feed');
  return { items, etag: res.headers.get('etag'), lastModified: res.headers.get('last-modified') };
}
