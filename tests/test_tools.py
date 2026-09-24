from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from deutsches_recht_mcp.config import Settings
from deutsches_recht_mcp.server import build_app, build_server
from deutsches_recht_mcp.textutil import extract_norm

from .conftest import INSO_HTML, NEURIS, OLDP


# ---------------------------------------------------------------- Textextraktion
def test_extract_norm_ueberspringt_inhaltsuebersicht():
    text = extract_norm(INSO_HTML, "26")
    assert text.startswith("§ 26 Abweisung mangels Masse")
    assert "(4) Zur Leistung eines Vorschusses" in text
    assert "§ 4 gilt entsprechend." in text  # Querverweis beendet den Paragraphen nicht
    assert "26a" not in text and "Eröffnungsbeschluß" not in text


def test_extract_norm_buchstabenparagraph_und_absatz():
    assert extract_norm(INSO_HTML, "26a").startswith("§ 26a Vergütung")
    abs3 = extract_norm(INSO_HTML, "26", absatz="3")
    assert abs3.splitlines()[0] == "§ 26 Abweisung mangels Masse"
    assert "(3) Wer nach Absatz 1" in abs3 and "(4)" not in abs3


def test_extract_norm_ohne_ueberschrift_tags():
    html = INSO_HTML.replace("<h3>", "<p>").replace("</h3>", "</p>")
    text = extract_norm(html, "26")
    assert "(3) Wer nach Absatz 1" in text and "Eröffnungsbeschluß" not in text


def test_extract_norm_nicht_vorhanden():
    assert extract_norm(INSO_HTML, "999") is None


# ------------------------------------------------------------------- MCP-Tools
async def call(server, name, **args):
    res = await server.call_tool(name, args)
    if isinstance(res, tuple):
        structured = res[1]
    else:
        structured = json.loads(res[0].text)
    if isinstance(structured, dict) and set(structured) == {"result"}:
        return structured["result"]
    return structured


async def test_tool_liste(cfg, transport):
    server = build_server(cfg, transport)
    names = {t.name for t in await server.list_tools()}
    assert names == {
        "gesetz_suchen", "norm_abrufen", "rechtsprechung_suchen", "entscheidung_abrufen",
        "rechtsprechung_zu_norm", "zitierende_entscheidungen", "verweise_einer_entscheidung", "quellenstatus",
    }
    for t in await server.list_tools():
        assert t.annotations.readOnlyHint is True


async def test_norm_abrufen_waehlt_geltende_fassung(cfg, transport):
    r = await call(build_server(cfg, transport), "norm_abrufen", gesetz="InsO", paragraph="26", absatz="4")
    assert r["gefunden"] is True
    assert r["eli"].endswith("2024-01-01/1/deu")
    assert "Zur Leistung eines Vorschusses" in r["wortlaut"]
    assert r["url"].startswith(NEURIS)


async def test_norm_abrufen_unbekanntes_gesetz(cfg, transport):
    r = await call(build_server(cfg, transport), "norm_abrufen", gesetz="XYZG", paragraph="1")
    assert r["gefunden"] is False


async def test_rechtsprechung_suchen_beide_quellen(cfg, transport):
    r = await call(build_server(cfg, transport), "rechtsprechung_suchen", suchbegriff="Massekostenvorschuss")
    ids = [t["id"] for t in r["treffer"]]
    assert ids == ["neuris:KORE700012024", "oldp:4711"]  # nach Datum absteigend
    assert r["treffer"][0]["aktenzeichen"] == "IX ZR 1/23"
    assert r["treffer"][1]["gericht"] == "OLG Stuttgart"
    assert r["fehler"] == []


async def test_entscheidung_abrufen(cfg, transport):
    s = build_server(cfg, transport)
    n = await call(s, "entscheidung_abrufen", id="neuris:KORE700012024")
    assert "Revision wird zurückgewiesen" in n["volltext"]
    o = await call(s, "entscheidung_abrufen", id="oldp:4711")
    assert "§ 26 Abs. 3 InsO" in o["volltext"]
    bad = await call(s, "entscheidung_abrufen", id="4711")
    assert bad["fehler"]


async def test_rechtsprechung_zu_norm(cfg, transport):
    r = await call(build_server(cfg, transport), "rechtsprechung_zu_norm", gesetz="InsO", paragraph="26")
    assert r["oldp_norm"]["id"] == "oldp-norm:899"
    assert r["zitierende_entscheidungen"][0]["aktenzeichen"] == "10 U 5/22"
    assert r["volltexttreffer_bundesgerichte"][0]["ecli"].startswith("ECLI:DE:BGH")


async def test_zitationsgraph_tools(cfg, transport):
    s = build_server(cfg, transport)
    assert (await call(s, "zitierende_entscheidungen", id="oldp:4711"))["gesamt"] == 0
    v = await call(s, "verweise_einer_entscheidung", id="oldp:4711")
    assert v["verweise"]["law_references"][0]["section"] == "§ 26"
    assert (await call(s, "zitierende_entscheidungen", id="neuris:X"))["fehler"]


async def test_quelle_ausgefallen_liefert_teilergebnis(cfg):
    def half_down(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(OLDP):
            return httpx.Response(503)
        from .conftest import handler
        return handler(request)

    s = build_server(cfg, httpx.MockTransport(half_down))
    r = await call(s, "rechtsprechung_suchen", suchbegriff="Massekostenvorschuss")
    assert [t["id"] for t in r["treffer"]] == ["neuris:KORE700012024"]
    assert "503" in r["fehler"][0]
    st = await call(s, "quellenstatus")
    assert st["neuris"] == "erreichbar" and st["open_legal_data"].startswith("Fehler")


# ------------------------------------------------- End-to-End über Streamable HTTP
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(transport):
    port = _free_port()
    cfg = Settings(neuris_base=NEURIS, oldp_base=OLDP, max_retries=0, path_secret="geheim123",
                   bearer_token="tok", port=port, host="127.0.0.1")
    server = uvicorn.Server(uvicorn.Config(build_app(cfg, transport), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    th.join(timeout=5)


async def test_end_to_end_streamable_http(live_server):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with httpx.AsyncClient() as c:
        assert (await c.get(f"{live_server}/health")).text == "ok"
        # falscher Pfad bzw. fehlendes Token werden abgewiesen
        assert (await c.post(f"{live_server}/mcp", json={})).status_code == 404
        assert (await c.post(f"{live_server}/geheim123/mcp", json={})).status_code == 401

    async with streamablehttp_client(f"{live_server}/geheim123/mcp", headers={"Authorization": "Bearer tok"}) as (r, w, _):
        async with ClientSession(r, w) as session:
            info = await session.initialize()
            assert info.serverInfo.name == "Deutsches Recht"
            tools = await session.list_tools()
            assert len(tools.tools) == 8
            res = await session.call_tool("norm_abrufen", {"gesetz": "InsO", "paragraph": "26", "absatz": "3"})
            payload = res.structuredContent or json.loads(res.content[0].text)
            payload = payload.get("result", payload)
            assert "Wer nach Absatz 1 Satz 2" in payload["wortlaut"]
