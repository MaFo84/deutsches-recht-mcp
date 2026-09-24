"""Gemeinsame Test-Fixtures: simulierte NeuRIS- und OLDP-Antworten (keine echten Netzaufrufe)."""

from __future__ import annotations

import json

import httpx
import pytest

from deutsches_recht_mcp.config import Settings

NEURIS = "https://neuris.test"
OLDP = "https://oldp.test/api"

INSO_HTML = """
<html><body>
<nav>Navigation</nav>
<div class="toc">
  <p>§ 26 Abweisung mangels Masse</p>
  <p>§ 26a Vergütung des vorläufigen Insolvenzverwalters</p>
  <p>§ 27 Eröffnungsbeschluß</p>
</div>
<section>
  <h3>§ 26 Abweisung mangels Masse</h3>
  <p>(1) Das Insolvenzgericht weist den Antrag auf Eröffnung des Insolvenzverfahrens ab, wenn das Vermögen des Schuldners voraussichtlich nicht ausreichen wird, um die Kosten des Verfahrens zu decken.</p>
  <p>(2) Das Gericht ordnet die Eintragung des Schuldners in das Schuldnerverzeichnis an.</p>
  <p>(3) Wer nach Absatz 1 Satz 2 einen Vorschuß geleistet hat, kann die Erstattung des vorgeschossenen Betrages von jeder Person verlangen, die entgegen den Vorschriften des Insolvenz- oder Gesellschaftsrechts den Antrag pflichtwidrig und schuldhaft nicht gestellt hat.</p>
  <p>(4) Zur Leistung eines Vorschusses nach Absatz 1 Satz 2 ist jede Person verpflichtet, die entgegen den Vorschriften des Insolvenz- oder Gesellschaftsrechts pflichtwidrig und schuldhaft keinen Antrag gestellt hat.</p>
  <p>§ 4 gilt entsprechend.</p>
  <h3>§ 26a Vergütung des vorläufigen Insolvenzverwalters</h3>
  <p>(1) Wird das Insolvenzverfahren nicht eröffnet, setzt das Insolvenzgericht die Vergütung fest.</p>
  <h3>§ 27 Eröffnungsbeschluß</h3>
  <p>(1) Wird das Insolvenzverfahren eröffnet, so ernennt das Insolvenzgericht einen Insolvenzverwalter.</p>
</section>
</body></html>
"""

LEGISLATION_SEARCH = {
    "totalItems": 2,
    "member": [
        {
            "item": {
                "@type": "Legislation",
                "@id": "/v1/legislation/eli/bund/bgbl-1/1994/s2866/2020-01-01/1/deu",
                "name": "Insolvenzordnung",
                "abbreviation": "InsO",
                "inForce": False,
                "temporalCoverage": "2020-01-01/2023-12-31",
                "workExample": {
                    "legislationIdentifier": "eli/bund/bgbl-1/1994/s2866/2020-01-01/1/deu",
                    "encoding": [
                        {"contentUrl": "/v1/legislation/eli/bund/bgbl-1/1994/s2866/2020-01-01/1/deu/2020-01-01/regelungstext-1.html",
                         "encodingFormat": "text/html"}
                    ],
                },
            },
            "textMatches": [],
        },
        {
            "item": {
                "@type": "Legislation",
                "@id": "/v1/legislation/eli/bund/bgbl-1/1994/s2866/2024-01-01/1/deu",
                "name": "Insolvenzordnung",
                "abbreviation": "InsO",
                "inForce": True,
                "temporalCoverage": "2024-01-01/..",
                "workExample": {
                    "legislationIdentifier": "eli/bund/bgbl-1/1994/s2866/2024-01-01/1/deu",
                    "encoding": [
                        {"contentUrl": "/v1/legislation/eli/bund/bgbl-1/1994/s2866/2024-01-01/1/deu/2024-01-01/regelungstext-1.xml",
                         "encodingFormat": "application/xml"},
                        {"contentUrl": "/v1/legislation/eli/bund/bgbl-1/1994/s2866/2024-01-01/1/deu/2024-01-01/regelungstext-1.html",
                         "encodingFormat": "text/html"},
                    ],
                },
            },
            "textMatches": [{"name": "text", "text": "Insolvenzordnung", "@type": "SearchResultMatch"}],
        },
    ],
}

CASE_SEARCH = {
    "member": [
        {
            "item": {
                "@type": "Decision",
                "documentNumber": "KORE700012024",
                "ecli": "ECLI:DE:BGH:2024:010224UIXZR1.23.0",
                "courtName": "BGH",
                "judicialBody": "9. Zivilsenat",
                "decisionDate": "2024-02-01",
                "fileNumbers": ["IX ZR 1/23"],
                "documentType": "Urteil",
                "headline": "Erstattung des Massekostenvorschusses",
            },
            "textMatches": [{"name": "text", "text": "§ 26 Abs. 3 InsO"}],
        }
    ]
}

OLDP_CASES = {
    "count": 1,
    "results": [
        {"id": 4711, "slug": "olg-stuttgart-2023-05-10-10-u-5-22", "court": {"name": "OLG Stuttgart"},
         "date": "2023-05-10", "file_number": "10 U 5/22", "type": "Urteil", "snippets": ["<em>Massekostenvorschuss</em>"]}
    ],
}

OLDP_LAWS = {
    "count": 2,
    "results": [
        {"id": 900, "book_code": "inso", "section": "§ 27", "title": "Eröffnungsbeschluß"},
        {"id": 899, "book_code": "inso", "section": "§ 26", "title": "Abweisung mangels Masse"},
    ],
}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    path = request.url.path
    if url.startswith(NEURIS):
        if path == "/v1/legislation":
            return httpx.Response(200, json=LEGISLATION_SEARCH)
        if path.endswith("2024-01-01/regelungstext-1.html"):
            return httpx.Response(200, text=INSO_HTML, headers={"content-type": "text/html"})
        if path == "/v1/case-law":
            return httpx.Response(200, json=CASE_SEARCH)
        if path == "/v1/case-law/KORE700012024":
            return httpx.Response(200, json=CASE_SEARCH["member"][0]["item"])
        if path == "/v1/case-law/KORE700012024.html":
            return httpx.Response(200, text="<html><body><h1>Urteil</h1><p>Tenor: Die Revision wird zurückgewiesen.</p></body></html>")
    if url.startswith(OLDP):
        if path == "/api/cases/search/":
            return httpx.Response(200, json=OLDP_CASES)
        if path == "/api/cases/4711/":
            return httpx.Response(200, json={**OLDP_CASES["results"][0], "content": "<p>Gründe: Der Anspruch aus § 26 Abs. 3 InsO besteht.</p>"})
        if path == "/api/laws/search/":
            return httpx.Response(200, json=OLDP_LAWS)
        if path == "/api/laws/899/citing_cases/":
            return httpx.Response(200, json=OLDP_CASES)
        if path == "/api/cases/4711/citing_cases/":
            return httpx.Response(200, json={"count": 0, "results": []})
        if path == "/api/cases/4711/references/":
            return httpx.Response(200, json={"law_references": [{"book_code": "inso", "section": "§ 26"}], "case_references": []})
    return httpx.Response(404, text=json.dumps({"detail": "not found", "url": url}))


@pytest.fixture
def cfg() -> Settings:
    return Settings(neuris_base=NEURIS, oldp_base=OLDP, max_retries=0, path_secret="geheim123")


@pytest.fixture
def transport() -> httpx.MockTransport:
    return httpx.MockTransport(handler)
