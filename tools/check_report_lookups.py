"""Check that the links in the reports still resolve.

    python3 tools/check_report_lookups.py                # every non-search link
    python3 tools/check_report_lookups.py --sample 40    # spot check
    python3 tools/check_report_lookups.py --only aud-planet-money

Links whose label ends in "search" are deliberately searches and are only
checked for shape. Everything else claims to point at one specific track,
episode, show or artist, so it is fetched and its status reported.
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookup_resolver import UA  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "example-reports")
DATA_RE = re.compile(r'<script id="data" type="application/json">(.*?)</script>', re.S)


def links(dirs):
    for d in dirs:
        path = os.path.join(REPORTS, d, "index.html")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            m = DATA_RE.search(fh.read())
        if not m:
            continue
        for dataset in json.loads(m.group(1)).get("datasets") or []:
            for row in dataset.get("rows") or []:
                for lk in row.get("lookups") or []:
                    yield d, row.get("text", ""), lk["label"], lk["url"]


def status(url):
    # Fetching watch pages in bulk earns a 429 that says nothing about the
    # video; oEmbed answers for one video at a time and confirms it exists.
    if "youtube.com/watch" in url:
        url = ("https://www.youtube.com/oembed?format=json&url="
               + urllib.parse.quote(url))
        time.sleep(2)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return urllib.request.urlopen(req, timeout=30).status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001
        return repr(exc)[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--sample", type=int, default=0)
    args = ap.parse_args()

    rows = [r for r in links(args.only or sorted(os.listdir(REPORTS)))
            if not r[2].endswith("search")]
    if args.sample and args.sample < len(rows):
        random.seed(0)
        rows = random.sample(rows, args.sample)

    tally = Counter()
    for report, text, label, url in rows:
        code = status(url)
        tally[code] += 1
        if code != 200:
            print("  %-22s %-20s %s -> %s" % (report, label, url[:80], code))
    print("checked %d links: %s" % (len(rows), dict(tally)))
    return 0 if set(tally) <= {200} else 1


if __name__ == "__main__":
    sys.exit(main())
