from kit import *
import kit


def rot(x, y, a):
    kit.C.saveState(); kit.C.translate(x, y); kit.C.rotate(a)


def done():
    kit.C.restoreState()


def santa_hat(x, y, w, tilt=1, h=None):
    """Santa hat whose band is centred at (x, y) with width w."""
    h = h or w * .9
    hat = P()
    hat.moveTo(x - w / 2, y)
    hat.curveTo(x - w * .4, y + h * .8, x + w * .2, y + h * 1.05, x + tilt * w * .6, y + h * .7)
    hat.curveTo(x + tilt * w * .45, y + h * .5, x + w * .45, y + h * .3, x + w / 2, y)
    hat.close()
    draw(hat)
    draw(cloud(x + tilt * w * .62, y + h * .66, w * .12, w * .12, 8, .22), OUT)
    draw(smooth([(x - w * .58, y - w * .06), (x, y - w * .1), (x + w * .58, y - w * .06),
                 (x + w * .58, y + w * .12), (x, y + w * .08), (x - w * .58, y + w * .12)], t=.8), OUT)


# ------------------------------------------------------------------ cozy house
def cozy_house():
    snow_ground(10, 2, 2, 1.5)
    accents([('star', 10, 90, 4), ('star', 88, 92, 3.5), ('flake', 90, 60, 4.5), ('flake', 10, 60, 4.5),
             ('dot', 30, 90, 1.3), ('dot', 64, 94, 1.3)])
    # pine trees at sides
    for (x, s) in ((14, 1), (86, .85)):
        draw(rrect(x - 1.5, 8, 3, 6, .5), IN)
        draw(smooth([(x, 14 + 30 * s), (x + 8 * s, 14 + 16 * s), (x + 5 * s, 14 + 16 * s), (x + 10 * s, 12), (x - 10 * s, 12), (x - 5 * s, 14 + 16 * s), (x - 8 * s, 14 + 16 * s)], t=.3))
    draw(rrect(60, 58, 8, 16, 1))                            # chimney
    draw(cloud(64, 74.5, 5.5, 2, 7, .25), IN)
    draw(cloud(70, 82, 3.5, 2.8, 7, .25), IN)
    draw(cloud(76, 88, 2.6, 2.2, 6, .25), IN)
    draw(rrect(26, 10, 48, 34, 1.5))                         # walls
    draw(poly([(20, 42), (50, 68), (80, 42)]))               # roof
    draw(smooth([(18, 42), (30, 42), (40, 41), (50, 42), (60, 41), (70, 42), (82, 42), (82, 46), (70, 47.5), (60, 46), (50, 48), (40, 46), (30, 47.5), (18, 46)], t=.6), IN)
    draw(smooth([(50, 68), (58, 61), (62, 58), (58, 56), (50, 62), (42, 56), (38, 58), (42, 61)], t=.6), IN)
    # door + wreath
    draw(rrect(44, 10, 12, 20, 5))
    draw(ell(53, 19, .9), FINE)
    draw(ell(50, 25, 3.2), IN)
    draw(ell(50, 25, 1.6), FINE)
    # windows with warm light
    for x in (30, 60):
        draw(rrect(x, 20, 10, 12, 1))
        draw(poly([(x + 5, 20), (x + 5, 32)], False), FINE, fill=False)
        draw(poly([(x, 26), (x + 10, 26)], False), FINE, fill=False)
        draw(rrect(x - 1.5, 18.5, 13, 2.2, .8), IN)
    draw(ell(50, 54, 3.6), IN)
    # string of lights under roof
    for k in range(7):
        x = 28 + k * 7.3
        draw(smooth([(x - 1.2, 40), (x + 1.2, 40), (x + 1.4, 37.5), (x, 35.6), (x - 1.4, 37.5)], t=.8), FINE)


# ------------------------------------------------------------------ mouse
def mouse():
    accents([('star', 12, 88, 4), ('sparkle', 88, 88, 4), ('flake', 12, 34, 4.5), ('flake', 88, 34, 4.5),
             ('dot', 18, 62, 1.3), ('dot', 84, 64, 1.3)])
    # stocking bed
    sock = smooth([(24, 52), (66, 52), (70, 30), (80, 22), (82, 12), (70, 8), (46, 8), (26, 14), (22, 32)], t=.8)
    # mouse behind cuff
    for sg in (-1, 1):
        draw(ell(45 + sg * 12, 72, 8))
        draw(ell(45 + sg * 12, 72, 4.5), FINE)
    draw(ell(45, 60, 14, 12))
    eyes(45, 62, 10, 2.3)
    draw(ell(45, 57, 2.2, 1.7), IN)
    smile(45, 54.5, 2.6, lw=FINE)
    blush(36, 57.5, 2)
    blush(54, 57.5, 2)
    for sg in (-1, 1):
        for dy in (-1, 1.2):
            draw(poly([(45 + sg * 5, 57 + dy * .6), (45 + sg * 13, 57 + dy * 1.6)], False), FINE * .8, fill=False)
    draw(sock)
    for (x, y) in ((34, 38), (46, 34), (58, 40), (40, 24), (54, 22), (68, 20)):
        draw(round_star(x, y, 3, 1.5), FINE)
    draw(cloud(45, 52, 23, 5.2, 16, .16), OUT)
    for sg in (-1, 1):
        draw(ell(45 + sg * 7, 53.5, 3, 2.4), OUT)                # little paws on the cuff


# ------------------------------------------------------------------ kitty
def kitty():
    accents([('sparkle', 12, 88, 4), ('flake', 88, 88, 5), ('flake', 10, 50, 4.5), ('star', 90, 54, 3.5),
             ('dot', 20, 70, 1.3), ('dot', 82, 72, 1.3)])
    # tail
    draw(smooth([(62, 14), (76, 14), (84, 22), (84, 32), (80, 36), (78, 30), (78, 24), (72, 20), (62, 20)], t=.9))
    draw(smooth([(50, 44), (62, 40), (66, 26), (62, 12), (50, 10), (38, 12), (34, 26), (38, 40)], t=.9))   # body
    for sg in (-1, 1):
        draw(ell(50 + sg * 7, 12, 5.5, 3.6))
        for k in (-1.8, 0, 1.8):
            draw(poly([(50 + sg * 7 + k, 9), (50 + sg * 7 + k, 11)], False), FINE * .8, fill=False)
    # ornament being batted
    draw(poly([(22, 44), (22, 100)], False), FINE, fill=False)
    draw(rrect(19.5, 38.5, 5, 3, .8), IN)
    draw(ell(22, 31, 7.5))
    draw(poly([(14.6, 31), (29.4, 31)], False), FINE, fill=False)
    draw(round_star(22, 31, 2.6, 1.3), FINE)
    # ears
    for sg in (-1, 1):
        draw(smooth([(50 + sg * 8, 68), (50 + sg * 16, 80), (50 + sg * 18, 62)], t=.45))
        draw(smooth([(50 + sg * 10.5, 67), (50 + sg * 15.5, 75.5), (50 + sg * 16.5, 65)], t=.45), FINE)
    draw(ell(50, 58, 18, 14.5))
    eyes(50, 60, 13, 2.5)
    draw(smooth([(48, 55.5), (52, 55.5), (50, 53.5)], t=.6), IN)
    draw(arc(48.2, 52.4, 1.8, 200, 340), FINE, fill=False)
    draw(arc(51.8, 52.4, 1.8, 200, 340), FINE, fill=False)
    blush(39.5, 55)
    blush(60.5, 55)
    for sg in (-1, 1):
        for dy in (-1.5, 1):
            draw(poly([(50 + sg * 8, 54.5 + dy * .4), (50 + sg * 17, 54.5 + dy * 1.6)], False), FINE * .8, fill=False)
    # collar with bell
    draw(smooth([(40, 45), (50, 43), (60, 45), (60, 48), (50, 46.2), (40, 48)], t=.8), IN)
    draw(ell(50, 43.5, 2.4), IN)


# ------------------------------------------------------------------ puppy
def puppy():
    snow_ground(10, 2, 2, .7)
    accents([('flake', 12, 88, 5), ('star', 88, 88, 4), ('sparkle', 10, 48, 4), ('flake', 90, 44, 4.5),
             ('dot', 20, 70, 1.3), ('dot', 82, 72, 1.3)])
    draw(smooth([(64, 20), (70, 24), (74, 32), (71, 33), (67, 26), (62, 24)], t=.8))   # tail
    draw(smooth([(50, 44), (62, 40), (66, 26), (63, 12), (50, 10), (37, 12), (34, 26), (38, 40)], t=.9))
    draw(ell(50, 26, 8, 9), IN)
    for sg in (-1, 1):
        draw(ell(50 + sg * 8, 11.5, 6, 3.8))
    # floppy ears
    for sg in (-1, 1):
        draw(smooth([(50 + sg * 12, 68), (50 + sg * 21, 66), (50 + sg * 23, 54), (50 + sg * 19, 48), (50 + sg * 15, 56)], t=.9))
    draw(ell(50, 60, 17, 14.5))
    draw(ell(50, 54, 7.5, 5.8))
    draw(ell(50, 57, 3.2, 2.4))
    smile(50, 52.2, 2.6, lw=FINE)
    draw(ell(44, 63.5, 4.6, 4.4), FINE)                          # eye patch
    eyes(50, 63, 12, 2.4)
    blush(40, 57)
    blush(60, 57)
    santa_hat(50, 72.5, 24, 1, 17)
    bow(50, 44, .55, 0, False)


# ------------------------------------------------------------------ moon
def moon():
    accents([('star', 12, 88, 5), ('star', 30, 20, 4), ('star', 86, 22, 5), ('sparkle', 88, 78, 4),
             ('sparkle', 16, 50, 3.5), ('dot', 70, 12, 1.4), ('dot', 22, 70, 1.4), ('star', 62, 88, 3.5)])
    m = P()
    m.moveTo(56, 86)
    m.curveTo(28, 84, 18, 58, 26, 38)
    m.curveTo(34, 18, 60, 12, 76, 24)
    m.curveTo(58, 24, 44, 38, 44, 56)
    m.curveTo(44, 70, 50, 80, 56, 86)
    m.close()
    draw(m)
    # sleepy face
    draw(arc(36, 56, 3, 200, 340), IN, fill=False)
    draw(curve((35.5, 60), (37.5, 61.4), (40, 61)), FINE, fill=False)
    smile(37.5, 46, 3.2)
    blush(31, 50, 2.2)
    # nightcap
    cap = P()
    cap.moveTo(40, 80)
    cap.curveTo(46, 94, 66, 98, 76, 86)
    cap.curveTo(80, 80, 78, 74, 76, 68)
    cap.curveTo(68, 76, 56, 80, 46, 74)
    cap.close()
    draw(cap)
    draw(cloud(76.5, 66, 3.8, 3.6, 8, .22), OUT)
    for (x, y) in ((52, 86), (62, 88), (68, 80)):
        draw(round_star(x, y, 2.2, 1.1), FINE)
    # zzz
    kit.C.saveState()
    for (x, y, s) in ((62, 40, 7), (72, 48, 5.5), (80, 54, 4)):
        draw(poly([(x, y + s), (x + s, y + s), (x, y), (x + s, y)], False), IN, fill=False)
    kit.C.restoreState()


# ------------------------------------------------------------------ lights
def lights():
    accents([('sparkle', 12, 90, 4), ('flake', 88, 90, 5), ('star', 50, 12, 4), ('flake', 14, 14, 4.5),
             ('sparkle', 86, 14, 4)])
    for (y0, amp, phase) in ((70, 7, 0), (42, 7, 1.6)):
        pts = []
        for k in range(13):
            x = -6 + k * 9.5
            pts.append((x, y0 + amp * math.sin(phase + k * .9)))
        draw(smooth(pts, closed=False), IN, fill=False)
        s = sample_smooth(pts, 10)
        for i in range(5, len(s) - 5, 13):
            x, y = s[i]
            a = math.degrees(math.atan2(s[i + 1][1] - s[i - 1][1], s[i + 1][0] - s[i - 1][0]))
            rot(x, y, a - 90 + (180 if (i // 10) % 2 else 0))
            draw(rrect(-2.6, -3, 5.2, 4.2, 1), IN)
            draw(smooth([(-3.4, -3), (3.4, -3), (4.3, -9), (0, -15), (-4.3, -9)], t=.9))
            draw(arc(-1.4, -8.5, 1.9, 120, 220), FINE, fill=False)
            done()


# ------------------------------------------------------------------ gift stack
def gift_stack():
    snow_ground(8, 1.8, 2, .2)
    accents([('sparkle', 12, 88, 4.5), ('star', 88, 88, 4), ('flake', 12, 50, 4.5), ('flake', 90, 50, 4.5),
             ('dot', 22, 72, 1.3), ('dot', 80, 72, 1.3)])
    # bottom big
    draw(rrect(18, 10, 64, 28, 2))
    draw(poly([(50, 10), (50, 38)], False), OUT, fill=False)
    for x in range(22, 80, 7):
        draw(poly([(x, 10), (x + 6, 38)], False), FINE, fill=False) if x not in (46, 50) else None
    draw(rrect(46, 10, 8, 28, 0), OUT)
    # middle
    draw(rrect(28, 38, 44, 20, 2))
    for (x, y) in ((33, 44), (40, 51), (60, 44), (67, 51), (33, 53), (67, 43)):
        draw(ell(x, y, 2), FINE)
    draw(rrect(46, 38, 8, 20, 0), OUT)
    # top small
    draw(rrect(37, 58, 26, 14, 2))
    draw(poly([(37, 65), (63, 65)], False), IN, fill=False)
    draw(rrect(46.5, 58, 7, 14, 0), OUT)
    bow(50, 76, .9)


# ------------------------------------------------------------------ santa's sack
def santa_sack():
    snow_ground(8, 1.8, 2, 2.2)
    accents([('star', 12, 90, 4), ('sparkle', 88, 88, 4.5), ('flake', 10, 40, 4.5), ('flake', 90, 40, 4.5),
             ('dot', 20, 66, 1.3), ('dot', 82, 70, 1.3)])
    # toys peeking out
    draw(rrect(34, 64, 14, 14, 1.5))
    draw(poly([(41, 64), (41, 78)], False), IN, fill=False)
    bow(41, 79, .45, 0, False)
    draw(ell(58, 74, 7))                                  # teddy head
    for sg in (-1, 1):
        draw(ell(58 + sg * 6, 80, 2.8))
    draw(ell(58, 74, 7), OUT)
    eyes(58, 75, 5.5, 1.5)
    draw(ell(58, 72, 1.3), FINE)
    tube([(66, 60), (70, 84), (73, 88), (77, 87), (78, 83)], 3)
    # sack
    sack = smooth([(30, 66), (70, 66), (78, 50), (82, 30), (76, 12), (50, 8), (24, 12), (18, 30), (22, 50)], t=.9)
    draw(sack)
    draw(curve((34, 50), (36, 36), (34, 22)), FINE, fill=False)
    draw(curve((66, 50), (65, 38), (68, 24)), FINE, fill=False)
    # patch
    draw(rrect(54, 22, 12, 10, 1.5), IN)
    for k in range(4):
        draw(poly([(55 + k * 3, 21), (55 + k * 3, 23)], False), FINE * .8, fill=False)
    draw(round_star(40, 30, 6, 3), IN)
    # rope tie
    draw(smooth([(28, 64), (50, 61), (72, 64), (72, 68), (50, 65.5), (28, 68)], t=.8), OUT)


# ------------------------------------------------------------------ chimney
def chimney():
    accents([('star', 12, 90, 4), ('star', 88, 88, 3.5), ('flake', 90, 60, 4.5), ('flake', 10, 60, 4.5),
             ('sparkle', 30, 84, 3.5), ('dot', 72, 94, 1.3)])
    # roof
    draw(poly([(-10, 8), (110, 8), (110, 18), (-10, 30)]))
    for k in range(-2, 14):
        draw(poly([(k * 9, 8), (k * 9 + 2, 28 - k * 1)], False), FINE, fill=False) if False else None
    draw(scallop_line([(-10, 30), (10, 28), (30, 26), (50, 24), (70, 22), (90, 20), (110, 18)], .3), IN, fill=False)
    # boots sticking out
    for sg in (-1, 1):
        x = 50 + sg * 6
        draw(rrect(x - 4, 56, 8, 18, 2))
        draw(cloud(x, 58, 5.4, 2.4, 7, .25), IN)
        draw(smooth([(x - 4.5, 72), (x + 4.5, 72), (x + 4.5 + sg * 5, 76), (x + 4.5 + sg * 3, 80), (x - 4.5, 80)], t=.5))
    # chimney
    draw(rrect(30, 18, 40, 40, 1))
    rows = [26, 34, 42, 50]
    prev = 18
    for i, y in enumerate(rows + [58]):
        if y < 58:
            draw(poly([(30, y), (70, y)], False), IN, fill=False)
        off = 0 if i % 2 == 0 else 5
        for x in range(35 + off, 70, 10):
            draw(poly([(x, prev), (x, min(y, 58))], False), IN, fill=False)
        prev = y
    draw(rrect(27, 56, 46, 6, 1.5))
    draw(cloud(50, 62.5, 22, 2.4, 12, .22), IN)


# ------------------------------------------------------------------ snow friends
def snow_friends():
    snow_ground(10, 2.5, 2, 1.1)
    accents([('flake', 12, 90, 5), ('flake', 88, 90, 5), ('sparkle', 50, 92, 4), ('flake', 50, 72, 3.5),
             ('dot', 30, 84, 1.3), ('dot', 70, 84, 1.3)])
    for (x, s, hat) in ((30, 1.0, 'beanie'), (70, .85, 'top')):
        # arms
        tubes([[(x - 11 * s, 30 * s), (x - 19 * s, 36 * s)], [(x + 11 * s, 30 * s), (x + 19 * s, 36 * s)]], 1.8)
        draw(ell(x, 10 + 14 * s, 15 * s, 13 * s))
        draw(ell(x, 10 + 36 * s, 11 * s))
        for yy in (20, 28):
            draw(ell(x, 10 + yy * s * .9, 1.6), IN)
        eyes(x, 10 + 38 * s, 7 * s, 1.8)
        cp = P()
        cp.moveTo(x, 10 + 35.5 * s)
        cp.lineTo(x + 7 * s, 10 + 34 * s)
        cp.lineTo(x, 10 + 33 * s)
        cp.close()
        draw(cp, FINE)
        smile(x, 10 + 30.5 * s, 3 * s, lw=FINE)
        blush(x - 6.5 * s, 10 + 33 * s, 1.6)
        blush(x + 6.5 * s, 10 + 33 * s, 1.6)
        draw(smooth([(x - 10 * s, 10 + 27 * s), (x, 10 + 25.5 * s), (x + 10 * s, 10 + 27 * s), (x + 10 * s, 10 + 30 * s), (x, 10 + 28.5 * s), (x - 10 * s, 10 + 30 * s)], t=.8), IN)
        top = 10 + 45 * s
        if hat == 'beanie':
            draw(smooth([(x - 10, top), (x - 7, top + 9), (x, top + 12), (x + 7, top + 9), (x + 10, top)], closed=True, t=.8))
            draw(rrect(x - 11.5, top - 2.5, 23, 5, 2), IN)
            draw(cloud(x, top + 13.5, 3, 2.8, 8, .22), IN)
        else:
            draw(ell(x, top - .5, 11 * s, 2.2))
            draw(rrect(x - 7 * s, top, 14 * s, 11 * s, 1.5))
            draw(rrect(x - 7 * s, top + 1.2, 14 * s, 3, .6), IN)
    # hearts between them
    for (x, y, sz) in ((50, 50, 3.2), (54, 58, 2.2)):
        h = P()
        h.moveTo(x, y - sz)
        h.curveTo(x - sz * 2.2, y + sz * .4, x - sz * .6, y + sz * 1.8, x, y + sz * .5)
        h.curveTo(x + sz * .6, y + sz * 1.8, x + sz * 2.2, y + sz * .4, x, y - sz)
        h.close()
        draw(h, IN)
