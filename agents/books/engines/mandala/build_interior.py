"""Adult mandala coloring book - interior PDF from a JSON config.

    python3 build_interior.py configs/christmas-mandalas.json out/interior.pdf

The config sets title, author, motif set, title/front-matter text and the page PLAN.
Page count = 4 front pages (title, notes, test page, blank) + 2 per design (design + blank back).
The christmas-mandalas.json config reproduces the original Christmas Mandalas interior exactly.
"""
import os, sys, json, random
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, '..', 'fonts')
for name, f in (('Caladea-Bold', 'Caladea-Bold.ttf'), ('Caladea', 'Caladea-Regular.ttf'), ('Caladea-Italic', 'Caladea-Italic.ttf'),
                ('Poppins', 'Poppins-Regular.ttf'), ('Poppins-Light', 'Poppins-Light.ttf')):
    pdfmetrics.registerFont(TTFont(name, os.path.join(FONTS, f)))

if HERE not in sys.path:
    sys.path.insert(0, HERE)
from pages import *  # noqa: E402,F401  (art + page kinds)
import art  # noqa: E402


def load_config(path):
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
    validate(cfg)
    return cfg


def validate(cfg):
    for k in ('title', 'author', 'motifs', 'plan'):
        if k not in cfg:
            raise ValueError(f'config missing {k}')
    allowed = CHRISTMAS_KINDS + GENERIC_KINDS if cfg['motifs'] == 'christmas' else GENERIC_KINDS
    for i, p in enumerate(cfg['plan']):
        if p['kind'] not in allowed:
            raise ValueError(f"plan[{i}] kind {p['kind']} not allowed for motifs={cfg['motifs']}")
        if cfg['motifs'] != 'christmas':
            if p.get('center') in art.SEASONAL_ONLY:
                raise ValueError(f"plan[{i}] centre {p.get('center')} is a christmas motif")
            if p.get('bg') == 'snow':
                raise ValueError(f'plan[{i}] snow background is a christmas motif')
    if 'pages' in cfg and cfg['pages'] != page_count(cfg):
        raise ValueError(f"config says {cfg['pages']} pages but the plan makes {page_count(cfg)}")


def page_count(cfg):
    return 4 + 2 * len(cfg['plan'])


def draw_design(c, st, p):
    kind, seed = p['kind'], p['seed']
    if kind == 'classic':
        page_classic(c, st, seed, p['bg'], center=p.get('center'), k=p.get('k'))
    elif kind == 'snow':
        page_snowmandala(c, st, seed, p['bg'])
    elif kind == 'tree':
        page_tree(c, st, seed, p['bg'])
    elif kind == 'orn3':
        page_ornaments3(c, st, seed, p['bg'])
    elif kind == 'wreath':
        page_wreath(c, st, seed, p['bg'], p['center'], p.get('word', 'Noël'))
    elif kind == 'quilt':
        page_quilt(c, st, seed, p['bg'])
    elif kind == 'bauble':
        page_bauble(c, st, seed, p['bg'])
    elif kind == 'bands':
        page_bands(c, st, seed, p['bg'])
    elif kind == 'trio':
        page_trio(c, st, seed, p['bg'])
    frame(c, st, BOX)


def caption(c, i, name):
    c.setFillColor(black)
    c.setFont('Caladea-Italic', 10)
    c.drawCentredString(W / 2, 38, f'No. {i}  ·  {name}')


def fit(c, txt, font, size, maxw):
    """Largest size <= size at which txt fits in maxw points (long generated titles never overflow)."""
    w = c.stringWidth(txt, font, size)
    return size if w <= maxw else size * maxw / w


def centered(c, txt, font, size, y, col=black, maxw=500):
    size = fit(c, txt, font, size, maxw)
    c.setFillColor(col)
    c.setFont(font, size)
    c.drawCentredString(W / 2, y, txt)


def title_page(c, st, cfg):
    t = cfg.get('title_page', {})
    m = t.get('mandala', {})
    rng = random.Random(m.get('rng', 7))
    spec = mandala_spec(m.get('spec_r', 118), rng, k=m.get('k', 12), center=m.get('center', 'poinsettia'), outer=m.get('outer', 'lace'))
    draw_mandala(c, st, spec, W / 2, 420)
    medallion(c, st, W / 2, 420, m.get('spec_r', 118))
    centered(c, cfg['title'], 'Caladea-Bold', t.get('title_size', 46), 640)
    centered(c, t.get('kicker', 'AN ADULT COLORING BOOK'), 'Poppins-Light', 13, 606)
    c.setLineWidth(.7); c.line(W / 2 - 60, 592, W / 2 + 60, 592)
    centered(c, t.get('tagline', f"{len(cfg['plan'])} intricate designs for calm and creativity"), 'Caladea-Italic', 13, 572)
    centered(c, 'This book belongs to', 'Caladea-Italic', 13, 215)
    c.setLineWidth(.8); c.line(W / 2 - 140, 180, W / 2 + 140, 180)
    centered(c, cfg['author'].upper(), 'Poppins-Light', 10, 100)


NOTES = [
    'Every design in this book is printed on its own page, with the back left blank,',
    'so markers and pens will not ruin the artwork behind it.',
    '',
    'If you color with alcohol markers or ink, slip a sheet of scrap paper or',
    'card behind the page you are working on.',
    '',
    'Colored pencils, gel pens and fine-tip markers all work beautifully.',
    'Try your palette on the test page first.',
    '',
    'There are no rules. Pick a page, pour something warm, and take your time.',
]


def copyright_page(c, st, cfg):
    y = 560
    lines = [('Caladea-Bold', 16, 'Before You Begin'), None]
    for t in cfg.get('notes', NOTES):
        lines.append(None if not t else ('Caladea', 11.5, t))
    for ln in lines:
        if ln is None:
            y -= 12
            continue
        f, s, t = ln
        centered(c, t, f, s, y)
        y -= s + 7
    c.saveState(); c.translate(W / 2, 640)
    fillstroke(c, st, star_path(c, 16, 7, 8, 90), white, .8)
    c.restoreState()
    year = cfg.get('year', 2026)
    y = 200
    for t in [f"{cfg['title']}: {cfg.get('copyright_kind', 'An Adult Coloring Book')}",
              f"Copyright © {year} {cfg['author']}. All rights reserved.",
              'No part of this book may be reproduced or distributed in any form without',
              'written permission from the publisher, except for personal, non-commercial use',
              'of the coloring pages by the purchaser.',
              'First edition, %d.' % year]:
        centered(c, t, 'Caladea', 9.5, y)
        y -= 14


def test_page(c, st):
    centered(c, 'Color Test Page', 'Caladea-Bold', 26, 700)
    centered(c, 'Try your pencils, pens and markers here before you begin.', 'Caladea-Italic', 12, 676)
    x0, y0 = 90, 560
    for r in range(5):
        for k in range(6):
            x = x0 + k * 86
            y = y0 - r * 100
            if r % 2 == 0:
                circ(c, st, x, y, 34, white, 1.0)
                circ(c, st, x, y, 16, white, .7)
            else:
                c.saveState(); c.translate(x, y)
                fillstroke(c, st, petal_path(c, -36, 36, 26, 'point'), white, 1.0)
                petal_deco(c, st, -36, 36, 26, 'point', ('inner',), white)
                c.restoreState()
    frame(c, st, BOX)


def build(path, cfg):
    art.set_motifs(cfg['motifs'], cfg.get('petal_styles'))
    c = canvas.Canvas(path, pagesize=(W, H), initialFontName='Caladea', initialFontSize=10)
    c.setTitle(cfg['title'])
    c.setAuthor(cfg['author'])
    st = Style()
    title_page(c, st, cfg); c.showPage()
    copyright_page(c, st, cfg); c.showPage()
    test_page(c, st); c.showPage()
    c.showPage()  # blank back
    for i, p in enumerate(cfg['plan'], 1):
        draw_design(c, st, p)
        caption(c, i, p['name'])
        c.showPage()
        c.showPage()  # blank back
    c.save()
    return page_count(cfg)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit('usage: build_interior.py <config.json> <out.pdf>')
    n = build(sys.argv[2], load_config(sys.argv[1]))
    print('interior pages', n)
