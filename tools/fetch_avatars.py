"""Fetch missing artist headshots from Wikipedia/Wikimedia, with provenance.

Collection pages fall back to a monogram tile whenever
example-reports/avatars/<slug>.jpg is absent. This fills those gaps.

Source choice matters here. Wikipedia/Wikimedia is used rather than general
image search because every file carries machine-readable licence metadata,
so each download can be recorded with its licence, author and source URL.
The manifest it writes (example-reports/avatars/PROVENANCE.csv) is what
makes the set auditable later — attributing, replacing or removing a
specific image is a lookup rather than an investigation.

Matching is deliberately conservative. Cartoonist names collide badly with
other public figures ("Mike Peters", "Michael Gallagher", "John Whitaker"),
so a candidate is only accepted when the article text looks like the right
kind of person. Anything ambiguous is skipped and listed in the report as
needing a manual decision, because a confidently wrong face is worse than a
monogram.

Usage:
  python3 tools/fetch_avatars.py --dry-run      # report what it would fetch
  python3 tools/fetch_avatars.py                # fetch and write files
  python3 tools/fetch_avatars.py --only ny-     # restrict to a prefix
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AVATARS = os.path.join(ROOT, "example-reports", "avatars")
MANIFEST = os.path.join(AVATARS, "PROVENANCE.csv")
UA = "sfai-avatars/1.0 (https://sfai.agency; info@sfai.agency)"
API = "https://en.wikipedia.org/w/api.php"
SIZE = 400

# Domains differ in what a correct match looks like. Searching "Bob Dylan
# cartoonist" and then rejecting his article for not being art-related is how
# the original single-domain version would have failed on the audio rosters,
# so the disambiguating vocabulary is selected per domain.
DOMAINS = {
    "art": {
        # parenthetical article suffixes, tried most specific first
        "suffixes": [" (cartoonist)", " (comics)", " (illustrator)",
                     " (artist)", ""],
        "search_term": "cartoonist",
        "good": ["cartoonist", "comic", "illustrator", "animator", "artist",
                 "caricatur", "graphic novel", "strip", "editorial cartoon",
                 "photograph", "designer", "writer"],
    },
    # Spoken and music are split rather than one "audio" domain because show
    # titles collide with band names: searching the podcast "Criminal" as
    # generic audio returned Criminal (band), a thrash metal group, which
    # would have put four strangers on Phoebe Judge's report.
    "spoken": {
        "suffixes": [" (podcast)", " (radio program)", " (radio programme)",
                     " (radio series)", " (journalist)", " (comedian)", ""],
        "search_term": "podcast radio program",
        "good": ["podcast", "radio", "broadcast", "npr", "public radio",
                 "talk show", "host", "presenter", "journalist", "comedian",
                 "correspondent", "episodes", "programme", "program"],
        # A definition that opens with these is a musical act, not a
        # spoken-word programme. "singer" is deliberately NOT here: plenty of
        # podcast hosts also sing (it rejected Ashly Burch), and "band" plus
        # the genre words are what actually catch a band article.
        "disqualifying": ["band", "album", "discography", "thrash",
                          "heavy metal", "guitarist"],
    },
    "music": {
        "suffixes": [" (musician)", " (singer)", " (band)", " (rapper)", ""],
        "search_term": "musician band",
        "good": ["musician", "singer", "songwriter", "rapper", "band",
                 "guitarist", "drummer", "bassist", "composer", "record",
                 "album", "discography", "recording artist"],
        "disqualifying": [],
    },
}
# words that indicate we matched the wrong famous person. Shared: these are
# wrong in every domain we publish.
BAD = ["footballer", "baseball", "basketball", "cricketer", "politician",
        "senator", "governor", "bishop", "admiral", "rugby", "boxer",
        "racing driver", "golfer", "soccer"]


def get(url, params=None, binary=False, tries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read() if binary else json.load(r)
        except Exception as e:
            if a == tries - 1:
                return None
            time.sleep(1.5 * (a + 1))


def search(name, domain="art"):
    """Candidate article titles, most specific first."""
    d = DOMAINS[domain]
    out = [name + suffix for suffix in d["suffixes"]]
    r = get(API, {"action": "query", "list": "search", "format": "json",
                  "srsearch": f"{name} {d['search_term']}", "srlimit": "3"})
    if r:
        for s in r.get("query", {}).get("search", []):
            if s["title"] not in out:
                out.append(s["title"])
    return out


def page_info(title):
    r = get(API, {"action": "query", "format": "json", "redirects": "1",
                  "prop": "pageimages|extracts", "piprop": "original",
                  "exintro": "1", "explaintext": "1", "titles": title})
    if not r:
        return None
    pages = r.get("query", {}).get("pages", {})
    for pid, p in pages.items():
        if pid == "-1":
            return None
        img = (p.get("original") or {}).get("source")
        return {"title": p.get("title"), "extract": p.get("extract", ""),
                "image": img}
    return None


def image_license(file_url):
    """Licence metadata for a Commons file, from its filename."""
    # strip any query string first -- Wikipedia appends ?utm_source=... to
    # pageimage URLs, which otherwise corrupts the filename and silently
    # loses the licence metadata this whole approach exists to capture
    fname = urllib.parse.unquote(file_url.split("?")[0].rsplit("/", 1)[-1])
    r = get(API, {"action": "query", "format": "json",
                  "titles": "File:" + fname, "prop": "imageinfo",
                  "iiprop": "extmetadata|url"})
    if not r:
        return {}
    for pid, p in r.get("query", {}).get("pages", {}).items():
        ii = (p.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata", {}) or {}
        def v(k):
            return re.sub(r"<[^>]+>", "", str(em.get(k, {}).get("value", ""))).strip()
        return {"license": v("LicenseShortName") or v("License"),
                "author": v("Artist"), "credit": v("Credit"),
                "descurl": ii.get("descriptionurl", ""),
                "file": fname}
    return {}


def title_matches(title, name):
    """Reject articles whose title is not the person we asked for.

    Without this the search fallback happily returns a RELATED artist --
    it offered Frans Masereel for Eric Drooker -- which would put the wrong
    face on a report. Surnames must match and every query token must appear.
    """
    t = re.sub(r"\s*\(.*?\)\s*", " ", title).lower().strip()
    n = name.lower().strip()
    if t == n:
        return True
    tn, nn = t.split(), n.split()
    if not tn or not nn:
        return False
    if tn[-1] != nn[-1]:                 # surname must match
        return False
    return all(any(w == x or (len(w) == 2 and w[0] == x[0])
                   for x in tn) for w in nn)


def wikidata_image(title):
    """Some articles carry a Commons portrait via Wikidata P18 even when the
    Wikipedia pageimage is absent."""
    r = get(API, {"action": "query", "format": "json", "prop": "pageprops",
                  "redirects": "1", "titles": title})
    if not r:
        return None
    for pid, p in r.get("query", {}).get("pages", {}).items():
        qid = (p.get("pageprops") or {}).get("wikibase_item")
        if not qid:
            return None
        d = get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
        if not d:
            return None
        cl = d.get("entities", {}).get(qid, {}).get("claims", {})
        for c in cl.get("P18", []):
            fn = c.get("mainsnak", {}).get("datavalue", {}).get("value")
            if fn:
                fn = fn.replace(" ", "_")
                import hashlib
                h = hashlib.md5(fn.encode()).hexdigest()
                return (f"https://upload.wikimedia.org/wikipedia/commons/"
                        f"{h[0]}/{h[:2]}/{urllib.parse.quote(fn)}")
    return None


def plausible(extract, name, domain="art"):
    d = DOMAINS[domain]
    good = d["good"]
    t = (extract or "").lower()
    if not t:
        return False, "no article text"
    # Wikipedia's opening sentence is the definition -- "X is a Chilean thrash
    # metal band". Checking only there keeps a passing later mention ("the
    # theme is played by the band ...") from disqualifying a real match.
    lead = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0]
    for b in d.get("disqualifying", []):
        if b in lead:
            return False, f"article defines a {b}, not a {domain} subject"
    if any(b in t for b in BAD) and not any(g in t for g in good):
        return False, "looks like a different public figure"
    if not any(g in t for g in good):
        return False, f"article does not look {domain}-related"
    return True, ""


def square(data):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    s = min(w, h)
    # crop toward the top — portraits put the face above centre
    top = max(0, int((h - s) * 0.25))
    im = im.crop(((w - s) // 2, top, (w - s) // 2 + s, top + s))
    im = im.resize((SIZE, SIZE), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue()


COLLECTION_DOMAIN = {
    "early-adopters": "art", "new-yorker": "art", "osu-archive": "art",
    "signup-form": "art",
    "radio-hosts": "spoken", "podcasters": "spoken", "musicians": "music",
}


def missing_targets(only=None):
    """(slug, display name, domain) for every monogram tile across collections."""
    seen, out = set(), []
    for coll, domain in COLLECTION_DOMAIN.items():
        p = os.path.join(ROOT, "example-reports", coll, "index.html")
        if not os.path.exists(p):
            continue
        s = open(p).read()
        for slug, nm in re.findall(
                r'<a class="er-card" href="\.\./([^/"]+)/"><div class="er-mono">'
                r'[^<]*</div><div class="er-name">([^<]*)', s):
            if slug in seen:
                continue
            if only and not slug.startswith(only):
                continue
            seen.add(slug)
            out.append((slug, re.sub(r"\s+", " ", nm).strip(), domain))
    return out


def clean_name(nm):
    nm = re.sub(r"[“”\"]", "", nm)          # drop nicknames in quotes
    nm = re.sub(r"\s*/\s*.*$", "", nm)                 # "A/B" -> A
    nm = re.sub(r"\s+and\s+.*$", "", nm, flags=re.I)   # duos -> first person
    return nm.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    targets = missing_targets(args.only)
    if args.limit:
        targets = targets[:args.limit]
    print(f"{len(targets)} entries without a headshot\n", flush=True)

    rows, got, skipped = [], 0, []
    for i, (slug, disp, domain) in enumerate(targets, 1):
        dest = os.path.join(AVATARS, slug + ".jpg")
        if os.path.exists(dest):
            continue
        name = clean_name(disp)
        found, reason = None, "no Wikipedia article found"
        for title in search(name, domain):
            info = page_info(title)
            if not info:
                continue
            if not title_matches(info["title"], name):
                if reason == "no Wikipedia article found":
                    reason = "only wrong-person matches"
                continue
            ok, why = plausible(info["extract"], name, domain)
            if not ok:
                reason = why
                continue
            # from here the article IS the right person
            if not info.get("image"):
                img = wikidata_image(info["title"])
                if not img:
                    reason = "article exists but has no free portrait"
                    continue
                info["image"] = img
            found = info
            break

        if not found:
            skipped.append((slug, disp, reason))
            print(f"[{i}/{len(targets)}] {disp:38s} -- skip", flush=True)
            continue

        lic = image_license(found["image"])
        if args.dry_run:
            print(f"[{i}/{len(targets)}] {disp:38s} -> {found['title']} "
                  f"[{lic.get('license','?')}]", flush=True)
            rows.append([slug, disp, found["title"], found["image"],
                         lic.get("license", ""), lic.get("author", ""),
                         lic.get("descurl", "")])
            continue

        data = get(found["image"], binary=True)
        if not data:
            skipped.append((slug, disp, "download failed"))
            continue
        try:
            open(dest, "wb").write(square(data))
        except Exception as e:
            skipped.append((slug, disp, f"decode failed: {type(e).__name__}"))
            continue
        got += 1
        rows.append([slug, disp, found["title"], found["image"],
                     lic.get("license", ""), lic.get("author", ""),
                     lic.get("descurl", "")])
        print(f"[{i}/{len(targets)}] {disp:38s} OK  [{lic.get('license','?')}]",
              flush=True)

    if rows and not args.dry_run:
        new = not os.path.exists(MANIFEST)
        with open(MANIFEST, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["slug", "display_name", "wikipedia_article",
                            "image_url", "license", "author", "description_url"])
            w.writerows(rows)

    print(f"\nfetched {got}, skipped {len(skipped)}")
    if skipped:
        print("\nneeds a manual decision:")
        for s, d, why in skipped:
            print(f"  {d:38s} {why}")


if __name__ == "__main__":
    main()
