"""HTML-Aufbereitung und Extraktion einzelner Paragraphen/Artikel."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

BLOCK_TAGS = [
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd", "td", "th",
    "div", "section", "article", "blockquote", "pre",
]
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
HEADING_CLASS_HINT = re.compile(r"(heading|ueberschrift|überschrift|titel|title|num|bezeichnung)", re.I)
NORM_HEAD = re.compile(r"^\s*(§|Art\.?|Artikel)\s*(\d+[a-z]?)(?=[\s.,;:]|$)")
ABSATZ_HEAD = re.compile(r"^\s*\((\d+[a-z]?)\)")


def _norm_nr(nr: str) -> str:
    return re.sub(r"\s+", "", str(nr)).lower().lstrip("§").replace("art.", "").replace("artikel", "")


def blocks(html: str) -> list[tuple[str, str, str]]:
    """Liefert (tag, class, text) je Blockelement ohne Block-Nachfahren, in Dokumentreihenfolge."""
    soup = BeautifulSoup(html, "lxml")
    for bad in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        bad.decompose()
    out: list[tuple[str, str, str]] = []
    for el in soup.find_all(BLOCK_TAGS):
        if not isinstance(el, Tag):
            continue
        if el.find(BLOCK_TAGS):
            continue
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if text:
            cls = " ".join(el.get("class", []) or [])
            out.append((el.name, cls, text))
    return out


def html_to_text(html: str) -> str:
    return "\n".join(t for _, _, t in blocks(html))


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n[… gekürzt]", True
    return text, False


def _is_heading(tag: str, cls: str, text: str, strict: bool) -> re.Match | None:
    m = NORM_HEAD.match(text)
    if not m:
        return None
    if strict:
        return m if (tag in HEADING_TAGS or HEADING_CLASS_HINT.search(cls or "")) else None
    return m if len(text) <= 140 else None


def extract_norm(html: str, nr: str, absatz: str | None = None) -> str | None:
    """Extrahiert § bzw. Art. <nr> (optional nur Absatz <absatz>) aus dem Gesetzes-HTML.

    Mehrere Fundstellen (z.B. Inhaltsübersicht und Normtext) werden verglichen;
    zurückgegeben wird die inhaltsreichste.
    """
    target = _norm_nr(nr)
    bl = blocks(html)
    if not bl:
        return None

    strict = any(_is_heading(t, c, x, strict=True) for t, c, x in bl)
    heads = [
        (i, _norm_nr(m.group(2)))
        for i, (t, c, x) in enumerate(bl)
        if (m := _is_heading(t, c, x, strict))
    ]
    candidates: list[list[str]] = []
    for idx, (i, num) in enumerate(heads):
        if num != target:
            continue
        end = len(bl)
        for j, other in heads[idx + 1:]:
            if other != target:
                end = j
                break
        candidates.append([x for _, _, x in bl[i:end]])
    if not candidates:
        return None
    best = max(candidates, key=lambda c: sum(len(x) for x in c))

    if absatz:
        want = _norm_nr(absatz)
        start = None
        for k, line in enumerate(best):
            m = ABSATZ_HEAD.match(line)
            if m and m.group(1).lower() == want:
                start = k
                break
        if start is None:
            return None
        sub = [best[start]]
        for line in best[start + 1:]:
            if ABSATZ_HEAD.match(line):
                break
            sub.append(line)
        return "\n".join([best[0]] + sub) if start != 0 else "\n".join(sub)

    return "\n".join(best)
