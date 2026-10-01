from kit import *
import kit


def rot(x, y, a):
    kit.C.saveState(); kit.C.translate(x, y); kit.C.rotate(a)


def done():
    kit.C.restoreState()


# ------------------------------------------------------------------ elf
def elf():
    snow_ground(10, 2.5, 2, 2)
    accents([('star', 12, 88, 4), ('sparkle', 90, 60, 4), ('flake', 12, 50, 4.5), ('flake', 88, 30, 4.5),
             ('dot', 20, 70, 1.3), ('dot', 82, 80, 1.3)])
    # legs + curly shoes
    for sg in (-1, 1):
        x = 50 + sg * 6
        draw(rrect(x - 3.5, 12, 7, 12, 2))
        shoe = smooth([(x - sg * 4, 9), (x + sg * 4, 8.5), (x + sg * 9, 10), (x + sg * 12, 14), (x + sg * 10, 15),
                       (x + sg * 8, 13), (x + sg * 4, 14), (x - sg * 4, 14.5)], t=.8)
        draw(shoe)
        draw(ell(x + sg * 11.5, 16, 1.8), IN)
    # arms (one waving)
    tubes([[(40, 38), (32, 44), (27, 52)]], 5.5)
    draw(ell(26, 54, 3.8), OUT)
    tubes([[(60, 38), (67, 32), (70, 27)]], 5.5)
    draw(ell(71, 25, 3.8), OUT)
    # tunic
    draw(smooth([(40, 44), (60, 44), (63, 30), (66, 20), (50, 18), (34, 20), (37, 30)], t=.7))
    draw(rrect(35.5, 25, 29, 5, 1), OUT)
    draw(rrect(46.5, 24, 7, 7, 1.2), IN)
    draw(rrect(48.5, 26, 3, 3, .5), FINE)
    # zigzag collar
    col = []
    for k in range(9):
        a = math.radians(200 + 140 * k / 8)
        r = 11 if k % 2 == 0 else 7.5
        col.append((50 + r * math.cos(a) * 1.25, 47 + r * math.sin(a) * .7))
    draw(poly([(37, 47)] + col + [(63, 47)]), OUT)
    # ears
    for sg in (-1, 1):
        e = smooth([(50 + sg * 12, 61), (50 + sg * 19, 62.5), (50 + sg * 23, 64), (50 + sg * 19, 57), (50 + sg * 12.5, 54)], t=.8)
        draw(e)
    draw(ell(50, 58, 14, 13.5))                            # head
    face(50, 58, 10, 2.4, 'open', True, 3.8)
    for (x, y) in ((42, 54.5), (43.5, 53.2), (56.5, 53.2), (58, 54.5)):
        draw(ell(x, y, .45), FINE * .8)
    # hat
    hat = P()
    hat.moveTo(36, 66)
    hat.curveTo(38, 80, 52, 92, 70, 95)
    hat.curveTo(66, 88, 64, 78, 64, 66)
    hat.close()
    draw(hat)
    draw(ell(71.5, 95.5, 3.4), OUT)                        # bell
    draw(poly([(69, 94.5), (74, 96.5)], False), FINE, fill=False)
    band = []
    for k in range(11):
        band.append((35 + k * 3, 64 if k % 2 == 0 else 69.5))
    draw(smooth([(35, 64), (50, 62.2), (65, 64), (65, 69), (50, 67.5), (35, 69)], t=.6), OUT)
    for k in range(5):
        draw(ell(38 + k * 6, 65.6, .9), FINE)


# ------------------------------------------------------------------ penguin
def penguin():
    snow_ground(10, 2.5, 2, .4)
    accents([('flake', 12, 88, 5), ('flake', 88, 84, 5), ('sparkle', 12, 40, 4), ('sparkle', 90, 40, 3.5),
             ('dot', 22, 66, 1.3), ('dot', 80, 64, 1.3)])
    for sg in (-1, 1):                                        # feet
        draw(ell(50 + sg * 8, 10.5, 7, 3.4))
    for sg in (-1, 1):                                        # flippers
        rot(50 + sg * 18.5, 36, sg * 28)
        draw(smooth([(0, 10), (sg * 4, 6), (sg * 5, -4), (sg * 2, -12), (0, -8)], t=.9))
        done()
    draw(ell(50, 40, 21, 31))
    draw(smooth([(50, 52), (60, 48), (63.5, 34), (60, 18), (50, 12), (40, 18), (36.5, 34), (40, 48)]), IN)   # belly
    # face patch
    draw(smooth([(50, 55), (58, 57), (62, 62), (58, 66.5), (50, 64.5), (42, 66.5), (38, 62), (42, 57)], t=.9), IN)
    eyes(50, 61.5, 10, 2.3)
    blush(40.5, 58.2, 2)
    blush(59.5, 58.2, 2)
    draw(smooth([(46.5, 58.5), (53.5, 58.5), (50, 54.5)], t=.5), IN)   # beak
    # scarf
    draw(smooth([(31, 45.5), (50, 42.5), (69, 45.5), (68.5, 51), (50, 48.3), (31.5, 51)]), OUT)
    draw(smooth([(58, 45), (61, 36), (63, 28), (68, 29), (66.5, 38), (63, 46)], t=.8), OUT)
    for x in (62.5, 64.5, 66.5):
        draw(poly([(x, 28.6), (x - .3, 25.5)], False), FINE, fill=False)
    draw(poly([(60.8, 37), (65.8, 37.8)], False), FINE, fill=False)
    # beanie
    draw(smooth([(33, 73), (37, 85), (50, 90), (63, 85), (67, 73)], closed=True, t=.8))
    draw(rrect(31, 68.5, 38, 7, 3), OUT)
    for x in (35, 40, 45, 50, 55, 60, 65):
        draw(poly([(x, 69), (x, 75)], False), FINE, fill=False)
    for x in (42, 50, 58):
        draw(poly([(x, 78), (x, 85)], False), FINE, fill=False)
    draw(cloud(50, 92.5, 4.5, 4.2, 9, .22), OUT)


# ------------------------------------------------------------------ polar bear
def polar_bear():
    snow_ground(10, 2, 2, 1.2)
    accents([('flake', 12, 86, 5), ('star', 88, 88, 4), ('flake', 90, 44, 4.5), ('sparkle', 10, 40, 4),
             ('dot', 22, 66, 1.3), ('dot', 82, 70, 1.3)])
    for sg in (-1, 1):                                        # feet
        draw(ell(50 + sg * 13, 12, 8, 5.5))
        for k in (-3, 0, 3):
            draw(ell(50 + sg * 13 + k, 14.5, 1.4, 1.1), FINE)
        draw(ell(50 + sg * 13, 11, 3.2, 2.2), FINE)
    draw(ell(50, 28, 23, 18))                               # body
    draw(ell(50, 26, 13, 11), IN)                          # tummy
    # present held in paws
    draw(rrect(41, 22, 18, 13, 1.5))
    draw(poly([(50, 22), (50, 35)], False), IN, fill=False)
    bow(50, 36, .55, 0, False)
    for sg in (-1, 1):
        draw(ell(50 + sg * 11, 28, 5, 4.5))                   # paws
    for sg in (-1, 1):                                        # ears
        draw(ell(50 + sg * 13, 71, 5.5))
        draw(ell(50 + sg * 13, 71, 2.8), FINE)
    draw(ell(50, 58, 18, 15.5))                             # head
    draw(ell(50, 52.5, 8, 6))                               # muzzle
    draw(smooth([(46.5, 56), (53.5, 56), (50, 52.8)], t=.7), IN)
    draw(poly([(50, 52.8), (50, 50.5)], False), FINE, fill=False)
    draw(arc(48, 50.5, 2, 200, 340), FINE, fill=False)
    draw(arc(52, 50.5, 2, 200, 340), FINE, fill=False)
    eyes(50, 61, 14, 2.4)
    blush(39, 55.5)
    blush(61, 55.5)
    # scarf
    draw(smooth([(34, 45), (50, 42), (66, 45), (66, 50), (50, 47.2), (34, 50)]), OUT)


# ------------------------------------------------------------------ owl
def owl():
    accents([('flake', 12, 88, 5), ('star', 88, 90, 4), ('sparkle', 10, 50, 4), ('flake', 90, 50, 4.5),
             ('dot', 20, 72, 1.3), ('dot', 84, 72, 1.3)])
    # branch
    tubes([[(-10, 20), (30, 22), (70, 20), (110, 23)], [(78, 21), (86, 28), (90, 33)]], 5)
    draw(smooth([(8, 23.5), (14, 26.5), (22, 27), (28, 25), (20, 23.5)], t=.8), IN)
    draw(smooth([(74, 23), (80, 26), (88, 26), (92, 23.5), (84, 22.5)], t=.8), IN)
    body = smooth([(50, 78), (64, 74), (70, 58), (69, 38), (62, 26), (50, 22), (38, 26), (31, 38), (30, 58), (36, 74)], t=.9)
    draw(body)
    # ear tufts
    for sg in (-1, 1):
        draw(smooth([(50 + sg * 12, 75), (50 + sg * 18, 84), (50 + sg * 19, 72)], t=.6), OUT)
    draw(body, OUT, fill=False)
    # belly feathers
    draw(smooth([(50, 50), (60, 46), (62, 36), (57, 27), (50, 25), (43, 27), (38, 36), (40, 46)]), IN)
    for (x, y) in ((45, 42), (50, 42), (55, 42), (47.5, 36), (52.5, 36), (50, 30)):
        draw(arc(x, y + 1.6, 2.3, 200, 340), FINE, fill=False)
    # wings
    for sg in (-1, 1):
        draw(smooth([(50 + sg * 18, 56), (50 + sg * 22, 46), (50 + sg * 20, 34), (50 + sg * 15, 30), (50 + sg * 15, 44)], t=.9))
    # eye discs
    for sg in (-1, 1):
        draw(ell(50 + sg * 8.5, 61, 8.5), OUT)
        eye(50 + sg * 8.5, 61, 3.6)
    draw(smooth([(47, 56), (53, 56), (50, 50.5)], t=.5), IN)   # beak
    # feet
    for sg in (-1, 1):
        for k in (-2, 0, 2):
            draw(ell(50 + sg * 6 + k, 22.5, 1.4, 2), FINE)
    # santa hat
    hat = P()
    hat.moveTo(36, 74)
    hat.curveTo(38, 88, 56, 95, 68, 88)
    hat.curveTo(72, 84, 68, 80, 64, 74)
    hat.close()
    draw(hat)
    draw(cloud(69, 86, 3.6, 3.4, 8, .22), OUT)
    draw(smooth([(34, 72), (50, 70), (66, 72), (66.5, 77.5), (50, 76), (33.5, 77.5)], t=.8), OUT)


# ------------------------------------------------------------------ fox
def fox():
    snow_ground(10, 2.5, 2, 2.4)
    accents([('flake', 12, 88, 5), ('flake', 88, 86, 5), ('sparkle', 90, 66, 4), ('star', 10, 44, 3.5),
             ('dot', 20, 68, 1.3), ('dot', 82, 70, 1.3)])
    # tail
    tail = smooth([(58, 14), (74, 11), (86, 20), (90, 36), (86, 50), (78, 56), (72, 52), (76, 44), (80, 34), (76, 24), (62, 20)], t=.9)
    draw(tail)
    kit.C.saveState(); clip(tail)
    draw(curve((70, 48), (78, 44.5), (86, 44), (94, 46)), IN, fill=False)
    kit.C.restoreState()
    draw(tail, OUT, fill=False)
    # body
    draw(smooth([(50, 46), (60, 42), (64, 28), (62, 14), (50, 12), (38, 14), (36, 28), (40, 42)], t=.9))
    draw(smooth([(50, 40), (56, 34), (56, 22), (50, 16), (44, 22), (44, 34)], t=.9), IN)
    for sg in (-1, 1):
        draw(ell(50 + sg * 7, 12.5, 5, 3.4))
    # ears
    for sg in (-1, 1):
        draw(smooth([(50 + sg * 8, 66), (50 + sg * 17, 82), (50 + sg * 19, 62)], t=.4))
        draw(smooth([(50 + sg * 11, 66), (50 + sg * 16.5, 76), (50 + sg * 17, 65)], t=.4), FINE)
    # head
    head = smooth([(50, 71), (62, 69), (70, 61), (66, 51), (58, 46.5), (50, 45), (42, 46.5), (34, 51), (30, 61), (38, 69)], t=.9)
    draw(head)
    kit.C.saveState(); clip(head)
    for sg in (-1, 1):
        draw(smooth([(50, 49), (50 + sg * 8, 50), (50 + sg * 16, 54), (50 + sg * 24, 50), (50 + sg * 14, 40), (50, 40)], t=.8), IN)
    kit.C.restoreState()
    draw(head, OUT, fill=False)
    draw(ell(50, 49.5, 2.6, 2), IN)
    smile(50, 47, 2.5, lw=FINE)
    eyes(50, 57, 12, 2.3)
    blush(40.5, 52.5, 2)
    blush(59.5, 52.5, 2)
    # scarf
    draw(smooth([(39, 41), (50, 38.5), (61, 41), (60.5, 45), (50, 43), (39.5, 45)]), OUT)


# ------------------------------------------------------------------ bunny
def bunny():
    snow_ground(10, 2, 2, .8)
    accents([('flake', 12, 88, 5), ('sparkle', 88, 88, 4), ('flake', 90, 44, 4.5), ('star', 10, 46, 3.5),
             ('dot', 22, 70, 1.3), ('dot', 80, 70, 1.3)])
    draw(cloud(69, 20, 4, 4, 8, .25), IN)                  # tail
    draw(ell(50, 26, 18, 16))                               # body
    draw(ell(50, 24, 10, 10), IN)
    for sg in (-1, 1):
        draw(ell(50 + sg * 10, 11.5, 7.5, 4))
        draw(ell(50 + sg * 10, 11, 3, 1.8), FINE)
    # ears
    for sg in (-1, 1):
        rot(50 + sg * 7, 64, sg * -12)
        draw(smooth([(0, 0), (5, 8), (5.5, 20), (0, 28), (-5.5, 20), (-5, 8)], t=.9))
        draw(smooth([(0, 3), (2.6, 9), (2.8, 19), (0, 24), (-2.8, 19), (-2.6, 9)], t=.9), FINE)
        done()
    draw(ell(50, 52, 16, 14))                               # head
    face(50, 54, 12, 2.3, 'none', True)
    draw(smooth([(48.3, 50.5), (51.7, 50.5), (50, 48.8)], t=.6), IN)
    draw(arc(48.3, 47.6, 1.7, 200, 340), FINE, fill=False)
    draw(arc(51.7, 47.6, 1.7, 200, 340), FINE, fill=False)
    # holding a candy cane
    tube([(62, 14), (60, 32), (60, 38), (56, 41), (53, 38)], 3.4)
    for yy in (18, 23, 28):
        draw(poly([(58.5, yy), (62, yy + 2)], False), FINE, fill=False)
    for sg in (-1, 1):
        draw(ell(50 + sg * 10, 28, 4, 3.5))
    # scarf
    draw(smooth([(37, 40), (50, 37.5), (63, 40), (62.5, 44), (50, 42), (37.5, 44)]), OUT)


# ------------------------------------------------------------------ gingerbread house
def gingerbread_house():
    snow_ground(10, 2, 2, .3)
    accents([('flake', 10, 88, 5), ('flake', 90, 88, 5), ('sparkle', 12, 60, 4), ('sparkle', 88, 58, 4),
             ('dot', 22, 76, 1.3), ('dot', 80, 76, 1.3)])
    draw(rrect(64, 64, 9, 16, 1))                            # chimney
    draw(cloud(68.5, 80.5, 6, 2.2, 7, .25), IN)
    draw(rrect(20, 10, 60, 40, 2))                           # walls
    roof = poly([(12, 48), (50, 82), (88, 48)])
    draw(roof)
    # icing on roof edge
    ic = []
    for k in range(13):
        t = k / 12
        ic.append((12 + 76 * t, 48 + (34 if t <= .5 else 34) * (1 - abs(t - .5) * 2)))
    draw(scallop_line(list(reversed(ic)), .38), OUT, fill=False)
    for (x, y) in ((30, 60), (50, 70), (70, 60), (40, 64), (60, 64)):
        draw(smooth([(x - 2.4, y - 1.6), (x + 2.4, y - 1.6), (x + 1.6, y + 2), (x - 1.6, y + 2)], t=.8), IN)   # gumdrops
    draw(ell(50, 56, 5), IN)                               # round window
    draw(poly([(45, 56), (55, 56)], False), FINE, fill=False)
    draw(poly([(50, 51), (50, 61)], False), FINE, fill=False)
    # door
    door = P()
    door.moveTo(42, 10)
    door.lineTo(42, 28)
    door.curveTo(42, 36, 58, 36, 58, 28)
    door.lineTo(58, 10)
    door.close()
    draw(door)
    draw(ell(54.5, 20, 1.2), FINE)
    draw(arc(50, 28, 5, 0, 180), FINE, fill=False)
    # windows
    for x in (24, 64):
        draw(rrect(x, 28, 12, 12, 1.5))
        draw(poly([(x + 6, 28), (x + 6, 40)], False), IN, fill=False)
        draw(poly([(x, 34), (x + 12, 34)], False), IN, fill=False)
        draw(scallop_line([(x - 1, 41), (x + 3.5, 41), (x + 8.5, 41), (x + 13, 41)], .4), IN, fill=False)
    # candy cane posts
    for x, sg in ((35, -1), (65, 1)):
        tube([(x, 8), (x, 22), (x - sg * 1, 25.5), (x - sg * 4, 25.5), (x - sg * 5, 23)], 3)
        for yy in (11, 15, 19):
            draw(poly([(x - 1.6, yy), (x + 1.6, yy + 1.8)], False), FINE, fill=False)
    # peppermints on wall
    for (x, y) in ((27, 17), (73, 17)):
        draw(ell(x, y, 3.2), IN)
        for k in range(3):
            a = math.radians(60 * k)
            draw(poly([(x + 3.2 * math.cos(a), y + 3.2 * math.sin(a)), (x - 3.2 * math.cos(a), y - 3.2 * math.sin(a))], False), FINE, fill=False)


# ------------------------------------------------------------------ sleigh
def sleigh():
    accents([('star', 10, 88, 4.5), ('star', 90, 90, 3.5), ('sparkle', 30, 92, 3.5), ('flake', 88, 60, 4.5),
             ('flake', 12, 58, 4), ('dot', 70, 86, 1.3), ('dot', 20, 26, 1.3), ('dot', 86, 22, 1.3)])
    # gifts
    for (x, y, w, h) in ((26, 46, 16, 14), (40, 50, 14, 18), (52, 46, 16, 12)):
        draw(rrect(x, y, w, h, 1))
        draw(poly([(x + w / 2, y), (x + w / 2, y + h)], False), IN, fill=False)
    bow(47, 69, .45, 0, False)
    bow(34, 61, .38, 0, False)
    bow(60, 59, .38, 0, False)
    # sack
    draw(smooth([(60, 44), (72, 44), (76, 54), (72, 64), (68, 68), (64, 64), (58, 56)], t=.9))
    draw(cloud(68, 68.5, 3.5, 2, 6, .25), IN)
    # runners
    run = smooth([(10, 20), (14, 16), (70, 16), (84, 18), (90, 26), (86, 30), (82, 26), (80, 22), (70, 21), (16, 21), (13, 23)], t=.8)
    draw(run)
    for x in (28, 58):
        draw(rrect(x, 20, 4, 10, .8), OUT)
    # body
    body = smooth([(16, 48), (20, 30), (30, 28), (66, 28), (78, 34), (84, 46), (90, 54), (86, 58), (78, 52), (72, 46), (60, 44), (30, 46)], t=.8)
    draw(body)
    draw(smooth([(24, 34), (66, 34), (74, 40), (64, 40), (26, 40)], t=.6), IN)
    for x in (32, 44, 56):
        draw(round_star(x, 37, 2.4, 1.2), FINE)
    draw(arc(86.5, 55, 2.6, 0, 360), IN, fill=False)


# ------------------------------------------------------------------ cookies & milk
def cookies():
    accents([('sparkle', 10, 88, 4.5), ('star', 90, 88, 4), ('flake', 12, 60, 4.5), ('flake', 90, 64, 4.5),
             ('dot', 30, 90, 1.3), ('dot', 70, 92, 1.3)])
    # table cloth line
    draw(poly([(-10, 16), (110, 16)], False), OUT, fill=False)
    # milk glass
    g = poly([(60, 18), (80, 18), (83, 64), (57, 64)])
    draw(g)
    draw(poly([(58.2, 50), (81.8, 50)], False), IN, fill=False)
    draw(curve((61, 26), (61.5, 40), (62, 46)), IN, fill=False)
    draw(ell(70, 64, 13, 2.6), IN)
    # straw
    tube([(73, 56), (77, 76), (84, 80)], 2.6)
    # plate
    draw(ell(36, 20, 28, 7))
    draw(ell(36, 21, 20, 4.2), IN)
    # cookies
    draw(ell(26, 32, 12, 11))
    for (x, y) in ((22, 35), (29, 36), (25, 28), (31, 30), (20, 30)):
        draw(ell(x, y, 1.5, 1.2), FINE)
    draw(round_star(44, 34, 13, 6.5, 5, 90, .25))
    draw(ell(40.5, 36.5, 1.3), FINE)
    draw(ell(47.5, 36.5, 1.3), FINE)
    smile(44, 33.5, 2.8, lw=FINE)
    # tree cookie leaning
    rot(35, 44, 15)
    draw(smooth([(0, 18), (7, 8), (4, 8), (9, 0), (-9, 0), (-4, 8), (-7, 8)], t=.35))
    draw(poly([(-5, 3), (5, 3)], False), FINE, fill=False)
    draw(poly([(-3, 10), (3, 10)], False), FINE, fill=False)
    done()


# ------------------------------------------------------------------ cocoa
def cocoa():
    accents([('sparkle', 10, 88, 4.5), ('flake', 90, 88, 5), ('flake', 12, 40, 4.5), ('star', 90, 44, 4),
             ('dot', 22, 66, 1.3), ('dot', 84, 66, 1.3)])
    # saucer
    draw(ell(50, 12, 34, 7))
    draw(ell(50, 13, 22, 3.8), IN)
    # handle
    tubes([[(66, 44), (78, 44), (80, 34), (74, 26), (66, 26)]], 5)
    # mug
    mug = smooth([(26, 60), (74, 60), (72, 30), (66, 16), (34, 16), (28, 30)], t=.5)
    draw(mug)
    draw(ell(50, 60, 24, 5))
    draw(ell(50, 60, 20, 3.6), IN)
    # marshmallows
    for (x, y) in ((40, 61), (48, 62.5), (56, 61.5), (44, 64.5), (53, 65)):
        draw(rrect(x - 3, y - 2.4, 6, 4.8, 1.4), IN)
    # heart on mug
    h = P()
    h.moveTo(50, 28)
    h.curveTo(38, 36, 42, 46, 50, 41)
    h.curveTo(58, 46, 62, 36, 50, 28)
    h.close()
    draw(h, IN)
    # candy cane stirrer
    tube([(62, 60), (64, 76), (66, 81), (71, 81), (72.5, 77)], 3.2)
    for yy in (64, 69, 74):
        draw(poly([(61.8, yy), (65.4, yy + 2)], False), FINE, fill=False)
    # steam
    for x in (40, 50):
        draw(curve((x, 70), (x - 3, 76), (x + 2, 82), (x - 1, 88)), IN, fill=False)
