"""Swap monogram tiles for <img> avatars wherever example-reports/avatars/<slug>.jpg
now exists on disk. Idempotent: cards that are already <img> are left alone, and a
slug with no avatar file stays a monogram.

  python3 tools/patch_collection_html.py            # apply
  python3 tools/patch_collection_html.py --check     # report only, exit 1 if stale
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AVATARS = os.path.join(ROOT, "example-reports", "avatars")
COLLECTIONS = ["early-adopters", "new-yorker", "osu-archive", "signup-form",
               "radio-hosts", "podcasters", "musicians"]

CARD_RE = re.compile(
    r'(<a class="er-card" href="\.\./(?P<slug>[^/"]+)/">)'
    r'<div class="er-mono">[^<]*</div>'
    r'(<div class="er-name">)'
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = 0
    for coll in COLLECTIONS:
        p = os.path.join(ROOT, "example-reports", coll, "index.html")
        if not os.path.exists(p):
            continue
        s = open(p).read()

        def repl(m):
            nonlocal total
            slug = m.group("slug")
            if not os.path.exists(os.path.join(AVATARS, slug + ".jpg")):
                return m.group(0)
            total += 1
            return (f'{m.group(1)}<img class="er-av" src="../avatars/{slug}.jpg" '
                    f'alt="" loading="lazy">{m.group(3)}')

        new = CARD_RE.sub(repl, s)
        if new != s:
            print(f"{coll}: patched")
            if not args.check:
                open(p, "w").write(new)

    print(f"\n{total} card(s) {'would be ' if args.check else ''}switched to a photo")
    if args.check:
        sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
