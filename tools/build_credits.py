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
# licences worked out after the fact for portraits that predate the manifest;
# kept separate so the audit trail still says which is which
RECONSTRUCTED = os.path.join(AVATARS, "PROVENANCE_RECONSTRUCTED.csv")
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
    # reconstructed first, so a row recorded at download time always wins
    for path in (RECONSTRUCTED, MANIFEST):
        if not os.path.exists(path):
            continue
        with open(path, newline="") as f:
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

    # Write BEFORE reporting. The missing list runs to dozens of lines, and
    # piping this into head sends SIGPIPE partway through it -- which killed
    # an earlier run after the report but before the write, leaving the page
    # untouched and the exit code 0. Doing the work first makes that
    # impossible.
    stale = new != page
    if not args.check and stale:
        open(PAGE, "w").write(new)

    n_attrib = sum(1 for r in rows if "cc" in (r["license"] or "").lower())
    print(f"{len(rows)} portraits credited "
          f"({n_attrib} under attribution-requiring licences)")
    if not args.check:
        print("wrote " + os.path.relpath(PAGE, ROOT) if stale
              else "page already up to date")
    if missing:
        print(f"\n{len(missing)} image(s) on disk with no provenance row -- "
              f"these are uncredited:")
        for s in missing:
            print("  " + s)

    if args.check:
        print("\n" + ("page is STALE -- run without --check" if stale
                      else "page is up to date"))
        sys.exit(1 if (stale or missing) else 0)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # piping into head is normal here; the page is already written by now
        os._exit(0)
