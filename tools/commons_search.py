"""Search Wikimedia Commons files directly for a set of queries.

fetch_avatars.py only looks at a Wikipedia article's designated pageimage
(plus Wikidata P18). Plenty of people and shows have freely-licensed photos
sitting in Commons that no article points at; this surfaces them, with
licence metadata, for manual review. Prints candidates only -- writes nothing.

Input on stdin: slug<TAB>query (one query per line; a slug may repeat).
"""
import json
import sys
import urllib.parse
import urllib.request

UA = "sfai-avatars/1.0 (https://sfai.agency; info@sfai.agency)"
API = "https://commons.wikimedia.org/w/api.php"

FREE = ("cc by", "cc-by", "cc0", "public domain", "pd", "no restrictions",
        "attribution", "gfdl", "ogl")
NONFREE = ("nc", "nd", "fair use", "non-free", "copyright")


def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def search_files(query, limit=8):
    r = get({"action": "query", "format": "json",
             "generator": "search", "gsrsearch": query,
             "gsrnamespace": "6", "gsrlimit": str(limit),
             "prop": "imageinfo",
             "iiprop": "extmetadata|url|size",
             "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription",
             "iiurlwidth": "400"})
    out = []
    for p in (r.get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata", {}) or {}
        lic = str(em.get("LicenseShortName", {}).get("value", "")).strip()
        low = lic.lower()
        free = any(f in low for f in FREE) and not any(n in low for n in NONFREE)
        out.append({"title": p.get("title", ""), "license": lic, "free": free,
                    "w": ii.get("width"), "h": ii.get("height"),
                    "url": ii.get("url", ""),
                    "thumb": ii.get("thumburl", "")})
    return out


def main():
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        slug, query = line.split("\t", 1)
        print(f"\n### {slug}  q={query!r}")
        try:
            for c in search_files(query):
                mark = "FREE " if c["free"] else "     "
                print(f"  {mark}{c['license']:18.18s} {c['w']}x{c['h']:<5} {c['title']}")
        except Exception as e:
            print(f"  ERROR {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
