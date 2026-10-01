from kit import *
import kit


# ------------------------------------------------------------------ Santa
def santa():
    accents([('flake', 10, 90, 5), ('sparkle', 90, 92, 4), ('star', 8, 30, 3.5), ('flake', 93, 28, 4.5),
             ('dot', 18, 76, 1.3), ('dot', 84, 70, 1.3)])
    # coat / shoulders
    body = smooth([(14, -2), (86, -2), (84, 14), (74, 26), (50, 30), (26, 26), (16, 14)])
    draw(body)
    draw(rrect(45, -4, 10, 30, 2), IN)                      # fur placket
    for yy in (4, 13):
        draw(ell(50, yy, 1.8), FINE)
    # ears
    draw(ell(31.5, 55, 3.6, 4.6), OUT)
    draw(ell(68.5, 55, 3.6, 4.6), OUT)
    # face
    draw(ell(50, 55, 18, 17))
    # beard: fluffy
    pts = [(32, 54), (29, 44), (32, 33), (38, 24), (45, 18.5), (50, 17), (55, 18.5), (62, 24), (68, 33), (71, 44), (68, 54)]
    bp = P()
    bp.moveTo(*pts[0])
    for a, b in zip(pts[:-1], pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        nx, ny = dy / L, -dx / L        # outward (right of travel, clockwise path)
        h = L * .45
        bp.curveTo(a[0] + nx * h, a[1] + ny * h, b[0] + nx * h, b[1] + ny * h, b[0], b[1])
    bp.curveTo(62, 47, 56, 44, 50, 44.5)
    bp.curveTo(44, 44, 38, 47, 32, 54)
    bp.close()
    draw(bp)
    # beard curls
    for (x, y) in ((40, 34), (50, 27), (60, 34), (45, 39), (55, 39)):
        draw(arc(x, y, 3, 200, 340), FINE, fill=False)
    # mouth
    draw(ell(50, 40.5, 3.2, 2.4), IN)
    # moustache
    for sg in (-1, 1):
        m = P()
        m.moveTo(50, 46.5)
        m.curveTo(50 + sg * 3, 49.5, 50 + sg * 9, 49.5, 50 + sg * 12, 46)
        m.curveTo(50 + sg * 13, 44.5, 50 + sg * 12.5, 42.8, 50 + sg * 11, 43.5)
        m.curveTo(50 + sg * 8, 45, 50 + sg * 4, 43.5, 50, 45.5)
        m.close()
        draw(m, OUT)
    draw(ell(50, 50, 3.6, 3.0), OUT)                       # nose
    happy_eye(43, 58, 3.0)
    happy_eye(57, 58, 3.0)
    blush(38.5, 52.5, 2.6)
    blush(61.5, 52.5, 2.6)
    # eyebrows
    draw(cloud(42.5, 63.5, 3.8, 1.5, 5, .3), IN)
    draw(cloud(57.5, 63.5, 3.8, 1.5, 5, .3), IN)
    # hat
    hat = P()
    hat.moveTo(32, 68)
    hat.curveTo(33, 84, 52, 94, 66, 93)
    hat.curveTo(74, 92.5, 80, 88, 82, 80)
    hat.curveTo(78, 84, 72, 84, 69, 80)
    hat.curveTo(68, 76, 68, 72, 68, 68)
    hat.close()
    draw(hat)
    draw(curve((40, 72), (46, 82), (58, 88)), FINE, fill=False)
    # fur band
    fb = [(29, 66), (35, 64.5), (42, 64), (50, 63.8), (58, 64), (65, 64.5), (71, 66), (71.5, 72), (65, 73), (58, 73.4), (50, 73.5), (42, 73.4), (35, 73), (28.5, 72)]
    draw(smooth(fb), OUT)
    for x in (34, 43, 52, 61):
        draw(arc(x + 2, 68.5, 2.2, 120, 240), FINE, fill=False)
    draw(cloud(82, 79, 5, 5, 9, .22), OUT)                # pompom


# ------------------------------------------------------------------ reindeer
def reindeer():
    snow_ground(12, 2.5, 2)
    accents([('star', 10, 88, 4), ('sparkle', 90, 90, 4), ('flake', 88, 60, 4.5), ('flake', 12, 58, 4),
             ('dot', 20, 72, 1.2), ('dot', 82, 76, 1.2)])
    # back legs
    for x in (36, 60):
        draw(rrect(x, 10, 7, 16, 3.5))
    # body
    draw(ell(50, 30, 21, 13))
    draw(cloud(71.5, 37, 3.2, 3.6, 7, .25), IN)
    for (x, y, r) in ((60, 36, 2.2), (65, 31, 1.6), (56, 31, 1.4)):
        draw(ell(x, y, r), FINE)
    # front legs
    for x in (40, 55):
        draw(rrect(x, 8, 7.5, 16, 3.7))
        draw(poly([(x + .3, 12), (x + 7.2, 12)], False), IN, fill=False)
    # antlers (behind head)
    for sg in (-1, 1):
        base = 50 + sg * 8
        main = [(base, 66), (base + sg * 3, 76), (base + sg * 5, 84), (base + sg * 4, 92)]
        t1 = [(base + sg * 3.2, 77), (base + sg * 10, 81), (base + sg * 13, 87)]
        t2 = [(base + sg * 4.8, 85), (base + sg * 0, 90)]
        tubes([main, t1, t2], 3.6)
    # ears
    for sg in (-1, 1):
        kit.C.saveState(); kit.C.translate(50 + sg * 16, 66); kit.C.rotate(sg * -60)
        e = P()
        e.moveTo(0, 0)
        e.curveTo(4.5, 3, 4, 10, 0, 12)
        e.curveTo(-4, 10, -4.5, 3, 0, 0)
        e.close()
        draw(e)
        draw(ell(0, 5.8, 1.6, 3.5), FINE)
        kit.C.restoreState()
    # scarf band
    draw(smooth([(36, 45), (50, 42), (64, 45), (64, 50), (50, 47.5), (36, 50)]), OUT)
    draw(smooth([(40, 46), (36.5, 39), (35, 32), (39.5, 31.5), (40.5, 38), (44, 45)]), OUT)
    draw(poly([(35.3, 34.5), (39.8, 34.2)], False), FINE, fill=False)
    # head
    draw(ell(50, 60, 17, 14.5))
    draw(ell(50, 52.5, 9.5, 6.8))                          # muzzle
    draw(ell(50, 55.5, 4, 2.9))                            # nose
    draw(ell(48.8, 56.3, 1.1, .7), FINE)
    smile(50, 50.5, 3.2)
    eyes(50, 62.5, 13, 2.6)
    blush(40, 57, 2.2)
    blush(60, 57, 2.2)
    # fringe tuft
    draw(cloud(50, 72.5, 4, 2.2, 6, .3), IN)


# ------------------------------------------------------------------ snowman
def snowman():
    snow_ground(12, 3, 2, .6)
    accents([('flake', 12, 88, 5), ('flake', 88, 86, 5.5), ('flake', 90, 28, 4), ('sparkle', 10, 28, 3.5),
             ('dot', 22, 70, 1.4), ('dot', 80, 66, 1.4), ('dot', 70, 94, 1.2)])
    # arms
    tubes([[(34, 36), (22, 44), (13, 50)], [(19, 46), (15, 53)], [(17, 47.5), (11, 45)]], 2.2)
    tubes([[(66, 36), (78, 44), (87, 50)], [(81, 46), (85, 53)], [(83, 47.5), (89, 45)]], 2.2)
    draw(ell(50, 27, 21, 18))                              # body
    for yy in (33, 25, 17):
        draw(ell(50, yy, 2.2), IN)
    # scarf tail (behind head)
    draw(smooth([(55, 47), (60, 40), (62, 31), (67, 32), (66, 41), (61, 49)]), OUT)
    for k in range(4):
        x = 61.8 + k * 1.4
        draw(poly([(x, 31.4 + k * .2), (x - .2, 28.5)], False), FINE, fill=False)
    draw(ell(50, 58, 14, 13))                              # head
    # scarf wrap
    draw(smooth([(36, 46.5), (50, 43.5), (64, 46.5), (64.5, 51), (50, 48.5), (35.5, 51)]), OUT)
    draw(poly([(44, 44.5), (45, 49)], False), FINE, fill=False)
    draw(poly([(56, 44.5), (55, 49)], False), FINE, fill=False)
    eyes(50, 61.5, 10, 2.3)
    # carrot
    cp = P()
    cp.moveTo(50, 57.5)
    cp.curveTo(56, 57.5, 62, 55.5, 66, 54.5)
    cp.curveTo(62, 53.8, 56, 53, 50, 54.3)
    cp.close()
    draw(cp, IN)
    draw(poly([(55, 56.8), (55.6, 54)], False), FINE, fill=False)
    for i in range(5):
        a = math.radians(215 + 27.5 * i)
        draw(ell(50 + 6 * math.cos(a), 54 + 4 * math.sin(a), .9), FINE)
    blush(41.5, 56, 2)
    blush(58.5, 57.5, 2)
    # hat
    draw(ell(50, 69.5, 13.5, 2.8))
    draw(rrect(41, 69.5, 18, 15, 2))
    draw(rrect(41, 71, 18, 4, .8), IN)
    holly(58, 74, .45, -20)


# ------------------------------------------------------------------ tree
def tree():
    snow_ground(10, 2.5, 2)
    accents([('flake', 12, 86, 5), ('flake', 88, 82, 5), ('sparkle', 16, 55, 3.5), ('sparkle', 86, 50, 3.5),
             ('dot', 22, 70, 1.3), ('dot', 80, 67, 1.3)])
    draw(rrect(45, 8, 10, 12, 1.5))                        # trunk
    # gifts at base
    for (x, w, h) in ((24, 14, 11), (64, 13, 9)):
        draw(rrect(x, 6, w, h, 1))
        draw(poly([(x + w / 2, 6), (x + w / 2, 6 + h)], False), IN, fill=False)
        bow(x + w / 2, 6 + h + .8, .38, 0, False)
    tiers = [(18, 42, 38), (36, 58, 30), (52, 74, 22), (66, 88, 14)]
    for (base, top, hw) in reversed(tiers):
        pass
    for i, (base, top, hw) in enumerate(tiers):
        p = P()
        p.moveTo(50, top)
        p.curveTo(50 + hw * .35, top - (top - base) * .35, 50 + hw * .8, base + 6, 50 + hw, base)
        n = 4 if hw > 25 else 3
        w = 2 * hw / n
        x = 50 + hw
        for k in range(n):
            p.curveTo(x - w * .1, base - w * .42, x - w * .9, base - w * .42, x - w, base)
            x -= w
        p.curveTo(50 - hw * .8, base + 6, 50 - hw * .35, top - (top - base) * .35, 50, top)
        p.close()
        draw(p)
    # garlands
    draw(curve((26, 26), (40, 21), (56, 23), (73, 29)), IN, fill=False)
    draw(curve((33, 42), (46, 38.5), (60, 40), (68, 44)), IN, fill=False)
    draw(curve((38, 58), (48, 55), (58, 56), (63, 59)), IN, fill=False)
    for (x, y, r) in ((30, 30, 2.8), (62, 32, 2.8), (44, 30, 2.4), (52, 46, 2.8), (38, 48, 2.2), (64, 49, 2.2),
                      (46, 64, 2.4), (57, 64, 2.2), (51, 76, 2.2), (78, 22, 2.4), (22, 21, 2.4)):
        draw(ell(x, y, r), IN)
        draw(poly([(x - .8, y + r), (x + .8, y + r)], False), FINE, fill=False)
    draw(round_star(50, 91, 7.5, 3.6), OUT)
    draw(round_star(50, 91, 3.2, 1.6), FINE)


# ------------------------------------------------------------------ present
def present():
    snow_ground(10, 2, 2, 1.3)
    accents([('sparkle', 12, 86, 4.5), ('star', 88, 88, 4), ('flake', 90, 50, 4.5), ('flake', 10, 48, 4.5),
             ('dot', 20, 70, 1.3), ('dot', 84, 70, 1.3)])
    draw(rrect(20, 8, 60, 44, 2.5))                         # box
    # polka dots
    for (x, y) in ((27, 16), (37, 24), (27, 34), (37, 44), (63, 16), (73, 24), (63, 34), (73, 44), (27, 44), (73, 36)):
        draw(ell(x, y, 2.4), FINE)
    draw(rrect(44, 8, 12, 44, 0), OUT)                      # vertical ribbon
    draw(rrect(16, 52, 68, 12, 2.5))                         # lid
    draw(rrect(44, 52, 12, 12, 0), OUT)
    bow(50, 70, 1.25)
    # tag
    kit.C.saveState(); kit.C.translate(73, 36); kit.C.rotate(-15)
    draw(poly([(0, 0), (10, 0), (13, 4), (10, 8), (0, 8)]), IN)
    draw(ell(10.6, 4, 1.1), FINE)
    kit.C.restoreState()


# ------------------------------------------------------------------ stocking
def stocking():
    accents([('flake', 12, 88, 5), ('star', 88, 86, 4), ('sparkle', 12, 30, 4), ('flake', 88, 26, 4.5),
             ('dot', 22, 60, 1.3), ('dot', 86, 56, 1.3)])
    # candy cane peeking out
    tube([(58, 74), (58, 90), (60.5, 95), (65, 95.5), (67.5, 92)], 4.2)
    for yy in (78, 83, 88):
        draw(poly([(55.9, yy), (60.1, yy + 2.6)], False), FINE, fill=False)
    # hanging loop
    draw(arc(34, 84, 4, 0, 180), IN, fill=False)
    sock = smooth([(30, 80), (62, 80), (62, 52), (61, 36), (66, 28), (74, 24), (80, 18), (78, 10), (66, 6),
                   (46, 8), (34, 16), (30, 30), (30, 52)])
    draw(sock)
    # heel and toe patches
    kit.C.saveState(); clip(sock)
    draw(ell(78, 13, 12, 10), IN)
    draw(ell(33, 12, 10, 10), IN)
    for (x, y) in ((40, 60), (52, 64), (46, 48), (40, 36), (52, 36), (56, 50)):
        draw(round_star(x, y, 3.2, 1.6), FINE)
    kit.C.restoreState()
    draw(sock, OUT, fill=False)
    # cuff
    draw(cloud(46, 80, 19, 5.2, 14, .18), OUT)


# ------------------------------------------------------------------ candy canes
def candy_canes():
    accents([('sparkle', 12, 90, 4), ('flake', 88, 90, 5), ('star', 12, 20, 4), ('flake', 88, 20, 4.5),
             ('dot', 14, 55, 1.3), ('dot', 86, 55, 1.3)])
    for sg in (-1, 1):
        pts = [(50 - sg * 20, 6), (50 + sg * 8, 62), (50 + sg * 11, 76), (50 + sg * 18, 85), (50 + sg * 27, 83), (50 + sg * 30, 75)]
        pth, s_ = ribbon_outline(pts, 9)
        draw(pth)
        kit.C.saveState(); clip(pth)
        for k in range(-25, 30):
            y = k * 4.6
            if sg < 0:
                draw(poly([(0, y - 14), (100, y + 18)], False), IN, fill=False)
            else:
                draw(poly([(100, y - 14), (0, y + 18)], False), IN, fill=False)
        kit.C.restoreState()
        draw(pth, OUT, fill=False)
    bow(50, 36, 1.05)
    holly(50, 30, .8, 180)


# ------------------------------------------------------------------ gingerbread
def gingerbread():
    accents([('star', 12, 88, 4), ('sparkle', 88, 88, 4.5), ('flake', 10, 30, 4.5), ('flake', 90, 30, 4.5),
             ('dot', 18, 62, 1.3), ('dot', 84, 64, 1.3)])
    body = smooth([(40, 66), (30, 64), (20, 62), (14, 58), (15, 51), (22, 49), (34, 50), (35, 40),
                   (30, 26), (24, 12), (26, 5), (34, 5), (42, 18), (50, 26), (58, 18), (66, 5), (74, 5), (76, 12),
                   (70, 26), (65, 40), (66, 50), (78, 49), (85, 51), (86, 58), (80, 62), (70, 64), (60, 66)], t=.9)
    draw(body)
    draw(ell(50, 74, 15, 14))
    # icing
    for (pts) in ([(18, 60), (19.5, 55.5), (18, 51)], [(82, 60), (80.5, 55.5), (82, 51)],
                  [(27, 10.5), (30.5, 11.5), (34, 10)], [(66, 10), (69.5, 11.5), (73, 10.5)]):
        a, b, c3 = pts
        draw(smooth([a, (b[0] + 1, b[1] + 1.8), b, (b[0] - 1, b[1] - 1.8), c3], closed=False), IN, fill=False)
    for yy in (44, 35):
        draw(ell(50, yy, 3), IN)
    # bow tie
    draw(poly([(50, 55), (42, 59), (42, 51)]), IN)
    draw(poly([(50, 55), (58, 59), (58, 51)]), IN)
    draw(ell(50, 55, 2), IN)
    face(50, 77, 10, 2.4, 'open', True, 4)
    draw(smooth([(38, 84), (44, 86.2), (50, 86.8), (56, 86.2), (62, 84)], closed=False), IN, fill=False)


# ------------------------------------------------------------------ ornament
def ornament():
    accents([('flake', 12, 22, 5), ('flake', 88, 20, 5), ('sparkle', 14, 60, 4), ('sparkle', 86, 62, 4),
             ('dot', 22, 40, 1.3), ('dot', 80, 38, 1.3)])
    # hanger string + bow
    draw(poly([(50, 80), (50, 100)], False), IN, fill=False)
    bow(50, 92, .8, 0, True)
    ball = ell(50, 44, 30)
    draw(ball)
    kit.C.saveState(); clip(ball)
    for y in (58, 52):
        draw(poly([(18, y), (82, y)], False), IN, fill=False)
    # zigzag band
    zz = [(18 + k * 6, 52 if k % 2 == 0 else 58) for k in range(12)]
    draw(poly(zz, False), IN, fill=False)
    for y in (36, 30):
        draw(poly([(18, y), (82, y)], False), IN, fill=False)
    for k in range(6):
        draw(ell(23 + k * 11, 33, 1.8), FINE)
    draw(arc(50, 17, 14, 30, 150, 6), IN, fill=False)
    kit.C.restoreState()
    draw(round_star(50, 44, 7, 3.4), IN)
    draw(ball, OUT, fill=False)
    # cap
    draw(rrect(43, 72, 14, 7, 1.5))
    for x in (46.5, 50, 53.5):
        draw(poly([(x, 72), (x, 79)], False), FINE, fill=False)
    draw(arc(50, 81.5, 2.6, 0, 360), IN, fill=False)
    # shine
    draw(arc(50, 44, 24, 115, 150), IN, fill=False)


# ------------------------------------------------------------------ bells
def bells():
    accents([('sparkle', 10, 88, 4.5), ('sparkle', 90, 88, 4), ('flake', 12, 22, 5), ('flake', 88, 22, 5),
             ('dot', 14, 55, 1.3), ('dot', 86, 55, 1.3)])
    for sg in (-1, 1):
        kit.C.saveState(); kit.C.translate(50 + sg * 15, 44); kit.C.rotate(sg * 20)
        draw(ell(0, -21, 4.2), OUT)                        # clapper
        b = smooth([(0, 22), (7.5, 19.5), (10.5, 11), (11.5, 0), (13, -9), (17, -15), (17.5, -18),
                    (0, -19.5), (-17.5, -18), (-17, -15), (-13, -9), (-11.5, 0), (-10.5, 11), (-7.5, 19.5)], t=.9)
        draw(b)
        draw(curve((-16.5, -14), (0, -16), (16.5, -14)), IN, fill=False)
        draw(curve((-12.2, -5), (0, -7), (12.2, -5)), IN, fill=False)
        draw(arc(-4.5, 8, 4.5, 110, 200), IN, fill=False)
        kit.C.restoreState()
    bow(50, 66, 1.0)
    holly(50, 69, .85, 0, 3)
