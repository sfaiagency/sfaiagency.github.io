"""Rewrite the "lookups" links in every example report so they resolve.

Usage
    python3 tools/fix_report_lookups.py            # rewrite every report
    python3 tools/fix_report_lookups.py --dry-run  # report coverage, write nothing
    python3 tools/fix_report_lookups.py --only aud-planet-money aud-criminal
    python3 tools/fix_report_lookups.py --offline   # cache only, no network

Each report carries its data in <script id="data" type="application/json">.
Rows under datasets[].rows[] hold a .lookups array of {label, url}. Those URLs
were search pages built from the row text; this rewrites them to the track,
the episode or — for a transcript snippet, which names no single item — the
show it was spoken on. Anything that cannot be resolved keeps a scoped search
and says so in its label, so a reader is never told a link is an exact match
when it is not.

Network answers land in tools/lookup_cache.json, which is build scratch and
not committed: re-running is cheap while the cache is warm, and the resolved
links themselves live in the reports.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lookup_resolver import (  # noqa: E402
    Cache, EPISODE_DATASETS, SNIPPET_DATASETS, SONG_DATASETS, apple_episode_index,
    apple_show, feed_index, norm, norm_spaces, resolve_artist_page, resolve_episode,
    itunes_search, resolve_song, resolve_youtube_episode, resolve_youtube_song,
    spotify_episode_search, spotify_show_search, spotify_track_search, title_variants,
    youtube_candidates,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "example-reports")
DATA_RE = re.compile(
    r'(<script id="data" type="application/json">)(.*?)(</script>)', re.S)

# A report is filed under the person or programme it is about; the podcast the
# evidence sits on is not always derivable from that name. These are the ones
# auto-resolution gets wrong or cannot see.
SHOW_OVERRIDES = {
    "aud-all-things-considered": "All Things Considered",
    "aud-ashly-burch": "Hey Riddle Riddle",
    "aud-bill-burr": "Monday Morning Podcast",
    "aud-chris-gethard": "Beautiful Stories From Anonymous People",
    "aud-elizabeth-laime": "Totally Laime",
    "aud-guy-raz": "How I Built This with Guy Raz",
    "aud-jackie-kashian": "The Dork Forest",
    "aud-krista-tippett": "On Being with Krista Tippett",
    "aud-kulap-vilaysack": "Who Charted?",
    "aud-marketplace": "Marketplace",
    # Renamed from "Terrible, Thanks for Asking"; Apple only lists the new title.
    "aud-nora-mcinerney": "Thanks For Asking",
    "aud-ologies": "Ologies with Alie Ward",
    "aud-on-being": "On Being with Krista Tippett",
    "aud-paul-gilmartin": "The Mental Illness Happy Hour",
    "aud-peter-sagal": "Wait Wait... Don't Tell Me!",
    "aud-quincy-larson": "freeCodeCamp Podcast",
    "aud-roman-mars": "99% Invisible",
    "aud-sam-sanders": "It's Been a Minute",
    "aud-shankar-vedantam": "Hidden Brain",
    "aud-tim-ferriss": "The Tim Ferriss Show",
    "aud-todd-glass": "The Todd Glass Show",
    "aud-up-first": "Up First from NPR",
    "aud-wait-wait": "Wait Wait... Don't Tell Me!",
    "aud-20k": "Twenty Thousand Hertz",
}

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_meta(meta):
    """Split 'The Indicator  ·  12 Feb 2020  ·  GigaSpeech titles'."""
    parts = [p.strip() for p in re.split(r"·", norm_spaces(meta)) if p.strip()]
    show, date = None, None
    for part in parts[:-1] if len(parts) > 1 else []:
        m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{4})$", part)
        if m and m.group(2)[:3].title() in MONTHS:
            date = "%s-%02d-%02d" % (m.group(3), MONTHS[m.group(2)[:3].title()],
                                     int(m.group(1)))
        else:
            show = part
    return show, date


def link(label, url):
    return {"label": label, "url": url}


# --------------------------------------------------------------------------
# per-row link sets
# --------------------------------------------------------------------------

def song_lookups(cache, artist, title, stats):
    exact, search = [], []
    video = resolve_youtube_song(cache, artist, title)
    if video:
        exact.append(link("YouTube", video))
        stats["youtube.exact"] += 1
    else:
        search.append(link("YouTube search",
                           "https://www.youtube.com/results?search_query=" +
                           _q("%s %s" % (artist, title))))
        stats["youtube.search"] += 1

    track = resolve_song(cache, artist, title)
    if track:
        exact.append(link("Apple Music", track["url"]))
        stats["apple.exact"] += 1
    else:
        page = resolve_artist_page(cache, artist)
        if page:
            exact.append(link("Apple Music artist", page))
            stats["apple.artist"] += 1
        else:
            search.append(link("Apple Music search",
                               "https://music.apple.com/us/search?term=" +
                               _q("%s %s" % (artist, title))))
            stats["apple.search"] += 1

    # Spotify exposes no search API without client credentials, so this stays a
    # search — but a field-scoped one that lands the track at the top.
    search.append(link("Spotify search", spotify_track_search(artist, title)))
    stats["spotify.search"] += 1
    return exact + search


def episode_lookups(cache, show_hint, title, date_hint, report_show, stats):
    found = resolve_episode(cache, title, [show_hint, report_show], date_hint)
    show = (found or {}).get("show") or show_hint or report_show
    exact, search = [], []

    if found and found.get("page"):
        exact.append(link("Episode page", found["page"]))
        stats["episode.page"] += 1
    elif report_show:
        # Not in the index: try the show's own feed directly.
        info = apple_show(cache, report_show)
        entry = feed_index(cache, info["feed"]).get(norm(title)) if info and info.get("feed") else None
        if entry and entry.get("link"):
            exact.append(link("Episode page", entry["link"]))
            stats["episode.page"] += 1

    info = apple_show(cache, show)
    if info and info.get("id"):
        apple_eps = apple_episode_index(cache, info["id"])
        episode_url = next((apple_eps[v] for v in title_variants(title)
                            if v in apple_eps), None)
        if episode_url:
            exact.append(link("Apple Podcasts", episode_url))
            stats["apple.exact"] += 1
        elif info.get("url"):
            exact.append(link("Apple Podcasts show", info["url"]))
            stats["apple.show"] += 1
    else:
        search.append(link("Apple Podcasts search",
                           "https://podcasts.apple.com/us/search?term=" +
                           _q("%s %s" % (show, title))))
        stats["apple.search"] += 1

    video = resolve_youtube_episode(cache, show, title)
    if video:
        exact.append(link("YouTube", video))
        stats["youtube.exact"] += 1

    search.append(link("Spotify search", spotify_episode_search(show, title)))
    stats["spotify.search"] += 1
    return exact + search


def snippet_lookups(cache, subject, is_music, stats):
    """A transcript line names no single recording.

    There is nothing to resolve to, so point at whoever was speaking — the
    show for a podcast, the artist for a musician — rather than searching a
    platform for a sentence, which is what these rows used to do.
    """
    out = []
    if is_music:
        page = resolve_artist_page(cache, subject)
        if page:
            out.append(link("Apple Music artist", page))
            stats["apple.artist"] += 1
        out.append(link("Spotify search",
                        "https://open.spotify.com/search/%s/artists" % _q(subject)))
        stats["spotify.search"] += 1
        return out

    info = apple_show(cache, subject) if subject else None
    if info and info.get("url"):
        out.append(link("Apple Podcasts show", info["url"]))
        stats["apple.show"] += 1
    out.append(link("Spotify search", spotify_show_search(subject)))
    stats["spotify.search"] += 1
    return out


def _q(text):
    import urllib.parse
    return urllib.parse.quote(norm_spaces(text))


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def prefetch_songs(cache, artist, data):
    """Warm the two calls every song row makes, several at a time.

    Resolution itself stays sequential and readable; this only fills the
    cache first so a forty-track report is not forty round trips deep.
    """
    terms = []
    for dataset in data.get("datasets") or []:
        if dataset.get("datasetName") not in SONG_DATASETS:
            continue
        for row in dataset.get("rows") or []:
            if row.get("lookups"):
                terms.append("%s %s" % (artist, norm_spaces(row.get("text"))))
    if not terms:
        return
    jobs = []
    for term in dict.fromkeys(terms):
        jobs.append(lambda t=term: itunes_search(cache, t, "song", limit=25))
        jobs.append(lambda t=term: youtube_candidates(cache, t))
    with ThreadPoolExecutor(max_workers=8) as pool:
        for future in as_completed([pool.submit(j) for j in jobs]):
            future.exception()  # failures are cached as empty by the resolver


def rewrite(report_dir, cache, stats, dry_run=False):
    path = os.path.join(REPORTS, report_dir, "index.html")
    with open(path, encoding="utf-8") as fh:
        page = fh.read()
    m = DATA_RE.search(page)
    if not m:
        return False
    data = json.loads(m.group(2))
    artist = norm_spaces(data.get("artistName") or data.get("reportName") or "")
    report_show = SHOW_OVERRIDES.get(report_dir, artist)
    changed = False

    # A report is about a musician or about a show, and that decides what a
    # row with nothing to resolve should fall back to.
    counts = Counter()
    for dataset in data.get("datasets") or []:
        for row in dataset.get("rows") or []:
            if row.get("lookups"):
                counts["song" if dataset.get("datasetName") in SONG_DATASETS
                       else "spoken"] += 1
    is_music = counts["song"] > counts["spoken"]
    prefetch_songs(cache, artist, data)

    for dataset in data.get("datasets") or []:
        name = dataset.get("datasetName")
        for row in dataset.get("rows") or []:
            if not row.get("lookups"):
                continue
            text = norm_spaces(row.get("text"))
            show_hint, date_hint = parse_meta(row.get("meta"))
            if name in SONG_DATASETS:
                new = song_lookups(cache, artist, text, stats)
            elif name in EPISODE_DATASETS:
                new = episode_lookups(cache, show_hint, text, date_hint,
                                      report_show, stats)
            elif name in SNIPPET_DATASETS:
                new = snippet_lookups(cache, artist if is_music else report_show,
                                      is_music, stats)
            else:
                continue
            stats["rows"] += 1
            if new != row["lookups"]:
                row["lookups"] = new
                changed = True

    if changed and not dry_run:
        body = json.dumps(data, ensure_ascii=False)
        page = page[:m.start(2)] + body + page[m.end(2):]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    cache = Cache(offline=args.offline)
    stats = Counter()
    dirs = args.only or sorted(os.listdir(REPORTS))
    touched = 0
    for d in dirs:
        if not os.path.isfile(os.path.join(REPORTS, d, "index.html")):
            continue
        try:
            if rewrite(d, cache, stats, args.dry_run):
                touched += 1
                print("rewrote", d, flush=True)
        finally:
            cache.save()

    print("\n%d reports touched, %d rows" % (touched, stats["rows"]))
    for key in sorted(stats):
        if key != "rows":
            print("  %-22s %d" % (key, stats[key]))


if __name__ == "__main__":
    main()
