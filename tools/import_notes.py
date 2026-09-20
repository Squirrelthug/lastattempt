"""Bring an episode's show notes into content/episodes/notes_NNN.json.

    python tools/import_notes.py 033        # one episode
    python tools/import_notes.py            # every episode folder under LAVods

Two sources, same output shape:

  1. NNN/docs/notes_NNN.json  (episodes 032+, written by the notes pipeline) — copied as-is.
  2. NNN/docs/episode-notes_YYYY-MM-DD.html  (episodes 005–031, the old printed-notes page) —
     parsed into the JSON shape. Blue "News Item" cards become segments; gold (intro, roundtable,
     recruitment), purple (guild raiding) and green (outro) cards are skipped. The intro card's
     "Today we've got" list becomes the rundown.

Then: python build.py, commit, push.
"""
from __future__ import annotations

import glob
import html
import json
import re
import shutil
import sys
from pathlib import Path

VODS = Path("G:/My Drive/LAVods")
DEST = Path(__file__).resolve().parents[1] / "content" / "episodes"

SKIP_CARDS = {"card-gold", "card-purple", "card-green"}
SKIP_HEADS = re.compile(r"intro script|roundtable|recruitment|outro|support|socials|this week.s progress|raiding discussion", re.I)
CARD_RE = re.compile(r'<div class="card (card-[\w-]+)"[^>]*>(.*?)(?=<div class="card |<div class="spacer"|</body>)', re.S)
HEAD_RE = re.compile(r'<div class="card-head">(.*?)</div>', re.S)
LINE_RE = re.compile(r'<div class="(n li|n|sub|q)">(.*?)</div>|<a class="source-link" href="([^"]+)"[^>]*>(.*?)</a>', re.S)
TITLE_PREFIX_RE = re.compile(r"^(?:news(?:\s+item)?\s*\d*)\s*[—–\-:]\s*", re.I)


def text(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def is_bold_lede(raw: str) -> bool:
    t = raw.strip()
    return t.startswith("<b>") and t.endswith("</b>") and t.count("<b>") == 1


def parse_card(body: str) -> dict:
    synopsis, points, questions, sources = "", [], [], []
    seen_lede = False
    for m in LINE_RE.finditer(body):
        cls, raw, href, label = m.groups()
        if href:
            sources.append({"label": text(label), "url": html.unescape(href)})
            continue
        t = text(raw)
        if not t:
            continue
        if cls == "q":
            questions.append(t)
        elif cls == "sub":
            if points:
                points[-1]["sub"] = (points[-1]["sub"] + " " if points[-1]["sub"] else "") + t
        elif t.lower().startswith("source:"):
            sources.append({"label": t[7:].strip(), "url": ""})
        elif not seen_lede and (cls == "n" and is_bold_lede(raw) or not synopsis and cls == "n"):
            synopsis = t
            seen_lede = True
        else:
            points.append({"text": t, "sub": ""})
    return {"synopsis": synopsis, "points": points, "questions": questions, "sources": sources}


def parse_intro(body: str) -> list[str]:
    lines = [text(m.group(2)) for m in LINE_RE.finditer(body) if m.group(2) is not None]
    for i, l in enumerate(lines):
        if re.search(r"today we.?ve got|on the show today|today we have", l, re.I):
            return [x for x in lines[i + 1:] if x]
    return []


def convert_html(path: Path, ep: str) -> dict:
    s = path.read_text(encoding="utf-8", errors="replace")
    date = re.search(r"episode-notes_(\d{4}-\d{2}-\d{2})", path.name).group(1)
    items, rundown = [], []
    for cls, body in CARD_RE.findall(s):
        hm = HEAD_RE.search(body)
        head = text(hm.group(1)) if hm else ""
        if cls in SKIP_CARDS or SKIP_HEADS.search(head):
            if re.search(r"intro", head, re.I):
                rundown = parse_intro(body)
            continue
        title = TITLE_PREFIX_RE.sub("", head).strip() or head
        card = parse_card(body)
        if not (card["synopsis"] or card["points"]):
            continue
        items.append({
            "title": title,
            "tab": "",
            "category": "News" if cls == "card-blue" else "Preview",
            **card,
            "media": [],
        })
    return {
        "episode": ep,
        "date": date,
        "subtitle": "",
        "source": "legacy-html",
        "intro": {"heads_up": "", "rundown": rundown},
        "items": items,
    }


def import_episode(n: str) -> str:
    ep = n.zfill(3)
    src_json = VODS / ep / "docs" / f"notes_{ep}.json"
    if src_json.exists():
        shutil.copy2(src_json, DEST / src_json.name)
        return f"{ep}: copied notes_{ep}.json"
    htmls = sorted(glob.glob(str(VODS / ep / "docs" / "episode-notes_*.html")))
    if htmls:
        data = convert_html(Path(htmls[0]), ep)
        (DEST / f"notes_{ep}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return f"{ep}: converted {Path(htmls[0]).name} -> {len(data['items'])} segments, {len(data['intro']['rundown'])} rundown lines"
    return f"{ep}: nothing to import"


if __name__ == "__main__":
    nums = sys.argv[1:] or sorted(p.name for p in VODS.iterdir() if p.name.isdigit())
    DEST.mkdir(parents=True, exist_ok=True)
    for n in nums:
        print(import_episode(n))
