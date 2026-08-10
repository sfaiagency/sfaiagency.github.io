"""Relaxed manual-review pass for names fetch_avatars.py's strict heuristics
rejected. Prints candidate Wikipedia titles + a short extract + image/licence
status for each, so a human (or an agent acting carefully) can accept or
reject a match -- this script never writes anything itself.

Input: a TSV of slug<TAB>display_name<TAB>domain on stdin.
"""
import sys
sys.path.insert(0, "tools")
import fetch_avatars as fa


def candidates(name, domain):
    seen = set()
    out = []
    # domain-specific suffixes/search, generic search, and a bare search with
    # no extra vocabulary at all (catches cases where adding "cartoonist" or
    # "podcast" to the query steered the search API away from a short/plain
    # article title)
    titles = list(fa.search(name, domain))
    r = fa.get(fa.API, {"action": "query", "list": "search", "format": "json",
                         "srsearch": name, "srlimit": "5"})
    if r:
        for s in r.get("query", {}).get("search", []):
            titles.append(s["title"])
    for t in titles:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:8]


def main():
    rows = [l.rstrip("\n").split("\t") for l in sys.stdin if l.strip()]
    for i, (slug, name, domain, reason) in enumerate(rows, 1):
        print(f"\n=== [{i}/{len(rows)}] {name}  ({slug}, {domain}, was: {reason})")
        for t in candidates(name, domain):
            info = fa.page_info(t)
            if not info:
                continue
            extract = (info.get("extract") or "").replace("\n", " ")[:160]
            img = info.get("image")
            if not img:
                img = fa.wikidata_image(info["title"])
            lic = ""
            if img:
                l = fa.image_license(img)
                lic = l.get("license", "?")
            print(f"  - {info['title']!r:45s} img={'Y' if img else 'N':1s} lic={lic:14s} {extract}")


if __name__ == "__main__":
    main()
