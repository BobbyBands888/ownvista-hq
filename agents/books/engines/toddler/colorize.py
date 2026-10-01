"""Render single subjects to PNG and colour them by region fill (multiply
blend keeps the black line art crisp). Background becomes transparent."""
import sys, subprocess, os, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import numpy as np
from PIL import Image
from scipy import ndimage
from reportlab.pdfgen import canvas
import kit
import subjects1 as s1, subjects2 as s2, subjects3 as s3, subjects4 as s4, subjects5 as s5

PX = 1600          # output size in px for the 100-unit design box
PAD = 10           # design units of padding around the box


def noop(*a, **k):
    pass


for m in (s1, s2, s3, s4, s5):
    m.accents = noop
    m.snow_ground = noop


def render(fn, name):
    size = 100 + 2 * PAD
    pdf = os.path.join(tempfile.gettempdir(), f'{name}.pdf')
    c = canvas.Canvas(pdf, pagesize=(size * 6, size * 6))
    kit.set_canvas(c)
    c.scale(6, 6)
    c.translate(PAD, PAD)
    fn()
    c.showPage(); c.save()
    dpi = PX * (size / 100) / (size * 6) * 72
    subprocess.run(['pdftoppm', '-r', str(dpi), '-gray', '-png', '-singlefile', pdf, os.path.join(tempfile.gettempdir(), name)], check=True)
    return np.array(Image.open(os.path.join(tempfile.gettempdir(), f'{name}.png')).convert('L'))


def to_px(x, y, shape):
    h, w = shape
    s = w / (100 + 2 * PAD)
    return int((x + PAD) * s), int(h - (y + PAD) * s)


def colorize(fn, name, seeds, out):
    g = render(fn, name)
    white = g > 170
    lab, n = ndimage.label(white)
    h, w = g.shape
    rgb = np.ones((h, w, 3), dtype=float)
    # background = region touching the border -> transparent
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    alpha = np.ones((h, w))
    bgmask = np.isin(lab, list(border))
    bgmask = ndimage.binary_dilation(bgmask, iterations=1) & (g > 110)
    for (x, y, col) in seeds:
        px, py = to_px(x, y, g.shape)
        if not (0 <= px < w and 0 <= py < h):
            continue
        L = lab[py, px]
        if L == 0 or L in border:
            print('  miss', name, x, y)
            continue
        m = ndimage.binary_dilation(lab == L, iterations=3)
        c = np.array([int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)])
        rgb[m] = c
    shade = (g / 255.0)[..., None]
    out_rgb = rgb * shade
    alpha[bgmask] = 0
    # soft edge: keep antialiased dark pixels opaque
    img = np.dstack([out_rgb * 255, alpha * 255]).astype(np.uint8)
    Image.fromarray(img, 'RGBA').save(out)


RED, DRED, GREEN, DGREEN, GOLD, SKIN, PINK, BROWN, TAN, ORANGE, BLUE, SLATE, CREAM, NAVY = (
    '#E23B3B', '#B22234', '#3FAE5A', '#2E8B57', '#F6C343', '#F8D3B5', '#F7A8B0', '#A8683A', '#E8C595',
    '#F59A3A', '#5DADE2', '#4A5A6E', '#FFF6E6', '#2F4A7A')

JOBS = {
    'santa': (s1.santa, [(45, 82, RED), (60, 86, RED), (70, 88, RED), (50, 18, CREAM), (46, 56, SKIN), (54, 60, SKIN), (50, 63, SKIN),
                         (31.5, 55, SKIN), (68.5, 55, SKIN), (50, 50, PINK), (38.5, 52.5, PINK), (61.5, 52.5, PINK),
                         (30, 12, RED), (70, 12, RED), (22, 16, RED), (78, 16, RED), (50, 40.5, DRED), (82, 79, CREAM)]),
    'reindeer': (s1.reindeer, [(38, 64, BROWN), (62, 64, BROWN), (50, 69, BROWN), (36, 30, BROWN), (64, 26, BROWN), (50, 24, BROWN),
                               (43.5, 17, BROWN), (58.7, 17, BROWN), (39.5, 13, BROWN), (63.5, 13, BROWN), (43.7, 10, TAN), (58.7, 10, TAN), (37, 12, BROWN), (62.5, 12, BROWN),
                               (45, 51, TAN), (55, 51, TAN), (50, 55.5, RED), (50, 46, RED), (57, 45.5, GREEN), (43, 45.5, GREEN),
                               (38, 37, GREEN), (40, 57, PINK), (60, 57, PINK), (60, 36, TAN), (65, 31, TAN), (56, 31, TAN),
                               (71.5, 37, CREAM), (61, 76, TAN), (39, 76, TAN), (63, 84, TAN), (37, 84, TAN)]),
    'snowman': (s1.snowman, [(50, 80, NAVY), (45, 73, RED), (60, 55.5, ORANGE), (40, 48, RED), (58, 48.5, RED), (63, 40, RED),
                             (64, 35, RED), (41.5, 56, PINK), (58.5, 57.5, PINK), (26, 41.5, BROWN), (74, 41.5, BROWN),
                             (50, 33, NAVY), (50, 25, NAVY), (50, 17, NAVY)]),
    'tree': (s1.tree, [(34, 30, GREEN), (66, 30, GREEN), (50, 32, GREEN), (40, 22, GREEN), (60, 21, GREEN), (22, 17, GREEN), (78, 17, GREEN),
                       (40, 44, GREEN), (58, 44, GREEN), (46, 50, GREEN), (58, 52, GREEN), (44, 60, GREEN), (54, 58, GREEN),
                       (50, 68, GREEN), (42, 70, GREEN), (58, 68, GREEN), (50, 82, GREEN), (48, 62, GREEN), (36, 36, GREEN), (64, 36, GREEN),
                       (30, 30, RED), (62, 32, GOLD), (44, 30, BLUE), (52, 46, RED), (38, 48, GOLD), (64, 49, BLUE),
                       (46, 64, RED), (57, 64, GOLD), (51, 76, BLUE), (78, 22, GOLD), (22, 21, RED),
                       (50, 95, GOLD), (47, 93, GOLD), (54, 90, GOLD), (50, 91, GOLD), (50, 13, BROWN),
                       (26, 10, RED), (35, 10, RED), (66, 10, BLUE), (74, 10, BLUE)]),
    'penguin': (s2.penguin, [(33, 30, SLATE), (67, 30, SLATE), (50, 68, SLATE), (37, 60, SLATE), (63, 60, SLATE), (40, 14, SLATE), (60, 14, SLATE),
                             (32, 38, SLATE), (68, 38, SLATE), (27.5, 36, SLATE), (72.5, 36, SLATE), (30, 40, SLATE), (70, 40, SLATE), (28.5, 30, SLATE), (71.5, 30, SLATE),
                             (50, 57.5, ORANGE), (42, 10.5, ORANGE), (58, 10.5, ORANGE), (40, 47, RED), (50, 45.5, RED), (60, 46.5, RED),
                             (64, 36, RED), (66, 32, RED), (46, 81, BLUE), (54, 81, BLUE), (38, 78, BLUE), (62, 78, BLUE), (50, 88, BLUE),
                             (40.5, 58.2, PINK), (59.5, 58.2, PINK)]),
    'gingerbread': (s1.gingerbread, [(40, 30, BROWN), (60, 30, BROWN), (28, 56, BROWN), (72, 56, BROWN), (30, 14, BROWN), (70, 14, BROWN),
                                     (40, 80, BROWN), (60, 80, BROWN), (50, 66, BROWN), (50, 40, BROWN), (45, 50, BROWN), (55, 50, BROWN),
                                     (50, 44, RED), (50, 35, GREEN), (45, 55, RED), (55, 55, RED), (40, 73, PINK), (60, 73, PINK)]),
    'present': (s1.present, [(32, 20, RED), (68, 20, RED), (30, 40, RED), (70, 40, RED), (24, 58, DRED), (76, 58, DRED),
                             (50, 30, GOLD), (50, 58, GOLD), (40, 72, GOLD), (60, 72, GOLD), (50, 70, GOLD), (45, 62, GOLD),
                             (78, 36, CREAM)]),
}

if __name__ == '__main__':
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), 'color')
    os.makedirs(out_dir, exist_ok=True)
    for name, (fn, seeds) in JOBS.items():
        colorize(fn, name, seeds, os.path.join(out_dir, f'{name}.png'))
        print('ok', name)
