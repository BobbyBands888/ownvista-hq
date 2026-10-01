# Toddler coloring book engine (vendored as-is)

Christmas Coloring Book for Toddlers (Little Pumpkin Press), 50 hand-coded vector drawings, 102 pages.
Used for reprints/variants only; the Book Studio does not invent new subjects in v1.

- kit.py            cute-style toolkit: smooth shapes, faces, bows, holly, snow, accents
- page.py           page layout: frame, big art box, bubble-letter word label (fonts from ../fonts)
- subjects1-5.py    the 50 drawings (one function each)
- build_interior.py 50-design plan -> interior.pdf
- colorize.py       renders chosen drawings and fills regions with color (cover art; needs numpy, scipy, Pillow, pdftoppm)
- build_cover.py    wraparound cover -> cover.pdf (reads the colored art from TODDLER_COLOR_DIR)

Build and verify through ../build.py: `python3 build.py --engine toddler --out DIR`.
Spine width = pages x 0.002252 in (white paper). Cover = 0.125+8.5+spine+8.5+0.125 in by 11.25 in.
