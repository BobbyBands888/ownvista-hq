"""Mandala coloring book - vector art engine (reportlab).
All drawing is deterministic given spec params, so the same design can be
rendered as line art (interior) or in colour (cover).

Motif sets: 'christmas' (the original engine: holly, pine, snowflakes, ornaments,
bells, poinsettias) or 'generic' (petals, beads, lace, stars, geometric bands only).
set_motifs() switches; the christmas set draws exactly what the original engine drew.
"""
import math, random
from reportlab.pdfgen.canvas import FILL_EVEN_ODD
from reportlab.lib.colors import white, black, HexColor, Color

TAU = math.pi * 2

# ----------------------------------------------------------------- motif set
MOTIFS = {'set': 'christmas', 'styles': None}
CHRISTMAS_CENTERS = ['poinsettia', 'snowflake', 'star', 'rose', 'holly']
CHRISTMAS_THEMES = ['holly', 'pine', 'flakes', 'ornaments', 'stars', 'bract', 'bells']
# Same list lengths as the christmas ones so seeded random draws line up.
GENERIC_CENTERS = ['rose', 'star', 'rose', 'star', 'rose']
GENERIC_THEMES = ['stars', 'bract']
SEASONAL_ONLY = {'holly', 'pine', 'flakes', 'ornaments', 'bells', 'poinsettia', 'snowflake'}


def set_motifs(name='christmas', petal_styles=None):
    if name not in ('christmas', 'generic'):
        raise ValueError(f'unknown motif set {name}')
    MOTIFS['set'] = name
    MOTIFS['styles'] = list(petal_styles) if petal_styles else None


def seasonal():
    return MOTIFS['set'] == 'christmas'


def _seasonal_only(name):
    if not seasonal():
        raise RuntimeError(f'{name} is a christmas motif and the book uses generic motifs')


def themes_for(christmas_list):
    """Theme list for a ring: the christmas list as-is, or only generic themes."""
    if seasonal():
        return christmas_list
    keep = [t for t in christmas_list if t not in SEASONAL_ONLY]
    return keep or list(GENERIC_THEMES)


# ----------------------------------------------------------------- style
class Style:
    """Line-art style (white fills) or coloured style (palette fills)."""
    def __init__(self, pal=None, ink=black, lw=0.95, lt=0.62):
        self.pal = pal
        self.ink = ink
        self.lw = lw      # main outline
        self.lt = lt      # detail line

    def col(self, idx):
        if self.pal is None or idx is None:
            return white
        return self.pal[idx % len(self.pal)]


def P(r, a):
    return (r * math.cos(a), r * math.sin(a))


def hwidth(r, n):
    return r * math.tan(math.pi / n)


def around(c, n, fn, offset=0.0):
    for i in range(n):
        c.saveState()
        c.rotate(offset + i * 360.0 / n)
        fn(i)
        c.restoreState()


def fillstroke(c, st, p, col, lw=None):
    c.setLineWidth(lw or st.lw)
    c.setFillColor(col)
    c.setStrokeColor(st.ink)
    c.drawPath(p, stroke=1, fill=1)


def stroke(c, st, p, lw=None):
    c.setLineWidth(lw or st.lt)
    c.setStrokeColor(st.ink)
    c.drawPath(p, stroke=1, fill=0)


def circ(c, st, x, y, r, col=None, lw=None, fill=True):
    p = c.beginPath()
    p.circle(x, y, r)
    if fill:
        fillstroke(c, st, p, col if col is not None else white, lw)
    else:
        stroke(c, st, p, lw)


def ring_circle(c, st, r, lw=None):
    circ(c, st, 0, 0, r, fill=False, lw=lw or st.lw)


def polyline(c, pts, close=False):
    p = c.beginPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if close:
        p.close()
    return p


# ---------------------------------------------------------------- shapes
def petal_path(c, r0, r1, hw, style):
    L = r1 - r0
    p = c.beginPath()
    p.moveTo(0, r0)
    if style == 'point':
        p.curveTo(hw * 1.3, r0 + .25 * L, hw * .95, r0 + .75 * L, 0, r1)
        p.curveTo(-hw * .95, r0 + .75 * L, -hw * 1.3, r0 + .25 * L, 0, r0)
    elif style == 'round':
        p.curveTo(hw * .85, r0 + .02 * L, hw * 1.08, r0 + .5 * L, hw * .8, r0 + .78 * L)
        p.curveTo(hw * .55, r1 + .03 * L, -hw * .55, r1 + .03 * L, -hw * .8, r0 + .78 * L)
        p.curveTo(-hw * 1.08, r0 + .5 * L, -hw * .85, r0 + .02 * L, 0, r0)
    elif style == 'ogee':
        p.curveTo(hw * 1.35, r0 + .18 * L, hw * 1.15, r0 + .55 * L, hw * .42, r0 + .74 * L)
        p.curveTo(hw * .08, r0 + .84 * L, 0, r0 + .9 * L, 0, r1)
        p.curveTo(0, r0 + .9 * L, -hw * .08, r0 + .84 * L, -hw * .42, r0 + .74 * L)
        p.curveTo(-hw * 1.15, r0 + .55 * L, -hw * 1.35, r0 + .18 * L, 0, r0)
    elif style == 'tear':
        p.curveTo(hw * 1.55, r0 - .02 * L, hw * 1.05, r0 + .6 * L, 0, r1)
        p.curveTo(-hw * 1.05, r0 + .6 * L, -hw * 1.55, r0 - .02 * L, 0, r0)
    elif style == 'bract':
        p.curveTo(hw * .95, r0 + .04 * L, hw * 1.2, r0 + .36 * L, hw * .82, r0 + .6 * L)
        p.curveTo(hw * .45, r0 + .82 * L, hw * .12, r0 + .9 * L, 0, r1)
        p.curveTo(-hw * .12, r0 + .9 * L, -hw * .45, r0 + .82 * L, -hw * .82, r0 + .6 * L)
        p.curveTo(-hw * 1.2, r0 + .36 * L, -hw * .95, r0 + .04 * L, 0, r0)
    elif style == 'heart':   # inverted heart / lotus
        p.curveTo(hw * 1.4, r0 + .1 * L, hw * 1.25, r0 + .95 * L, hw * .55, r1)
        p.curveTo(hw * .25, r1, hw * .05, r0 + .9 * L, 0, r0 + .8 * L)
        p.curveTo(-hw * .05, r0 + .9 * L, -hw * .25, r1, -hw * .55, r1)
        p.curveTo(-hw * 1.25, r0 + .95 * L, -hw * 1.4, r0 + .1 * L, 0, r0)
    p.close()
    return p


def petal_deco(c, st, r0, r1, hw, style, deco, cb):
    L = r1 - r0
    if 'inner' in deco:
        ip = petal_path(c, r0 + .16 * L, r1 - .16 * L, hw * .52,
                        style if style != 'heart' else 'round')
        fillstroke(c, st, ip, cb, st.lt)
    if 'inner2' in deco:
        ip = petal_path(c, r0 + .3 * L, r1 - .3 * L, hw * .26,
                        style if style != 'heart' else 'round')
        fillstroke(c, st, ip, white if st.pal is None else st.col(0), st.lt)
    if 'vein' in deco:
        stroke(c, st, polyline(c, [(0, r0 + .08 * L), (0, r1 - .1 * L)]))
    if 'dots' in deco:
        rr = min(hw * .13, L * .05)
        for t in (.3, .5, .7):
            circ(c, st, 0, r0 + t * L, rr, cb, st.lt)
    if 'chev' in deco:
        for t in (.25, .45, .65):
            y = r0 + t * L
            a = hw * (0.8 - t * 0.6)
            stroke(c, st, polyline(c, [(-a, y), (0, y + L * .12), (a, y)]))
    if 'veins' in deco:
        stroke(c, st, polyline(c, [(0, r0 + .05 * L), (0, r1 - .08 * L)]))
        for t in (.25, .45, .65):
            y = r0 + t * L
            w = hw * (0.75 - 0.5 * t)
            for s in (-1, 1):
                p = c.beginPath()
                p.moveTo(0, y)
                p.curveTo(s * w * .4, y + L * .05, s * w * .8, y + L * .1, s * w, y + L * .2)
                stroke(c, st, p)
    if 'arc' in deco:
        p = c.beginPath()
        a = hw * .55
        p.moveTo(-a, r0 + .2 * L)
        p.curveTo(-a * .5, r0 + .38 * L, a * .5, r0 + .38 * L, a, r0 + .2 * L)
        stroke(c, st, p)
    if 'tipdot' in deco:
        circ(c, st, 0, r1 - .2 * L, min(hw * .16, L * .07), cb, st.lt)


def holly_leaf(c, st, Lh, Wh, col):
    _seasonal_only('holly_leaf')
    """Holly leaf from origin pointing +y."""
    ts = [.2, .42, .64, .84]
    def half(t):
        return Wh * .5 * (math.sin(math.pi * t) ** .75)
    right = [(0, 0)] + [(half(t), t * Lh) for t in ts] + [(0, Lh)]
    p = c.beginPath()
    p.moveTo(0, 0)
    d = Wh * .14
    for a, b in zip(right[:-1], right[1:]):
        c1 = (a[0] + (b[0] - a[0]) / 3 - d, a[1] + (b[1] - a[1]) / 3)
        c2 = (a[0] + 2 * (b[0] - a[0]) / 3 - d, a[1] + 2 * (b[1] - a[1]) / 3)
        if a == (0, 0):
            c1 = (Wh * .12, Lh * .03)
        p.curveTo(c1[0], c1[1], c2[0], c2[1], b[0], b[1])
    left = [(-x, y) for x, y in reversed(right)]
    for a, b in zip(left[:-1], left[1:]):
        c1 = (a[0] + (b[0] - a[0]) / 3 + d, a[1] + (b[1] - a[1]) / 3)
        c2 = (a[0] + 2 * (b[0] - a[0]) / 3 + d, a[1] + 2 * (b[1] - a[1]) / 3)
        if b == (0, 0):
            c2 = (-Wh * .12, Lh * .03)
        p.curveTo(c1[0], c1[1], c2[0], c2[1], b[0], b[1])
    p.close()
    fillstroke(c, st, p, col)
    stroke(c, st, polyline(c, [(0, Lh * .02), (0, Lh * .9)]))
    for x, y in right[1:-1]:
        for s in (-1, 1):
            q = c.beginPath()
            q.moveTo(0, y - Lh * .09)
            q.curveTo(s * x * .3, y - Lh * .06, s * x * .55, y - Lh * .03, s * x * .7, y - Lh * .01)
            stroke(c, st, q)


def berry(c, st, x, y, r, col):
    circ(c, st, x, y, r, col, st.lw)
    circ(c, st, x - r * .35, y + r * .35, r * .28, white if st.pal is None else st.col(7), st.lt)


def berries(c, st, x, y, r, col):
    for dx, dy in ((-r * .95, -r * .3), (r * .95, -r * .3), (0, r * .75)):
        berry(c, st, x + dx, y + dy, r, col)


def pine_sprig(c, st, L, W, col, needles=6):
    _seasonal_only('pine_sprig')
    """Stem along +y from origin with lens needles."""
    stroke(c, st, polyline(c, [(0, 0), (0, L * .96)]), st.lw)
    nl = W * .95
    for i in range(needles):
        t = .12 + .8 * i / (needles - 1)
        y = t * L
        ln = nl * (1.0 - .45 * t)
        for s in (-1, 1):
            c.saveState()
            c.translate(0, y)
            c.rotate(-s * 52)
            fillstroke(c, st, petal_path(c, 0, ln, ln * .16, 'point'), col, st.lt)
            c.restoreState()
    c.saveState()
    c.translate(0, L * .9)
    fillstroke(c, st, petal_path(c, 0, nl * .5, nl * .08, 'point'), col, st.lt)
    c.restoreState()


def star_path(c, R, r, n=5, rot=90):
    p = c.beginPath()
    for i in range(2 * n):
        a = math.radians(rot + i * 180.0 / n)
        rr = R if i % 2 == 0 else r
        x, y = rr * math.cos(a), rr * math.sin(a)
        if i == 0:
            p.moveTo(x, y)
        else:
            p.lineTo(x, y)
    p.close()
    return p


def star(c, st, x, y, R, col, n=5, inner=True, ratio=.45):
    c.saveState()
    c.translate(x, y)
    fillstroke(c, st, star_path(c, R, R * ratio, n), col)
    if inner:
        fillstroke(c, st, star_path(c, R * .5, R * .5 * ratio, n), white if st.pal is None else st.col(0), st.lt)
    c.restoreState()


def sparkle(c, st, x, y, R, col):
    c.saveState()
    c.translate(x, y)
    p = c.beginPath()
    p.moveTo(0, R)
    for k in range(4):
        a0 = math.radians(90 + 90 * k)
        a1 = math.radians(90 + 90 * (k + 1))
        q = R * .18
        p.curveTo(q * math.cos(a0 + .9), q * math.sin(a0 + .9),
                  q * math.cos(a1 - .9), q * math.sin(a1 - .9),
                  R * math.cos(a1), R * math.sin(a1))
    p.close()
    fillstroke(c, st, p, col, st.lt)
    c.restoreState()


# ------------------------------------------------------- tube snowflakes
def snowflake_spec(R, rng, detail=1.0):
    ws = max(2.2, R * rng.uniform(.065, .085))
    spec = {'R': R, 'ws': ws, 'segs': [], 'plates': [], 'sec': None}
    y0 = R * .1
    y1 = R * .9
    spec['segs'].append((0, y0, 0, y1, ws))
    nb = rng.choice([2, 3, 3, 4]) if detail > .5 else rng.choice([1, 2])
    ts = sorted(rng.uniform(.28, .8) for _ in range(nb))
    # spread them
    ts = [.26 + (.55 * (i + .5) / nb) + rng.uniform(-.04, .04) for i in range(nb)]
    ang = math.radians(rng.choice([60, 60, 55, 45]))
    for t in ts:
        y = y0 + t * (y1 - y0)
        Lb = R * rng.uniform(.2, .33) * (1.25 - t)
        wb = ws * .72
        for s in (-1, 1):
            ex, ey = s * Lb * math.sin(ang), y + Lb * math.cos(ang)
            spec['segs'].append((0, y, ex, ey, wb))
            if detail > .5 and Lb > R * .14 and rng.random() < .6:
                for u in (.55,):
                    bx, by = s * Lb * u * math.sin(ang), y + Lb * u * math.cos(ang)
                    l2 = Lb * .38
                    a2 = ang + math.radians(60) * 1  # outward twig (closer to horizontal)
                    spec['segs'].append((bx, by, bx + s * l2 * math.sin(ang - math.radians(60)),
                                         by + l2 * math.cos(ang - math.radians(60)), ws * .5))
                    spec['segs'].append((bx, by, bx + s * l2 * math.sin(a2),
                                         by + l2 * math.cos(a2), ws * .5))
            if rng.random() < .35:
                spec['plates'].append(('dia', ex, ey, wb * .95))
    tip = rng.choice(['dia', 'hex', 'fork', 'circle', 'fork'])
    if tip == 'fork':
        for s in (-1, 1):
            spec['segs'].append((0, y1 - R * .08, s * R * .09, y1 + R * .02, ws * .6))
    else:
        spec['plates'].append((tip, 0, y1, ws * 1.3))
    if detail > .5 and rng.random() < .5:
        spec['plates'].append(('hex', 0, y0 + (y1 - y0) * rng.uniform(.12, .2), ws * 1.05))
    if detail > .5 and rng.random() < .6:
        spec['sec'] = rng.uniform(.28, .42)  # secondary short arms at 30deg
    spec['center'] = rng.choice(['hex', 'hexstar', 'circle'])
    return spec


def plate(c, st, kind, x, y, s, col):
    c.saveState()
    c.translate(x, y)
    if kind == 'dia':
        p = polyline(c, [(0, -s * 1.1), (s * .75, 0), (0, s * 1.3), (-s * .75, 0)], True)
        fillstroke(c, st, p, col)
        stroke(c, st, polyline(c, [(0, -s * .5), (0, s * .65)]))
    elif kind == 'hex':
        pts = [P(s, math.radians(90 + 60 * i)) for i in range(6)]
        fillstroke(c, st, polyline(c, pts, True), col)
        pts2 = [P(s * .5, math.radians(90 + 60 * i)) for i in range(6)]
        stroke(c, st, polyline(c, pts2, True))
    elif kind == 'circle':
        circ(c, st, 0, 0, s * .85, col)
        circ(c, st, 0, 0, s * .4, col, st.lt)
    c.restoreState()


def draw_snowflake(c, st, spec, col=None, col2=None, arms=6):
    _seasonal_only('draw_snowflake')
    col = col if col is not None else white
    col2 = col2 if col2 is not None else col
    R, ws = spec['R'], spec['ws']
    lwo = max(.6, st.lw * (.8 if R < 40 else 1.0))
    segs = list(spec['segs'])
    sec = []
    if spec.get('sec'):
        L = R * spec['sec']
        sec = [(0, R * .08, 0, L, ws * .6)]
    c.setLineCap(1)
    c.setLineJoin(1)
    for pas in (0, 1):
        for i in range(arms):
            c.saveState()
            c.rotate(i * 360.0 / arms)
            for (x1, y1, x2, y2, w) in segs:
                c.setLineWidth(w + 2 * lwo if pas == 0 else w)
                c.setStrokeColor(st.ink if pas == 0 else col)
                c.line(x1, y1, x2, y2)
            c.rotate(180.0 / arms)
            for (x1, y1, x2, y2, w) in sec:
                c.setLineWidth(w + 2 * lwo if pas == 0 else w)
                c.setStrokeColor(st.ink if pas == 0 else col)
                c.line(x1, y1, x2, y2)
            c.restoreState()
    for i in range(arms):
        c.saveState()
        c.rotate(i * 360.0 / arms)
        for (k, x, y, s) in spec['plates']:
            plate(c, st, k, x, y, s, col2)
        c.restoreState()
    # centre
    cr = R * .17
    ck = spec.get('center', 'hex')
    if ck == 'circle':
        circ(c, st, 0, 0, cr, col2)
        circ(c, st, 0, 0, cr * .55, col, st.lt)
    else:
        pts = [P(cr, math.radians(90 + 60 * i)) for i in range(6)]
        fillstroke(c, st, polyline(c, pts, True), col2)
        if ck == 'hexstar':
            c.saveState()
            fillstroke(c, st, star_path(c, cr * .8, cr * .4, 6), col, st.lt)
            c.restoreState()
        else:
            pts2 = [P(cr * .55, math.radians(90 + 60 * i)) for i in range(6)]
            fillstroke(c, st, polyline(c, pts2, True), col, st.lt)
            for q in pts:
                pass


def snowflake(c, st, x, y, R, rng, col=None, rot=0, detail=1.0):
    spec = snowflake_spec(R, rng, detail)
    c.saveState()
    c.translate(x, y)
    c.rotate(rot)
    draw_snowflake(c, st, spec, col)
    c.restoreState()


# ------------------------------------------------------------ ring types
def pick_n(r, target, k, lo=1):
    target = max(target, 10.5)
    m = max(lo, int(round(TAU * r / (k * target))))
    return k * m


def draw_ring(c, st, rg):
    t = rg['type']
    r0, r1, n = rg['r0'], rg['r1'], rg['n']
    ca, cb, cc = st.col(rg.get('ca')), st.col(rg.get('cb')), st.col(rg.get('cc'))
    L = r1 - r0
    rm = (r0 + r1) / 2
    rng = random.Random(rg.get('seed', 1))

    if t in ('petals',):
        style = rg['style']
        rw = r0 + .4 * L
        hw = hwidth(rw, n) / .86
        if rg.get('layered', True):
            back_r1 = r1
            front_r1 = r1 - L * rg.get('drop', .22)
            def back(i):
                fillstroke(c, st, petal_path(c, r0, back_r1, hw * 1.02, style), cc)
                if rg.get('back_deco'):
                    petal_deco(c, st, r0 + L * .45, back_r1, hw * .55, style, rg['back_deco'], cb)
            around(c, n, back, 180.0 / n)
            def front(i):
                fillstroke(c, st, petal_path(c, r0, front_r1, hw * .98, style), ca)
                petal_deco(c, st, r0, front_r1, hw * .98, style, rg['deco'], cb)
            around(c, n, front)
        else:
            def front(i):
                fillstroke(c, st, petal_path(c, r0, r1, hw, style), ca)
                petal_deco(c, st, r0, r1, hw, style, rg['deco'], cb)
            around(c, n, front)

    elif t == 'holly':
        th = math.radians(rg.get('ang', 38))
        base = r0 + .06 * L
        Lh = (r1 - base) / math.cos(th) * .97
        Wh = Lh * .46
        def unit(i):
            for s in (-1, 1):
                c.saveState()
                c.translate(0, base)
                c.rotate(-s * math.degrees(th))
                holly_leaf(c, st, Lh, Wh, ca)
                c.restoreState()
            berries(c, st, 0, base + L * .1, L * .085, cb)
        around(c, n, unit)

    elif t == 'pine':
        def unit(i):
            if rg.get('cones') and i % 2 == 1:
                pine_cone(c, st, r0 + L * .08, r1 - L * .05, L * .22, cb)
            else:
                c.saveState()
                c.translate(0, r0 + L * .04)
                pine_sprig(c, st, L * .94, L * .34, ca, 6)
                c.restoreState()
        around(c, n, unit)

    elif t == 'flakes':
        s = min(L * .46, hwidth(rm, n) * .9)
        def unit(i):
            line_flake(c, st, 0, rm, s, 90)
        around(c, n, unit)
        def dot(i):
            circ(c, st, 0, rm, min(L * .08, hwidth(rm, n) * .12), cb, st.lt)
        around(c, n, dot, 180.0 / n)

    elif t == 'ornaments':
        b = min(L * .34, hwidth(rm, n) * .72)
        cy = r1 - b - L * .06
        def unit(i):
            stroke(c, st, polyline(c, [(0, r0), (0, cy - b * 1.2)]))
            capw, caph = b * .55, b * .32
            p = polyline(c, [(-capw / 2, cy - b * .92), (capw / 2, cy - b * .92),
                             (capw / 2, cy - b * .92 - caph), (-capw / 2, cy - b * .92 - caph)], True)
            fillstroke(c, st, p, cb, st.lt)
            circ(c, st, 0, cy - b * 1.24 - caph * .2, b * .12, None, st.lt, fill=False)
            circ(c, st, 0, cy, b, ca)
            c.saveState()
            q = c.beginPath(); q.circle(0, cy, b)
            c.clipPath(q, stroke=0, fill=0)
            for yy in (-b * .32, b * .32):
                stroke(c, st, polyline(c, [(-b, cy + yy), (b, cy + yy)]))
            m = 6
            pts = []
            for j in range(m + 1):
                x = -b + 2 * b * j / m
                pts.append((x, cy + (b * .32 if j % 2 == 0 else -b * .32)))
            p2 = polyline(c, pts)
            stroke(c, st, p2)
            c.restoreState()
            circ(c, st, 0, cy, b, None, st.lw, fill=False)
        around(c, n, unit)

    elif t == 'beads':
        b = min(L * .42, hwidth(rm, n) * .8)
        def unit(i):
            circ(c, st, 0, rm, b, ca)
            circ(c, st, 0, rm, b * .45, cb, st.lt)
        around(c, n, unit)

    elif t == 'dots':
        b = min(L * .3, hwidth(rm, n) * .55)
        def unit(i):
            circ(c, st, 0, rm, b, ca, st.lt)
        around(c, n, unit)
        def dia(i):
            s = b * .9
            stroke(c, st, polyline(c, [(0, rm - s), (s * .6, rm), (0, rm + s), (-s * .6, rm)], True))
        around(c, n, dia, 180.0 / n)

    elif t == 'zigzag':
        step = TAU / n
        pts = []
        for i in range(n):
            pts.append(P(r0, i * step))
            pts.append(P(r1, (i + .5) * step))
        zp = polyline(c, pts, True)
        zp.circle(0, 0, r0)
        c.setLineWidth(st.lt); c.setFillColor(ca); c.setStrokeColor(st.ink)
        c.drawPath(zp, stroke=1, fill=1, fillMode=FILL_EVEN_ODD)
        rr = min(L * .16, hwidth(r0 + L * .3, n) * .2)
        def unit(i):
            circ(c, st, 0, r0 + L * .3, rr, cb, st.lt)
        around(c, n, unit, 180.0 / n + 90 - 90)

    elif t == 'lattice':
        step = TAU / n
        for i in range(n):
            a = i * step
            stroke(c, st, polyline(c, [P(r0, a), P(r1, a + step)]))
            stroke(c, st, polyline(c, [P(r0, a + step), P(r1, a)]))
        bb = min(L * .2, hwidth(rm, n) * .3)
        def unit(i):
            circ(c, st, 0, rm, bb, ca, st.lt)
        around(c, n, unit, 180.0 / n - 90 + 90)

    elif t == 'rope':
        step = TAU / n
        for i in range(n):
            a = i * step
            p = c.beginPath()
            x, y = P(r0, a)
            p.moveTo(x, y)
            c1 = P(r0 + L * .1, a + step * .9)
            c2 = P(r1 - L * .1, a + step * .6)
            e = P(r1, a + step * 1.6)
            p.curveTo(c1[0], c1[1], c2[0], c2[1], e[0], e[1])
            stroke(c, st, p)

    elif t == 'chevron':
        step = TAU / n
        for i in range(n):
            a = i * step
            for f in (0.0, .45):
                stroke(c, st, polyline(c, [P(r0, a + f * step), P(rm, a + (f + .45) * step), P(r1, a + f * step)]))

    elif t == 'scallop':
        a = hwidth(r0, n) * .98
        def unit(i):
            p = c.beginPath()
            p.moveTo(a, r0)
            p.curveTo(a, r0 + a * 1.33 * (L / a if L < a else 1), -a, r0 + a * 1.33 * (L / a if L < a else 1), -a, r0)
            p.close()
            fillstroke(c, st, p, ca, st.lw)
            q = c.beginPath()
            a2 = a * .55
            h2 = min(L, a) * .7
            q.moveTo(a2, r0)
            q.curveTo(a2, r0 + h2, -a2, r0 + h2, -a2, r0)
            q.close()
            fillstroke(c, st, q, cb, st.lt)
        around(c, n, unit)

    elif t == 'lace':
        a = hwidth(r0, n) * 1.0
        h = L * .75
        def unit(i):
            p = c.beginPath()
            p.moveTo(a, r0)
            p.curveTo(a * 1.05, r0 + h * 1.25, -a * 1.05, r0 + h * 1.25, -a, r0)
            p.close()
            fillstroke(c, st, p, ca, st.lw)
            q = c.beginPath()
            q.moveTo(a * .6, r0)
            q.curveTo(a * .6, r0 + h * .8, -a * .6, r0 + h * .8, -a * .6, r0)
            q.close()
            fillstroke(c, st, q, cb, st.lt)
            circ(c, st, 0, r0 + h * .3, min(a * .2, h * .16), None, st.lt, fill=False)
            circ(c, st, 0, r0 + h * .98 + L * .1, min(a * .16, L * .09), cc, st.lt)
        around(c, n, unit)
        def picot(i):
            stroke(c, st, polyline(c, [(0, r0), (0, r0 + h * .55)]))
            circ(c, st, 0, r0 + h * .6, min(a * .14, L * .08), cc, st.lt)
        around(c, n, picot, 180.0 / n)

    elif t == 'stars':
        s = min(L * .44, hwidth(rm, n) * .78)
        def unit(i):
            c.saveState(); c.translate(0, rm); c.rotate(0)
            fillstroke(c, st, star_path(c, s, s * .45, 5), ca)
            circ(c, st, 0, 0, s * .2, cb, st.lt)
            c.restoreState()
        around(c, n, unit)
        def dot(i):
            circ(c, st, 0, rm, s * .18, cb, st.lt)
        around(c, n, dot, 180.0 / n)

    elif t == 'rays':
        step = TAU / n
        for i in range(n):
            stroke(c, st, polyline(c, [P(r0, i * step), P(r1, i * step)]))
        hw = hwidth(r0 + .4 * L, n) * .55
        def unit(i):
            fillstroke(c, st, petal_path(c, r0 + L * .14, r1 - L * .1, hw, 'tear'), ca, st.lt)
        around(c, n, unit, 180.0 / n)

    elif t == 'bells':
        s = min(L * .42, hwidth(rm, n) * .8)
        def unit(i):
            c.saveState(); c.translate(0, rm)
            bell(c, st, s, ca, cb)
            c.restoreState()
        around(c, n, unit)

    elif t == 'sep':
        pass


def pine_cone(c, st, y0, y1, w, col):
    _seasonal_only('pine_cone')
    h = y1 - y0
    p = c.beginPath()
    p.moveTo(0, y0)
    p.curveTo(w * 1.2, y0 + h * .15, w * 1.0, y0 + h * .8, 0, y1)
    p.curveTo(-w * 1.0, y0 + h * .8, -w * 1.2, y0 + h * .15, 0, y0)
    p.close()
    fillstroke(c, st, p, col)
    c.saveState()
    c.clipPath(p, stroke=0, fill=0)
    rows = 6
    for j in range(rows + 1):
        yy = y0 + h * (j / rows)
        cols = 3
        for k in range(-cols, cols + 1):
            xx = k * w * .55 + (w * .275 if j % 2 else 0)
            q = c.beginPath()
            q.moveTo(xx - w * .28, yy)
            q.curveTo(xx - w * .28, yy + h * .12, xx + w * .28, yy + h * .12, xx + w * .28, yy)
            stroke(c, st, q)
    c.restoreState()
    fillstroke(c, st, p, None, st.lw) if False else stroke(c, st, p, st.lw)


def bell(c, st, s, ca, cb):
    _seasonal_only('bell')
    """Bell centred at origin, mouth toward +y (outward)."""
    p = c.beginPath()
    p.moveTo(-s * .25, -s * .8)
    p.curveTo(-s * .55, -s * .7, -s * .5, 0, -s * .6, s * .45)
    p.curveTo(-s * .65, s * .65, -s * .9, s * .7, -s * .9, s * .8)
    p.lineTo(s * .9, s * .8)
    p.curveTo(s * .9, s * .7, s * .65, s * .65, s * .6, s * .45)
    p.curveTo(s * .5, 0, s * .55, -s * .7, s * .25, -s * .8)
    p.close()
    fillstroke(c, st, p, ca)
    stroke(c, st, polyline(c, [(-s * .62, s * .5), (s * .62, s * .5)]))
    circ(c, st, 0, s * .9, s * .16, cb, st.lt)
    circ(c, st, 0, -s * .9, s * .12, None, st.lt, fill=False)


# -------------------------------------------------------- centres
def draw_center(c, st, cen):
    kind = cen['kind']
    R = cen['R']
    ca, cb, cc = st.col(cen.get('ca')), st.col(cen.get('cb')), st.col(cen.get('cc'))
    if kind == 'poinsettia':
        n = cen.get('n', 8)
        hw = hwidth(R * .45, n) / .8
        around(c, n, lambda i: (fillstroke(c, st, petal_path(c, R * .12, R, hw * 1.1, 'bract'), cc),
                                petal_deco(c, st, R * .12, R, hw * 1.1, 'bract', ('veins',), cb)), 180.0 / n)
        around(c, n, lambda i: (fillstroke(c, st, petal_path(c, R * .1, R * .72, hw * .8, 'bract'), ca),
                                petal_deco(c, st, R * .1, R * .72, hw * .8, 'bract', ('veins',), cb)))
        circ(c, st, 0, 0, R * .2, cb)
        for i in range(7):
            a = TAU * i / 7
            x, y = P(R * .11, a) if i else (0, 0)
            circ(c, st, x, y, R * .05, cc, st.lt)
    elif kind == 'snowflake':
        spec = snowflake_spec(R, random.Random(cen.get('seed', 3)), 1.0)
        circ(c, st, 0, 0, R, cc, st.lw)
        c.saveState(); c.rotate(90)
        draw_snowflake(c, st, spec, ca, cb, cen.get('arms', 6))
        c.restoreState()
    elif kind == 'star':
        n = cen.get('n', 8)
        circ(c, st, 0, 0, R, cc)
        c.saveState(); c.rotate(90)
        fillstroke(c, st, star_path(c, R * .95, R * .5, n, 0), ca)
        c.rotate(180.0 / n)
        fillstroke(c, st, star_path(c, R * .6, R * .32, n, 0), cb, st.lt)
        c.restoreState()
        circ(c, st, 0, 0, R * .22, cc)
        circ(c, st, 0, 0, R * .1, ca, st.lt)
    elif kind == 'rose':
        n = cen.get('n', 8)
        circ(c, st, 0, 0, R, cc)
        around(c, n, lambda i: fillstroke(c, st, petal_path(c, R * .25, R * .98, hwidth(R * .55, n) * 1.15, 'round'), cb), 180.0 / n)
        around(c, n, lambda i: fillstroke(c, st, petal_path(c, R * .2, R * .8, hwidth(R * .45, n) * 1.1, 'point'), ca))
        around(c, n, lambda i: petal_deco(c, st, R * .2, R * .8, hwidth(R * .45, n) * 1.1, 'point', ('vein',), cb))
        circ(c, st, 0, 0, R * .26, cb)
        circ(c, st, 0, 0, R * .12, cc, st.lt)
    elif kind == 'holly':
        circ(c, st, 0, 0, R, cc)
        n = cen.get('n', 4)
        def u(i):
            holly_leaf(c, st, R * .92, R * .42, ca)
        around(c, n, u, 45)
        berries(c, st, 0, 0, R * .16, cb)


# -------------------------------------------------------- mandala spec
BIG = ['petals', 'petals', 'petals', 'holly', 'pine', 'flakes', 'ornaments', 'bells', 'bract']
SMALL = ['beads', 'zigzag', 'lattice', 'rope', 'chevron', 'scallop', 'dots', 'stars', 'rays']
STYLES = ['point', 'round', 'ogee', 'tear', 'heart']
DECOS = [('inner', 'vein'), ('inner', 'dots'), ('inner', 'inner2'), ('chev',), ('inner', 'tipdot'),
         ('inner', 'arc'), ('vein', 'dots'), ('inner',)]


def mandala_spec(R, rng, k=None, center=None, themes=None, outer=None, density=1.0):
    k = k or rng.choice([8, 8, 10, 12, 12, 16])
    center = center or rng.choice(CHRISTMAS_CENTERS if seasonal() else GENERIC_CENTERS)
    if not seasonal() and center in SEASONAL_ONLY:
        raise ValueError(f'centre {center} is a christmas motif')
    cR = max(22 if R < 140 else 16, R * rng.uniform(.13, .18))
    spec = {'R': R, 'k': k, 'rings': [], 'center': {'kind': center, 'R': cR, 'n': k if center != 'snowflake' else 6,
                                                  'seed': rng.randint(0, 9999), 'ca': 1, 'cb': 2, 'cc': 3}}
    if center == 'snowflake':
        spec['center']['n'] = 6
    if center == 'holly':
        spec['center']['n'] = 4 if k % 4 == 0 else 5
    themes = themes_for(themes or CHRISTMAS_THEMES)
    outer_t = max(12, R * rng.uniform(.09, .13))
    Rin = R - outer_t
    r = cR
    seq = []
    big_turn = True
    used_theme = set()
    last = None
    while True:
        remaining = Rin - r
        if remaining < R * .045:
            if seq and remaining > 0:
                t, a, b = seq[-1]
                seq[-1] = (t, a, b + remaining)
            break
        if big_turn:
            t = rng.choice(BIG)
            if t in ('holly', 'pine', 'flakes', 'ornaments', 'bells', 'bract'):
                if t not in themes or t in used_theme or r < R * .3:
                    t = 'petals'
            th = R * rng.uniform(.11, .17) * density
            if t in ('holly', 'pine'):
                th = R * rng.uniform(.13, .17)
            if t in ('flakes', 'ornaments', 'bells'):
                th = R * rng.uniform(.09, .12)
        else:
            t = rng.choice(SMALL)
            while t == last or (t in used_theme and rng.random() < .6):
                t = rng.choice(SMALL)
            if t == 'stars' and r < R * .35:
                t = 'beads'
            th = R * rng.uniform(.035, .055) * density
        th = max(th, 17 if big_turn else 6.5)
        big_turn = not big_turn if rng.random() < .9 else big_turn
        if r + th > Rin:
            th = Rin - r
        seq.append((t, r, r + th))
        used_theme.add(t)
        last = t
        r += th + (R * .012 if rng.random() < .45 else 0)
    if outer is None:
        outer = rng.choice(['lace', 'petals', 'petals', 'bract', 'lace'])
    seq.append((outer, Rin + R * .008, R))
    rings = []
    for (t, a, b) in seq:
        rg = {'type': t, 'r0': a, 'r1': b, 'seed': rng.randint(0, 99999),
              'ca': rng.randint(0, 7), 'cb': rng.randint(0, 7), 'cc': rng.randint(0, 7)}
        L = b - a
        rm = (a + b) / 2
        if t == 'petals' or t == 'bract':
            rg['type'] = 'petals'
            rg['style'] = 'bract' if t == 'bract' else rng.choice(MOTIFS['styles'] or STYLES)
            unit = L * rng.uniform(.5, .85)
            rg['n'] = pick_n(a + L * .4, unit, k)
            rg['deco'] = ('veins',) if t == 'bract' else rng.choice(DECOS)
            rg['layered'] = rng.random() < .75
            rg['back_deco'] = rng.choice([None, ('inner',), ('vein',), ('tipdot',)])
            rg['drop'] = rng.uniform(.18, .3)
        elif t == 'holly':
            rg['n'] = pick_n(rm, L * 1.7, k)
        elif t == 'pine':
            rg['n'] = pick_n(rm, L * .75, k)
            rg['cones'] = rng.random() < .5
        elif t == 'flakes':
            rg['n'] = pick_n(rm, L * 1.05, k)
        elif t == 'ornaments':
            rg['n'] = pick_n(rm, L * .95, k)
        elif t == 'bells':
            rg['n'] = pick_n(rm, L * 1.1, k)
        elif t == 'lace':
            rg['n'] = pick_n(a, L * 1.35, k)
        elif t in ('beads', 'dots', 'stars'):
            rg['n'] = pick_n(rm, L * (1.1 if t != 'stars' else 1.25), k)
        elif t in ('zigzag', 'lattice', 'rope', 'chevron', 'rays'):
            rg['n'] = pick_n(rm, L * rng.uniform(.8, 1.3), k)
        elif t == 'scallop':
            rg['n'] = pick_n(a, L * 1.4, k)
        rings.append(rg)
    spec['rings'] = rings
    spec['seps'] = [rng.random() < .35 for _ in rings]
    return spec


def draw_mandala(c, st, spec, x, y, rot=0, bg=True):
    c.saveState()
    c.translate(x, y)
    c.rotate(rot)
    c.setLineJoin(1)
    c.setLineCap(1)
    R = spec['R']
    if bg:
        # coloured mode: fill annuli
        if st.pal is not None:
            for rg in reversed(spec['rings']):
                circ(c, st, 0, 0, rg['r1'], st.col(rg['cc'] + 2), .01)
        else:
            circ(c, st, 0, 0, R, white, .01)
    draw_center(c, st, spec['center'])
    ring_circle(c, st, spec['center']['R'])
    for rg, sep in zip(spec['rings'], spec['seps']):
        ring_circle(c, st, rg['r0'])
        if sep and rg['type'] not in ('lace',):
            circ(c, st, 0, 0, rg['r0'] + 2.2, fill=False, lw=st.lt)
        draw_ring(c, st, rg)
        if rg['type'] in ('beads', 'dots', 'zigzag', 'lattice', 'rope', 'chevron', 'rays', 'stars', 'flakes', 'ornaments', 'bells'):
            ring_circle(c, st, rg['r1'])
    c.restoreState()


# -------------------------------------------------------- backgrounds
def line_flake(c, st, x, y, R, rot=0):
    _seasonal_only('line_flake')
    c.saveState(); c.translate(x, y); c.rotate(rot)
    c.setLineCap(1)
    for i in range(6):
        c.saveState(); c.rotate(60 * i)
        stroke(c, st, polyline(c, [(0, R * .22), (0, R)]))
        for t, l in ((.5, .28), (.75, .2)):
            stroke(c, st, polyline(c, [(-l * R * .8, (t + l * .55) * R), (0, t * R), (l * R * .8, (t + l * .55) * R)]))
        c.restoreState()
    circ(c, st, 0, 0, R * .22, white, st.lt)
    c.restoreState()


def rect_minus_circles(c, x0, y0, x1, y1, holes):
    p = c.beginPath()
    p.rect(x0, y0, x1 - x0, y1 - y0)
    for (hx, hy, hr) in holes:
        p.circle(hx, hy, hr)
    return p


def bg_scatter(c, st, box, holes, rng, kinds=('flake', 'star', 'dot', 'sparkle'), dens=1.0, smin=6, smax=16):
    x0, y0, x1, y1 = box
    pts = []
    tries = 0
    target = int((x1 - x0) * (y1 - y0) / 1900 * dens)
    while len(pts) < target and tries < 20000:
        tries += 1
        x, y = rng.uniform(x0 - 6, x1 + 6), rng.uniform(y0 - 6, y1 + 6)
        s = rng.uniform(smin, smax)
        ok = True
        for (hx, hy, hr) in holes:
            if math.hypot(x - hx, y - hy) < hr + s * .9:
                ok = False
                break
        if not ok:
            continue
        for (px, py, ps) in pts:
            if math.hypot(x - px, y - py) < (s + ps) * 1.25 + 3:
                ok = False
                break
        if ok:
            pts.append((x, y, s))
    for (x, y, s) in pts:
        kd = rng.choice(kinds)
        if s < smin + (smax - smin) * .3 and kd == 'flake':
            kd = 'sparkle'
        if kd == 'flake' and not seasonal():
            kd = 'sparkle'
        if kd == 'flake':
            line_flake(c, st, x, y, s * 1.1, rng.uniform(0, 60))
        elif kd == 'star':
            star(c, st, x, y, s * .8, white, 5, inner=s > 11)
        elif kd == 'sparkle':
            sparkle(c, st, x, y, s * .8, white)
        else:
            circ(c, st, x, y, s * .28, white, st.lt)


def bg_rays(c, st, box, cx, cy, R0, n, rng):
    x0, y0, x1, y1 = box
    far = math.hypot(x1 - x0, y1 - y0)
    for i in range(n):
        a = TAU * i / n
        stroke(c, st, polyline(c, [(cx + R0 * math.cos(a), cy + R0 * math.sin(a)),
                                   (cx + far * math.cos(a), cy + far * math.sin(a))]))
    # dots / stars inside alternating wedges on concentric arcs
    for j, rr in enumerate([R0 + 26 + 34 * m for m in range(12)]):
        for i in range(n):
            a = TAU * (i + .5) / n
            x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
            if not (x0 < x < x1 and y0 < y < y1):
                continue
            w = rr * math.sin(math.pi / n)
            s = min(9, w * .6)
            if s < 2.5:
                continue
            if (i + j) % 2 == 0:
                circ(c, st, x, y, s * .6, white, st.lt)
            else:
                c.saveState(); c.translate(x, y); c.rotate(math.degrees(a) - 90)
                fillstroke(c, st, petal_path(c, -s * 1.3, s * 1.3, s * .55, 'point'), white, st.lt)
                c.restoreState()


def bg_lattice(c, st, box, rng, step=34):
    x0, y0, x1, y1 = box
    W, H = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    m = int((W + H) / step) + 2
    for i in range(-m, m + 1):
        o = i * step
        stroke(c, st, polyline(c, [(cx + o - H, cy - H), (cx + o + H, cy + H)]))
        stroke(c, st, polyline(c, [(cx + o + H, cy - H), (cx + o - H, cy + H)]))
    # ornaments at intersections and centres of diamonds
    s2 = step / math.sqrt(2) if False else step
    for i in range(-m, m + 1):
        for j in range(-m, m + 1):
            x = cx + (i + j) * step / 2
            y = cy + (j - i) * step / 2
            if x0 - 10 < x < x1 + 10 and y0 - 10 < y < y1 + 10:
                circ(c, st, x, y, step * .11, white, st.lt)
            xm, ym = x + step / 2, y
            if x0 - 10 < xm < x1 + 10 and y0 - 10 < ym < y1 + 10:
                if (i + j) % 2 == 0:
                    sparkle(c, st, xm, ym, step * .26, white)
                else:
                    stroke(c, st, polyline(c, [(xm, ym - step * .2), (xm + step * .14, ym), (xm, ym + step * .2), (xm - step * .14, ym)], True))


def bg_corners(c, st, box, rng, k=16, Rc=150):
    x0, y0, x1, y1 = box
    spec = mandala_spec(Rc, rng, k=k, center=rng.choice(['star', 'rose', 'poinsettia'] if seasonal() else ['star', 'rose', 'star']),
                        themes=themes_for(['holly', 'stars', 'flakes']))
    for (x, y) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        draw_mandala(c, st, spec, x, y)


def frame(c, st, box, style=0):
    x0, y0, x1, y1 = box
    c.setStrokeColor(st.ink)
    c.setLineWidth(1.5)
    c.rect(x0, y0, x1 - x0, y1 - y0, stroke=1, fill=0)
    c.setLineWidth(.7)
    g = 4
    c.rect(x0 + g, y0 + g, x1 - x0 - 2 * g, y1 - y0 - 2 * g, stroke=1, fill=0)


def corner_ornaments(c, st, box):
    x0, y0, x1, y1 = box
    for (x, y) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        circ(c, st, x, y, 9, white, 1.2)
        c.saveState(); c.translate(x, y)
        fillstroke(c, st, star_path(c, 7, 3, 4, 45), white, st.lt)
        c.restoreState()
