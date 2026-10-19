#!/usr/bin/env python3
"""Build the small square thumbnails used by the landing page.

The originals in artists/<Name>/ are full-size uploads (up to ~3000px and
1.5 MB each). The hero circles show them at 55-100px and the "Trusted by"
grid at under 100px, so both point at 200px WebP thumbnails in assets/hero/
instead.

    python3 tools/build_hero_thumbs.py            # write thumbnails
    python3 tools/build_hero_thumbs.py --rings    # also print hero ring markup

Requires Pillow (pip install pillow). Not part of the Pages build: run it by
hand after adding or replacing an image in artists/.

--rings prints the <div class="circle-track"> blocks for index.html. Every
image appears exactly once across all rings, so the counts in RINGS must add
up to the number of images in artists/. If you change a ring's count, update
that ring's --total in styles.css to match.
"""

import random
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "artists"
OUT = ROOT / "assets" / "hero"
SIZE = 200
QUALITY = 78

# (class, number of balls, faces among them), innermost first. Inner rings
# show at every width; ring-5 only on wide screens.
RINGS = [
    ("inner-circle", 8, 3),
    ("outer-circle", 12, 4),
    ("ring-3", 15, 4),
    ("ring-4", 18, 5),
    ("ring-5", 22, 5),
]
SEED = 7


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def thumb_name(path):
    return f"{slug(path.parent.name)}-{path.stem}.webp"


def make_thumb(src, dest):
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        side = min(w, h)
        left = (w - side) // 2
        # Portrait photos: crop nearer the top so heads stay in frame.
        top = int((h - side) * (0.25 if src.stem == "profile" else 0.5))
        im = im.crop((left, top, left + side, top + side))
        im = im.resize((SIZE, SIZE), Image.LANCZOS)
        im.save(dest, "WEBP", quality=QUALITY, method=6)


def sources():
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    return sorted(p for p in SRC.glob("*/*") if p.suffix.lower() in exts)


def ring_layout(paths):
    """Assign every image to exactly one ring slot.

    Faces and artwork are mixed in each ring, and no two neighbours on a ring
    come from the same artist.
    """
    total = sum(n for _, n, _ in RINGS)
    if total != len(paths):
        sys.exit(f"RINGS hold {total} balls but there are {len(paths)} images")
    faces = [p for p in paths if p.stem == "profile"]
    works = [p for p in paths if p.stem != "profile"]
    if sum(f for _, _, f in RINGS) != len(faces):
        sys.exit(f"RINGS place {sum(f for _, _, f in RINGS)} faces "
                 f"but there are {len(faces)} profile images")

    rng = random.Random(SEED)
    for _ in range(10000):
        rng.shuffle(faces)
        rng.shuffle(works)
        fi = wi = 0
        layout = []
        ok = True
        for cls, n, f in RINGS:
            ring_faces = faces[fi:fi + f]
            ring_works = works[wi:wi + n - f]
            fi += f
            wi += n - f
            # Spread the faces evenly around the ring.
            face_slots = {round(k * n / f) for k in range(f)}
            slots, fq, wq = [], list(ring_faces), list(ring_works)
            for i in range(n):
                slots.append(fq.pop() if i in face_slots and fq else wq.pop())
            artists = [p.parent.name for p in slots]
            if any(artists[i] == artists[(i + 1) % n] for i in range(n)):
                ok = False
                break
            layout.append((cls, slots))
        if ok:
            return layout
    sys.exit("could not find a layout without neighbouring duplicates")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = sources()
    for p in paths:
        make_thumb(p, OUT / thumb_name(p))
    print(f"Wrote {len(paths)} thumbnails to {OUT.relative_to(ROOT)}/",
          file=sys.stderr)

    if "--rings" in sys.argv:
        for cls, slots in ring_layout(paths):
            # Rings that can be hidden on narrow screens load lazily.
            lazy = ' loading="lazy"' if cls == "ring-5" else ""
            print(f'            <div class="circle-track {cls}" aria-hidden="true">')
            for i, p in enumerate(slots):
                print(f'                <div class="ball" style="--i: {i};">'
                      f'<img src="assets/hero/{thumb_name(p)}" alt="" '
                      f'width="{SIZE}" height="{SIZE}" decoding="async"{lazy}>'
                      f'</div>')
            print("            </div>")


if __name__ == "__main__":
    main()
