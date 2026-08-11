"""Resolve report evidence rows to specific tracks / episodes on listening platforms.

Every piece of evidence in a report carries links a reader follows to check
the match for themselves. This module works out where each row actually
lives:

  song rows      iTunes Search API      -> the track's Apple Music page
                 YouTube search         -> the artist's video for that track
  episode rows   fyyd open podcast API  -> the episode, its show and its feed
                 the show's RSS feed    -> the episode's own page
                 iTunes lookup          -> the episode on Apple Podcasts
  snippet rows   iTunes Search API      -> the show the transcript came from

Spotify is absent throughout: its search API needs client credentials and it
forbids the web player's anonymous token endpoint, so there is no legitimate
way to resolve a track or episode id here. Given credentials, that is the one
platform left to add.

Every network answer is cached in tools/lookup_cache.json, which is build
scratch rather than a committed artefact.
"""

import html
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, "lookup_cache.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# Datasets whose rows name a song, an episode, or neither.
SONG_DATASETS = {"Genius Song Lyrics", "LAION-DISCO-12M", "Spotify Million Song"}
EPISODE_DATASETS = {"GigaSpeech titles"}
SNIPPET_DATASETS = {"GigaSpeech transcripts", "The People's Speech"}


# --------------------------------------------------------------------------
# cache + fetch
# --------------------------------------------------------------------------

class Cache:
    def __init__(self, path=CACHE_PATH, offline=False):
        self.path = path
        self.offline = offline
        self.dirty = False
        self.lock = threading.Lock()
        try:
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, produce):
        """Return cached value for key, calling produce() on a miss.

        Misses run outside the lock so the prefetch pass can hold several
        requests open at once; a duplicate fetch costs less than serialising
        every caller behind one slow response.
        """
        with self.lock:
            if key in self.data:
                return self.data[key]
        if self.offline:
            return None
        value = produce()
        with self.lock:
            self.data[key] = value
            self.dirty = True
        return value

    def save(self):
        if not self.dirty:
            return
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        self.dirty = False


def fetch(url, timeout=40, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (400, 403, 404):
                break
            time.sleep(2 ** i)
        except Exception as exc:  # noqa: BLE001 - network is best effort
            last = exc
            time.sleep(2 ** i)
    raise last if last else RuntimeError("fetch failed: " + url)


def fetch_json(url, **kw):
    return json.loads(fetch(url, **kw))


def fetch_text(url, **kw):
    return fetch(url, **kw).decode("utf-8", "replace")


# --------------------------------------------------------------------------
# text matching
# --------------------------------------------------------------------------

def norm(text):
    """Fold to comparable form: strip accents, punctuation and case."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", html.unescape(str(text)))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def words(text):
    return [w for w in re.split(r"[^a-z0-9]+", norm_spaces(text).lower()) if w]


def norm_spaces(text):
    text = unicodedata.normalize("NFKD", html.unescape(str(text or "")))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def title_core(title):
    """Drop trailing qualifiers a platform may or may not carry.

    'Crazy (Live)' and 'Crazy - Remastered 2009' both reduce to 'crazy', so a
    row taken from one catalogue still matches the same song in another.
    """
    t = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*$", "", norm_spaces(title))
    t = re.split(r"\s+-\s+", t)[0]
    return norm(t) or norm(title)


def overlap(a, b):
    """Fraction of a's words that appear in b."""
    aw, bw = set(words(a)), set(words(b))
    if not aw:
        return 0.0
    return len(aw & bw) / len(aw)


# --------------------------------------------------------------------------
# resolvers
# --------------------------------------------------------------------------

def itunes_search(cache, term, entity, limit=25, media="music"):
    url = ("https://itunes.apple.com/search?media=%s&entity=%s&limit=%d&term=%s"
           % (media, entity, limit, urllib.parse.quote(term)))
    key = "itunes:" + url

    # iTunes returns fifty-odd fields per result; keep the handful that decide
    # a match so the cache stays a few megabytes rather than hundreds.
    keep = ("wrapperType", "artistName", "trackName", "collectionName",
            "trackViewUrl", "artistLinkUrl", "collectionViewUrl", "collectionId",
            "feedUrl")

    def produce():
        try:
            rows = fetch_json(url).get("results", [])
        except Exception:  # noqa: BLE001
            return []
        return [{k: r[k] for k in keep if k in r} for r in rows]

    return cache.get(key, produce) or []


def clean_apple(url):
    """Drop the affiliate/analytics tail iTunes appends to its URLs."""
    url = re.sub(r"[?&]uo=\d+", "", url or "")
    return url.replace("itunes.apple.com", "music.apple.com") if "/album/" in url else url


def resolve_song(cache, artist, title):
    """The song's own Apple Music page, or None."""
    for term in ("%s %s" % (artist, title), title):
        for row in itunes_search(cache, term, "song", limit=25):
            if not row.get("trackViewUrl"):
                continue
            artist_ok = (norm(artist) in norm(row.get("artistName")) or
                         norm(row.get("artistName")) in norm(artist))
            title_ok = title_core(row.get("trackName")) == title_core(title)
            if artist_ok and title_ok:
                return {
                    "url": clean_apple(row["trackViewUrl"]),
                    "track": norm_spaces(row.get("trackName")),
                    "artist": norm_spaces(row.get("artistName")),
                    "album": norm_spaces(row.get("collectionName")),
                }
    return None


def resolve_artist_page(cache, artist):
    for row in itunes_search(cache, artist, "musicArtist", limit=10):
        url = clean_apple(row.get("artistLinkUrl") or "")
        # A comedian who also wrote a book comes back as an /author/ page,
        # which is not the musician link the row is claiming.
        if norm(row.get("artistName")) == norm(artist) and "/artist/" in url:
            return url
    return None


YT_VIDEO_RE = re.compile(
    r'"videoRenderer":\{"videoId":"([\w-]{11})".*?'
    r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"\}\].*?'
    r'"ownerText":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', re.S)


def youtube_candidates(cache, query):
    # sp=EgIQAQ%3D%3D restricts the result page to videos, dropping channels,
    # playlists and the "people also watched" shelves.
    url = ("https://www.youtube.com/results?search_query=%s&sp=EgIQAQ%%253D%%253D"
           % urllib.parse.quote(query))
    key = "youtube:" + query

    def produce():
        try:
            page = fetch_text(url, timeout=60)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for m in YT_VIDEO_RE.finditer(page):
            vid, title, owner = m.groups()
            out.append({
                "id": vid,
                "title": json.loads('"%s"' % title),
                "owner": json.loads('"%s"' % owner),
            })
            if len(out) >= 12:
                break
        return out

    return cache.get(key, produce) or []


def resolve_youtube_song(cache, artist, title):
    """A video of this song on the artist's own channel, or None."""
    for cand in youtube_candidates(cache, "%s %s" % (artist, title)):
        owner = norm(cand["owner"]).removesuffix("topic").removesuffix("vevo")
        owner_ok = owner and (owner in norm(artist) or norm(artist) in owner)
        title_ok = title_core(title) in norm(cand["title"])
        if owner_ok and title_ok:
            return "https://www.youtube.com/watch?v=" + cand["id"]
    return None


def resolve_youtube_episode(cache, show, title):
    """The episode's video, only when the uploader is plainly the show."""
    for cand in youtube_candidates(cache, "%s %s" % (show, title)):
        owner_ok = (norm(show) in norm(cand["owner"]) or
                    norm(cand["owner"]) in norm(show))
        if owner_ok and overlap(title, cand["title"]) >= 0.6:
            return "https://www.youtube.com/watch?v=" + cand["id"]
    return None


# --------------------------------------------------------------------------
# podcasts
# --------------------------------------------------------------------------

def fyyd_shows(cache, show_name, feed_url=None):
    """fyyd records for a show. It carries duplicates, so return them all."""
    key = "fyydshows:%s|%s" % (norm(show_name), feed_url or "")

    def produce():
        found = {}
        urls = ["https://api.fyyd.de/0.2/search/podcast?title=%s&count=10"
                % urllib.parse.quote(show_name)]
        if feed_url:
            urls.insert(0, "https://api.fyyd.de/0.2/search/podcast?url=%s"
                        % urllib.parse.quote(feed_url))
        for url in urls:
            try:
                data = fetch_json(url).get("data") or []
            except Exception:  # noqa: BLE001
                continue
            for pod in data if isinstance(data, list) else [data]:
                if overlap(show_name, pod.get("title") or "") >= 0.6:
                    found[pod["id"]] = {"id": pod["id"],
                                        "title": norm_spaces(pod.get("title")),
                                        "feed": pod.get("xmlURL")}
        return list(found.values())

    return cache.get(key, produce) or []


# Episode archives are large and only a handful of titles per show are ever
# needed, so they are held for the run and never written to the cache file.
_ARCHIVES = {}
_INDEXES = {}


def fyyd_archive(podcast_id, max_pages=8):
    """Every episode fyyd holds for a show: normalised title -> page URL."""
    if podcast_id in _ARCHIVES:
        return _ARCHIVES[podcast_id]
    index = {}
    for page in range(max_pages):
        url = ("https://api.fyyd.de/0.2/podcast/episodes?podcast_id=%s&count=500&page=%d"
               % (podcast_id, page))
        try:
            data = fetch_json(url, timeout=60).get("data") or {}
        except Exception:  # noqa: BLE001
            break
        episodes = data.get("episodes", []) if isinstance(data, dict) else data
        if not episodes:
            break
        for ep in episodes:
            key = norm(ep.get("title"))
            if key and key not in index:
                index[key] = {"title": norm_spaces(ep.get("title")),
                              "url": ep.get("url") or "",
                              "fyyd": ep.get("url_fyyd") or "",
                              "date": (ep.get("pubdate") or "")[:10]}
        if len(episodes) < 500:
            break
    _ARCHIVES[podcast_id] = index
    return index


def feed_index(cache, feed_url):
    """Map normalised episode title -> {link, date} for a podcast feed."""
    key = "feed:" + feed_url

    def produce():
        try:
            xml = fetch_text(feed_url, timeout=60)
        except Exception:  # noqa: BLE001
            return {}
        out = {}
        for item in re.findall(r"<item[ >].*?</item>", xml, re.S):
            t = re.search(r"<title>(.*?)</title>", item, re.S)
            if not t:
                continue
            title = re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1)).strip()
            link = re.search(r"<link>(.*?)</link>", item, re.S)
            date = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
            out[norm(title)] = {
                "title": norm_spaces(title),
                "link": html.unescape(link.group(1).strip()) if link else None,
                "date": date.group(1).strip() if date else None,
            }
        return out

    return cache.get(key, produce) or {}


def apple_show(cache, show_name, feed_url=None):
    """The show's Apple Podcasts page, matched on feed URL where possible."""
    results = itunes_search(cache, show_name, "podcast", limit=25, media="podcast")
    if not results:
        return None
    best = None
    for row in results:
        if feed_url and row.get("feedUrl") == feed_url:
            best = row
            break
        if best is None and norm(row.get("collectionName")) == norm(show_name):
            best = row
    if best is None:
        # Never settle for "the first thing iTunes returned" — a podcast that
        # merely mentions the name is not the show.
        near = [r for r in results if overlap(show_name, r.get("collectionName") or "") >= 0.8
                and overlap(r.get("collectionName") or "", show_name) >= 0.5]
        best = near[0] if near else None
    if not best:
        return None
    return {
        "name": norm_spaces(best.get("collectionName")),
        "id": best.get("collectionId"),
        "url": re.sub(r"[?&](uo|mt)=\d+", "", best.get("collectionViewUrl") or ""),
        "feed": best.get("feedUrl"),
    }


def apple_episode_index(cache, collection_id):
    """Apple only exposes a show's most recent episodes; index what it gives."""
    url = ("https://itunes.apple.com/lookup?id=%s&entity=podcastEpisode&limit=200"
           % collection_id)
    key = "appleeps:%s" % collection_id

    def produce():
        try:
            rows = fetch_json(url).get("results", [])
        except Exception:  # noqa: BLE001
            return {}
        return {norm(r.get("trackName")): re.sub(r"[?&]uo=\d+", "", r.get("trackViewUrl") or "")
                for r in rows if r.get("wrapperType") == "podcastEpisode"}

    return cache.get(key, produce) or {}


def title_variants(title):
    """Forms of an episode title a catalogue might hold it under.

    Shows renumber and rebrand their back catalogue: NPR dropped the '#882:'
    prefixes from Planet Money years after those episodes aired, and guest
    appearances arrive suffixed with the host show. Compare on every form.
    """
    base = norm_spaces(title)
    seen, out = set(), []
    for cand in (
        base,
        re.sub(r"^#?\s*\d+\s*[:.–-]\s*", "", base),
        re.sub(r"^(?:episode|ep\.?|no\.?|part|pt\.?)\s*#?\s*\d+\s*[:.–-]\s*",
               "", base, flags=re.I),
        re.split(r"\s*\|\s*", base)[0],
        re.sub(r"^[^:]{1,40}:\s*", "", base),
        # 'One Head, Two Brains: How The Brain's Hemispheres…' is filed under
        # its headline alone once a show tidies its archive.
        base.split(":")[0] if len(words(base.split(":")[0])) >= 2 else "",
    ):
        key = norm(cand)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def useful_page(url):
    """A link is only worth showing if it points at a page, not a homepage."""
    if not url or not url.startswith("http"):
        return False
    path = urllib.parse.urlparse(url).path.strip("/")
    return bool(path) and path.lower() not in ("index.html", "home")


def episode_index(cache, show_name):
    """Everything known about a show's episodes, best link per title.

    The live RSS feed gives canonical episode pages but only for as far back
    as the publisher keeps it; fyyd's mirror reaches further but sometimes
    only recorded a directory homepage. Merge the two, feed first.
    """
    key = norm(show_name)
    if key in _INDEXES:
        return _INDEXES[key]

    info = apple_show(cache, show_name)
    pods = fyyd_shows(cache, show_name, (info or {}).get("feed"))
    index = {}
    for pod in pods:
        for title_key, entry in fyyd_archive(pod["id"]).items():
            if title_key not in index or not useful_page(index[title_key]["url"]):
                index[title_key] = dict(entry, show=pod["title"])
    for feed_url in {(info or {}).get("feed")} | {p.get("feed") for p in pods}:
        if not feed_url:
            continue
        for title_key, entry in feed_index(cache, feed_url).items():
            if useful_page(entry.get("link")):
                index[title_key] = dict(index.get(title_key) or {},
                                        title=entry["title"], url=entry["link"],
                                        show=(info or {}).get("name") or show_name)
    _INDEXES[key] = index
    return index


def resolve_episode(cache, title, show_names, date_hint=None):
    """Locate one episode: which show it aired on, and its own page.

    show_names is tried in order — the show named beside the row first, the
    show the report is about second — because a title alone is ambiguous
    across a catalogue of millions.
    """
    if not norm(title):
        return None
    shows = [s for s in show_names if s]
    key = "ep:%s|%s" % ("/".join(norm(s) for s in shows), norm(title))

    def produce():
        variants = title_variants(title)
        for show in shows:
            index = episode_index(cache, show)
            if not index:
                continue
            hit = next((index[v] for v in variants if v in index), None)
            if hit is None:
                # Shows retitle their archive — 'What Twins Tell Us' is the
                # same episode GigaSpeech recorded as 'What Twins Can Tell Us
                # About Who We Are'. Accept when one title contains almost all
                # of the other and neither is a bare stub.
                scored = []
                for entry in index.values():
                    fwd, back = overlap(title, entry["title"]), overlap(entry["title"], title)
                    if max(fwd, back) >= 0.85 and min(fwd, back) >= 0.4 \
                            and len(words(entry["title"])) >= 3:
                        scored.append((min(fwd, back), max(fwd, back), entry))
                if scored:
                    hit = max(scored)[2]
            if not hit:
                continue
            if date_hint and hit.get("date") and hit["date"][:4] != date_hint[:4]:
                continue
            # The publisher's own page where the feed still carries it, else
            # the directory page, which at least plays the right episode.
            page = next((u for u in (hit.get("url"), hit.get("fyyd"))
                         if useful_page(u)), None)
            if page:
                return {"show": hit.get("show") or show, "page": page,
                        "title": hit.get("title"), "date": hit.get("date"),
                        "publisher": useful_page(hit.get("url"))}
        return None

    return cache.get(key, produce)
