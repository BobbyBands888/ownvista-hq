"""Book Studio build + verify (runs on the GitHub Actions runner; needs reportlab + pypdf).

    python3 build.py --engine mandala --config cfg.json --out DIR [--pages 84]
    python3 build.py --engine toddler --out DIR [--pages 102]     (reprint of the vendored toddler book)

Writes DIR/interior.pdf and DIR/cover.pdf (plus DIR/cover-thumb.png when pdftoppm is installed), checks them
with pypdf against KDP's paperback rules, prints one JSON line and exits 1 if anything is off:
  - interior: expected page count, every page exactly 8.5 x 11 in, 24-828 pages
  - cover: one page, width = 0.125 + 8.5 + spine + 8.5 + 0.125 in, height = 11.25 in, spine = pages x 0.002252 in
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRIM_W, TRIM_H, BLEED_IN, SPINE_PER_PAGE = 8.5, 11.0, 0.125, 0.002252
TOL = 0.01  # inches


def cover_size(pages):
    spine = pages * SPINE_PER_PAGE
    return 2 * BLEED_IN + 2 * TRIM_W + spine, TRIM_H + 2 * BLEED_IN, spine


def verify(interior, cover, pages):
    from pypdf import PdfReader
    problems = []
    r = PdfReader(interior)
    n = len(r.pages)
    if n != pages:
        problems.append(f'interior has {n} pages, expected {pages}')
    if not 24 <= n <= 828:
        problems.append(f'interior page count {n} outside KDP paperback range 24-828')
    for i, p in enumerate(r.pages, 1):
        w, h = float(p.mediabox.width) / 72, float(p.mediabox.height) / 72
        if abs(w - TRIM_W) > TOL or abs(h - TRIM_H) > TOL:
            problems.append(f'interior page {i} is {w:.3f} x {h:.3f} in, expected 8.5 x 11')
            break
    c = PdfReader(cover)
    if len(c.pages) != 1:
        problems.append(f'cover has {len(c.pages)} pages, expected 1')
    cw, ch = float(c.pages[0].mediabox.width) / 72, float(c.pages[0].mediabox.height) / 72
    ew, eh, spine = cover_size(n)
    if abs(cw - ew) > TOL or abs(ch - eh) > TOL:
        problems.append(f'cover is {cw:.4f} x {ch:.4f} in, expected {ew:.4f} x {eh:.4f} in for {n} pages')
    return {'pages': n, 'interior_in': [TRIM_W, TRIM_H], 'cover_in': [round(cw, 4), round(ch, 4)],
            'expected_cover_in': [round(ew, 4), round(eh, 4)], 'spine_in': round(spine, 6), 'problems': problems}


def thumb(cover, out_dir, pages):
    """Small PNG of the front panel (skipped when pdftoppm isn't installed)."""
    if not shutil.which('pdftoppm'):
        return None
    dpi = 24
    cw, ch, spine = cover_size(pages)
    x = int(round((BLEED_IN + TRIM_W + spine) * dpi))
    base = os.path.join(out_dir, 'cover-thumb')
    try:
        subprocess.run(['pdftoppm', '-png', '-r', str(dpi), '-singlefile', '-x', str(x), '-y', '0',
                        '-W', str(int(round((TRIM_W + BLEED_IN) * dpi))), '-H', str(int(round(ch * dpi))), cover, base],
                       check=True, capture_output=True, timeout=120)
    except Exception:
        return None
    return base + '.png' if os.path.exists(base + '.png') else None


def build_mandala(cfg_path, out_dir):
    sys.path.insert(0, os.path.join(HERE, 'mandala'))
    import build_interior as B
    import build_cover as C
    cfg = B.load_config(cfg_path)
    pages = B.build(os.path.join(out_dir, 'interior.pdf'), cfg)
    C.build(os.path.join(out_dir, 'cover.pdf'), cfg)
    return pages


def build_toddler(out_dir):
    eng = os.path.join(HERE, 'toddler')
    color = os.path.join(out_dir, 'color')
    py = sys.executable
    subprocess.run([py, os.path.join(eng, 'build_interior.py'), os.path.join(out_dir, 'interior.pdf')], check=True, cwd=out_dir)
    subprocess.run([py, os.path.join(eng, 'colorize.py'), color], check=True, cwd=out_dir, capture_output=True)
    subprocess.run([py, os.path.join(eng, 'build_cover.py'), os.path.join(out_dir, 'cover.pdf')], check=True, cwd=out_dir,
                   env={**os.environ, 'TODDLER_COLOR_DIR': color})
    return 102


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', required=True, choices=['mandala', 'toddler'])
    ap.add_argument('--config')
    ap.add_argument('--out', required=True)
    ap.add_argument('--pages', type=int)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    try:
        if a.engine == 'mandala':
            if not a.config:
                raise ValueError('--config is required for the mandala engine')
            built = build_mandala(a.config, a.out)
        else:
            built = build_toddler(a.out)
        expected = a.pages or built
        res = verify(os.path.join(a.out, 'interior.pdf'), os.path.join(a.out, 'cover.pdf'), expected)
        if built != expected:
            res['problems'].append(f'engine built {built} pages, expected {expected}')
        res['thumb'] = thumb(os.path.join(a.out, 'cover.pdf'), a.out, res['pages']) if not res['problems'] else None
        res['ok'] = not res['problems']
    except Exception as e:  # report, never hang
        res = {'ok': False, 'problems': [f'{type(e).__name__}: {e}']}
    print(json.dumps(res))
    sys.exit(0 if res['ok'] else 1)


if __name__ == '__main__':
    main()
