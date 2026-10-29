"""Finds free stock / Creative-Commons photos & clips for scenes, and does light topic research (Wikipedia)."""
import html
import io
import json
import re
import urllib.parse
import urllib.request

from PIL import Image

UA = "ReelForge/1.0 (personal local video maker; contact: local-user)"
BAD_TITLE = re.compile(r"logo|icon|signature|coat[_ ]of[_ ]arms|seal[_ ]of|flag[_ ]of|\.svg|\.pdf|\.djvu|diagram|chart", re.I)
STOP = set("a an the of in on at to for with and or but is are was were be been it its this that these those from by as "
           "into about over your you we our they their he she his her them my me i us very more most so just not no "
           "can will would should could has have had do does did make create video reel short clip about".split())


def _get(url, headers=None, timeout=25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _json(url, headers=None, timeout=25):
    return json.loads(_get(url, headers, timeout))


def _strip(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def topic_of(prompt: str) -> str:
    """'Make a 30s reel about the history of the Taj Mahal for instagram' -> 'history of the Taj Mahal'"""
    t = prompt.strip().split("\n")[0]
    t = re.sub(r"(?i)^\s*(please\s+)?(make|create|generate|build|produce|give me|i want|do)\s+(me\s+)?(an?\s+)?", "", t)
    t = re.sub(r"(?i)\b(\d+\s*(s|sec|seconds?|min|minutes?)\b\s*)", "", t)
    t = re.sub(r"(?i)^\s*(an?|the)\s+", "", t)
    t = re.sub(r"(?i)^(short|quick|cool|nice|cinematic|viral|fun|engaging|beautiful|epic|energetic|instagram|youtube|tiktok|\s)*", "", t)
    t = re.sub(r"(?i)^(video|reel|short|clip|explainer|montage|story|ad|trailer|post)s?\s+(about|on|of|for|showing|explaining)?\s*", "", t)
    t = re.sub(r"(?i)\s+(for|on)\s+(instagram|youtube|tiktok|reels?|shorts|social media)\b.*$", "", t)
    t = re.split(r"[,.;!?]| - | with ", t)[0]
    return " ".join(t.split()[:8]).strip() or prompt.strip()[:60]


def subject_of(topic: str) -> str:
    """'the history of the Taj Mahal' -> 'Taj Mahal' (what to search pictures / encyclopedias for)."""
    t = re.sub(r"(?i)^(the\s+)?(top\s+)?(\d+\s+)?(amazing\s+|fun\s+|interesting\s+|surprising\s+)?"
               r"(history|story|facts?|science|truth|secrets?|evolution|rise and fall|life|biography|origins?|basics|"
               r"future|benefits|importance|meaning|things|reasons|ways|tips|guide|introduction|overview|mystery|legend)\s+"
               r"(of|about|behind|on|to|for)\s+", "", topic.strip())
    t = re.sub(r"(?i)^(how|why|what|when|where|who)\s+(is|are|was|were|did|does|do)\s+", "", t)
    t = re.sub(r"(?i)\s+(work|happen|form|exist|grow|fly|evolve)s?\??$", "", t)
    t = re.sub(r"(?i)^the\s+", "", t)
    return t.strip() or topic


def keywords(text, n=2):
    """Visual-ish keywords: longest plain lowercase nouns (names/places are usually poor image queries)."""
    words = re.findall(r"(?<![A-Za-z])[a-z][a-z-]{4,}", text)
    out = []
    for w in sorted((w for w in words if w not in STOP and not w.endswith(("ly", "ing", "ed"))), key=len, reverse=True):
        if w not in out:
            out.append(w)
    return out[:n]


# ---------------------------------------------------------------- research
def wikipedia_research(topic, log=print, max_chars=6000) -> str:
    try:
        q = urllib.parse.quote(topic)
        res = _json(f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&srlimit=1&srinfo=suggestion&format=json")
        if not res["query"]["search"] and res["query"].get("searchinfo", {}).get("suggestion"):
            sug = res["query"]["searchinfo"]["suggestion"]
            log(f"Wikipedia: did you mean '{sug}'?")
            res = _json(f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(sug)}&srlimit=1&format=json")
        if not res["query"]["search"]:
            return ""
        title = res["query"]["search"][0]["title"]
        pages = _json("https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=1&explaintext=1&redirects=1"
                      "&format=json&titles=" + urllib.parse.quote(title))["query"]["pages"]
        text = next(iter(pages.values())).get("extract", "")
        text = re.sub(r"\s*\([^()]*\)", "", re.sub(r"\s*\([^()]*\([^()]*\)[^()]*\)", "", text))
        text = re.sub(r"\[\d+\]|\s+(?=[,.])", "", text)
        if text:
            log(f"Researched on Wikipedia: '{title}'")
        return text[:max_chars]
    except Exception as e:
        log(f"Wikipedia research failed: {e}")
        return ""


# ---------------------------------------------------------------- providers
def _orientation(aspect):
    return {"9:16": "portrait", "4:5": "portrait", "16:9": "landscape", "1:1": "square"}.get(aspect, "portrait")


def pexels_photos(q, key, aspect):
    d = _json(f"https://api.pexels.com/v1/search?query={urllib.parse.quote(q)}&per_page=15&orientation={_orientation(aspect)}",
              {"Authorization": key})
    return [{"url": p["src"]["original"] + "?auto=compress&cs=tinysrgb&w=2200", "kind": "image", "source": "Pexels",
             "credit": f"Photo by {p['photographer']} on Pexels", "license": "Pexels License", "page": p["url"]}
            for p in d.get("photos", [])]


def pexels_videos(q, key, aspect):
    d = _json(f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&per_page=10&orientation={_orientation(aspect)}",
              {"Authorization": key})
    out = []
    for v in d.get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
        files = [f for f in files if min(f["width"], f["height"]) <= 1080] or files
        if not files:
            continue
        f = max(files, key=lambda f: min(f["width"], f["height"]))
        out.append({"url": f["link"], "kind": "video", "source": "Pexels", "credit": f"Video by {v['user']['name']} on Pexels",
                    "license": "Pexels License", "page": v["url"]})
    return out


def _prefer_shape(items, aspect):
    """Stable re-order: results whose shape suits the video format first (keeps relevance order within groups)."""
    target = {"9:16": 9 / 16, "4:5": 0.8, "16:9": 16 / 9, "1:1": 1.0}.get(aspect, 9 / 16)

    def bucket(c):
        w, h = c.get("_w") or 0, c.get("_h") or 0
        if not w or not h:
            return 1
        r = (w / h) / target
        return 0 if 0.7 < r < 1.45 else 1 if 0.5 < r < 2.0 else 2

    return sorted(items, key=bucket)


def commons_photos(q, _key=None, aspect="9:16"):
    url = ("https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrlimit=30&format=json"
           "&prop=imageinfo&iiprop=url|size|extmetadata&iiurlwidth=1920&gsrsearch=" + urllib.parse.quote(f"filetype:bitmap {q}"))
    pages = sorted(_json(url).get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        if BAD_TITLE.search(p["title"]) or min(ii.get("width", 0), ii.get("height", 0)) < 700 or not ii.get("thumburl"):
            continue
        meta = ii.get("extmetadata", {})
        artist = _strip(meta.get("Artist", {}).get("value")) or "Unknown"
        lic = _strip(meta.get("LicenseShortName", {}).get("value")) or "see source"
        out.append({"url": ii["thumburl"], "kind": "image", "source": "Wikimedia Commons", "license": lic,
                    "credit": f"{p['title'][5:]} by {artist[:80]} ({lic}), Wikimedia Commons", "page": ii.get("descriptionurl", ""),
                    "_w": ii.get("width"), "_h": ii.get("height")})
    return _prefer_shape(out, aspect)


def wikipedia_photos(q, _key=None, aspect="9:16"):
    url = ("https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrlimit=10&format=json&prop=pageimages"
           "&piprop=thumbnail|name&pithumbsize=1920&gsrsearch=" + urllib.parse.quote(q))
    pages = sorted(_json(url).get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    qwords = {w for w in re.findall(r"[a-z0-9]{4,}", q.lower())}
    out = []
    for p in pages:
        th = p.get("thumbnail")
        if not th or BAD_TITLE.search(p.get("pageimage", "")) or min(th.get("width", 0), th.get("height", 0)) < 600:
            continue
        if qwords and not qwords & set(re.findall(r"[a-z0-9]{4,}", p["title"].lower())):
            continue
        out.append({"url": th["source"], "kind": "image", "source": "Wikipedia", "license": "see Wikimedia Commons",
                    "credit": f"Image from Wikipedia article '{p['title']}' (Wikimedia Commons: {p.get('pageimage', '')})",
                    "page": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(p['title'].replace(' ', '_'))}",
                    "_w": th.get("width"), "_h": th.get("height")})
    return _prefer_shape(out, aspect)


def openverse_photos(q, _key, aspect):
    ar = {"portrait": "tall", "landscape": "wide", "square": "square"}[_orientation(aspect)]
    d = _json(f"https://api.openverse.org/v1/images/?q={urllib.parse.quote(q)}&page_size=20&size=large&aspect_ratio={ar}", timeout=8)
    return [{"url": r["url"], "kind": "image", "source": "Openverse",
             "credit": f"{r.get('title') or 'Image'} by {r.get('creator') or 'Unknown'} ({(r.get('license') or '').upper()} {r.get('license_version') or ''})",
             "license": f"{(r.get('license') or '').upper()} {r.get('license_version') or ''}".strip(), "page": r.get("foreign_landing_url", "")}
            for r in d.get("results", [])]


class Finder:
    """Searches providers in order, downloads unused results and registers them as library assets."""

    def __init__(self, settings, aspect, log, store):
        self.key = settings.get("pexels_api_key", "")
        self.aspect, self.log, self.store = aspect, log, store
        self.cache, self.used, self.dead = {}, set(), set()

    def _providers(self, media):
        p = []
        if self.key:
            p.append(("pexels_v", pexels_videos) if media == "video" else ("pexels", pexels_photos))
            if media == "video":
                p.append(("pexels", pexels_photos))
        p += [("commons", commons_photos), ("wikipedia", wikipedia_photos), ("openverse", openverse_photos)]
        return p

    def _results(self, name, fn, q):
        if (name, q) not in self.cache:
            if name in self.dead:
                return []
            try:
                self.cache[(name, q)] = fn(q, self.key, self.aspect)
            except Exception as e:
                self.log(f"  {name} search failed: {str(e)[:120]}")
                if name in ("openverse",) or "401" in str(e) or "timed out" in str(e):
                    self.dead.add(name)
                self.cache[(name, q)] = []
        return self.cache[(name, q)]

    def find(self, query, media="photo"):
        for name, fn in self._providers(media):
            for c in self._results(name, fn, query):
                if c["url"] in self.used:
                    continue
                self.used.add(c["url"])
                try:
                    return self._download(c, query)
                except Exception as e:
                    self.log(f"  download failed ({c['source']}): {str(e)[:100]}")
        return None

    def _download(self, c, query):
        data = _get(c["url"], timeout=60)
        if c["kind"] == "image":
            img = Image.open(io.BytesIO(data))
            img.verify()
            ext = ".png" if (img.format or "").upper() == "PNG" else ".jpg"
        else:
            ext = ".mp4"
        slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")[:40]
        aid, path = self.store.new_path(ext)
        path.write_bytes(data)
        a = self.store.register(aid, path, f"web_{slug}{ext}",
                                {"source": c["source"], "credit": c["credit"], "license": c["license"], "page": c["page"], "query": query,
                                 "url": c["url"], "web_kind": c["kind"]})
        self.log(f"  found {c['kind']} for '{query}' on {c['source']}")
        return a


def resolve(plan, finder, card_size, log, store, aspect="9:16"):
    """Turn scenes that have a 'source' (stock query / design card) into real library assets."""
    from .designer import render_card

    W, H = card_size
    new_assets = []
    scenes = plan.get("scenes", [])
    known = store.ids()
    todo = [s for s in scenes if isinstance(s.get("source"), dict) and s.get("asset_id") not in known]
    for s in todo:
        if s["source"].get("type") == "design":
            s["text"] = ""
    if todo:
        log(f"Collecting media for {len(todo)} scene(s)...")
    for s in todo:
        src = s["source"]
        a = None
        if src.get("type") == "animation":
            spec = {k: v for k, v in src.items() if k != "type"}
            bg = spec.get("background") if isinstance(spec.get("background"), dict) else {"style": spec.get("background") or "arena"}
            if bg.get("style") == "photo":
                pa = finder.find(str(bg.get("query") or plan.get("title") or "city skyline"))
                bg = {**bg, "photo_path": pa["path"]} if pa else {**bg, "style": "gradient"}
            spec["background"] = bg
            for actor in spec.get("actors") or []:
                img = store.get(actor.get("image_asset_id"))
                if img and img["kind"] == "image":
                    actor.update(kind="image", image_path=img["path"])
            aid, path = store.new_path(".json")
            path.write_text(json.dumps(spec), encoding="utf-8")
            a = store.register(aid, path, "animation.json", {"kind": "anim", "anim": spec, "source": "animation"})
            log("  animated a cartoon scene")
            s["motion"] = "static"
        elif src.get("type") == "stock":
            q = str(src.get("query") or s.get("text") or "").strip()
            words = q.split()
            tries = [q] + [" ".join(words[:k]) for k in range(len(words) - 1, 0, -1)]
            if src.get("fallback_query"):
                tries.append(src["fallback_query"])
            found = src.get("found")
            if isinstance(found, dict) and found.get("url"):
                try:
                    finder.used.add(found["url"])
                    a = finder._download({**found, "kind": found.get("kind", "image")}, q)
                except Exception as e:
                    log(f"  re-download failed ({str(e)[:80]}); searching again")
            for t in dict.fromkeys(t for t in tries if t):
                if a:
                    break
                a = finder.find(t, src.get("media", "photo"))
            if a:
                src["found"] = {"url": a.get("url"), "kind": a.get("web_kind", a["kind"]), "source": a.get("source"),
                                "credit": a.get("credit"), "license": a.get("license"), "page": a.get("page")}
            if not a:
                log(f"  no media found for '{q}' - using a designed card instead")
                src = {"type": "design", "layout": "text", "headline": s.get("text") or q.title()}
                s["text"] = ""
        if not a:
            aid, path = store.new_path(".png")
            render_card(src, W, H, path)
            a = store.register(aid, path, f"design_{src.get('layout', 'text')}.png", {"source": "design", "card": src, "aspect": aspect})
            log(f"  designed a {src.get('layout', 'text')} card")
        s["asset_id"] = a["id"]
        s["start"] = 0
        new_assets.append(a)
    return plan, new_assets
