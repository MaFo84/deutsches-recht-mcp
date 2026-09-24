"""MCP-Server „Deutsches Recht“: Gesetze und Rechtsprechung aus NeuRIS und Open Legal Data."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from .config import Settings, settings as default_settings
from .http import ApiClient, QuelleNichtErreichbar
from .neuris import NeurisClient
from .oldp import OldpClient
from .textutil import extract_norm, html_to_text, truncate

log = logging.getLogger("deutsches_recht_mcp")

HINWEIS = (
    "Arbeitsgrundlage, keine amtliche Fundstelle: NeuRIS ist in der Testphase, Open Legal Data ist unvollständig. "
    "Zitate vor Verwendung in Schriftsätzen am amtlichen Text bzw. an der Originalentscheidung verifizieren."
)

INSTRUCTIONS = """\
Recherche im deutschen Recht über offizielle und offene Schnittstellen:
- NeuRIS (rechtsinformationen.bund.de): Bundesgesetze/-verordnungen, Entscheidungen von BVerfG, BGH, BVerwG, BFH, BAG, BSG.
- Open Legal Data (de.openlegaldata.io): Entscheidungen auch von OLG/LG/AG, Zitationsgraph Norm -> Urteile.

Vorgehen:
1. Normtext immer mit norm_abrufen prüfen, bevor eine Norm zitiert wird (Abkürzung wie 'InsO', 'BGB', 'GmbHG').
2. Rechtsprechung zu einer Norm: rechtsprechung_zu_norm; freie Suche: rechtsprechung_suchen.
3. Volltext einer Entscheidung: entscheidung_abrufen mit der id aus den Treffern ('neuris:...' oder 'oldp:...').
4. Zitiere mit Gericht, Datum, Aktenzeichen und, wenn vorhanden, ECLI. Nichts zitieren, was nicht abgerufen wurde.
Beide Quellen sind unvollständig; fehlende Treffer bedeuten nicht, dass keine Rechtsprechung existiert.
"""

RO = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)


class Clients:
    def __init__(self, cfg: Settings, transport=None) -> None:
        oldp_headers = {"Authorization": f"Token {cfg.oldp_api_token}"} if cfg.oldp_api_token else None
        self.neuris = NeurisClient(ApiClient(cfg.neuris_base, cfg, "NeuRIS", transport=transport))
        self.oldp = OldpClient(ApiClient(cfg.oldp_base, cfg, "Open Legal Data", oldp_headers, transport=transport))


def _clamp(n: int, lo: int = 1, hi: int = 50) -> int:
    try:
        return max(lo, min(hi, int(n)))
    except (TypeError, ValueError):
        return 10


def _sort_by_date(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: str(r.get("datum") or ""), reverse=True)


def build_server(cfg: Settings | None = None, transport=None) -> FastMCP:
    cfg = cfg or default_settings
    clients = Clients(cfg, transport=transport)

    security = (
        TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=cfg.allowed_hosts)
        if cfg.allowed_hosts
        else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    mcp = FastMCP(
        "Deutsches Recht",
        instructions=INSTRUCTIONS,
        host=cfg.host,
        port=cfg.port,
        streamable_http_path=cfg.mcp_path,
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
    mcp._clients = clients  # für Tests

    # ------------------------------------------------------------------ Gesetze
    @mcp.tool(annotations=RO)
    async def gesetz_suchen(suchbegriff: str, anzahl: int = 10) -> dict:
        """Sucht Bundesgesetze und -verordnungen in NeuRIS (Titel, Abkürzung, Volltext).

        Args:
            suchbegriff: z.B. 'Insolvenzordnung', 'InsO', 'Massekostenvorschuss'
            anzahl: maximale Trefferzahl (1-50)
        """
        try:
            total, items = await clients.neuris.search_legislation(suchbegriff, size=_clamp(anzahl))
        except QuelleNichtErreichbar as exc:
            return {"treffer": [], "fehler": [str(exc)], "hinweis": HINWEIS}
        return {
            "gesamt": total,
            "treffer": [clients.neuris.normalize_legislation(i) for i in items],
            "hinweis": HINWEIS,
        }

    @mcp.tool(annotations=RO)
    async def norm_abrufen(gesetz: str, paragraph: str, absatz: str | None = None) -> dict:
        """Ruft den Wortlaut einer Norm aus der aktuell geltenden Fassung ab (NeuRIS).

        Args:
            gesetz: amtliche Abkürzung, z.B. 'InsO', 'BGB', 'GmbHG', 'AnfG', 'ZPO', 'GG'
            paragraph: Paragraph bzw. Artikel ohne Zeichen, z.B. '26', '15b', '823'
            absatz: optional nur dieser Absatz, z.B. '4'
        """
        try:
            act = await clients.neuris.find_act(gesetz)
            if not act:
                return {
                    "gefunden": False,
                    "meldung": f"Gesetz '{gesetz}' in NeuRIS nicht gefunden. Abkürzung prüfen oder gesetz_suchen nutzen.",
                    "hinweis": HINWEIS,
                }
            html, url = await clients.neuris.law_html(act)
        except QuelleNichtErreichbar as exc:
            return {"gefunden": False, "fehler": [str(exc)], "hinweis": HINWEIS}

        text = extract_norm(html, paragraph, absatz)
        meta = clients.neuris.normalize_legislation(act)
        base = {
            "gesetz": meta["abkuerzung"] or gesetz,
            "titel": meta["titel"],
            "eli": meta["eli"],
            "in_kraft": meta["in_kraft"],
            "quelle": meta["quelle"],
            "url": url,
            "hinweis": HINWEIS,
        }
        if not text:
            return {
                **base,
                "gefunden": False,
                "meldung": f"§/Art. {paragraph}{' Abs. ' + absatz if absatz else ''} im Text nicht gefunden.",
            }
        return {**base, "gefunden": True, "norm": f"§ {paragraph}" + (f" Abs. {absatz}" if absatz else ""), "wortlaut": text}

    # ---------------------------------------------------------- Rechtsprechung
    @mcp.tool(annotations=RO)
    async def rechtsprechung_suchen(
        suchbegriff: str,
        gericht: str | None = None,
        datum_von: str | None = None,
        datum_bis: str | None = None,
        quelle: Literal["alle", "neuris", "oldp"] = "alle",
        anzahl: int = 10,
    ) -> dict:
        """Volltextsuche in Gerichtsentscheidungen (NeuRIS: Bundesgerichte; Open Legal Data: alle Instanzen).

        Args:
            suchbegriff: z.B. 'Massekostenvorschuss Geschäftsführer Erstattung'
            gericht: optional, z.B. 'BGH' (NeuRIS) bzw. Gerichts-Slug (Open Legal Data)
            datum_von / datum_bis: optional, Format JJJJ-MM-TT
            quelle: 'alle', 'neuris' oder 'oldp'
            anzahl: Treffer je Quelle (1-50)
        """
        n = _clamp(anzahl)
        tasks: dict[str, Any] = {}
        if quelle in ("alle", "neuris"):
            tasks["neuris"] = clients.neuris.search_case_law(suchbegriff, gericht, datum_von, datum_bis, n)
        if quelle in ("alle", "oldp"):
            tasks["oldp"] = clients.oldp.search_cases(suchbegriff, gericht, datum_von, datum_bis, n)
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        rows, fehler, gesamt = [], [], {}
        for name, res in zip(tasks, results):
            if isinstance(res, Exception):
                fehler.append(str(res))
                continue
            total, items = res
            gesamt[name] = total
            norm = clients.neuris.normalize_case if name == "neuris" else clients.oldp.normalize_case
            rows.extend(norm(i) for i in items)
        return {"gesamt_je_quelle": gesamt, "treffer": _sort_by_date(rows), "fehler": fehler, "hinweis": HINWEIS}

    @mcp.tool(annotations=RO)
    async def entscheidung_abrufen(id: str, max_zeichen: int = 30000) -> dict:
        """Ruft Metadaten und Volltext einer Entscheidung ab.

        Args:
            id: Kennung aus den Suchtreffern, z.B. 'neuris:KORE123452024' oder 'oldp:123456'
            max_zeichen: Volltext wird danach gekürzt (Standard 30000)
        """
        src, _, key = id.partition(":")
        if not key:
            return {"fehler": ["id muss mit 'neuris:' oder 'oldp:' beginnen"], "hinweis": HINWEIS}
        try:
            if src == "neuris":
                meta, html, url = await clients.neuris.get_case(key)
                row = clients.neuris.normalize_case(meta)
                text = html_to_text(html) if html else None
                row["url"] = url
            elif src == "oldp":
                meta = await clients.oldp.get_case(int(key))
                row = clients.oldp.normalize_case(meta)
                content = meta.get("content") or ""
                text = html_to_text(content) if content else None
            else:
                return {"fehler": [f"Unbekannte Quelle '{src}'"], "hinweis": HINWEIS}
        except (QuelleNichtErreichbar, ValueError) as exc:
            return {"fehler": [str(exc)], "hinweis": HINWEIS}
        if text:
            text, gekuerzt = truncate(text, max(1000, int(max_zeichen)))
        else:
            gekuerzt = False
        return {**row, "volltext": text, "gekuerzt": gekuerzt, "hinweis": HINWEIS}

    @mcp.tool(annotations=RO)
    async def rechtsprechung_zu_norm(gesetz: str, paragraph: str, anzahl: int = 20) -> dict:
        """Findet Entscheidungen, die eine Norm zitieren (Zitationsgraph Open Legal Data, ergänzt um NeuRIS-Volltexttreffer).

        Args:
            gesetz: amtliche Abkürzung, z.B. 'InsO'
            paragraph: z.B. '26'
            anzahl: maximale Treffer je Quelle (1-50)
        """
        n = _clamp(anzahl)
        fehler: list[str] = []
        zitiert: list[dict] = []
        norm_info = None
        try:
            law = await clients.oldp.find_law(gesetz, paragraph)
            if law and law.get("id") is not None:
                norm_info = clients.oldp.normalize_law(law)
                _, items = await clients.oldp.law_citing_cases(int(law["id"]), n)
                zitiert = [clients.oldp.normalize_case(i) for i in items]
            else:
                fehler.append(f"Open Legal Data: Norm {gesetz} § {paragraph} nicht im Zitationsgraph gefunden")
        except QuelleNichtErreichbar as exc:
            fehler.append(str(exc))

        ergaenzend: list[dict] = []
        try:
            _, items = await clients.neuris.search_case_law(f"§ {paragraph} {gesetz}", size=n)
            ergaenzend = [clients.neuris.normalize_case(i) for i in items]
        except QuelleNichtErreichbar as exc:
            fehler.append(str(exc))

        return {
            "norm": f"§ {paragraph} {gesetz}",
            "oldp_norm": norm_info,
            "zitierende_entscheidungen": _sort_by_date(zitiert),
            "volltexttreffer_bundesgerichte": _sort_by_date(ergaenzend),
            "fehler": fehler,
            "hinweis": HINWEIS,
        }

    @mcp.tool(annotations=RO)
    async def zitierende_entscheidungen(id: str, anzahl: int = 20) -> dict:
        """Listet Entscheidungen, die eine Entscheidung zitieren (nur Open Legal Data).

        Args:
            id: 'oldp:123456'
            anzahl: 1-50
        """
        src, _, key = id.partition(":")
        if src != "oldp" or not key.isdigit():
            return {"fehler": ["Nur für Open-Legal-Data-IDs ('oldp:123456') verfügbar"], "hinweis": HINWEIS}
        try:
            total, items = await clients.oldp.citing_cases(int(key), _clamp(anzahl))
        except QuelleNichtErreichbar as exc:
            return {"fehler": [str(exc)], "hinweis": HINWEIS}
        return {"gesamt": total, "treffer": _sort_by_date([clients.oldp.normalize_case(i) for i in items]), "hinweis": HINWEIS}

    @mcp.tool(annotations=RO)
    async def verweise_einer_entscheidung(id: str) -> dict:
        """Listet Normen und Entscheidungen, auf die eine Entscheidung verweist (nur Open Legal Data).

        Args:
            id: 'oldp:123456'
        """
        src, _, key = id.partition(":")
        if src != "oldp" or not key.isdigit():
            return {"fehler": ["Nur für Open-Legal-Data-IDs ('oldp:123456') verfügbar"], "hinweis": HINWEIS}
        try:
            raw = await clients.oldp.references(int(key))
        except QuelleNichtErreichbar as exc:
            return {"fehler": [str(exc)], "hinweis": HINWEIS}
        return {"verweise": raw, "hinweis": HINWEIS}

    @mcp.tool(annotations=RO)
    async def quellenstatus() -> dict:
        """Prüft, ob NeuRIS und Open Legal Data erreichbar sind."""
        async def probe(coro):
            try:
                await coro
                return "erreichbar"
            except QuelleNichtErreichbar as exc:
                return f"Fehler: {exc}"

        n, o = await asyncio.gather(
            probe(clients.neuris.search_legislation("Bürgerliches Gesetzbuch", size=1)),
            probe(clients.oldp.search_laws("Bürgerliches Gesetzbuch", size=1)),
        )
        return {"neuris": n, "open_legal_data": o}

    # ------------------------------------------------------------ Health-Check
    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return mcp


def build_app(cfg: Settings | None = None, transport=None):
    """ASGI-App inkl. optionaler Bearer-Token-Prüfung."""
    cfg = cfg or default_settings
    mcp = build_server(cfg, transport)
    app = mcp.streamable_http_app()
    if not cfg.bearer_token:
        return app

    expected = f"Bearer {cfg.bearer_token}"

    async def guarded(scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(cfg.mcp_path):
            headers = dict(scope.get("headers") or [])
            got = headers.get(b"authorization", b"").decode()
            if not secrets.compare_digest(got, expected):
                resp = JSONResponse({"error": "unauthorized"}, status_code=401)
                await resp(scope, receive, send)
                return
        await app(scope, receive, send)

    return guarded


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    cfg = default_settings
    if not cfg.path_secret and not cfg.bearer_token:
        log.warning("Weder MCP_PATH_SECRET noch MCP_BEARER_TOKEN gesetzt: Endpunkt ist öffentlich.")
    log.info("MCP-Endpunkt: %s", cfg.mcp_path)
    uvicorn.run(build_app(cfg), host=cfg.host, port=cfg.port, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
