"""Adult mandala coloring book - wraparound paperback cover from the same JSON config.

    python3 build_cover.py configs/christmas-mandalas.json out/cover.pdf

KDP math (B&W interior, white paper): spine = pages x 0.002252 in; 0.125 in bleed on every edge.
Cover width = 0.125 + 8.5 + spine + 8.5 + 0.125 in, height = 0.125 + 11 + 0.125 in.
The back panel's lower-right area is left clear for KDP's barcode.
"""
import os, sys, random, math
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import build_interior as B  # noqa: E402  (registers fonts)
from pages import *  # noqa: E402,F401
import art  # noqa: E402

SPINE_IN_PER_PAGE = 0.002252
BLEED = 9  # 0.125 in


def geometry(pages):
    spine = pages * SPINE_IN_PER_PAGE * 72
    cw = 2 * BLEED + 2 * 612 + spine
    ch = 2 * BLEED + 792
    return spine, cw, ch


DEFAULT_COLORS = {'bg': '#123A27', 'bg2': '#1C4A33', 'accent': '#D9AE4A', 'text': '#F5EBD3', 'ink': '#2A1914',
                  'palette': ['#F3E6C8', '#B42335', '#D6A739', '#2E6B47', '#6E1A2B', '#8DB39A', '#C9DDE3', '#FBF4E6']}


def curated(spec):
    T = [(1, 2, 0), (3, 7, 5), (2, 1, 4), (5, 3, 7), (1, 0, 3), (6, 2, 4), (2, 4, 0), (3, 1, 6), (4, 2, 5), (1, 7, 3)]
    for i, rg in enumerate(spec['rings']):
        a, b, bg = T[i % len(T)]
        rg['ca'], rg['cb'], rg['cc'] = a, b, bg - 2
    spec['center'].update(ca=1, cb=2, cc=4)
    return spec


class Cover:
    def __init__(self, cfg):
        self.cfg = cfg
        cv = cfg.get('cover', {})
        col = {**DEFAULT_COLORS, **cv.get('colors', {})}
        self.GREEN, self.GREEN2 = HexColor(col['bg']), HexColor(col['bg2'])
        self.GOLD, self.CREAM, self.INK = HexColor(col['accent']), HexColor(col['text']), HexColor(col['ink'])
        self.PAL = [HexColor(h) for h in col['palette']]
        self.pages = cfg.get('pages') or B.page_count(cfg)
        self.SPINE, self.CW, self.CH = geometry(self.pages)
        self.FX = BLEED + 612 + self.SPINE
        self.BX = BLEED

    def lattice_bg(self, c):
        CH = self.CH
        c.setStrokeColor(self.GREEN2)
        c.setLineWidth(1)
        step = 40
        for i in range(-40, 80):
            o = i * step
            c.line(o, 0, o + CH, CH)
            c.line(o, CH, o + CH, 0)
        c.setFillColor(self.GREEN2)
        for i in range(0, 60):
            for j in range(0, 30):
                c.circle(i * step, j * step, 2.2, stroke=0, fill=1)

    def gold_frame(self, c, x0, y0, x1, y1):
        c.setStrokeColor(self.GOLD)
        c.setLineWidth(1.6)
        c.rect(x0, y0, x1 - x0, y1 - y0)
        c.setLineWidth(.7)
        c.rect(x0 + 5, y0 + 5, x1 - x0 - 10, y1 - y0 - 10)
        for (x, y) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            c.saveState(); c.translate(x, y)
            c.setFillColor(self.GREEN); c.circle(0, 0, 10, stroke=0, fill=1)
            c.setStrokeColor(self.GOLD); c.setLineWidth(1.1); c.circle(0, 0, 10, stroke=1, fill=0)
            c.setFillColor(self.GOLD)
            c.drawPath(star_path(c, 7, 2.6, 4, 45), stroke=0, fill=1)
            c.restoreState()

    @staticmethod
    def spaced(c, txt, font, size, cx, y, col, sp=3):
        c.setFont(font, size)
        c.setFillColor(col)
        w = sum(c.stringWidth(ch, font, size) for ch in txt) + sp * (len(txt) - 1)
        x = cx - w / 2
        for ch in txt:
            c.drawString(x, y, ch)
            x += c.stringWidth(ch, font, size) + sp

    def half_colored_mandala(self, c, x, y, R, seed, m):
        rng = random.Random(seed)
        spec = curated(mandala_spec(R, rng, k=m.get('k', 12), center=m.get('center', 'poinsettia'), outer=m.get('outer', 'petals'),
                                    themes=m.get('themes', ['holly', 'stars', 'flakes', 'ornaments'])))
        c.setFillColor(self.GOLD); c.circle(x, y, R + 9, stroke=0, fill=1)
        c.setFillColor(self.GREEN); c.circle(x, y, R + 6, stroke=0, fill=1)
        col = Style(pal=self.PAL, ink=self.INK, lw=1.0, lt=.65)
        line = Style(ink=self.INK, lw=1.0, lt=.65)
        a = math.radians(62)
        far = R * 3

        def half(sign):
            p = c.beginPath()
            dx, dy = math.cos(a) * far, math.sin(a) * far
            nx, ny = -math.sin(a) * far * sign, math.cos(a) * far * sign
            ox = R * .18
            p.moveTo(x - dx + ox, y - dy); p.lineTo(x + dx + ox, y + dy)
            p.lineTo(x + dx + nx + ox, y + dy + ny); p.lineTo(x - dx + nx + ox, y - dy + ny); p.close()
            return p
        c.saveState(); c.clipPath(half(1), stroke=0, fill=0)
        draw_mandala(c, col, spec, x, y)
        c.restoreState()
        c.saveState(); c.clipPath(half(-1), stroke=0, fill=0)
        draw_mandala(c, line, spec, x, y)
        c.restoreState()
        c.setStrokeColor(self.INK); c.setLineWidth(1.4); c.circle(x, y, R, stroke=1, fill=0)

    def line_thumb(self, c, x, y, R, seed, **kw):
        rng = random.Random(seed)
        spec = mandala_spec(R, rng, **kw)
        c.setFillColor(self.GOLD); c.circle(x, y, R + 5, stroke=0, fill=1)
        draw_mandala(c, Style(ink=self.INK, lw=.7, lt=.45), spec, x, y)

    def build(self, path):
        cfg, cv = self.cfg, self.cfg.get('cover', {})
        art.set_motifs(cfg['motifs'], cfg.get('petal_styles'))
        CW, CH, FX, BX = self.CW, self.CH, self.FX, self.BX
        c = canvas.Canvas(path, pagesize=(CW, CH), initialFontName='Caladea')
        c.setTitle(f"{cfg['title']} - cover")
        c.setFillColor(self.GREEN); c.rect(0, 0, CW, CH, stroke=0, fill=1)
        self.lattice_bg(c)

        # ---------------- front
        cx = FX + 306
        self.gold_frame(c, FX + 26, BLEED + 26, FX + 612 - 26, BLEED + 792 - 26)
        self.spaced(c, cv.get('kicker', 'AN ADULT COLORING BOOK'), 'Poppins-Light', 12.5, cx, BLEED + 716, self.GOLD, 3.2)
        c.setFillColor(self.CREAM)
        lines = cv.get('title_lines') or [cfg['title']]
        size = cv.get('title_size', 66)
        for i, ln in enumerate(lines[:2]):
            c.setFont('Caladea-Bold', B.fit(c, ln, 'Caladea-Bold', size, 520))
            c.drawCentredString(cx, BLEED + 645 - i * 62, ln)
        m = cv.get('mandala', {})
        self.half_colored_mandala(c, cx, BLEED + 322, 208, m.get('seed', 11), m)
        c.setFillColor(self.CREAM)
        sub = cv.get('subtitle', cfg.get('subtitle', ''))
        c.setFont('Caladea-Italic', B.fit(c, sub, 'Caladea-Italic', 17, 520))
        c.drawCentredString(cx, BLEED + 78, sub)
        self.spaced(c, cfg['author'].upper(), 'Poppins-Light', 10, cx, BLEED + 52, self.GOLD, 2.6)

        # ---------------- back
        bx = BX + 306
        self.gold_frame(c, BX + 26, BLEED + 26, BX + 612 - 26, BLEED + 792 - 26)
        c.setFillColor(self.CREAM)
        head = cv.get('back_headline', '')
        c.setFont('Caladea-Bold', B.fit(c, head, 'Caladea-Bold', 27, 520))
        c.drawCentredString(bx, BLEED + 700, head)
        y = BLEED + 662
        for ln in simpleSplit(cv.get('back_body', ''), 'Caladea', 14, 440):
            c.setFont('Caladea', 14); c.drawCentredString(bx, y, ln); y -= 20
        y -= 14
        for b in cv.get('bullets', []):
            c.saveState(); c.translate(bx - 205, y + 4)
            c.setFillColor(self.GOLD); c.drawPath(star_path(c, 5, 2, 4, 45), stroke=0, fill=1)
            c.restoreState()
            c.setFillColor(self.CREAM); c.setFont('Caladea', B.fit(c, b, 'Caladea', 12.5, 420))
            c.drawString(bx - 192, y, b)
            y -= 21
        ty = BLEED + 330
        th = cv.get('thumbs', [
            {'seed': 21, 'k': 12, 'center': 'star', 'outer': 'lace'},
            {'seed': 22, 'k': 12, 'center': 'snowflake', 'outer': 'petals'},
            {'seed': 23, 'k': 16, 'center': 'rose', 'outer': 'lace'}])
        for (dx, dy, r), t in zip(((-165, 0, 64), (0, 10, 82), (165, 0, 64)), th):
            self.line_thumb(c, bx + dx, ty + dy, r, t['seed'], k=t['k'], center=t['center'], outer=t['outer'])
        c.setFillColor(self.CREAM); c.setFont('Caladea-Italic', 12)
        c.drawCentredString(bx, ty - 118, 'A glimpse inside')
        # barcode area (left clear for KDP): bottom right of back panel
        self.spaced(c, cfg['author'].upper(), 'Poppins-Light', 9, BX + 150, BLEED + 60, self.GOLD, 2.2)

        # ---------------- spine (plain: KDP allows spine text only from 100 pages)
        c.setFillColor(self.GREEN); c.rect(BLEED + 612, 0, self.SPINE, CH, stroke=0, fill=1)
        c.showPage()
        c.save()
        return {'width_in': CW / 72, 'height_in': CH / 72, 'spine_in': self.SPINE / 72, 'pages': self.pages}


def build(path, cfg):
    return Cover(cfg).build(path)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit('usage: build_cover.py <config.json> <out.pdf>')
    g = build(sys.argv[2], B.load_config(sys.argv[1]))
    print('cover', g['width_in'], g['height_in'], 'spine', g['spine_in'])
