"""Remove dashes used as sentence punctuation. The site's author never writes with them.

    python tools/dedash.py                 # rewrite every file under content/ in place
    python tools/dedash.py path [...]      # rewrite specific files (.md / .json / .html)
    python tools/dedash.py --check dist    # report anything left in built output

build.py runs dedash() over every rendered page, so text from the podcast feed and Raider.IO
is covered too; import_notes.py runs it over each notes file it brings in. This file is the
one place the rules live.

Rules, in order:
  - en dash between two words/numbers with no spaces: a range ("1–60" -> "1 to 60",
    "Tuesday–Thursday" -> "Tuesday to Thursday") or a compound modifier when the right side
    is lowercase ("Cutting Edge–focused" -> "Cutting Edge focused")
  - a pair of dashes setting off an aside inside one sentence -> commas
  - a single dash followed by a joining word (and, but, which, especially ...) -> comma
  - a single dash opening a question (is, does, what ...?) -> full stop, capitalised
  - any other single dash -> colon, or comma if the sentence already has a colon
  - a dash that opens or closes a line is dropped
A spaced hyphen used as a dash (" - ") is treated the same way.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DASHES = "—–"
DASH_RE = re.compile(r"[ \t]*[—–][ \t]*|(?<=\S) - (?=\S)")
RANGE_RE = re.compile(r"(?<=\w)–(?=\w)")
SENT_END_RE = re.compile(r"[.!?][\"'”’)\]]*(?=\s|$)|\n")
WORD_RE = re.compile(r"[\"'“‘(]*([\w'’]+)")

# The clause after the dash continues the sentence: a comma reads right.
COMMA_WORDS = {
    "and", "but", "or", "nor", "so", "yet", "which", "who", "whose", "whom", "where", "when",
    "while", "though", "although", "even", "especially", "particularly", "mostly", "mainly",
    "largely", "partly", "not", "plus", "meaning", "because", "as", "if", "unless", "at", "in",
    "with", "without", "from", "for", "to", "on", "by", "after", "before", "until", "like",
    "unlike", "including", "then", "just", "still", "either", "whether", "along", "rather",
    "presumably", "apparently", "arguably", "roughly", "about", "more", "less", "again", "too",
    "also", "given", "provided", "assuming", "perhaps", "maybe", "probably", "likely", "ideally",
    "hopefully", "basically", "essentially", "specifically", "namely", "i.e", "e.g", "except",
    "than", "once", "since", "thanks", "courtesy", "via", "per", "minus", "down", "up", "out",
    "over", "under", "through", "across", "toward", "towards", "into", "onto", "off", "of",
    "hence", "thus", "otherwise", "instead", "regardless", "whatever", "whichever", "however",
    "worth", "enough", "much", "very", "far", "way", "almost", "nearly", "only", "ever", "never",
    "always", "usually", "often", "sometimes", "now", "already", "yes", "no", "sort", "kind",
    "something", "someone", "somewhere", "anything", "anyone", "nothing", "none", "neither",
    "both", "each", "every", "all", "any", "some", "most", "many", "few", "several", "half",
}
# The clause after the dash is a question: start a new sentence.
QUESTION_WORDS = {
    "is", "are", "was", "were", "do", "does", "did", "will", "would", "should", "can", "could",
    "has", "have", "had", "how", "what", "why", "when", "who", "which", "where", "isn't",
    "aren't", "doesn't", "don't", "didn't", "won't", "wouldn't", "shouldn't", "can't",
    "couldn't", "hasn't", "haven't", "or",
}


def _capitalize(s: str) -> str:
    m = WORD_RE.match(s)
    if not m:
        return s
    i = m.start(1)
    return s[:i] + s[i].upper() + s[i + 1:]


def _range(m: re.Match) -> str:
    nxt = m.string[m.end()]
    if nxt.islower():
        return " "
    return " and " if re.search(r"between \w+$", m.string[:m.start()]) else " to "


def dedash(text: str) -> str:
    if not text or not (any(d in text for d in DASHES) or " - " in text):
        return text
    text = RANGE_RE.sub(_range, text)
    matches = list(DASH_RE.finditer(text))
    if not matches:
        return text
    out: list[str] = []
    pos = 0
    i = 0
    while i < len(matches):
        m = matches[i]
        before = text[pos:m.start()]
        full_before = text[:m.start()]
        after = text[m.end():]
        line_before = full_before.rsplit("\n", 1)[-1]
        out.append(before)
        pos = m.end()

        # Dash opening a line, or closing one: drop it.
        if not line_before.strip() or not after or after[0] in ",.;:!?)\n" or after.startswith("</"):
            i += 1
            continue

        # Paired dashes inside one sentence: an aside. Commas on both sides.
        if i + 1 < len(matches):
            between = text[m.end():matches[i + 1].start()]
            after2 = text[matches[i + 1].end():]
            same_kind = (m.group(0).strip() in DASHES) == (matches[i + 1].group(0).strip() in DASHES)
            # The sentence has to carry on after the aside (lowercase), otherwise
            # "Source — Title — Subtitle" style labels would be read as an aside.
            continues = bool(after2) and (after2[0].islower() or after2[0] in ",.;:!?")
            if same_kind and continues and 0 < len(between) < 200 and not SENT_END_RE.search(between):
                out.append(" " if line_before.rstrip().endswith((",", ";", ":")) else ", ")
                out.append(between)
                out.append(after2[0] in ",.;:!?" and "" or ", ")
                pos = matches[i + 1].end()
                i += 2
                continue

        wm = WORD_RE.match(after)
        word = re.sub(r"['’]s$", "", wm.group(1).lower()) if wm else ""
        clause = SENT_END_RE.split(after, 1)[0]
        clause_end = SENT_END_RE.search(after)
        ends_question = bool(clause_end and clause_end.group(0).startswith("?"))
        sent_starts = [s.end() for s in SENT_END_RE.finditer(full_before)]
        sentence_before = full_before[sent_starts[-1]:] if sent_starts else full_before

        if line_before.rstrip().endswith((",", ";", ":")):
            rep = " "
        elif word in COMMA_WORDS:
            rep = ", "
        elif word in QUESTION_WORDS and ends_question:
            rep = ". "
            after = _capitalize(after)
            text = text[:m.end()] + after
            # positions of later matches are unchanged: capitalising swaps one character
        elif ":" in sentence_before or ":" in clause:
            rep = ", "
        else:
            rep = ": "
        out.append(rep)
        i += 1
    out.append(text[pos:])
    return "".join(out)


def dedash_obj(obj):
    """Apply dedash to every string inside parsed JSON."""
    if isinstance(obj, str):
        return dedash(obj)
    if isinstance(obj, list):
        return [dedash_obj(v) for v in obj]
    if isinstance(obj, dict):
        return {k: dedash_obj(v) for k, v in obj.items()}
    return obj


def rewrite_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(raw)
        fixed = dedash_obj(data)
        if fixed == data:
            return False
        second_line = raw.split("\n", 1)[1]
        indent = len(second_line) - len(second_line.lstrip(" ")) or 2
        new = json.dumps(fixed, indent=indent, ensure_ascii=False) + ("\n" if raw.endswith("\n") else "")
    else:
        new = dedash(raw)
        if new == raw:
            return False
    path.write_text(new, encoding="utf-8", newline="\n")
    return True


def find_dashes(root: Path) -> list[tuple[Path, int, str]]:
    hits = []
    for p in sorted(root.rglob("*")):
        if p.suffix not in (".html", ".xml", ".md", ".json", ".txt"):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if any(d in line for d in DASHES) or re.search(r"\S - \S", line):
                hits.append((p, n, line.strip()))
    return hits


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    if argv and argv[0] == "--check":
        target = Path(argv[1]) if len(argv) > 1 else root / "dist"
        hits = find_dashes(target)
        for p, n, line in hits:
            print(f"{p.relative_to(target)}:{n}: {line[:120]}")
        print(f"{len(hits)} line(s) with dashes under {target}")
        return 1 if hits else 0
    paths = [Path(a) for a in argv] or [p for p in (root / "content").rglob("*") if p.suffix in (".md", ".json")]
    changed = [p for p in paths if rewrite_file(p)]
    for p in changed:
        print(f"rewrote {p}")
    print(f"{len(changed)} file(s) changed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
