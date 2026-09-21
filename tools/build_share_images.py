#!/usr/bin/env python3
"""Build 1200x630 social share cards from blog hero images.

LinkedIn, Facebook, X and Slack all crop a preview image to roughly 1.91:1.
Handing them a hero image straight from blog/posts/images/ means letting each
platform guess the crop, and they guess badly: the National Cartoonists Society
scroll is 1621x4408, so a centre crop lands on blank paper, and the square
Croquis score card loses its headline off the top and bottom.

So we pre-render the card ourselves, once, and commit the result. The rule is
driven by the source aspect ratio:

    >= 1.6   already wide      -> cover crop, centred
    1.1-1.6  editorial capture -> cover crop, weighted towards the top, where
                                  mastheads and cartoons sit
    0.9-1.1  square            -> contain; these are designed cards and cropping
                                  them destroys the design
    < 0.9    tall              -> cover crop anchored at the top

Contained images are padded out to width by stretching their own outermost
columns, so a card on a flat background widens seamlessly: the coral Croquis
cartoon simply gains more coral, and the score card's coral rule and grey
footer run the full width instead of floating in the middle of a letterbox.

A post can override the choice in manifest.json with "shareFocus", one of
"top", "center", "bottom" or "contain".

Run after adding or changing a post's hero image:

    pip install Pillow && python3 tools/build_share_images.py

The generated files are committed, so neither the site nor the Pages workflow
needs Pillow at deploy time.
"""

import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - dependency hint only
    sys.exit("Pillow is required: pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "blog" / "posts" / "manifest.json"
OUT_DIR = ROOT / "assets" / "share"

CARD_W, CARD_H = 1200, 630
CARD_RATIO = CARD_W / CARD_H
JPEG_QUALITY = 92
CORAL = (225, 90, 74)  # --coral from styles.css


def edge_color(im):
    """Median colour of the source's left and right edges.

    Sampling only the vertical edges is deliberate: a contained image is padded
    horizontally, so those are the pixels the padding has to blend into. Used
    to flatten transparency; the contain path replicates edges instead.
    """
    w, h = im.size
    strip = max(1, w // 100)
    raw = im.crop((0, 0, strip, h)).tobytes() + im.crop((w - strip, 0, w, h)).tobytes()
    channels = [sorted(raw[i::3]) for i in range(3)]
    return tuple(c[len(c) // 2] for c in channels)


def pick_mode(ratio, override):
    if override:
        return override
    if ratio >= 1.6:
        return "center"
    if ratio >= 1.1:
        return "top-weighted"
    if ratio >= 0.9:
        return "contain"
    return "top"


def render(src_path, mode):
    im = Image.open(src_path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, edge_color(im.convert("RGB")))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")

    w, h = im.size

    if mode == "contain":
        scale = min(CARD_W / w, CARD_H / h)
        fitted = im.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                           Image.LANCZOS)
        card = Image.new("RGB", (CARD_W, CARD_H), edge_color(im))
        x = (CARD_W - fitted.width) // 2
        y = (CARD_H - fitted.height) // 2
        # Stretch the outermost column of pixels across the padding on each
        # side. On a flat background this is invisible; on a designed card it
        # carries horizontal rules out to the full width of the preview.
        if x > 0:
            left = fitted.crop((0, 0, 1, fitted.height)).resize((x, fitted.height))
            right = fitted.crop((fitted.width - 1, 0, fitted.width, fitted.height)) \
                          .resize((CARD_W - x - fitted.width, fitted.height))
            card.paste(left, (0, y))
            card.paste(right, (x + fitted.width, y))
        if y > 0:
            top = fitted.crop((0, 0, fitted.width, 1)).resize((fitted.width, y))
            bottom = fitted.crop((0, fitted.height - 1, fitted.width, fitted.height)) \
                           .resize((fitted.width, CARD_H - y - fitted.height))
            card.paste(top, (x, 0))
            card.paste(bottom, (x, y + fitted.height))
        card.paste(fitted, (x, y))
        return card

    # Cover: scale so the card is filled, then choose which slice survives.
    scale = max(CARD_W / w, CARD_H / h)
    scaled = im.resize((max(CARD_W, round(w * scale)), max(CARD_H, round(h * scale))),
                       Image.LANCZOS)
    overflow_y = scaled.height - CARD_H
    anchors = {"top": 0.0, "top-weighted": 0.18, "center": 0.5, "bottom": 1.0}
    top = round(overflow_y * anchors.get(mode, 0.5))
    left = (scaled.width - CARD_W) // 2
    return scaled.crop((left, top, left + CARD_W, top + CARD_H))


# Brand cards for the pages that have no photograph of their own. Every page on
# the site points at one of these, so a shared link always carries an image.
#   name -> (source logo, fraction of the card width it should occupy)
BRAND_CARDS = {
    "default": ("assets/logo.png", 0.62),
    "blog": ("assets/blog/blog-post-banner-logo.png", 0.52),
    "croquis": ("assets/croquis-logo.png", 0.34),
}


def build_brand_card(name, logo_rel, width_fraction):
    """Centre a logo on white between two coral rules."""
    src = ROOT / logo_rel
    if not src.exists() or src.stat().st_size < 1024:
        # Several files under assets/ are 12-byte "placeholder" stubs.
        print(f"  skip {name}: {logo_rel} is missing or a placeholder")
        return None

    card = Image.new("RGB", (CARD_W, CARD_H), (255, 255, 255))
    logo = Image.open(src).convert("RGBA")
    target_w = round(CARD_W * width_fraction)
    target_h = round(logo.height * target_w / logo.width)
    if target_h > CARD_H * 0.74:  # keep tall marks clear of the rules
        target_h = round(CARD_H * 0.74)
        target_w = round(logo.width * target_h / logo.height)
    logo = logo.resize((target_w, target_h), Image.LANCZOS)
    card.paste(logo, ((CARD_W - target_w) // 2, (CARD_H - target_h) // 2), logo)

    bar = Image.new("RGB", (CARD_W, 16), CORAL)
    card.paste(bar, (0, 0))
    card.paste(bar, (0, CARD_H - 16))

    out = OUT_DIR / f"{name}.jpg"
    card.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    posts = json.loads(MANIFEST.read_text())

    built = []
    for post in posts:
        image = post.get("image")
        if not image:
            print(f"  skip {post['slug']}: no hero image in manifest")
            continue
        src = ROOT / "blog" / image
        if not src.exists():
            print(f"  skip {post['slug']}: {src} missing")
            continue

        im = Image.open(src)
        ratio = im.width / im.height
        mode = pick_mode(ratio, post.get("shareFocus"))
        card = render(src, mode)
        out = OUT_DIR / f"blog-{post['slug']}.jpg"
        card.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        built.append(out)
        print(f"  {post['slug']}: {im.width}x{im.height} (r={ratio:.2f}) "
              f"-> {mode} -> {out.relative_to(ROOT)} "
              f"({out.stat().st_size // 1024}KB)")

    for name, (logo_rel, fraction) in BRAND_CARDS.items():
        out = build_brand_card(name, logo_rel, fraction)
        if out:
            built.append(out)
            print(f"  {name}: {out.relative_to(ROOT)} "
                  f"({out.stat().st_size // 1024}KB)")

    print(f"Built {len(built)} share cards.")


if __name__ == "__main__":
    main()
