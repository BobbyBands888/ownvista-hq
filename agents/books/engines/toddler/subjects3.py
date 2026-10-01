from kit import *
import kit


def rot(x, y, a):
    kit.C.saveState(); kit.C.translate(x, y); kit.C.rotate(a)


def done():
    kit.C.restoreState()


def wheel(x, y, r, spokes=6):
    draw(ell(x, y, r))
    draw(ell(x, y, r * .35), IN)
    for k in range(spokes // 2):
        a = math.radians(180 * k / (spokes // 2))
        draw(poly([(x + r * .35 * math.cos(a), y + r * .35 * math.sin(a)), (x + r * .85 * math.cos(a), y + r * .85 * math.sin(a))], False), FINE, fill=False)
        draw(poly([(x - r * .35 * math.cos(a), y - r * .35 * math.sin(a)), (x - r * .85 * math.cos(a), y - r * .85 * math.sin(a))], False), FINE, fill=False)


# ------------------------------------------------------------------ train
def train():
    snow_ground(12, 1.5, 2, 1)
    accents([('star', 10, 90, 4), ('sparkle', 60, 92, 3.5), ('flake', 88, 88, 5), ('flake', 88, 62, 4),
             ('dot', 40, 88, 1.3), ('dot', 76, 78, 1.3)])
    draw(poly([(-10, 14), (110, 14)], False), IN, fill=False)
    for x in range(-6, 110, 8):
        draw(rrect(x, 12.4, 4.5, 1.6, .5), FINE)
    # smoke
    draw(cloud(22, 76, 6, 4.5, 9, .22), IN)
    draw(cloud(12, 86, 4.5, 3.5, 8, .22), IN)
    draw(cloud(30, 70, 3.5, 3, 7, .22), IN)
    # wagon with gifts and a tree
    draw(poly([(68, 36), (68, 50), (72, 50)], False), IN, fill=False)
    draw(round_star(80, 64, 3.2, 1.6), IN)
    draw(smooth([(80, 62), (86, 50), (84, 50), (88, 42), (72, 42), (76, 50), (74, 50)], t=.3))
    draw(rrect(68, 22, 26, 20, 2))
    draw(poly([(68, 32), (94, 32)], False), IN, fill=False)
    for (x, y) in ((74, 27), (81, 27), (88, 27), (74, 37), (81, 37), (88, 37)):
        draw(round_star(x, y, 2.3, 1.1), FINE)
    wheel(74, 20, 5)
    wheel(88, 20, 5)
    draw(rrect(62, 25, 7, 3, 1.2), IN)                      # coupling
    # engine
    draw(rrect(40, 22, 22, 30, 2))                           # cab
    draw(rrect(37, 50, 28, 5, 1.5))                          # roof
    draw(rrect(45, 34, 12, 11, 1.5), IN)                    # window
    draw(poly([(51, 34), (51, 45)], False), FINE, fill=False)
    draw(rrect(12, 22, 30, 18, 6))                           # boiler
    for x in (22, 32):
        draw(poly([(x, 22.5), (x, 39.5)], False), IN, fill=False)
    draw(smooth([(19, 40), (27, 40), (30, 56), (16, 56)], t=.2))   # funnel
    draw(rrect(14.5, 55, 17, 4, 1.4), IN)
    draw(ell(30, 43, 3), IN)                                 # dome
    draw(ell(12, 33, 2.4), IN)                               # lamp
    draw(poly([(6, 14.5), (14, 24), (14, 14.5)]), IN)        # cow catcher
    wheel(22, 18, 6)
    wheel(50, 20, 8)
    draw(round_star(51, 28, 2.4, 1.2), FINE)


# ------------------------------------------------------------------ teddy bear
def teddy_bear():
    accents([('sparkle', 12, 88, 4), ('flake', 88, 88, 5), ('flake', 12, 30, 4.5), ('star', 88, 30, 4),
             ('dot', 16, 60, 1.3), ('dot', 84, 60, 1.3)])
    for sg in (-1, 1):                                        # legs
        draw(ell(50 + sg * 14, 16, 9, 8))
        draw(ell(50 + sg * 14, 15, 5, 4.4), IN)
        for k in (-3, 0, 3):
            draw(ell(50 + sg * 14 + k, 20.5, 1.3, 1), FINE)
    for sg in (-1, 1):                                        # arms
        rot(50 + sg * 18, 36, sg * 30)
        draw(ell(0, -5, 6, 10))
        done()
    draw(ell(50, 32, 18, 17))                               # body
    draw(ell(50, 30, 10, 10), IN)
    for sg in (-1, 1):                                        # ears
        draw(ell(50 + sg * 14, 72, 6.5))
        draw(ell(50 + sg * 14, 72, 3.5), FINE)
    draw(ell(50, 60, 18, 15.5))                              # head
    draw(ell(50, 54.5, 8, 6))
    draw(smooth([(46.5, 58), (53.5, 58), (50, 54.5)], t=.7), IN)
    draw(poly([(50, 54.5), (50, 52.5)], False), FINE, fill=False)
    draw(arc(48, 52.5, 2, 200, 340), FINE, fill=False)
    draw(arc(52, 52.5, 2, 200, 340), FINE, fill=False)
    eyes(50, 63, 14, 2.4)
    blush(39, 57.5)
    blush(61, 57.5)
    # patch stitch on head
    draw(rrect(56, 67, 6, 5, 1), FINE)
    for k in range(3):
        draw(poly([(57 + k * 2, 66), (57 + k * 2, 73)], False), FINE * .8, fill=False)
    bow(50, 45, .75, 0, False)


# ------------------------------------------------------------------ drum
def drum():
    accents([('star', 12, 88, 4), ('sparkle', 88, 90, 4.5), ('flake', 10, 30, 4.5), ('flake', 90, 30, 4.5),
             ('dot', 18, 60, 1.3), ('dot', 84, 60, 1.3)])
    body = P()
    body.moveTo(20, 60)
    body.lineTo(20, 22)
    body.curveTo(20, 12, 80, 12, 80, 22)
    body.lineTo(80, 60)
    body.close()
    draw(body)
    draw(smooth([(20, 26), (50, 18.5), (80, 26)], closed=False), IN, fill=False)
    draw(smooth([(20, 56), (50, 50), (80, 56)], closed=False), IN, fill=False)
    # lacing
    pts = []
    for k in range(9):
        x = 20 + 60 * k / 8
        yb = 22 + 4 * (1 - ((x - 50) / 30) ** 2) * -1 + 1
        y = (53.5 - 5 * (1 - ((x - 50) / 30) ** 2)) if k % 2 == 0 else (24 - 5 * (1 - ((x - 50) / 30) ** 2) + 2)
        pts.append((x, y))
    draw(poly(pts, False), IN, fill=False)
    for (x, y) in pts:
        draw(ell(x, y, 1.3), FINE)
    draw(ell(50, 60, 30, 8))
    draw(ell(50, 60, 26, 6), IN)
    # sticks
    for sg in (-1, 1):
        tube([(50 + sg * 6, 62), (50 + sg * 22, 82)], 2.4)
        draw(ell(50 + sg * 23.5, 84, 3), OUT)
    holly(24, 54, .6, 30)


# ------------------------------------------------------------------ rocking horse
def rocking_horse():
    accents([('star', 12, 88, 4), ('flake', 88, 90, 5), ('sparkle', 90, 50, 4), ('flake', 10, 60, 4),
             ('dot', 30, 90, 1.3), ('dot', 58, 94, 1.3)])
    rp, _ = ribbon_outline([(8, 24), (28, 13), (50, 10.5), (72, 13), (92, 24)], 5)
    draw(rp)
    for (x0, x1) in ((30, 24), (40, 40), (58, 60), (66, 74)):
        draw(poly([(x0 - 2.6, 44), (x0 + 2.6, 44), (x1 + 2.6, 14.5), (x1 - 2.6, 14.5)]), OUT)
    # tail
    draw(smooth([(24, 50), (16, 48), (11, 38), (13, 30), (18, 36), (22, 42)], t=.9))
    draw(curve((21, 47), (16, 42), (15, 35)), FINE, fill=False)
    draw(ell(46, 47, 25, 11))                                # body
    # saddle + blanket
    draw(smooth([(34, 56), (52, 56), (55, 46), (50, 40), (36, 40), (31, 46)], t=.8))
    draw(smooth([(38, 58.5), (50, 58.5), (52, 54), (36, 54)], t=.6), IN)
    for x in (37, 43, 49):
        draw(ell(x, 44.5, 1.2), FINE)
    # neck + head
    head = smooth([(60, 50), (62, 62), (64, 72), (70, 80), (80, 81), (88, 76), (91, 69), (87, 65), (80, 67), (75, 62), (72, 50), (68, 44)], t=.9)
    draw(head)
    draw(ell(88.5, 70, 1.2), FINE)
    draw(arc(86, 67.5, 3, 200, 300), FINE, fill=False)
    eye(77, 74, 2.2)
    draw(smooth([(70, 80), (69.5, 88), (75, 82)], t=.5))     # ear
    # mane: puffs along the back of the neck
    for (x, y, r) in ((61, 52, 3.4), (60.5, 59, 3.6), (61.5, 66, 3.6), (64, 73, 3.4), (68.5, 79, 3.2)):
        draw(ell(x, y, r), IN)
    draw(curve((80, 67), (72, 60), (62, 55)), FINE, fill=False)   # rein
    draw(rrect(66, 64, 3, 6, 1.2), IN)                       # handle


# ------------------------------------------------------------------ holly
def holly_sprig():
    accents([('sparkle', 12, 88, 4.5), ('flake', 88, 90, 5), ('flake', 12, 22, 5), ('star', 88, 22, 4),
             ('dot', 20, 60, 1.3), ('dot', 82, 62, 1.3)])
    bow(50, 22, 1.1)
    holly(50, 34, 3.0, 0, 3)


# ------------------------------------------------------------------ toy soldier
def toy_soldier():
    snow_ground(8, 1.8, 2, 1.8)
    accents([('star', 12, 88, 4), ('sparkle', 88, 88, 4), ('flake', 12, 40, 4.5), ('flake', 88, 44, 4.5),
             ('dot', 20, 66, 1.3), ('dot', 82, 70, 1.3)])
    for sg in (-1, 1):                                        # legs + boots
        draw(rrect(50 + sg * 5 - 4, 14, 8, 16, 1))
        draw(smooth([(50 + sg * 5 - 4.5, 16), (50 + sg * 5 + 4.5, 16), (50 + sg * 5 + 4.5 + sg * 2, 10), (50 + sg * 5 - 4.5, 10)], t=.3))
    # arms
    for sg in (-1, 1):
        draw(rrect(50 + sg * 17 - 3.5, 30, 7, 20, 3.2))
        draw(ell(50 + sg * 17, 29, 3.6), OUT)
        draw(rrect(50 + sg * 17 - 4.5, 46, 9, 5, 2), IN)       # epaulette
    draw(rrect(36, 28, 28, 24, 3))                            # jacket
    draw(poly([(37, 50), (63, 30)], False), IN, fill=False)
    draw(poly([(63, 50), (37, 30)], False), IN, fill=False)
    draw(rrect(35.5, 26, 29, 5, 1), OUT)                     # belt
    draw(rrect(47, 25.5, 6, 6, 1), IN)
    for y in (46, 40, 34):
        draw(ell(50, y, 1.4), FINE)
    draw(ell(50, 60, 10, 9))                                  # head
    face(50, 61, 8, 2, 'smile', True, 3)
    draw(ell(50, 58.5, 1.5), FINE)
    # tall hat
    draw(rrect(40, 66, 20, 22, 4))
    draw(rrect(39, 65, 22, 4, 1.5), OUT)
    draw(poly([(40, 78), (60, 78)], False), IN, fill=False)
    draw(round_star(50, 73, 3, 1.5), FINE)
    draw(smooth([(50, 88), (47, 92), (50, 99), (53, 92)], t=.8), IN)   # plume
    draw(arc(50, 60, 10.5, 190, 350), FINE, fill=False)          # chin strap


# ------------------------------------------------------------------ cupcake
def cupcake():
    accents([('sparkle', 12, 88, 4.5), ('star', 88, 88, 4), ('flake', 12, 30, 4.5), ('flake', 88, 30, 4.5),
             ('dot', 18, 60, 1.3), ('dot', 84, 60, 1.3)])
    wrap = poly([(28, 44), (72, 44), (66, 10), (34, 10)])
    draw(wrap)
    for k in range(1, 8):
        t = k / 8
        draw(poly([(28 + 44 * t, 44), (34 + 32 * t, 10)], False), IN, fill=False)
    # frosting tiers
    draw(smooth([(22, 46), (26, 52), (38, 55), (50, 56), (62, 55), (74, 52), (78, 46), (72, 41), (50, 40), (28, 41)], t=.9))
    draw(smooth([(29, 56), (33, 61.5), (50, 64.5), (67, 61.5), (71, 56), (66, 51.5), (50, 51), (34, 51.5)], t=.9))
    draw(smooth([(36, 64), (40, 69.5), (50, 72), (60, 69.5), (64, 64), (58, 60), (50, 59.5), (42, 60)], t=.9))
    draw(smooth([(50, 70), (54, 74), (50, 79), (46, 74)], t=.8))
    # sprinkles
    for (x, y, a) in ((36, 49, 30), (44, 51, -20), (58, 50, 40), (64, 47, -30), (42, 59, 10), (55, 60, -40), (48, 66, 60)):
        rot(x, y, a)
        draw(rrect(-2, -.7, 4, 1.4, .7), FINE)
        done()
    # cherry
    draw(curve((54, 84), (56, 90), (60, 92)), IN, fill=False)
    draw(ell(52, 82, 4.5))
    draw(arc(50.5, 83.5, 2, 110, 200), FINE, fill=False)


# ------------------------------------------------------------------ sled
def sled():
    snow_ground(18, 2.5, 1.5, 2)
    accents([('flake', 12, 88, 5), ('flake', 88, 86, 5), ('sparkle', 50, 90, 4), ('star', 20, 64, 3.5),
             ('dot', 80, 70, 1.3), ('dot', 34, 80, 1.3)])
    # gift on sled
    draw(rrect(38, 40, 22, 18, 1.5))
    draw(poly([(49, 40), (49, 58)], False), IN, fill=False)
    draw(poly([(38, 49), (60, 49)], False), IN, fill=False)
    bow(49, 59, .6, 0, False)
    draw(rrect(62, 40, 12, 12, 1.5))
    draw(poly([(68, 40), (68, 52)], False), IN, fill=False)
    bow(68, 53, .42, 0, False)
    # seat
    draw(rrect(20, 34, 62, 7, 2))
    for x in (34, 48, 62):
        draw(poly([(x, 34), (x, 41)], False), FINE, fill=False)
    # struts
    for x in (28, 50, 72):
        draw(rrect(x - 1.8, 24, 3.6, 10, .8), IN)
    # runner
    rp, _ = ribbon_outline([(16, 26), (60, 24), (78, 24), (88, 28), (90, 36), (84, 40), (80, 36)], 3.4)
    draw(rp)
    # rope
    draw(curve((88, 34), (92, 26), (96, 22), (102, 22)), IN, fill=False)


# ------------------------------------------------------------------ igloo
def igloo():
    snow_ground(14, 2, 2, 1)
    accents([('flake', 12, 88, 5), ('flake', 88, 88, 5), ('star', 50, 92, 4), ('sparkle', 12, 56, 4),
             ('sparkle', 90, 58, 4), ('dot', 30, 82, 1.3), ('dot', 72, 84, 1.3)])
    dome = P()
    dome.moveTo(14, 14)
    dome.curveTo(14, 64, 86, 64, 86, 14)
    dome.close()
    draw(dome)
    kit.C.saveState(); clip(dome)
    rows = [22, 30, 38, 45, 51]
    prev = 14
    for i, y in enumerate(rows):
        draw(poly([(0, y), (100, y)], False), IN, fill=False)
        off = 0 if i % 2 == 0 else 6
        for x in range(4 + off, 100, 12):
            draw(poly([(x, prev), (x, y)], False), IN, fill=False)
        prev = y
    kit.C.restoreState()
    draw(dome, OUT, fill=False)
    # entrance tunnel
    tun = P()
    tun.moveTo(34, 14)
    tun.curveTo(34, 38, 66, 38, 66, 14)
    tun.close()
    draw(tun)
    door = P()
    door.moveTo(40, 14)
    door.curveTo(40, 31, 60, 31, 60, 14)
    door.close()
    draw(door, IN)
    # little penguin peeking
    draw(ell(50, 19, 6.5, 6))
    draw(ell(50, 18, 4.2, 3.6), FINE)
    eyes(50, 21.5, 5, 1.4)
    draw(smooth([(48.6, 19.3), (51.4, 19.3), (50, 17.5)], t=.5), FINE)


# ------------------------------------------------------------------ snow globe
def snow_globe():
    accents([('sparkle', 10, 90, 4.5), ('sparkle', 90, 90, 4), ('star', 12, 30, 4), ('star', 88, 30, 4),
             ('dot', 16, 60, 1.3), ('dot', 86, 60, 1.3)])
    # base
    base = smooth([(22, 8), (78, 8), (74, 24), (26, 24)], t=.3)
    draw(base)
    draw(rrect(38, 12, 24, 8, 2), IN)
    draw(round_star(50, 16, 2.6, 1.3), FINE)
    globe = ell(50, 50, 29)
    draw(globe)
    kit.C.saveState(); clip(globe)
    draw(smooth([(10, 30), (30, 34), (50, 32), (70, 35), (90, 30), (90, 20), (10, 20)], t=.7), IN)
    # little house
    draw(rrect(38, 32, 18, 14, 1), IN)
    draw(poly([(35, 45), (47, 56), (59, 45)]), IN)
    draw(rrect(44, 32, 5, 8, 1), FINE)
    draw(rrect(50.5, 38, 4, 4, .5), FINE)
    # tree
    draw(smooth([(68, 60), (74, 48), (72, 48), (77, 38), (59, 38), (64, 48), (62, 48)], t=.3), IN)
    draw(rrect(66.5, 34, 3, 4, .5), FINE)
    for (x, y) in ((30, 66), (40, 72), (54, 70), (62, 76), (34, 54), (28, 44), (66, 64), (46, 62), (72, 68), (58, 58)):
        draw(ell(x, y, 1.2), FINE)
    kit.C.restoreState()
    draw(globe, OUT, fill=False)
    draw(arc(50, 50, 24, 110, 150), IN, fill=False)
