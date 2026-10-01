import sys
import os
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from reportlab.pdfgen import canvas
from page import *
import kit
import subjects1 as s1, subjects2 as s2, subjects3 as s3, subjects4 as s4, subjects5 as s5

TITLE = 'Christmas Coloring Book for Toddlers'
AUTHOR = 'Little Pumpkin Press'

PLAN = [
    (s1.santa, 'Santa'), (s1.reindeer, 'Reindeer'), (s1.snowman, 'Snowman'), (s1.tree, 'Christmas Tree'),
    (s1.present, 'Present'), (s2.penguin, 'Penguin'), (s1.stocking, 'Stocking'), (s1.gingerbread, 'Gingerbread Man'),
    (s2.elf, 'Elf'), (s1.candy_canes, 'Candy Canes'), (s2.polar_bear, 'Polar Bear'), (s1.ornament, 'Ornament'),
    (s2.cocoa, 'Hot Cocoa'), (s2.owl, 'Owl'), (s1.bells, 'Bells'), (s3.train, 'Toy Train'),
    (s2.bunny, 'Bunny'), (s2.gingerbread_house, 'Gingerbread House'), (s5.big_star, 'Star'), (s3.teddy_bear, 'Teddy Bear'),
    (s2.sleigh, 'Sleigh'), (s2.fox, 'Fox'), (s2.cookies, 'Cookies & Milk'), (s5.mittens, 'Mittens'),
    (s4.kitty, 'Kitty'), (s5.wreath, 'Wreath'), (s3.drum, 'Drum'), (s3.igloo, 'Igloo'),
    (s4.puppy, 'Puppy'), (s5.candle, 'Candle'), (s3.rocking_horse, 'Rocking Horse'), (s5.big_snowflake, 'Snowflake'),
    (s4.mouse, 'Mouse'), (s3.cupcake, 'Cupcake'), (s3.toy_soldier, 'Toy Soldier'), (s3.sled, 'Sled'),
    (s5.cardinal, 'Cardinal'), (s3.snow_globe, 'Snow Globe'), (s4.gift_stack, 'Presents'), (s4.cozy_house, 'Home'),
    (s3.holly_sprig, 'Holly'), (s5.sweater, 'Sweater'), (s4.santa_sack, "Santa's Sack"), (s5.pinecone, 'Pinecone'),
    (s4.lights, 'Lights'), (s4.chimney, 'Chimney'), (s5.candy, 'Candy'), (s4.snow_friends, 'Snow Friends'),
    (s4.moon, 'Good Night'), (s5.merry_christmas, 'Merry Christmas'),
]
assert len(PLAN) == 50


def outline_text(c, txt, x, y, size, lw=2.6, font='Poppins-Bold', center=True):
    c.saveState()
    t = c.beginText()
    t.setTextRenderMode(2)
    t.setFont(font, size)
    w = c.stringWidth(txt, font, size)
    t.setTextOrigin(x - w / 2 if center else x, y)
    c.setLineWidth(lw)
    c.setStrokeColor(black)
    c.setFillColor(white)
    c.setLineJoin(1)
    t.textOut(txt)
    c.drawText(t)
    c.restoreState()


def mini(c, fn, cx, cy, size):
    """Draw a subject small (for title page)."""
    kit.set_canvas(c)
    c.saveState()
    c.translate(cx - size / 2, cy - size / 2)
    c.scale(size / 100, size / 100)
    fn()
    c.restoreState()


def title_page(c):
    frame(c)
    outline_text(c, 'Christmas', W / 2, 640, 64, 3)
    outline_text(c, 'Coloring Book', W / 2, 580, 46, 2.6)
    c.setFillColor(black)
    c.setFont('Poppins-Medium', 18)
    c.drawCentredString(W / 2, 546, 'for Toddlers  •  Ages 2–5')
    mini(c, s1.santa, W / 2, 392, 250)
    c.setFont('Poppins-Medium', 20)
    c.drawCentredString(W / 2, 196, 'This book belongs to:')
    c.setLineWidth(2)
    c.line(W / 2 - 170, 150, W / 2 + 170, 150)
    c.setFont('Poppins-Light', 11)
    c.drawCentredString(W / 2, 88, AUTHOR.upper())


def grownups_page(c):
    c.setFillColor(black)
    c.setFont('Poppins-Bold', 20)
    c.drawCentredString(W / 2, 640, 'For Grown-Ups')
    lines = [
        'Every picture is big, bold and simple, sized for little hands and chunky crayons.',
        'Each one is printed on its own page with a blank back, so markers',
        'won’t bleed through onto the next picture.',
        '',
        'Say the word under each picture together as your child colors.',
        'It’s a fun way to learn new holiday words.',
        '',
        'Tip: tear out a finished page and hang it on the fridge!',
    ]
    y = 596
    for ln in lines:
        c.setFont('Poppins', 12.5)
        c.drawCentredString(W / 2, y, ln)
        y -= 22 if ln else 12
    mini(c, s5.big_star, W / 2, 330, 160)
    c.setFont('Poppins', 9.5)
    y = 170
    for ln in [f'{TITLE}', f'Copyright © 2026 {AUTHOR}. All rights reserved.',
               'No part of this book may be reproduced without written permission from the publisher,',
               'except for personal, non-commercial use of the coloring pages by the purchaser.',
               'First edition, 2026.']:
        c.drawCentredString(W / 2, y, ln)
        y -= 14


def build(path):
    c = canvas.Canvas(path, pagesize=(W, H), initialFontName='Poppins', initialFontSize=10)
    c.setTitle(TITLE)
    c.setAuthor(AUTHOR)
    title_page(c); c.showPage()
    grownups_page(c); c.showPage()
    for fn, label in PLAN:
        draw_page(c, fn, label)
        c.showPage()
        c.showPage()
    c.save()


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), 'interior.pdf'))
