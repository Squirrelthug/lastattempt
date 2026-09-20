"""Derive every brand asset from the master logo.

    static/img/logo-master-black.png   the original export (logo on solid black) — never edited
    static/img/logo-full.png           transparent-background version, trimmed
    static/img/logo-mark.png           square mark (transparent)
    static/img/og-default.png          1200x630 social banner
    favicon.ico / favicon.png / apple-touch-icon.png / icon-512.png

Run once (and again whenever the master logo changes):
    python tools/make_brand_assets.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

IMG = Path(__file__).resolve().parents[1] / "static" / "img"
SITE_BG = (12, 10, 15)

master = Image.open(IMG / "logo-master-black.png").convert("RGBA")

# --- transparent full logo: flood the outside black from the edges, use as alpha
mask = master.convert("RGB")
w, h = mask.size
for pt in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]:
    ImageDraw.floodfill(mask, pt, (255, 0, 255), thresh=48)
alpha = Image.new("L", (w, h), 255)
px, ap = mask.load(), alpha.load()
for y in range(h):
    for x in range(w):
        if px[x, y] == (255, 0, 255):
            ap[x, y] = 0
full = master.copy()
full.putalpha(alpha)
full = full.crop(full.getbbox())
full.save(IMG / "logo-full.png", optimize=True)
fw, fh = full.size

# --- square mark: the compass ring, centred; top spike and bottom point trimmed
box = fw
top = int((fh - box) / 2) + int(fh * 0.02)
mark = full.crop((0, top, fw, top + box))
mark.save(IMG / "logo-mark.png", optimize=True)

for name, size in (("favicon.png", 192), ("apple-touch-icon.png", 180), ("icon-512.png", 512)):
    icon = Image.new("RGBA", (size, size), SITE_BG + (255,)) if name == "apple-touch-icon.png" else Image.new("RGBA", (size, size), (0, 0, 0, 0))
    m = mark.resize((size, size), Image.LANCZOS)
    icon.paste(m, (0, 0), m)
    icon.save(IMG / name, optimize=True)
mark.resize((64, 64), Image.LANCZOS).save(IMG / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

# --- social banner: gold glow on the site background, logo centred
banner = Image.new("RGBA", (1200, 630), SITE_BG + (255,))
glow = Image.new("RGBA", (1200, 630), (0, 0, 0, 0))
g = Image.new("RGBA", (700, 700), (228, 176, 74, 80))
glow.paste(g, (250, -35), g)
glow = glow.filter(ImageFilter.GaussianBlur(160))
banner = Image.alpha_composite(banner, glow)
logo = full.resize((int(fw * 580 / fh), 580), Image.LANCZOS)
banner.paste(logo, ((1200 - logo.width) // 2, 25), logo)
banner.convert("RGB").save(IMG / "og-default.png", optimize=True)

print("wrote:", ", ".join(sorted(p.name for p in IMG.glob("*"))))
