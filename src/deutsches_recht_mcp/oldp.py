"""Adapter für Open Legal Data (de.openlegaldata.io).

Gerichtsentscheidungen aller Instanzen (unvollständig) und Normen mit Zitationsgraph.
API: REST, öffentlich lesbar; optionaler Token (OLDP_API_TOKEN).
"""

from __future__ import annotations

import re
from typing import Any

from .http import ApiClient

QUELLE = "Open Legal Data (de.openlegaldata.io)"
WEB_BASE = "https://de.openlegaldata.io"


def _results(raw: Any) -> tuple[int | None, list[dict]]:
    if isinstance(raw, dict):
        return raw.get("count"), [r for r in raw.get("results", []) if isinstance(r, dict)]
    if isinstance(raw, list):
        return len(raw), [r for r in raw if isinstance(r, dict)]
    return None, []


def _court(c: Any) -> str | None:
    if isinstance(c, dict):
        return c.get("name") or c.get("code") or c.get("slug")
    return c if isinstance(c, str) else None


def _snips(h: dict) -> str | None:
    s = h.get("snippets") or h.get("snippet")
    if isinstance(s, list):
        s = " … ".join(str(x) for x in s[:2])
    if isinstance(s, str):
        return re.sub(r"<[^>]+>", "", s).strip() or None
    return None


def _sec(value: Any) -> str:
    return re.sub(r"[\s§]|art\.?|artikel", "", str(value or ""), flags=re.I).lower()


class OldpClient:
    def __init__(self, api: ApiClient) -> None:
        self.api = api

    # ---------- Entscheidungen ----------
    def normalize_case(self, h: dict) -> dict:
        cid = h.get("id")
        slug = h.get("slug")
        return {
            "id": f"oldp:{cid}" if cid is not None else None,
            "quelle": QUELLE,
            "gericht": _court(h.get("court")),
            "datum": h.get("date"),
            "aktenzeichen": h.get("file_number"),
            "ecli": h.get("ecli") or None,
            "typ": h.get("type") or h.get("decision_type"),
            "treffer": _snips(h),
            "url": f"{WEB_BASE}/case/{slug}" if slug else self.api.url(f"cases/{cid}/"),
        }

    async def search_cases(
        self,
        text: str,
        court: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        size: int = 10,
    ) -> tuple[int | None, list[dict]]:
        raw = await self.api.get_json(
            "cases/search/",
            {
                "text": text,
                "page": 1,
                "page_size": size,
                "court": court,
                "start_date": date_from,
                "end_date": date_to,
            },
        )
        return _results(raw)

    async def get_case(self, case_id: int) -> dict:
        return await self.api.get_json(f"cases/{int(case_id)}/")

    async def citing_cases(self, case_id: int, size: int = 20) -> tuple[int | None, list[dict]]:
        return _results(await self.api.get_json(f"cases/{int(case_id)}/citing_cases/", {"page_size": size}))

    async def references(self, case_id: int) -> dict:
        raw = await self.api.get_json(f"cases/{int(case_id)}/references/")
        return raw if isinstance(raw, dict) else {"results": raw}

    # ---------- Normen ----------
    def normalize_law(self, h: dict) -> dict:
        return {
            "id": f"oldp-norm:{h.get('id')}" if h.get("id") is not None else None,
            "quelle": QUELLE,
            "gesetz": h.get("book_code") or (h["book"].get("code") if isinstance(h.get("book"), dict) else None),
            "norm": h.get("section"),
            "titel": h.get("title"),
            "treffer": _snips(h),
        }

    async def search_laws(self, text: str, size: int = 10) -> tuple[int | None, list[dict]]:
        return _results(await self.api.get_json("laws/search/", {"text": text, "page_size": size}))

    async def find_law(self, book_code: str, nr: str) -> dict | None:
        """Findet die OLDP-Norm-ID zu z.B. ('InsO', '26')."""
        want_book, want_sec = book_code.strip().lower(), _sec(nr)
        for query in (f"§ {nr} {book_code}", f"{book_code} {nr}"):
            _, hits = await self.search_laws(query, size=25)
            for h in hits:
                book = self.normalize_law(h)["gesetz"]
                if str(book or "").lower() == want_book and _sec(h.get("section")) == want_sec:
                    return h
        return None

    async def law_citing_cases(self, law_id: int, size: int = 20) -> tuple[int | None, list[dict]]:
        return _results(await self.api.get_json(f"laws/{int(law_id)}/citing_cases/", {"page_size": size}))
