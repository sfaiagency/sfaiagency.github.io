"""Point every audio evidence row at the recording it matched.

Usage
    python3 tools/fix_report_lookups.py            # rewrite every report
    python3 tools/fix_report_lookups.py --dry-run  # report coverage, write nothing
    python3 tools/fix_report_lookups.py --only aud-planet-money aud-criminal
    python3 tools/fix_report_lookups.py --offline   # cache only, no network

Each report carries its data in <script id="data" type="application/json">.
A row under datasets[].rows[] renders as a card, where `url` makes the title
clickable and `links` lists the platforms underneath. This fills both in for
rows from the audio datasets: the track for a song, the episode for an episode
title, and — for a transcript line, which names no single recording — the show
or artist who spoke it, in `links` only, because a sentence is not a work.

A row keeps no link at all rather than a search. `url` is only ever the work
itself, so a bare publisher homepage found on a row is dropped: it is not the
episode.

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
    apple_show, norm_spaces, resolve_artist_page, resolve_episode,
    itunes_search, resolve_song, resolve_youtube_episode, resolve_youtube_song,
    title_variants, useful_page, youtube_candidates,
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
    """Links for a song row: the track, then the video, then the artist."""
    item, about = [], []
    track = resolve_song(cache, artist, title)
    if track:
        item.append(link("Apple Music", track["url"]))
        stats["apple.exact"] += 1

    video = resolve_youtube_song(cache, artist, title)
    if video:
        item.append(link("YouTube", video))
        stats["youtube.exact"] += 1

    if not item:
        page = resolve_artist_page(cache, artist)
        if page:
            about.append(link("Apple Music artist", page))
            stats["apple.artist"] += 1
    return item, about


def episode_lookups(cache, show_hint, title, date_hint, report_show, stats):
    """Links for an episode row: the episode, then where it is published."""
    found = resolve_episode(cache, title, [show_hint, report_show], date_hint)
    show = (found or {}).get("show") or show_hint or report_show
    item, about = [], []

    if found and found.get("page"):
        item.append(link("Episode page", found["page"]))
        stats["episode.page"] += 1

    info = apple_show(cache, show)
    if info and info.get("id"):
        apple_eps = apple_episode_index(cache, info["id"])
        episode_url = next((apple_eps[v] for v in title_variants(title)
                            if v in apple_eps), None)
        if episode_url:
            item.append(link("Apple Podcasts", episode_url))
            stats["apple.exact"] += 1
        elif info.get("url"):
            about.append(link("Apple Podcasts show", info["url"]))
            stats["apple.show"] += 1

    video = resolve_youtube_episode(cache, show, title)
    if video:
        item.append(link("YouTube", video))
        stats["youtube.exact"] += 1
    return item, about


def snippet_lookups(cache, subject, is_music, stats):
    """A transcript line names no single recording.

    There is no episode to resolve to, so point at whoever was speaking — the
    show for a podcast, the artist for a musician. Never the row's own title:
    a sentence is not a work, and linking it as one would overstate what the
    match actually is.
    """
    if is_music:
        page = resolve_artist_page(cache, subject)
        if page:
            stats["apple.artist"] += 1
            return [], [link("Apple Music artist", page)]
        return [], []

    info = apple_show(cache, subject) if subject else None
    if info and info.get("url"):
        stats["apple.show"] += 1
        return [], [link("Apple Podcasts show", info["url"])]
    return [], []


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

PLATFORM_ORDER = ["Episode page", "Apple Podcasts", "Apple Music", "YouTube"]


def platform(label):
    """'Apple Podcasts show' and 'Apple Podcasts' are the same destination."""
    return re.sub(r"\s+(show|artist)$", "", label)


def apply_links(row, item, about):
    """Merge freshly resolved links into whatever the row already carries.

    A row may already hold links resolved by an earlier pass, and those are
    not all reproducible here — Apple exposes only a show's most recent
    episodes, so an episode link captured earlier cannot be looked up again.
    Keep the more specific link per platform rather than overwriting.

    `url` makes the row's title clickable and should only ever be the work
    itself, so a show or artist page goes in `links` alone, and a bare
    publisher homepage is dropped: it is not the episode.
    """
    before = (row.get("url"), row.get("links"), "lookups" in row)

    # rank 2 = the recording itself, 1 = the show or artist behind it
    best = {}
    for rank, links in ((1, about), (2, item)):
        for lk in links:
            key = platform(lk["label"])
            if rank >= best.get(key, (0,))[0]:
                best[key] = (rank, lk)
    for lk in row.get("links") or []:
        key = platform(lk["label"])
        if key not in best or best[key][0] < 2:
            best[key] = (2, lk)  # an earlier pass only ever wrote exact links

    merged = [best[k][1] for k in PLATFORM_ORDER if k in best]
    merged += [v[1] for k, v in best.items() if k not in PLATFORM_ORDER]
    if merged:
        row["links"] = merged
    else:
        row.pop("links", None)

    # The title should open the work, so prefer the publisher's own page, then
    # Apple, and only then the podcast directory that stands in when a show's
    # feed no longer carries the episode.
    exact = [best[k][1]["url"] for k in PLATFORM_ORDER
             if k in best and best[k][0] == 2]
    exact.sort(key=lambda u: "fyyd.de" in u)
    if exact:
        row["url"] = exact[0]
    elif not useful_page(row.get("url")):
        row.pop("url", None)
    row.pop("lookups", None)  # the search-link schema this replaces
    return before != (row.get("url"), row.get("links"), False)


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
            if row.get("text"):
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
        name = dataset.get("datasetName")
        if name in SONG_DATASETS or name in EPISODE_DATASETS or name in SNIPPET_DATASETS:
            for row in dataset.get("rows") or []:
                if row.get("text"):
                    counts["song" if name in SONG_DATASETS else "spoken"] += 1
    is_music = counts["song"] > counts["spoken"]
    prefetch_songs(cache, artist, data)

    for dataset in data.get("datasets") or []:
        name = dataset.get("datasetName")
        for row in dataset.get("rows") or []:
            if not row.get("text"):
                continue
            text = norm_spaces(row.get("text"))
            show_hint, date_hint = parse_meta(row.get("meta"))
            if name in SONG_DATASETS:
                item, about = song_lookups(cache, artist, text, stats)
            elif name in EPISODE_DATASETS:
                item, about = episode_lookups(cache, show_hint, text, date_hint,
                                              report_show, stats)
            elif name in SNIPPET_DATASETS:
                item, about = snippet_lookups(
                    cache, artist if is_music else report_show, is_music, stats)
            else:
                continue
            stats["rows"] += 1
            if apply_links(row, item, about):
                changed = True
            if not item and not about:
                stats["unresolved"] += 1

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
