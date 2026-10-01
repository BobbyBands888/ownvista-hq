"""Toddler Christmas coloring book - drawing toolkit.
Everything is drawn in a 100 x 100 design box (y up) which the page maps
onto a large square area. Line widths are given in design units.
"""
import math
from reportlab.lib.colors import white, black

OUT = 1.15    # outer contour  (~5pt on page)
IN = 0.8      # inner detail   (~3.4pt)
FINE = 0.6    # small detail   (~2.6pt)

C = None      # active canvas (set by page)
FILL = white  # fill used for shapes (white for line art)
LWK = 1.0     # line-width compensation when drawing under scale()


def set_canvas(c):
    global C
    C = c


def P():
    return C.beginPath()


def draw(p, lw=OUT, fill=True, col=None):
    C.setLineWidth(lw * LWK)
    C.setStrokeColor(black)
    C.setLineJoin(1)
    C.setLineCap(1)
    if fill:
        C.setFillColor(col if col is not None else FILL)
        C.drawPath(p, stroke=1, fill=1)
    else:
        C.drawPath(p, stroke=1, fill=0)


def solid(p, col=black):
    C.setFillColor(col)
    C.drawPath(p, stroke=0, fill=1)


# ---------------------------------------------------------------- paths
def smooth(pts, closed=True, t=1.0):
    """Catmull-Rom spline through pts -> bezier path."""
    p = P()
    n = len(pts)
    p.moveTo(*pts[0])
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0 = pts[(i - 1) % n] if (closed or i > 0) else pts[i]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if (closed or i + 2 < n) else pts[(i + 1) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6 * t, p1[1] + (p2[1] - p0[1]) / 6 * t)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6 * t, p2[1] - (p3[1] - p1[1]) / 6 * t)
        p.curveTo(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])
    if closed:
        p.close()
    return p


def poly(pts, closed=True):
    p = P()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if closed:
        p.close()
    return p


def ell(cx, cy, rx, ry=None):
    ry = rx if ry is None else ry
    p = P()
    p.ellipse(cx - rx, cy - ry, 2 * rx, 2 * ry)
    return p


def rrect(x, y, w, h, r):
    p = P()
    p.roundRect(x, y, w, h, r)
    return p


def arc(cx, cy, r, a0, a1, ry=None):
    """open arc path, angles in degrees (counter-clockwise from a0 to a1)."""
    ry = r if ry is None else ry
    p = P()
    steps = max(2, int(abs(a1 - a0) / 30) + 1)
    pts = []
    for i in range(steps * 6 + 1):
        a = math.radians(a0 + (a1 - a0) * i / (steps * 6))
        pts.append((cx + r * math.cos(a), cy + ry * math.sin(a)))
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    return p


def curve(*pts):
    """open smooth curve through points"""
    return smooth(list(pts), closed=False)


def cloud(cx, cy, rx, ry, n=10, puff=.28, rot=0):
    """Fluffy shape: bumps around an ellipse."""
    p = P()
    pts = []
    for i in range(n):
        a = math.radians(rot + 360 * i / n)
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    p.moveTo(*pts[0])
    for i in range(n):
        a0 = math.radians(rot + 360 * i / n)
        a1 = math.radians(rot + 360 * (i + 1) / n)
        am = (a0 + a1) / 2
        k = 1 + puff * 1.9
        cxm, cym = cx + rx * k * math.cos(am), cy + ry * k * math.sin(am)
        q0, q1 = pts[i], pts[(i + 1) % n]
        p.curveTo(q0[0] + (cxm - q0[0]) * .75, q0[1] + (cym - q0[1]) * .75,
                  q1[0] + (cxm - q1[0]) * .75, q1[1] + (cym - q1[1]) * .75, q1[0], q1[1])
    p.close()
    return p


def scallop_line(pts, bulge=.5, closed=False, lead=None):
    """Chain of outward bumps between successive points (for fur, frosting,
    beard edges). Bulge side is to the left of travel direction."""
    p = P()
    p.moveTo(*pts[0])
    seq = list(zip(pts[:-1], pts[1:]))
    if closed:
        seq.append((pts[-1], pts[0]))
    for a, b in seq:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        nx, ny = -dy / L, dx / L
        h = L * bulge
        p.curveTo(a[0] + nx * h, a[1] + ny * h, b[0] + nx * h, b[1] + ny * h, b[0], b[1])
    if closed:
        p.close()
    return p


def star_pts(cx, cy, R, r, n=5, rot=90):
    pts = []
    for i in range(2 * n):
        a = math.radians(rot + i * 180 / n)
        rr = R if i % 2 == 0 else r
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def round_star(cx, cy, R, r, n=5, rot=90, k=.18):
    """Star with softly rounded tips (friendlier for toddlers)."""
    pts = star_pts(cx, cy, R, r, n, rot)
    p = P()
    m = len(pts)
    def lerp(a, b, t):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    start = lerp(pts[0], pts[1], k)
    p.moveTo(*start)
    for i in range(1, m + 1):
        cur = pts[i % m]
        prv = pts[i - 1]
        nxt = pts[(i + 1) % m]
        a = lerp(cur, prv, k)
        b = lerp(cur, nxt, k)
        p.lineTo(*a)
        p.curveTo(cur[0], cur[1], cur[0], cur[1], b[0], b[1])
    p.close()
    return p


# ---------------------------------------------------------------- faces
def eye(x, y, r=2.4, look=(0, 0)):
    solid(ell(x, y, r * .85, r))
    solid(ell(x - r * .3 + look[0], y + r * .35 + look[1], r * .34), white)


def eyes(x, y, sep, r=2.4):
    eye(x - sep / 2, y, r)
    eye(x + sep / 2, y, r)


def happy_eye(x, y, w=3.2):
    draw(arc(x, y - w * .35, w, 20, 160, w * .8), IN, fill=False)


def smile(x, y, w=5, h=None, lw=IN):
    h = w * .55 if h is None else h
    draw(arc(x, y + h, w, 205, 335, h * 1.25), lw, fill=False)


def open_smile(x, y, w=4.5):
    p = P()
    p.moveTo(x - w, y)
    p.curveTo(x - w * .8, y - w * 1.25, x + w * .8, y - w * 1.25, x + w, y)
    p.close()
    draw(p, IN)
    # tongue
    q = P()
    q.moveTo(x - w * .45, y - w * .62)
    q.curveTo(x - w * .2, y - w * .2, x + w * .2, y - w * .2, x + w * .45, y - w * .62)
    draw(q, FINE, fill=False)


def blush(x, y, r=2.6):
    draw(ell(x, y, r * 1.25, r * .8), FINE)


def face(x, y, sep=11, r=2.4, mouth='smile', blushes=True, mw=4.5):
    eyes(x, y, sep, r)
    if mouth == 'smile':
        smile(x, y - r * 2.4, mw)
    elif mouth == 'open':
        open_smile(x, y - r * 2.0, mw)
    if blushes:
        blush(x - sep * .85, y - r * 2.0)
        blush(x + sep * .85, y - r * 2.0)


# ---------------------------------------------------------------- scenery
def snow_ground(y=12, amp=3.5, waves=3, phase=0.0):
    q = []
    n = 30
    for i in range(n + 1):
        x = -25 + 150 * i / n
        q.append((x, y + amp * math.sin(phase + waves * math.pi * 2 * (x + 8) / 116)))
    p = P()
    p.moveTo(-25, -60)
    p.lineTo(*q[0])
    for i in range(len(q) - 1):
        p0 = q[i - 1] if i > 0 else q[i]
        p1, p2 = q[i], q[i + 1]
        p3 = q[i + 2] if i + 2 < len(q) else q[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        p.curveTo(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])
    p.lineTo(125, -60)
    p.close()
    draw(p, OUT)


def snowflake(x, y, R, lw=IN):
    for i in range(6):
        a = math.radians(90 + 60 * i)
        ex, ey = x + R * math.cos(a), y + R * math.sin(a)
        draw(poly([(x, y), (ex, ey)], False), lw, fill=False)
        mx, my = x + R * .6 * math.cos(a), y + R * .6 * math.sin(a)
        for s in (-1, 1):
            b = a + s * math.radians(45)
            draw(poly([(mx, my), (mx + R * .3 * math.cos(b), my + R * .3 * math.sin(b))], False), lw, fill=False)
    draw(ell(x, y, R * .18), FINE)


def sparkle(x, y, R, lw=IN):
    p = P()
    p.moveTo(x, y + R)
    p.curveTo(x + R * .12, y + R * .12, x + R * .12, y + R * .12, x + R, y)
    p.curveTo(x + R * .12, y - R * .12, x + R * .12, y - R * .12, x, y - R)
    p.curveTo(x - R * .12, y - R * .12, x - R * .12, y - R * .12, x - R, y)
    p.curveTo(x - R * .12, y + R * .12, x - R * .12, y + R * .12, x, y + R)
    p.close()
    draw(p, lw)


def little_star(x, y, R, lw=IN):
    draw(round_star(x, y, R, R * .5), lw)


def dot(x, y, r=1.4):
    draw(ell(x, y, r), FINE)


def accents(spots):
    """spots: list of (kind, x, y, size)"""
    for k, x, y, s in spots:
        {'flake': snowflake, 'sparkle': sparkle, 'star': little_star}.get(k, lambda a, b, c: dot(a, b, c))(x, y, s)


def tube(pts, w, lw=OUT, smooth_it=True):
    """Hollow tube along a centreline (branches, antlers, handles)."""
    p = smooth(pts, closed=False) if smooth_it and len(pts) > 2 else poly(pts, False)
    C.setLineCap(1); C.setLineJoin(1)
    C.setStrokeColor(black); C.setLineWidth(w + 2 * lw)
    C.drawPath(p, stroke=1, fill=0)
    C.setStrokeColor(FILL); C.setLineWidth(w)
    C.drawPath(p, stroke=1, fill=0)


def tubes(paths, w, lw=OUT):
    """Several tubes merged (outlines first, then fills) so joints look clean."""
    ps = [smooth(pts, closed=False) if len(pts) > 2 else poly(pts, False) for pts in paths]
    C.setLineCap(1); C.setLineJoin(1)
    for pas in (0, 1):
        for p, pts in zip(ps, paths):
            C.setStrokeColor(black if pas == 0 else FILL)
            ww = w if not isinstance(pts, tuple) else w
            C.setLineWidth(w + 2 * lw if pas == 0 else w)
            C.drawPath(p, stroke=1, fill=0)


def sample_smooth(pts, per=12):
    """Points along a Catmull-Rom open spline."""
    out = []
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
        for k in range(per):
            t = k / per
            t2, t3 = t * t, t * t * t
            x = .5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = .5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(pts[-1])
    return out


def ribbon_outline(pts, w, cap=True):
    """Closed outline of a band of width w along a smooth centreline."""
    s = sample_smooth(pts, 10)
    L, R = [], []
    for i, (x, y) in enumerate(s):
        a = s[max(0, i - 1)]
        b = s[min(len(s) - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy) or 1
        nx, ny = -dy / d, dx / d
        L.append((x + nx * w / 2, y + ny * w / 2))
        R.append((x - nx * w / 2, y - ny * w / 2))
    p = P()
    p.moveTo(*L[0])
    for q in L[1:]:
        p.lineTo(*q)
    if cap:
        # round cap at end
        ex, ey = s[-1]
        a0 = math.atan2(L[-1][1] - ey, L[-1][0] - ex)
        for k in range(1, 9):
            a = a0 - math.pi * k / 8
            p.lineTo(ex + w / 2 * math.cos(a), ey + w / 2 * math.sin(a))
    for q in reversed(R):
        p.lineTo(*q)
    if cap:
        sx, sy = s[0]
        a0 = math.atan2(R[0][1] - sy, R[0][0] - sx)
        for k in range(1, 9):
            a = a0 - math.pi * k / 8
            p.lineTo(sx + w / 2 * math.cos(a), sy + w / 2 * math.sin(a))
    p.close()
    return p, s


def clip(p):
    C.clipPath(p, stroke=0, fill=0)


def scaled(s):
    global LWK
    LWK = 1.0 / s


def bow(x, y, s=1.0, rot=0, tails=True):
    """Big friendly bow centred at (x, y)."""
    C.saveState(); C.translate(x, y); C.rotate(rot); C.scale(s, s); scaled(s)
    if tails:
        for sg in (-1, 1):
            p = P()
            p.moveTo(sg * 1.5, -1)
            p.curveTo(sg * 4, -5, sg * 5, -9, sg * 8, -13)
            p.lineTo(sg * 5.5, -12.2)
            p.lineTo(sg * 4.2, -14.5)
            p.curveTo(sg * 3, -9, sg * 1.5, -6, -sg * 1, -1.5)
            p.close()
            draw(p, OUT)
    for sg in (-1, 1):
        p = P()
        p.moveTo(0, 0)
        p.curveTo(sg * 3, 8, sg * 12, 8.5, sg * 11.5, 1.5)
        p.curveTo(sg * 11, -4, sg * 4, -3.5, 0, 0)
        p.close()
        draw(p, OUT)
        q = P()
        q.moveTo(sg * 2, 1)
        q.curveTo(sg * 4.5, 5, sg * 8, 5.2, sg * 8.5, 2.2)
        draw(q, FINE, fill=False)
    draw(rrect(-2.4, -2.6, 4.8, 5.2, 1.6), OUT)
    C.restoreState(); scaled(1)


def holly(x, y, s=1.0, rot=0, n=2):
    C.saveState(); C.translate(x, y); C.rotate(rot); C.scale(s, s); scaled(s)
    for ang in ((-35, 35) if n == 2 else (-50, 0, 50)):
        C.saveState(); C.rotate(ang)
        pts = [(0, 0), (3.2, 3), (4.8, 2.2), (4.6, 5.6), (6.4, 7), (4.4, 9.2), (4.8, 11.8), (2.6, 12.2), (0, 16),
               (-2.6, 12.2), (-4.8, 11.8), (-4.4, 9.2), (-6.4, 7), (-4.6, 5.6), (-4.8, 2.2), (-3.2, 3)]
        p = P()
        p.moveTo(*pts[0])
        for i in range(1, len(pts) + 1):
            a, b = pts[i - 1], pts[i % len(pts)]
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            # concave between spikes
            cxp, cyp = mx * .82, my
            p.curveTo(cxp, cyp, cxp, cyp, b[0], b[1])
        p.close()
        draw(p, IN)
        draw(poly([(0, 1), (0, 13)], False), FINE, fill=False)
        C.restoreState()
    for bx, by in ((-2.2, -.5), (2.2, -.5), (0, 2.6)):
        draw(ell(bx, by, 2.4), IN)
        draw(ell(bx - .8, by + .8, .55), FINE * .8)
    C.restoreState(); scaled(1)
