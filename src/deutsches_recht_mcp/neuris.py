"""Adapter für NeuRIS (rechtsinformationen.bund.de, Testphase).

Bundesgesetze/-verordnungen und Rechtsprechung der obersten Bundesgerichte.
API: keylos, öffentlich. Datenmodell FRBR/ELI. Antworten: {"member": [{"item": {...}, "textMatches": [...]}]}.
"""

from __future__ import annotations

from typing import Any, Iterator

from .http import ApiClient, QuelleNichtErreichbar

QUELLE = "NeuRIS (rechtsinformationen.bund.de, Testphase)"


def _members(raw: Any) -> tuple[int | None, list[dict]]:
    if isinstance(raw, dict):
        members = raw.get("member") or raw.get("items") or []
        total = raw.get("totalItems")
    elif isinstance(raw, list):
        members, total = raw, None
    else:
        return None, []
    out = []
    for m in members:
        if isinstance(m, dict) and isinstance(m.get("item"), dict):
            item = dict(m["item"])
            item["_textMatches"] = m.get("textMatches") or []
            out.append(item)
        elif isinstance(m, dict):
            out.append(m)
    return total, out


def _walk(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def find_content_url(obj: Any, fmt: str = "html") -> str | None:
    """Sucht rekursiv eine Manifestation (contentUrl) im gewünschten Format."""
    fallback = None
    for d in _walk(obj):
        url = d.get("contentUrl")
        if not isinstance(url, str):
            continue
        enc = str(d.get("encodingFormat", "")).lower()
        if url.lower().endswith(f".{fmt}") or fmt in enc:
            return url
        if fallback is None and fmt == "html" and not url.lower().endswith((".xml", ".zip")):
            fallback = url
    return fallback


def _snippet(item: dict) -> str | None:
    tm = item.get("_textMatches") or []
    texts = [t.get("text") for t in tm if isinstance(t, dict) and t.get("text")]
    return " … ".join(texts[:2]) if texts else None


def _eli(item: dict) -> str | None:
    we = item.get("workExample") if isinstance(item.get("workExample"), dict) else {}
    return we.get("legislationIdentifier") or item.get("legislationIdentifier") or item.get("eli")


class NeurisClient:
    def __init__(self, api: ApiClient) -> None:
        self.api = api

    # ---------- Gesetze ----------
    async def search_legislation(self, term: str, size: int = 10, page: int = 0) -> tuple[int | None, list[dict]]:
        raw = await self.api.get_json(
            "/v1/legislation", {"searchTerm": term, "size": size, "pageIndex": page}
        )
        return _members(raw)

    def normalize_legislation(self, item: dict) -> dict:
        html = find_content_url(item, "html")
        return {
            "quelle": QUELLE,
            "titel": item.get("name") or item.get("headline"),
            "kurztitel": item.get("alternateName"),
            "abkuerzung": item.get("abbreviation"),
            "eli": _eli(item),
            "in_kraft": item.get("inForce"),
            "ausfertigungsdatum": item.get("legislationDate"),
            "geltungszeitraum": item.get("temporalCoverage"),
            "url": self.api.url(html) if html else self.api.url(item.get("@id", "")) if item.get("@id") else None,
            "treffer": _snippet(item),
        }

    async def find_act(self, abbreviation: str) -> dict | None:
        """Findet die aktuell geltende Fassung eines Gesetzes anhand der amtlichen Abkürzung."""
        want = abbreviation.strip().lower()
        _, items = await self.search_legislation(abbreviation, size=50)
        exact = [i for i in items if str(i.get("abbreviation", "")).strip().lower() == want]
        if not exact:
            exact = [
                i for i in items
                if want in str(i.get("alternateName", "")).lower() or want == str(i.get("name", "")).lower()
            ]
        if not exact:
            return None

        def rank(i: dict) -> tuple:
            in_force = i.get("inForce")
            return (
                1 if in_force is True else 0 if in_force is None else -1,
                str(i.get("temporalCoverage") or ""),
                str(_eli(i) or ""),
            )

        return sorted(exact, key=rank, reverse=True)[0]

    async def law_html(self, item: dict) -> tuple[str, str]:
        url = find_content_url(item, "html")
        if not url and item.get("@id"):
            meta = await self.api.get_json(item["@id"])
            url = find_content_url(meta, "html")
        if not url:
            raise QuelleNichtErreichbar("NeuRIS: keine HTML-Fassung für dieses Gesetz gefunden")
        return await self.api.get_text(url), self.api.url(url)

    # ---------- Rechtsprechung ----------
    async def search_case_law(
        self,
        term: str,
        court: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        size: int = 10,
    ) -> tuple[int | None, list[dict]]:
        raw = await self.api.get_json(
            "/v1/case-law",
            {"searchTerm": term, "court": court, "dateFrom": date_from, "dateTo": date_to, "size": size},
        )
        return _members(raw)

    def normalize_case(self, item: dict) -> dict:
        doc = item.get("documentNumber")
        return {
            "id": f"neuris:{doc}" if doc else None,
            "quelle": QUELLE,
            "gericht": item.get("courtName") or item.get("courtType"),
            "spruchkoerper": item.get("judicialBody"),
            "datum": item.get("decisionDate"),
            "aktenzeichen": ", ".join(item.get("fileNumbers") or []) or None,
            "ecli": item.get("ecli"),
            "typ": item.get("documentType"),
            "titel": item.get("headline"),
            "treffer": _snippet(item),
            "url": self.api.url(f"/v1/case-law/{doc}.html") if doc else None,
        }

    async def get_case(self, document_number: str) -> tuple[dict, str | None, str | None]:
        meta = await self.api.get_json(f"/v1/case-law/{document_number}")
        url = find_content_url(meta, "html") or f"/v1/case-law/{document_number}.html"
        try:
            html = await self.api.get_text(url)
        except QuelleNichtErreichbar:
            html = None
        return meta, html, self.api.url(url)
