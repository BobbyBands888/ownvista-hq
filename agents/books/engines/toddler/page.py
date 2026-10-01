import sys
import os
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import white, black
import kit

GF = os.path.join(HERE, '..', 'fonts') + os.sep
for n, f in (('Poppins-Bold', 'Poppins-Bold.ttf'), ('Poppins', 'Poppins-Regular.ttf'),
             ('Poppins-Medium', 'Poppins-Medium.ttf'), ('Poppins-Light', 'Poppins-Light.ttf')):
    pdfmetrics.registerFont(TTFont(n, GF + f))

W, H = 612, 792
S = 5.0                      # design unit -> points
OX, OY = (W - 100 * S) / 2, 182
FRAME = (42, 58, 570, 752)


def frame(c):
    x0, y0, x1, y1 = FRAME
    c.setStrokeColor(black)
    c.setLineWidth(2.6)
    c.roundRect(x0, y0, x1 - x0, y1 - y0, 26, stroke=1, fill=0)


def bubble_label(c, text, y=100, size=54, maxw=450):
    c.saveState()
    f = 'Poppins-Bold'
    w = c.stringWidth(text, f, size)
    if w > maxw:
        size = size * maxw / w
        w = maxw
    t = c.beginText()
    t.setTextRenderMode(2)
    t.setFont(f, size)
    t.setCharSpace(1.5)
    w = c.stringWidth(text, f, size) + 1.5 * (len(text) - 1)
    t.setTextOrigin(W / 2 - w / 2, y)
    c.setLineWidth(2.8)
    c.setStrokeColor(black)
    c.setFillColor(white)
    c.setLineJoin(1)
    t.textOut(text)
    c.drawText(t)
    c.restoreState()


def draw_page(c, fn, label):
    kit.set_canvas(c)
    c.saveState()
    # clip art to inside the frame
    p = c.beginPath()
    x0, y0, x1, y1 = FRAME
    p.roundRect(x0 + 2, y0 + 2, x1 - x0 - 4, y1 - y0 - 4, 24)
    c.clipPath(p, stroke=0, fill=0)
    c.translate(OX, OY)
    c.scale(S, S)
    fn()
    c.restoreState()
    # label band: white plate so ground lines never cross the word
    c.setFillColor(white)
    c.setStrokeColor(black)
    c.setLineWidth(2.2)
    bubble_label(c, label)
    frame(c)
