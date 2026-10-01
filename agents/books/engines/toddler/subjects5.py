from kit import *
import kit


def rot(x, y, a):
    kit.C.saveState(); kit.C.translate(x, y); kit.C.rotate(a)


def done():
    kit.C.restoreState()


# ------------------------------------------------------------------ pinecone
def pinecone():
    accents([('flake', 12, 88, 5), ('sparkle', 88, 88, 4), ('flake', 12, 30, 4.5), ('star', 88, 30, 4),
             ('dot', 18, 60, 1.3), ('dot', 84, 58, 1.3)])
    # needles sprig behind
    for sg in (-1, 1):
        rot(50, 74, sg * 55)
        draw(poly([(0, 0), (0, 22)], False), IN, fill=False)
        for k in range(5):
            y = 4 + k * 4
            for s2 in (-1, 1):
                rot(0, y, s2 * 50)
                draw(smooth([(0, 0), (1, 4), (0, 8), (-1, 4)], t=.8), FINE)
                done()
        done()
    cone = smooth([(50, 76), (64, 70), (70, 52), (66, 30), (56, 14), (50, 10), (44, 14), (34, 30), (30, 52), (36, 70)], t=.9)
    draw(cone)
    kit.C.saveState(); clip(cone)
    rows = 8
    for j in range(rows):
        y = 16 + j * 7.5
        off = 0 if j % 2 == 0 else 4.5
        for k in range(-3, 4):
            x = 50 + k * 9 + off
            sc = P()
            sc.moveTo(x - 4.5, y + 6)
            sc.curveTo(x - 4.5, y - 1, x + 4.5, y - 1, x + 4.5, y + 6)
            draw(sc, IN)
    kit.C.restoreState()
    draw(cone, OUT, fill=False)
    bow(50, 76, .8)


# ------------------------------------------------------------------ cardinal
def cardinal():
    accents([('flake', 12, 88, 5), ('flake', 88, 88, 5), ('sparkle', 12, 56, 4), ('star', 90, 62, 3.5),
             ('dot', 26, 76, 1.3), ('dot', 76, 80, 1.3)])
    tubes([[(-10, 22), (40, 24), (110, 20)], [(70, 22), (80, 30), (84, 36)]], 5)
    draw(smooth([(8, 25), (20, 29), (30, 29), (24, 25.5)], t=.8), IN)
    draw(smooth([(72, 25), (82, 29), (92, 28), (86, 24)], t=.8), IN)
    holly(84, 36, .7, -30, 2)
    # tail
    draw(smooth([(34, 40), (22, 30), (18, 22), (24, 20), (30, 26), (40, 34)], t=.8))
    draw(poly([(22, 22), (33, 34)], False), FINE, fill=False)
    # body
    body = smooth([(56, 74), (64, 70), (68, 58), (64, 40), (54, 30), (42, 30), (34, 38), (36, 50), (44, 60), (46, 70)], t=.9)
    draw(body)
    # crest
    draw(smooth([(52, 74), (50, 84), (58, 78), (60, 72)], t=.8))
    draw(body, OUT, fill=False)
    # wing
    draw(smooth([(42, 52), (52, 50), (58, 42), (54, 34), (42, 36), (38, 44)], t=.9), IN)
    for (a, b) in (((44, 40), (54, 40)), ((42, 45), (55, 46))):
        draw(poly([a, b], False), FINE, fill=False)
    # face mask + beak
    draw(smooth([(56, 66), (64, 66), (68, 60), (62, 56), (56, 58)], t=.8), IN)
    draw(smooth([(64, 63), (72, 60), (64, 57)], t=.4), IN)
    eye(58.5, 64, 1.9)
    blush(58, 57.5, 1.6)
    for x in (46, 52):
        for k in (-1.6, 0, 1.6):
            draw(poly([(x, 30), (x + k, 25.5)], False), FINE, fill=False)


# ------------------------------------------------------------------ wreath
def wreath():
    accents([('sparkle', 10, 90, 4), ('flake', 90, 90, 5), ('flake', 10, 20, 4.5), ('star', 90, 20, 4)])
    outer = ell(50, 52, 34)
    draw(outer)
    draw(ell(50, 52, 17), OUT)
    # leaves ring
    for k in range(14):
        a = 360 * k / 14
        x, y = 50 + 25.5 * math.cos(math.radians(a)), 52 + 25.5 * math.sin(math.radians(a))
        rot(x, y, a + 60)
        draw(smooth([(0, -6), (3.2, -1), (2.4, 4), (0, 6.5), (-2.4, 4), (-3.2, -1)], t=.9), IN)
        draw(poly([(0, -4.5), (0, 5)], False), FINE, fill=False)
        done()
    for k in range(7):
        a = math.radians(360 * k / 7 + 20)
        x, y = 50 + 25.5 * math.cos(a), 52 + 25.5 * math.sin(a)
        for dx, dy in ((-1.6, -.8), (1.6, -.8), (0, 1.4)):
            draw(ell(x + dx, y + dy, 1.7), IN)
    bow(50, 21, 1.35)


# ------------------------------------------------------------------ candle
def candle():
    accents([('sparkle', 12, 88, 4.5), ('sparkle', 88, 86, 4), ('star', 14, 50, 3.5), ('star', 86, 52, 3.5),
             ('dot', 22, 70, 1.3), ('dot', 80, 72, 1.3)])
    # holder
    draw(ell(50, 12, 30, 6))
    draw(ell(50, 13, 20, 3.5), IN)
    tube([(78, 12), (86, 12), (88, 18), (84, 22), (80, 20)], 3)
    holly(26, 14, .75, 60, 2)
    # candle body
    draw(rrect(38, 14, 24, 46, 2))
    for y in (22, 32, 42):
        draw(poly([(38, y), (62, y + 8)], False), IN, fill=False)
    # drips
    draw(smooth([(38, 60), (40, 54), (42, 58), (46, 52), (48, 56), (52, 55), (56, 50), (58, 56), (62, 54), (62, 60)], t=.8), IN)
    draw(poly([(50, 60), (50, 64)], False), IN, fill=False)
    # flame + glow
    draw(smooth([(50, 63), (55, 68), (54, 75), (50, 82), (46, 75), (45, 68)], t=.9))
    draw(smooth([(50, 65), (52.5, 69), (50, 74), (47.5, 69)], t=.9), FINE)
    for k in range(8):
        a = math.radians(90 + 45 * k)
        if k in (4,):
            continue
        x0, y0 = 50 + 13 * math.cos(a), 71 + 13 * math.sin(a)
        x1, y1 = 50 + 17 * math.cos(a), 71 + 17 * math.sin(a)
        if y0 > 62:
            draw(poly([(x0, y0), (x1, y1)], False), IN, fill=False)


# ------------------------------------------------------------------ candy
def candy():
    accents([('sparkle', 12, 90, 4.5), ('star', 88, 90, 4), ('flake', 10, 30, 4.5), ('flake', 90, 44, 4.5),
             ('dot', 30, 94, 1.3)])
    # lollipop
    tube([(40, 8), (40, 54)], 4)
    draw(ell(40, 66, 18))
    sp = []
    for i in range(80):
        t = i / 79
        a = t * 4.2 * math.pi
        r = 16.5 * t
        sp.append((40 + r * math.cos(a), 66 + r * math.sin(a)))
    draw(smooth(sp, closed=False), IN, fill=False)
    bow(40, 44, .6)
    # wrapped sweet
    rot(72, 26, 20)
    for sg in (-1, 1):
        draw(smooth([(sg * 8, 0), (sg * 16, 7), (sg * 18, 0), (sg * 16, -7)], t=.3))
        draw(poly([(sg * 12, 1.5), (sg * 16, 3.5)], False), FINE, fill=False)
    draw(ell(0, 0, 10, 8))
    for x in (-4, 0, 4):
        draw(poly([(x - 2, -7.6), (x + 2, 7.6)], False), IN, fill=False)
    done()
    # peppermint
    draw(ell(76, 62, 10))
    for k in range(4):
        a = math.radians(45 * k)
        draw(poly([(76 + 10 * math.cos(a), 62 + 10 * math.sin(a)), (76 - 10 * math.cos(a), 62 - 10 * math.sin(a))], False), IN, fill=False)
    draw(ell(76, 62, 3), IN)


# ------------------------------------------------------------------ mittens
def mittens():
    accents([('flake', 12, 90, 5), ('flake', 88, 90, 5), ('sparkle', 50, 90, 4), ('star', 12, 24, 4),
             ('dot', 88, 24, 1.3)])
    for sg, cx, a in ((-1, 27, 12), (1, 73, -12)):
        rot(cx, 44, a)
        m = smooth([(-12, -22), (12, -22), (13, 0), (12, 18), (6, 26), (-4, 25), (-10, 16), (-12, 6), (-18, 8), (-22, 2), (-18, -6), (-12, -6)], t=.9) if sg > 0 else \
            smooth([(12, -22), (-12, -22), (-13, 0), (-12, 18), (-6, 26), (4, 25), (10, 16), (12, 6), (18, 8), (22, 2), (18, -6), (12, -6)], t=.9)
        draw(m)
        kit.C.saveState(); clip(m)
        for y in (-6, 6):
            draw(poly([(-30, y), (30, y)], False), IN, fill=False)
        for k in range(-3, 4):
            draw(round_star(k * 7.5, 0, 2.4, 1.2), FINE) if k % 2 == 0 else draw(ell(k * 7.5, 0, 1.2), FINE)
        for (x, y) in ((-4, 13), (4, 16), (0, -13), (-6, -15), (6, -15)):
            snowflake(x, y, 2.6, FINE)
        kit.C.restoreState()
        draw(m, OUT, fill=False)
        draw(cloud(0, -24, 13.5, 4, 10, .2), OUT)
        done()


# ------------------------------------------------------------------ big star
def big_star():
    accents([('sparkle', 12, 90, 4.5), ('sparkle', 88, 88, 4), ('flake', 12, 22, 5), ('flake', 88, 22, 5),
             ('star', 18, 60, 3), ('star', 84, 58, 3)])
    draw(round_star(50, 50, 38, 17, 5, 90, .14))
    draw(round_star(50, 50, 26, 11.5, 5, 90, .14), IN)
    face(50, 50, 11, 2.6, 'open', True, 4)
    for k in range(5):
        a = math.radians(90 + 72 * k)
        draw(ell(50 + 31 * math.cos(a), 50 + 31 * math.sin(a), 1.8), FINE)


# ------------------------------------------------------------------ big snowflake
def big_snowflake():
    accents([('sparkle', 10, 90, 4), ('sparkle', 90, 90, 4), ('flake', 12, 12, 4), ('flake', 88, 12, 4)])
    kit.C.saveState(); kit.C.translate(50, 50)
    arms = []
    for i in range(6):
        a = math.radians(90 + 60 * i)
        ca, sa = math.cos(a), math.sin(a)
        def R(x, y):
            return (x * ca - y * sa, x * sa + y * ca)
        arms.append([R(8, 0), R(40, 0)])
        for (t, l) in ((18, 10), (28, 8)):
            for s in (-1, 1):
                arms.append([R(t, 0), R(t + l * .7, s * l)])
    tubes(arms, 5.5)
    for i in range(6):
        a = math.radians(90 + 60 * i)
        x, y = 42 * math.cos(a), 42 * math.sin(a)
        draw(ell(x, y, 4.2))
        for (t,) in ((34,),):
            pass
    pts = [(12 * math.cos(math.radians(90 + 60 * i)), 12 * math.sin(math.radians(90 + 60 * i))) for i in range(6)]
    draw(poly(pts))
    draw(round_star(0, 0, 6, 3, 6, 90, .2), IN)
    kit.C.restoreState()


# ------------------------------------------------------------------ sweater
def sweater():
    accents([('flake', 12, 90, 5), ('flake', 88, 90, 5), ('sparkle', 12, 16, 4), ('sparkle', 88, 16, 4)])
    body = smooth([(38, 84), (30, 82), (14, 72), (6, 50), (8, 30), (16, 30), (20, 50), (24, 58), (24, 16), (76, 16), (76, 58), (80, 50), (84, 30), (92, 30), (94, 50), (86, 72), (70, 82), (62, 84), (56, 80), (50, 79), (44, 80)], t=.5)
    draw(body)
    kit.C.saveState(); clip(body)
    for y in (26, 30):
        draw(poly([(0, y), (100, y)], False), FINE, fill=False)
    for k in range(-1, 12):
        x = k * 8 + 22
        draw(poly([(x, 26), (x + 4, 30), (x + 8, 26)], False), FINE, fill=False)
    for y in (64, 68):
        draw(poly([(0, y), (100, y)], False), FINE, fill=False)
    for k in range(0, 14):
        draw(round_star(4 + k * 7.5, 66, 1.6, .8), FINE)
    kit.C.restoreState()
    draw(body, OUT, fill=False)
    # ribbed cuffs + hem
    draw(rrect(23, 12, 54, 6, 1.5), OUT)
    for x in range(26, 76, 4):
        draw(poly([(x, 12.5), (x, 17.5)], False), FINE * .8, fill=False)
    for (x0, x1) in ((6, 17), (83, 94)):
        draw(rrect(x0, 26, x1 - x0, 6, 1.5), OUT)
    # collar
    draw(smooth([(38, 84), (50, 78), (62, 84), (58, 86.5), (50, 82.5), (42, 86.5)], t=.8), OUT)
    # reindeer face motif
    draw(ell(50, 46, 9, 8))
    for sg in (-1, 1):
        tubes([[(50 + sg * 4, 53), (50 + sg * 7, 60), (50 + sg * 6, 64)], [(50 + sg * 6.6, 58.5), (50 + sg * 11, 61)]], 2)
        draw(ell(50 + sg * 10, 50, 3, 1.8), IN)
    draw(ell(50, 46, 9, 8), OUT)
    eyes(50, 48, 7, 1.5)
    draw(ell(50, 43.5, 3, 2.3), IN)
    blush(44, 44, 1.5)
    blush(56, 44, 1.5)
    for (x, y) in ((32, 42), (68, 42), (36, 54), (64, 54), (34, 36), (66, 36)):
        snowflake(x, y, 3, FINE)


# ------------------------------------------------------------------ merry christmas
def merry_christmas():
    accents([('sparkle', 10, 92, 4), ('sparkle', 90, 92, 4), ('flake', 10, 10, 4.5), ('flake', 90, 10, 4.5)])
    # garland across top with ornaments
    draw(curve((-8, 90), (20, 82), (50, 86), (80, 82), (108, 90)), IN, fill=False)
    for (x, y, r) in ((18, 76, 5), (50, 78, 5.5), (82, 76, 5)):
        draw(poly([(x, y + r), (x, y + r + 4)], False), FINE, fill=False)
        draw(ell(x, y, r))
        draw(rrect(x - 2, y + r - .6, 4, 2.5, .6), IN)
        draw(poly([(x - r, y), (x + r, y)], False), FINE, fill=False)
    holly(34, 85, .6, 0)
    holly(66, 85, .6, 0)
    # lettering (outlined)
    c = kit.C
    for (txt, y, size) in (('Ho Ho', 44, 24), ('Ho!', 20, 24)):
        t = c.beginText()
        t.setTextRenderMode(2)
        t.setFont('Poppins-Bold', size)
        w = c.stringWidth(txt, 'Poppins-Bold', size)
        t.setTextOrigin(50 - w / 2, y)
        c.setLineWidth(IN * kit.LWK)
        c.setStrokeColor(black)
        c.setFillColor(white)
        c.setLineJoin(1)
        t.textOut(txt)
        c.drawText(t)
    for (x, y) in ((12, 58), (88, 58), (8, 34), (92, 34)):
        little_star(x, y, 3.2)
