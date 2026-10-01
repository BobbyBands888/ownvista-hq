import sys, math
import os
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import simpleSplit
import page  # registers fonts

PAGES = 102
SPINE = PAGES * 0.002252 * 72
BLEED = 9
CW = 2 * BLEED + 2 * 612 + SPINE
CH = 2 * BLEED + 792
FX = BLEED + 612 + SPINE
BX = BLEED

RED = HexColor('#D83A3A')
RED2 = HexColor('#E35858')
DRED = HexColor('#7A1020')
YEL = HexColor('#FFD54A')
GRN = HexColor('#2E9B55')
COL = os.environ.get('TODDLER_COLOR_DIR', os.path.join(os.getcwd(), 'color')) + os.sep


def flake(c, x, y, r, col, lw=1.6):
    c.setStrokeColor(col); c.setLineWidth(lw); c.setLineCap(1)
    for i in range(6):
        a = math.radians(90 + 60 * i)
        c.line(x, y, x + r * math.cos(a), y + r * math.sin(a))
        mx, my = x + r * .6 * math.cos(a), y + r * .6 * math.sin(a)
        for s in (-1, 1):
            b = a + s * math.radians(45)
            c.line(mx, my, mx + r * .3 * math.cos(b), my + r * .3 * math.sin(b))


def pattern(c):
    import random
    rng = random.Random(4)
    for i in range(170):
        x, y = rng.uniform(0, CW), rng.uniform(150, CH)
        if rng.random() < .55:
            flake(c, x, y, rng.uniform(6, 13), RED2, 1.6)
        else:
            c.setFillColor(RED2); c.circle(x, y, rng.uniform(2, 4), stroke=0, fill=1)


def hills(c):
    c.setFillColor(white); c.setStrokeColor(DRED); c.setLineWidth(3)
    p = c.beginPath()
    p.moveTo(-10, -10)
    p.lineTo(-10, 150)
    x = -10
    import random
    rng = random.Random(2)
    while x < CW + 10:
        w = rng.uniform(160, 260)
        h = rng.uniform(-22, 22)
        p.curveTo(x + w * .3, 175 + h, x + w * .7, 175 + h, x + w, 150 + rng.uniform(-10, 10))
        x += w
    p.lineTo(CW + 10, -10)
    p.close()
    c.drawPath(p, stroke=1, fill=1)


def outline(c, txt, cx, y, size, fill, stroke, lw, font='Poppins-Bold'):
    c.saveState()
    t = c.beginText()
    t.setTextRenderMode(2)
    t.setFont(font, size)
    w = c.stringWidth(txt, font, size)
    t.setTextOrigin(cx - w / 2, y)
    c.setLineWidth(lw); c.setStrokeColor(stroke); c.setFillColor(fill); c.setLineJoin(1)
    t.textOut(txt)
    c.drawText(t)
    c.restoreState()


def img(c, name, x, y, s):
    c.drawImage(COL + name + '.png', x, y, s, s, mask='auto')


def pill(c, cx, y, text, size, fill, tcol):
    w = c.stringWidth(text, 'Poppins-Bold', size) + 36
    c.setFillColor(fill); c.setStrokeColor(DRED); c.setLineWidth(3)
    c.roundRect(cx - w / 2, y - size * .55, w, size * 1.9, size * .95, stroke=1, fill=1)
    c.setFillColor(tcol); c.setFont('Poppins-Bold', size)
    c.drawCentredString(cx, y, text)


def build(path):
    c = canvas.Canvas(path, pagesize=(CW, CH), initialFontName='Poppins')
    c.setTitle('Christmas Coloring Book for Toddlers - cover')
    c.setFillColor(RED); c.rect(0, 0, CW, CH, stroke=0, fill=1)
    pattern(c)
    hills(c)

    # ------------------------------------------------ front
    cx = FX + 306
    outline(c, 'Christmas', cx, BLEED + 680, 92, white, DRED, 5)
    outline(c, 'Coloring Book', cx, BLEED + 614, 58, YEL, DRED, 4)
    pill(c, cx, BLEED + 566, 'for Toddlers  •  Ages 2–5', 19, GRN, white)
    # Santa medallion
    my = BLEED + 378
    c.setFillColor(YEL); c.circle(cx, my, 158, stroke=0, fill=1)
    c.setFillColor(white); c.setStrokeColor(DRED); c.setLineWidth(3)
    c.circle(cx, my, 149, stroke=1, fill=1)
    img(c, 'santa', cx - 160, my - 160, 320)
    # friends on the snow
    img(c, 'reindeer', FX - 6, BLEED + 20, 270)
    img(c, 'snowman', FX + 612 + 6 - 270, BLEED + 20, 270)
    img(c, 'present', cx - 80, BLEED + 18, 160)
    # badge
    bx, by = FX + 528, BLEED + 500
    c.setFillColor(YEL); c.setStrokeColor(DRED); c.setLineWidth(3)
    pts = []
    for i in range(32):
        a = math.radians(90 + i * 360 / 32)
        r = 58 if i % 2 == 0 else 50
        pts.append((bx + r * math.cos(a), by + r * math.sin(a)))
    p = c.beginPath(); p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    p.close(); c.drawPath(p, stroke=1, fill=1)
    c.setFillColor(DRED)
    c.setFont('Poppins-Bold', 30); c.drawCentredString(bx, by + 4, '50')
    c.setFont('Poppins-Bold', 10.5); c.drawCentredString(bx, by - 12, 'BIG & EASY')
    c.drawCentredString(bx, by - 24, 'PICTURES')
    c.setFillColor(DRED); c.setFont('Poppins-Medium', 11)
    c.drawCentredString(cx, BLEED + 22, 'LITTLE PUMPKIN PRESS')

    # ------------------------------------------------ back
    bxc = BX + 306
    outline(c, 'Ho Ho Ho!', bxc, BLEED + 690, 50, YEL, DRED, 3.5)
    c.setFillColor(white)
    body = ('Santa, reindeer, snowmen, penguins, cookies, presents and more: 50 big, bold '
            'and happy Christmas pictures made just for little hands.')
    y = BLEED + 646
    for ln in simpleSplit(body, 'Poppins-Medium', 15, 470):
        c.setFont('Poppins-Medium', 15); c.drawCentredString(bxc, y, ln); y -= 22
    y -= 16
    for b in ['Thick, easy lines for crayons and chunky markers',
              'One picture per page, printed single-sided',
              'A simple word under every picture to learn together',
              'A perfect stocking stuffer for ages 2 to 5']:
        c.setFillColor(YEL); c.circle(bxc - 206, y + 5, 5, stroke=0, fill=1)
        c.setFillColor(white); c.setFont('Poppins', 13.5); c.drawString(bxc - 192, y, b); y -= 25
    # colored samples in white cards
    cards = ['tree', 'penguin', 'gingerbread']
    for i, n in enumerate(cards):
        x = BX + 60 + i * 172
        c.setFillColor(white); c.setStrokeColor(DRED); c.setLineWidth(3)
        c.roundRect(x, BLEED + 232, 150, 150, 18, stroke=1, fill=1)
        img(c, n, x + 5, BLEED + 237, 140)
    c.setFillColor(DRED); c.setFont('Poppins-Medium', 11)
    c.drawString(BX + 40, BLEED + 60, 'LITTLE PUMPKIN PRESS')

    # ------------------------------------------------ spine: plain red (under 0.25 in, no text)
    c.showPage(); c.save()
    print('cover in', CW / 72, CH / 72, 'spine', SPINE / 72)


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), 'cover.pdf'))
