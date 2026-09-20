#!/usr/bin/env python
"""Build lastattempt.net into ./dist.

Sources:
  site.json                  site-wide config (names, URLs, socials, nav)
  data/feed.xml              cached podcast RSS (refreshed from site.feed_url at build time)
  content/episodes/*.json    per-episode notes exported from the LAPod notes pipeline
  content/articles/*.md      editorial articles (front matter + Markdown)
  content/pages/*.md         simple pages (about, legal, ...)
  content/cast.json          host / co-hosts / recurring guests
  templates/*.html           Jinja2 templates
  static/                    copied verbatim into dist/

Usage:
  python build.py            fetch feed (falls back to cache), build to dist/
  python build.py --offline  skip the network fetch
  python build.py --drafts   include articles marked draft: true
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
CONTENT = ROOT / "content"
DATA = ROOT / "data"
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
NS = {"itunes": ITUNES}

MD_EXTENSIONS = ["extra", "admonition", "toc", "sane_lists"]


# ---------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(f"[build] {msg}")


def read_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def excerpt(text: str, limit: int = 220) -> str:
    text = strip_tags(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "item"


def fmt_date(d: dt.date | dt.datetime | None, style: str = "long") -> str:
    if d is None:
        return ""
    if style == "iso":
        return d.strftime("%Y-%m-%d")
    if style == "short":
        return d.strftime("%b %d, %Y").replace(" 0", " ")
    return d.strftime("%B %d, %Y").replace(" 0", " ")


def fmt_duration(s: str | None) -> str:
    """'02:23:29' -> '2 hr 23 min'; '38:58' -> '38 min'."""
    if not s:
        return ""
    parts = [int(p) for p in s.split(":")]
    if len(parts) == 3:
        h, m, _ = parts
    elif len(parts) == 2:
        h, m = 0, parts[0]
    else:
        h, m = divmod(parts[0] // 60, 60)
    if h:
        return f"{h} hr {m} min"
    return f"{m} min"


def rfc2822(d: dt.datetime) -> str:
    return email.utils.format_datetime(d)


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Minimal 'key: value' front matter between --- fences. No YAML dependency."""
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    meta: dict = {}
    for line in fm.strip().splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if k == "tags":
            meta[k] = [t.strip() for t in v.split(",") if t.strip()]
        elif v.lower() in ("true", "false"):
            meta[k] = v.lower() == "true"
        else:
            meta[k] = v.strip('"').strip("'")
    return meta, body.lstrip("\n")


def md(text: str) -> str:
    return markdown.markdown(text, extensions=MD_EXTENSIONS, output_format="html5")


# ---------------------------------------------------------------- feed

def fetch_feed(url: str, cache: Path, offline: bool) -> str:
    if not offline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lastattempt.net build"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
            ET.fromstring(raw)  # validate before overwriting the cache
            cache.write_bytes(raw)
            log(f"fetched feed ({len(raw)} bytes)")
            return raw.decode("utf-8")
        except Exception as e:  # noqa: BLE001
            log(f"feed fetch failed ({e}); using cached copy")
    return cache.read_text(encoding="utf-8")


EP_NUM_RE = re.compile(r"(\d{3})\s*$")
SEP_RE = r"\s*[—–\-|:]\s*"


def clean_title(title: str, show_name: str) -> str:
    t = title.strip()
    t = re.sub(r"^" + re.escape(show_name) + SEP_RE, "", t, flags=re.I)
    t = re.sub(SEP_RE + r"\d{3}\s*$", "", t)
    return t.strip()


def parse_feed(xml_text: str, site: dict) -> tuple[dict, dict[str, dict]]:
    root = ET.fromstring(xml_text)
    ch = root.find("channel")
    img = ch.find("itunes:image", NS)
    show = {
        "title": ch.findtext("title", ""),
        "description": ch.findtext("description", ""),
        "image": img.get("href") if img is not None else "",
        "author": ch.findtext("itunes:author", "", NS),
        "link": ch.findtext("link", ""),
    }
    episodes: dict[str, dict] = {}
    for it in ch.findall("item"):
        title = it.findtext("title", "")
        m = EP_NUM_RE.search(title)
        if not m:
            log(f"skipping feed item without episode number: {title!r}")
            continue
        num = m.group(1)
        enc = it.find("enclosure")
        pub = it.findtext("pubDate")
        date = email.utils.parsedate_to_datetime(pub) if pub else None
        desc = it.findtext("description") or it.findtext("itunes:summary", "", NS) or ""
        episodes[num] = {
            "number": num,
            "feed_title": title,
            "headline": clean_title(title, site["show_name"]),
            "date": date,
            "duration": fmt_duration(it.findtext("itunes:duration", None, NS)),
            "description_html": desc,
            "summary": excerpt(desc, 260),
            "audio_url": enc.get("url") if enc is not None else "",
            "audio_type": enc.get("type", "audio/mpeg") if enc is not None else "",
            "spotify_url": it.findtext("link", ""),
            "guid": it.findtext("guid", ""),
        }
    return show, episodes


# ---------------------------------------------------------------- content

def load_notes() -> dict[str, dict]:
    notes: dict[str, dict] = {}
    for p in sorted((CONTENT / "episodes").glob("notes_*.json")):
        d = read_json(p)
        num = str(d.get("episode", p.stem.split("_")[-1])).zfill(3)
        items = []
        for it in d.get("items", []):
            points = []
            for pt in it.get("points", []):
                if isinstance(pt, dict):
                    points.append({"text": pt.get("text", ""), "sub": pt.get("sub", "")})
                else:
                    points.append({"text": pt, "sub": ""})
            items.append({
                "title": it.get("title", ""),
                "tab": it.get("tab", ""),
                "category": it.get("category", ""),
                "synopsis": it.get("synopsis", ""),
                "points": points,
                "slug": slugify(it.get("title", "")),
            })
        notes[num] = {
            "number": num,
            "date": dt.datetime.strptime(d["date"], "%Y-%m-%d") if d.get("date") else None,
            "subtitle": d.get("subtitle", ""),
            "heads_up": d.get("intro", {}).get("heads_up", ""),
            "rundown": d.get("intro", {}).get("rundown", []),
            "segments": items,
        }
    return notes


def merge_episodes(feed_eps: dict[str, dict], notes: dict[str, dict]) -> list[dict]:
    nums = sorted(set(feed_eps) | set(notes), key=int, reverse=True)
    out = []
    for n in nums:
        f = feed_eps.get(n)
        nt = notes.get(n)
        ep = {
            "number": n,
            "url": f"/episodes/{n}/",
            "published": f is not None,
            "headline": (f or {}).get("headline") or (nt or {}).get("subtitle") or f"Episode {n}",
            "date": (f or {}).get("date") or (nt or {}).get("date"),
            "duration": (f or {}).get("duration", ""),
            "description_html": (f or {}).get("description_html", ""),
            "summary": (f or {}).get("summary", ""),
            "audio_url": (f or {}).get("audio_url", ""),
            "audio_type": (f or {}).get("audio_type", ""),
            "spotify_url": (f or {}).get("spotify_url", ""),
            "notes": nt,
        }
        if not ep["summary"] and nt and nt["rundown"]:
            ep["summary"] = "This week: " + "; ".join(nt["rundown"][:3]) + "."
        # Topic chips: notes items if we have them, else the "Topics:" list Spotify descriptions carry.
        topics = [it["title"] for it in nt["segments"]] if nt else []
        if not topics and f:
            m = re.search(r"Topics:(.*?)(?:<p>_{3,}|$)", f["description_html"], flags=re.S)
            if m:
                topics = [t for t in (strip_tags(x) for x in re.split(r"</p>", m.group(1))) if t and t not in ("Topics:",)]
                topics = [re.sub(r"^[•\-–—]\s*", "", t) for t in topics]
        ep["topics"] = topics
        out.append(ep)
    return out


def load_articles(include_drafts: bool) -> list[dict]:
    arts = []
    for p in sorted((CONTENT / "articles").glob("*.md")):
        meta, body = parse_front_matter(p.read_text(encoding="utf-8"))
        if meta.get("draft") and not include_drafts:
            continue
        if "title" not in meta or "date" not in meta:
            log(f"article {p.name} missing title/date; skipped")
            continue
        slug = meta.get("slug") or p.stem
        body_html = md(body)
        arts.append({
            **meta,
            "slug": slug,
            "url": f"/articles/{slug}/",
            "date": dt.datetime.strptime(meta["date"], "%Y-%m-%d"),
            "author": meta.get("author", "Squirrelthug"),
            "summary": meta.get("summary") or excerpt(body_html, 200),
            "tags": meta.get("tags", []),
            "hero": meta.get("hero", ""),
            "hero_credit": meta.get("hero_credit", ""),
            "hero_alt": meta.get("hero_alt", meta.get("title", "")),
            "body_html": body_html,
            "reading_time": max(1, round(len(strip_tags(body_html).split()) / 230)),
            "draft": bool(meta.get("draft")),
        })
    arts.sort(key=lambda a: a["date"], reverse=True)
    return arts


def load_pages() -> dict[str, dict]:
    pages = {}
    for p in sorted((CONTENT / "pages").glob("*.md")):
        meta, body = parse_front_matter(p.read_text(encoding="utf-8"))
        pages[p.stem] = {**meta, "slug": p.stem, "body_html": md(body)}
    return pages


# ---------------------------------------------------------------- guilds

RAIDERIO = "https://raider.io/api/v1"
MIDNIGHT_EXPANSION_ID = 11


def _get_json(url: str, cache: Path, offline: bool):
    """Fetch JSON with a committed cache, same contract as the podcast feed."""
    if not offline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lastattempt.net build"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
            data = json.loads(raw)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data, indent=1), encoding="utf-8")
            return data
        except Exception as e:  # noqa: BLE001
            log(f"fetch failed for {url} ({e}); using cache")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    return None


def load_raid_names(offline: bool) -> dict[str, dict]:
    data = _get_json(f"{RAIDERIO}/raiding/static-data?expansion_id={MIDNIGHT_EXPANSION_ID}",
                     DATA / "raids.json", offline) or {}
    out = {}
    for i, r in enumerate(data.get("raids", [])):
        name = r["name"].replace("MN Tier 1", "Midnight Tier 1")
        out[r["slug"]] = {"name": name, "order": i, "bosses": len(r.get("encounters", []))}
    return out


def load_guilds(offline: bool, raids: dict[str, dict]) -> list[dict]:
    guilds = []
    for p in sorted((CONTENT / "guilds").glob("*.md")):
        meta, body = parse_front_matter(p.read_text(encoding="utf-8"))
        slug = meta.get("slug") or p.stem
        q = urllib.parse.urlencode({"region": meta["region"], "realm": meta["realm"], "name": meta["name"],
                                    "fields": "raid_progression,raid_rankings,members"})
        prof = _get_json(f"{RAIDERIO}/guilds/profile?{q}", DATA / "guilds" / f"{slug}.json", offline) or {}
        progression = []
        for raid_slug, prog in (prof.get("raid_progression") or {}).items():
            rank = (prof.get("raid_rankings") or {}).get(raid_slug, {})
            # Best difficulty reached, and its ranks.
            if prog.get("mythic_bosses_killed"):
                diff = "mythic"
            elif prog.get("heroic_bosses_killed"):
                diff = "heroic"
            else:
                diff = "normal"
            info = raids.get(raid_slug, {"name": raid_slug.replace("-", " ").title(), "order": 99})
            progression.append({
                "slug": raid_slug,
                "name": info["name"],
                "order": info["order"],
                "summary": prog.get("summary", ""),
                "total": prog.get("total_bosses", 0),
                "normal": prog.get("normal_bosses_killed", 0),
                "heroic": prog.get("heroic_bosses_killed", 0),
                "mythic": prog.get("mythic_bosses_killed", 0),
                "difficulty": diff,
                "world": rank.get(diff, {}).get("world", 0),
                "region_rank": rank.get(diff, {}).get("region", 0),
                "realm_rank": rank.get(diff, {}).get("realm", 0),
            })
        progression.sort(key=lambda r: r["order"], reverse=True)  # newest tier first
        members = prof.get("members") or []
        crawled = prof.get("last_crawled_at")
        links = [(k, meta[k]) for k in ("website", "discord", "twitch", "youtube", "x", "raiderio",
                                        "wowprogress", "warcraftlogs", "guildsofwow", "armory") if meta.get(k)]
        labels = {"website": "Website", "discord": "Discord", "twitch": "Twitch", "youtube": "YouTube", "x": "X",
                  "raiderio": "Raider.IO", "wowprogress": "WoWProgress", "warcraftlogs": "Warcraft Logs",
                  "guildsofwow": "Guilds of WoW", "armory": "Armory"}
        guilds.append({
            **meta,
            "slug": slug,
            "url": f"/guilds/{slug}/",
            "order": int(meta.get("order", 99)),
            "body_html": md(body),
            "progression": progression,
            "current": progression[0] if progression else None,
            "member_count": len(members),
            "faction": prof.get("faction", meta.get("faction", "")).title(),
            "realm": prof.get("realm", meta.get("realm")),
            "profile_url": prof.get("profile_url", meta.get("raiderio", "")),
            "crawled": dt.datetime.fromisoformat(crawled.replace("Z", "+00:00")) if crawled else None,
            "links": [{"key": k, "label": labels[k], "url": u} for k, u in links],
        })
    guilds.sort(key=lambda g: g["order"])
    return guilds


# ---------------------------------------------------------------- render

def make_env(site: dict) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["date"] = fmt_date
    env.filters["excerpt"] = excerpt
    env.globals["site"] = site
    env.globals["now"] = dt.datetime.now(dt.timezone.utc)
    return env


def write(path: str, content: str) -> None:
    """path is a site-relative URL path like /articles/foo/ or /feed.xml."""
    if path.endswith("/"):
        out = DIST / path.strip("/") / "index.html"
    else:
        out = DIST / path.strip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")


def build(offline: bool, drafts: bool) -> None:
    site = read_json(ROOT / "site.json")
    site["socials"] = [s for s in site.get("socials", []) if s.get("url")]
    cast = read_json(CONTENT / "cast.json") if (CONTENT / "cast.json").exists() else {"people": []}

    feed_text = fetch_feed(site["feed_url"], DATA / "feed.xml", offline)
    show, feed_eps = parse_feed(feed_text, site)
    notes = load_notes()
    episodes = merge_episodes(feed_eps, notes)
    articles = load_articles(drafts)
    pages = load_pages()
    raids = load_raid_names(offline)
    guilds = load_guilds(offline, raids)

    published = [e for e in episodes if e["published"]]
    stats = {
        "episode_count": len(published),
        "first_episode_date": min((e["date"] for e in published), default=None),
        "latest_episode_date": max((e["date"] for e in published), default=None),
        "article_count": len(articles),
        "guild_count": len(guilds),
    }
    latest = episodes[0] if episodes else None
    latest_with_notes = next((e for e in episodes if e["notes"]), None)

    # Clear dist's contents rather than the folder itself: a local dev server may hold it open.
    DIST.mkdir(exist_ok=True)
    for child in DIST.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    shutil.copytree(STATIC, DIST, dirs_exist_ok=True)

    env = make_env(site)
    ctx = {"show": show, "stats": stats, "cast": cast, "guilds": guilds}

    def render(template: str, path: str, **kw) -> None:
        tpl = env.get_template(template)
        write(path, tpl.render(**ctx, path=path, **kw))

    render("home.html", "/", articles=articles[:8], latest=latest, latest_with_notes=latest_with_notes,
           recent=[e for e in episodes if e["published"]][:6])
    render("articles.html", "/articles/", articles=articles)
    for a in articles:
        render("article.html", a["url"], article=a)
    render("episodes.html", "/episodes/", episodes=episodes)
    for e in episodes:
        render("episode.html", e["url"], episode=e)
    render("listen.html", "/listen/", latest=latest)
    render("guilds.html", "/guilds/")
    for g in guilds:
        render("guild.html", g["url"], guild=g)
    render("press.html", "/press/")
    render("contact.html", "/contact/")
    render("cast.html", "/cast/")
    for slug, page in pages.items():
        render("page.html", f"/{slug}/", page=page)
    render("404.html", "/404.html")

    # Article RSS feed
    render("feed.xml", "/feed.xml", articles=articles[:20], rfc2822=rfc2822)
    # Sitemap
    urls = ["/", "/articles/", "/episodes/", "/guilds/", "/listen/", "/press/", "/contact/", "/cast/"]
    urls += [f"/{s}/" for s in pages] + [a["url"] for a in articles] + [e["url"] for e in episodes]
    urls += [g["url"] for g in guilds]
    render("sitemap.xml", "/sitemap.xml", urls=urls)

    log(f"built {len(articles)} articles, {len(episodes)} episodes ({stats['episode_count']} published), "
        f"{len(pages)} pages, {len(guilds)} guilds -> {DIST}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--drafts", action="store_true")
    args = ap.parse_args()
    try:
        build(args.offline, args.drafts)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
