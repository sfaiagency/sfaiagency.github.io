"""Regenerate example-reports/credits/ from the portrait provenance manifest.

The credits list was maintained by hand, which was fine for one collection
and stops being fine the moment another one lands: the audio rosters added
37 portraits, 20-odd of them CC-BY, and every one of those carries an
attribution obligation that a hand-edited page silently drops.

fetch_avatars.py already records author, licence and source URL for each
file it downloads. This turns that manifest into the page, so the two cannot
drift: an image on the site that is missing from the credits list is now a
bug the script reports rather than something nobody notices.

Only the <ul class="cr-list"> block is rewritten. The surrounding page --
header, intro copy, footer -- is left exactly as it is.

  python3 tools/build_credits.py            # rewrite the page
  python3 tools/build_credits.py --check    # report drift, change nothing
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AVATARS = os.path.join(ROOT, "example-reports", "avatars")
MANIFEST = os.path.join(AVATARS, "PROVENANCE.csv")
PAGE = os.path.join(ROOT, "example-reports", "credits", "index.html")


def esc(s: str) -> str:
    return html.escape((s or "").strip(), quote=True)


def entry(row: dict) -> str:
    name = esc(row["display_name"])
    author = esc(row["author"]) or "unknown author"
    lic = esc(row["license"]) or "see source"
    url = esc(row["description_url"])
    link = (f'<a href="{url}" rel="noopener" target="_blank">{lic}</a>'
            if url else lic)
    return (f"        <li><b>{name}</b> &mdash; portrait by {author}, "
            f"{link}, via Wikimedia Commons.</li>")


def load() -> list[dict]:
    """One row per image actually on disk, newest manifest entry winning.

    The manifest is append-only, so a slug refetched later appears twice; the
    last row is the one describing the file that is currently there.
    """
    by_slug: dict[str, dict] = {}
    with open(MANIFEST, newline="") as f:
        for row in csv.DictReader(f):
            by_slug[row["slug"]] = row
    rows = [r for s, r in by_slug.items()
            if os.path.exists(os.path.join(AVATARS, s + ".jpg"))]
    rows.sort(key=lambda r: r["display_name"].lower())
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    rows = load()
    on_disk = {os.path.basename(p)[:-4] for p in os.listdir(AVATARS)
               if p.endswith(".jpg")}
    credited = {r["slug"] for r in rows}
    missing = sorted(on_disk - credited)

    body = "<ul class=\"cr-list\">\n" + "\n".join(entry(r) for r in rows) + "\n      </ul>"
    page = open(PAGE).read()
    new = re.sub(r'<ul class="cr-list">.*?</ul>', lambda _: body, page,
                 count=1, flags=re.S)
    if new == page and '<ul class="cr-list">' not in page:
        sys.exit("credits page has no cr-list block")

    n_attrib = sum(1 for r in rows if "cc" in (r["license"] or "").lower())
    print(f"{len(rows)} portraits credited "
          f"({n_attrib} under attribution-requiring licences)")
    if missing:
        print(f"\n{len(missing)} image(s) on disk with no provenance row -- "
              f"these are uncredited:")
        for s in missing:
            print("  " + s)

    if args.check:
        print("\n" + ("page is up to date" if new == page
                      else "page is STALE -- run without --check"))
        sys.exit(1 if (new != page or missing) else 0)

    open(PAGE, "w").write(new)
    print("\nwrote " + os.path.relpath(PAGE, ROOT))


if __name__ == "__main__":
    main()
