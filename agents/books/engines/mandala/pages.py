import math, random
from art import *

W, H = 612, 792
BOX = (42, 58, 570, 752)
IN = (46, 62, 566, 748)
CX, CY = 306, 405


def clip_rect(c, box):
    p = c.beginPath()
    p.rect(box[0], box[1], box[2] - box[0], box[3] - box[1])
    c.clipPath(p, stroke=0, fill=0)


def background(c, st, kind, rng, holes, center=(CX, CY), R0=260):
    c.saveState()
    clip = rect_minus_circles(c, *IN, holes)
    c.clipPath(clip, stroke=0, fill=0, fillMode=FILL_EVEN_ODD)
    if kind == 'scatter':
        bg_scatter(c, st, IN, holes, rng)
    elif kind == 'snow':
        bg_scatter(c, st, IN, holes, rng, kinds=('flake', 'flake', 'sparkle', 'dot'), smin=7, smax=20)
    elif kind == 'rays':
        bg_rays(c, st, IN, center[0], center[1], R0, rng.choice([36, 48, 60]), rng)
    elif kind == 'lattice':
        bg_lattice(c, st, IN, rng, step=rng.choice([30, 34, 38]))
    elif kind == 'corners':
        bg_corners(c, st, IN, rng, Rc=rng.choice([170, 185, 200]))
    c.restoreState()


def medallion(c, st, x, y, R):
    circ(c, st, x, y, R + 3.5, None, 1.3, fill=False)
    circ(c, st, x, y, R + 7, None, .7, fill=False)


# ------------------------------------------------------------ page kinds
def page_classic(c, st, seed, bg, center=None, k=None, themes=None, outer=None):
    rng = random.Random(seed)
    R = 248
    spec = mandala_spec(R, rng, k=k, center=center, themes=themes, outer=outer)
    background(c, st, bg, rng, [(CX, CY, R + 7)])
    draw_mandala(c, st, spec, CX, CY)
    medallion(c, st, CX, CY, R)
    return spec


def page_snowmandala(c, st, seed, bg):
    rng = random.Random(seed)
    R = 248
    spec = mandala_spec(R, rng, k=12, center='star', themes=['stars', 'flakes'], outer='lace')
    background(c, st, bg, rng, [(CX, CY, R + 7)])
    draw_mandala(c, st, spec, CX, CY)
    fs = snowflake_spec(R * .86, rng, 1.0)
    fs['ws'] = max(fs['ws'], 15)
    c.saveState(); c.translate(CX, CY); c.rotate(90)
    draw_snowflake(c, st, fs, white)
    c.restoreState()
    medallion(c, st, CX, CY, R)


# linear bands ------------------------------------------------------------
def band(c, st, kind, xa, xb, y0, y1, rng):
    h = y1 - y0
    ym = (y0 + y1) / 2
    stroke(c, st, polyline(c, [(xa, y0), (xb, y0)]), st.lw)
    stroke(c, st, polyline(c, [(xa, y1), (xb, y1)]), st.lw)
    if kind == 'zig':
        w = h * .9
        pts = []
        x = xa - w
        i = 0
        while x < xb + w:
            pts.append((x, y0 if i % 2 == 0 else y1))
            if i % 2 == 0:
                circ(c, st, x + w, y0 + h * .28, h * .12, white, st.lt) if False else None
            x += w / 2 * 2 if False else w / 2
            i += 1
        stroke(c, st, polyline(c, pts))
        x = xa - w
        while x < xb + w:
            circ(c, st, x + w / 2, y0 + h * .28, h * .11, white, st.lt)
            x += w
    elif kind == 'scal':
        w = h * 1.1
        x = xa - w
        while x < xb + w:
            p = c.beginPath()
            p.moveTo(x, y0)
            p.curveTo(x, y0 + h * 1.25, x + w, y0 + h * 1.25, x + w, y0)
            p.close()
            fillstroke(c, st, p, white, st.lt)
            q = c.beginPath()
            q.moveTo(x + w * .25, y0)
            q.curveTo(x + w * .25, y0 + h * .62, x + w * .75, y0 + h * .62, x + w * .75, y0)
            q.close()
            fillstroke(c, st, q, white, st.lt)
            x += w
    elif kind == 'beads':
        r = h * .38
        x = xa - r
        while x < xb + 2 * r:
            circ(c, st, x, ym, r, white, st.lt)
            circ(c, st, x, ym, r * .42, white, st.lt)
            x += 2 * r + h * .25
    elif kind == 'dia':
        w = h * .8
        x = xa - w
        i = 0
        while x < xb + w:
            fillstroke(c, st, polyline(c, [(x, y0 + 1), (x + w / 2, ym), (x, y1 - 1), (x - w / 2, ym)], True), white, st.lt)
            fillstroke(c, st, polyline(c, [(x, y0 + h * .3), (x + w * .2, ym), (x, y1 - h * .3), (x - w * .2, ym)], True), white, st.lt)
            circ(c, st, x + w / 2, ym, h * .08, white, st.lt)
            x += w
    elif kind == 'pet':
        w = h * .62
        style = rng.choice(['point', 'round', 'ogee', 'tear'])
        x = xa - w
        while x < xb + w:
            c.saveState(); c.translate(x, 0)
            fillstroke(c, st, petal_path(c, y0 + 1, y1 - 1, w * .55, style), white, st.lt)
            petal_deco(c, st, y0 + 1, y1 - 1, w * .55, style, ('inner',), white)
            c.restoreState()
            x += w
    elif kind == 'chev':
        w = h * .55
        x = xa - w
        while x < xb + w:
            stroke(c, st, polyline(c, [(x, y0), (x + w * .8, ym), (x, y1)]))
            x += w
    elif kind == 'holly':
        L = h * 1.05
        x = xa - L
        i = 0
        while x < xb + L:
            c.saveState(); c.translate(x, ym); c.rotate(-90 if i % 2 == 0 else 90)
            c.translate(0, -L / 2)
            holly_leaf(c, st, L, h * .7, white)
            c.restoreState()
            if i % 2 == 1:
                berries(c, st, x + L * .58, ym, h * .13, white)
            x += L * 1.15
            i += 1
    elif kind == 'stars':
        s = h * .4
        x = xa - s
        i = 0
        while x < xb + s:
            if i % 2 == 0:
                star(c, st, x, ym, s, white, 5, inner=True)
            else:
                circ(c, st, x, ym, s * .3, white, st.lt)
            x += s * 1.35
            i += 1
    elif kind == 'flakes':
        s = h * .42
        x = xa - s
        while x < xb + s:
            line_flake(c, st, x, ym, s, 0)
            x += s * 2.4
    elif kind == 'lat':
        w = h
        x = xa - w
        while x < xb + w:
            stroke(c, st, polyline(c, [(x, y0), (x + w, y1)]))
            stroke(c, st, polyline(c, [(x, y1), (x + w, y0)]))
            circ(c, st, x + w / 2, ym, h * .14, white, st.lt)
            x += w
    elif kind == 'wave':
        w = h * 1.4
        for off in (0, w / 2):
            p = c.beginPath()
            x = xa - w + off
            p.moveTo(x, y0 + h * .2)
            while x < xb + w:
                p.curveTo(x + w * .25, y0 + h * .2, x + w * .25, y1 - h * .2, x + w * .5, y1 - h * .2)
                p.curveTo(x + w * .75, y1 - h * .2, x + w * .75, y0 + h * .2, x + w, y0 + h * .2)
                x += w
            stroke(c, st, p)


BANDS = ['zig', 'scal', 'beads', 'dia', 'pet', 'chev', 'holly', 'stars', 'flakes', 'lat', 'wave']
GENERIC_BANDS = ['zig', 'scal', 'beads', 'dia', 'pet', 'chev', 'stars', 'lat', 'wave']


def fill_bands(c, st, xa, xb, ya, yb, rng, hmin=16, hmax=30, pool=None):
    pool = pool or (BANDS if seasonal() else GENERIC_BANDS)
    y = ya
    last = None
    while y < yb:
        h = rng.uniform(hmin, hmax)
        k = rng.choice(pool)
        while k == last:
            k = rng.choice(pool)
        if k in ('holly', 'pet'):
            h = max(h, 24)
        if k in ('chev', 'lat', 'beads'):
            h = min(h, 20)
        band(c, st, k, xa, xb, y, y + h, rng)
        last = k
        y += h + (4 if rng.random() < .5 else 0)


def bow(c, st, x, y, s, col=white):
    c.saveState(); c.translate(x, y)
    # tails
    for sg in (-1, 1):
        p = c.beginPath()
        p.moveTo(sg * s * .08, -s * .05)
        p.curveTo(sg * s * .25, -s * .4, sg * s * .35, -s * .7, sg * s * .55, -s * 1.05)
        p.lineTo(sg * s * .42, -s * .95)
        p.lineTo(sg * s * .33, -s * 1.12)
        p.curveTo(sg * s * .2, -s * .75, sg * s * .1, -s * .45, -sg * s * .06, -s * .08)
        p.close()
        fillstroke(c, st, p, col)
    # loops
    for sg in (-1, 1):
        p = c.beginPath()
        p.moveTo(0, 0)
        p.curveTo(sg * s * .25, s * .55, sg * s * .95, s * .6, sg * s * .9, s * .12)
        p.curveTo(sg * s * .88, -s * .2, sg * s * .4, -s * .2, 0, 0)
        p.close()
        fillstroke(c, st, p, col)
        q = c.beginPath()
        q.moveTo(sg * s * .12, s * .06)
        q.curveTo(sg * s * .35, s * .38, sg * s * .7, s * .4, sg * s * .72, s * .15)
        stroke(c, st, q)
    p = c.beginPath()
    p.roundRect(-s * .14, -s * .14, s * .28, s * .3, s * .08)
    fillstroke(c, st, p, col)
    c.restoreState()


def page_tree(c, st, seed, bg='snow'):
    rng = random.Random(seed)
    background(c, st, bg, rng, [])
    cx = 306
    # ground
    p = c.beginPath()
    p.moveTo(IN[0] - 2, 170)
    xs = [IN[0], 140, 230, 330, 430, 520, IN[2]]
    ys = [175, 188, 172, 186, 170, 184, 176]
    for i in range(1, len(xs)):
        xm = (xs[i - 1] + xs[i]) / 2
        p.curveTo(xm, ys[i - 1] + 10, xm, ys[i] + 10, xs[i], ys[i])
    top_only = c.beginPath()
    top_only.moveTo(IN[0] - 2, 170)
    for i in range(1, len(xs)):
        xm = (xs[i - 1] + xs[i]) / 2
        top_only.curveTo(xm, ys[i - 1] + 10, xm, ys[i] + 10, xs[i], ys[i])
    p.lineTo(IN[2] + 2, IN[1] - 2)
    p.lineTo(IN[0] - 2, IN[1] - 2)
    p.close()
    c.setFillColor(white); c.drawPath(p, stroke=0, fill=1)
    stroke(c, st, top_only, st.lw)
    c.saveState(); c.clipPath(p, stroke=0, fill=0)
    for i in range(22):
        line_flake(c, st, rng.uniform(60, 550), rng.uniform(75, 160), rng.uniform(5, 9), rng.uniform(0, 60))
    c.restoreState()
    # trunk
    tp = polyline(c, [(cx - 26, 182), (cx + 26, 182), (cx + 22, 262), (cx - 22, 262)], True)
    fillstroke(c, st, tp, white)
    c.saveState(); c.clipPath(tp, stroke=0, fill=0)
    for yy in range(186, 262, 12):
        stroke(c, st, polyline(c, [(cx - 30, yy), (cx + 30, yy + 6)]))
    c.restoreState()
    fillstroke(c, st, tp, white) if False else stroke(c, st, tp, st.lw)
    tiers = [(470, 256, 232), (560, 360, 190), (640, 455, 148), (705, 545, 104)]
    for (top, base, hw) in tiers:
        path = c.beginPath()
        path.moveTo(cx, top)
        path.curveTo(cx + hw * .25, top - (top - base) * .45, cx + hw * .7, base + 8, cx + hw, base)
        nsc = max(4, int(hw * 2 / 46))
        w = hw * 2 / nsc
        x = cx + hw
        for i in range(nsc):
            path.curveTo(x - w * .1, base - w * .45, x - w * .9, base - w * .45, x - w, base)
            x -= w
        path.curveTo(cx - hw * .7, base + 8, cx - hw * .25, top - (top - base) * .45, cx, top)
        path.close()
        fillstroke(c, st, path, white, .01)
        c.saveState(); c.clipPath(path, stroke=0, fill=0)
        fill_bands(c, st, cx - hw - 20, cx + hw + 20, base - w * .45, top - 10, rng, 16, 28)
        c.restoreState()
        stroke(c, st, path, 1.4)
    # star
    c.saveState(); c.translate(cx, 718)
    fillstroke(c, st, star_path(c, 36, 16, 8, 90), white, 1.3)
    fillstroke(c, st, star_path(c, 22, 10, 8, 90 + 22.5), white, st.lt)
    circ(c, st, 0, 0, 7, white, st.lt)
    c.restoreState()
    # gifts
    gifts = [(cx - 190, 168, 92, 70), (cx + 70, 162, 110, 58), (cx - 92, 172, 66, 96), (cx + 178, 170, 64, 44)]
    for gi, (gx, gy, gw, gh) in enumerate(gifts):
        box = polyline(c, [(gx, gy), (gx + gw, gy), (gx + gw, gy + gh), (gx, gy + gh)], True)
        fillstroke(c, st, box, white)
        c.saveState(); c.clipPath(box, stroke=0, fill=0)
        if gi % 2 == 0:
            for d in range(-200, 200, 14):
                stroke(c, st, polyline(c, [(gx + d, gy), (gx + d + gh, gy + gh)]))
        else:
            for yy in range(int(gy) + 8, int(gy + gh), 16):
                for xx in range(int(gx) + 8 + (8 if (yy // 16) % 2 else 0), int(gx + gw), 16):
                    circ(c, st, xx, yy, 3.2, white, st.lt)
        c.restoreState()
        stroke(c, st, box, st.lw)
        lid = polyline(c, [(gx - 5, gy + gh), (gx + gw + 5, gy + gh), (gx + gw + 5, gy + gh + 13), (gx - 5, gy + gh + 13)], True)
        fillstroke(c, st, lid, white)
        rb = polyline(c, [(gx + gw / 2 - 7, gy), (gx + gw / 2 + 7, gy), (gx + gw / 2 + 7, gy + gh + 13), (gx + gw / 2 - 7, gy + gh + 13)], True)
        fillstroke(c, st, rb, white)
        bow(c, st, gx + gw / 2, gy + gh + 16, 26 if gw > 70 else 20)


def cap(c, st, x, y, R):
    """Ornament cap sitting on top of a bauble centred (x,y) radius R."""
    cw, ch = R * .36, R * .2
    top = y + R + ch - R * .02
    p = c.beginPath()
    p.roundRect(x - cw / 2, y + R - R * .03, cw, ch, 2)
    fillstroke(c, st, p, white, st.lw)
    for i in range(1, 6):
        xx = x - cw / 2 + cw * i / 6
        stroke(c, st, polyline(c, [(xx, y + R), (xx, top - 1)]))
    circ(c, st, x, top + R * .07, R * .07, None, st.lw, fill=False)
    return top + R * .14


def garland(c, st, y, rng):
    x = IN[0] - 10
    items = []
    while x < IN[2] + 10:
        items.append(x)
        x += 30
    for i, x in enumerate(items):
        c.saveState(); c.translate(x, y + (6 if i % 2 else -2)); c.rotate(rng.uniform(-120, -60) if i % 2 else rng.uniform(60, 120))
        if i % 3 == 0:
            holly_leaf(c, st, 46, 22, white)
        else:
            pine_sprig(c, st, 50, 18, white, 6)
        c.restoreState()
    for i, x in enumerate(items):
        if i % 3 == 1:
            berries(c, st, x + 10, y + 2, 5, white)


def page_ornaments3(c, st, seed, bg='scatter'):
    rng = random.Random(seed)
    balls = [(160, 530, 100), (306, 300, 122), (452, 530, 100)]
    background(c, st, bg, rng, [(x, y, r + 6) for x, y, r in balls])
    for (x, y, R) in balls:
        top_y = y + R * 1.3
        c.setLineWidth(3.2); c.setStrokeColor(st.ink); c.line(x, top_y, x, IN[3])
        c.setLineWidth(1.6); c.setStrokeColor(white); c.line(x, top_y, x, IN[3])
        spec = mandala_spec(R - 2, rng, k=rng.choice([8, 12, 16]), themes=['holly', 'stars', 'flakes', 'pine'],
                            outer=rng.choice(['lace', 'petals']))
        circ(c, st, x, y, R, white, .01)
        draw_mandala(c, st, spec, x, y)
        circ(c, st, x, y, R + 1, None, 1.4, fill=False)
        cap(c, st, x, y, R)
    c.saveState(); clip_rect(c, IN)
    garland(c, st, IN[3] - 16, rng)
    c.restoreState()


def page_wreath(c, st, seed, bg='lattice', center='text', word='Noël'):
    rng = random.Random(seed)
    cx, cy = 306, 430
    Ri, Ro = 128, 238
    background(c, st, bg, rng, [(cx, cy, Ro + 10)])
    circ(c, st, cx, cy, Ro + 10, None, 1.3, fill=False)
    if center == 'mandala':
        spec = mandala_spec(Ri + 14, rng, k=12, center='poinsettia', themes=['stars', 'flakes'], outer='lace')
        draw_mandala(c, st, spec, cx, cy)
    items = []
    for i in range(340):
        a = rng.uniform(0, TAU)
        r = rng.uniform(Ri + 8, Ro - 12)
        kind = rng.choice(['holly', 'pine', 'pine', 'holly', 'leaf'])
        items.append((a, r, kind, rng.uniform(-50, 50)))
    # sort by angle chunks so layering looks natural
    rng.shuffle(items)
    for (a, r, kind, jit) in items:
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        c.saveState(); c.translate(x, y)
        c.rotate(math.degrees(a) + jit * .7)
        c.translate(0, -24)
        if kind == 'holly':
            holly_leaf(c, st, 56, 26, white)
        elif kind == 'pine':
            pine_sprig(c, st, 60, 20, white, 7)
        else:
            fillstroke(c, st, petal_path(c, 0, 50, 13, 'point'), white)
            petal_deco(c, st, 0, 50, 13, 'point', ('veins',), white)
        c.restoreState()
    for i in range(14):
        a = TAU * i / 14 + rng.uniform(-.1, .1)
        r = rng.uniform(Ri + 35, Ro - 40)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        berries(c, st, x, y, 7, white)
    for i in range(8):
        a = TAU * (i + .5) / 8
        r = (Ri + Ro) / 2
        c.saveState(); c.translate(cx + r * math.cos(a), cy + r * math.sin(a)); c.rotate(math.degrees(a) - 90)
        pine_cone(c, st, -20, 20, 12, white)
        c.restoreState()
    bow(c, st, cx, cy - Ro + 18, 88)
    if center == 'text':
        c.saveState()
        c.setFont('Caladea-Bold', 92)
        c.setLineWidth(1.3)
        c.setStrokeColor(st.ink)
        c.setFillColor(white)
        t = c.beginText()
        t.setTextRenderMode(2)
        t.setFont('Caladea-Bold', 92)
        wtxt = c.stringWidth(word, 'Caladea-Bold', 92)
        t.setTextOrigin(cx - wtxt / 2, cy - 22)
        t.textOut(word)
        c.drawText(t)
        c.restoreState()
        for (dx, dy, s) in ((-70, 58, 12), (70, 60, 10), (0, 78, 8), (-60, -48, 9), (62, -52, 11), (0, -70, 8)):
            sparkle(c, st, cx + dx, cy + dy, s, white)


def page_quilt(c, st, seed, bg='lattice'):
    rng = random.Random(seed)
    R = 118
    centers = [(306 - 130, 405 + 150), (306 + 130, 405 + 150), (306 - 130, 405 - 150), (306 + 130, 405 - 150)]
    holes = [(x, y, R + 7) for x, y in centers] + [(306, 405, 64)]
    background(c, st, bg, rng, holes)
    specA = mandala_spec(R, rng, k=rng.choice([8, 12]), themes=['holly', 'stars', 'flakes', 'pine', 'bract'])
    specB = mandala_spec(R, rng, k=rng.choice([8, 16]), themes=['ornaments', 'stars', 'bract', 'bells'])
    for i, (x, y) in enumerate(centers):
        draw_mandala(c, st, specA if i in (0, 3) else specB, x, y)
        medallion(c, st, x, y, R)
    specC = mandala_spec(58, rng, k=8, center='star', outer='petals')
    draw_mandala(c, st, specC, 306, 405)
    medallion(c, st, 306, 405, 57)


def page_bauble(c, st, seed, bg='rays'):
    rng = random.Random(seed)
    x, y, R = 306, 380, 220
    background(c, st, bg, rng, [(x, y, R + 4)], center=(x, y), R0=R + 4)
    circ(c, st, x, y, R, white, 1.5)
    p = c.beginPath(); p.circle(x, y, R)
    c.saveState(); c.clipPath(p, stroke=0, fill=0)
    fill_bands(c, st, x - R, x + R, y - R, y + R, rng, 20, 34)
    c.restoreState()
    # central medallion band
    spec = mandala_spec(78, rng, k=12, center='poinsettia', outer='lace')
    draw_mandala(c, st, spec, x, y)
    medallion(c, st, x, y, 78)
    circ(c, st, x, y, R, None, 1.6, fill=False)
    top = cap(c, st, x, y, R)
    c.setLineWidth(3.2); c.setStrokeColor(st.ink); c.line(x, top, x, IN[3])
    c.setLineWidth(1.6); c.setStrokeColor(white); c.line(x, top, x, IN[3])
    bow(c, st, x, top + 40, 60)


# ------------------------------------------------------------ generic page kinds
# Page kinds that only use generic motifs (petals, beads, lace, stars, geometric bands).
GENERIC_KINDS = ('classic', 'quilt', 'bands', 'trio')
CHRISTMAS_KINDS = ('classic', 'snow', 'tree', 'orn3', 'wreath', 'quilt', 'bauble')


def page_bands(c, st, seed, bg='lattice'):
    """Full medallion of stacked geometric bands with a mandala at its heart."""
    rng = random.Random(seed)
    x, y, R = 306, 405, 236
    background(c, st, bg, rng, [(x, y, R + 6)], center=(x, y), R0=R + 6)
    circ(c, st, x, y, R, white, 1.5)
    p = c.beginPath(); p.circle(x, y, R)
    c.saveState(); c.clipPath(p, stroke=0, fill=0)
    fill_bands(c, st, x - R, x + R, y - R, y + R, rng, 20, 34)
    c.restoreState()
    spec = mandala_spec(96, rng, k=rng.choice([8, 12, 16]), outer='lace')
    draw_mandala(c, st, spec, x, y)
    medallion(c, st, x, y, 96)
    circ(c, st, x, y, R, None, 1.6, fill=False)


def page_trio(c, st, seed, bg='scatter'):
    """Three medallions on a diagonal."""
    rng = random.Random(seed)
    spots = [(180, 585, 118), (306, 405, 92), (432, 225, 118)]
    background(c, st, bg, rng, [(sx, sy, r + 7) for sx, sy, r in spots])
    for (sx, sy, r) in spots:
        spec = mandala_spec(r, rng, k=rng.choice([8, 12, 16]), outer=rng.choice(['lace', 'petals']))
        draw_mandala(c, st, spec, sx, sy)
        medallion(c, st, sx, sy, r)
