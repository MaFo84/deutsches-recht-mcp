"""Live-Abnahmetest gegen einen laufenden Server.

Aufruf:  python smoke_test.py https://<host>/<MCP_PATH_SECRET>/mcp [BEARER_TOKEN]
Prüft die echten Schnittstellen von NeuRIS und Open Legal Data über den Server.
"""

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

CHECKS = [
    ("quellenstatus", {}),
    ("norm_abrufen", {"gesetz": "InsO", "paragraph": "26", "absatz": "4"}),
    ("norm_abrufen", {"gesetz": "BGB", "paragraph": "199"}),
    ("gesetz_suchen", {"suchbegriff": "Anfechtungsgesetz", "anzahl": 3}),
    ("rechtsprechung_suchen", {"suchbegriff": "Massekostenvorschuss Erstattung", "anzahl": 3}),
    ("rechtsprechung_zu_norm", {"gesetz": "InsO", "paragraph": "15b", "anzahl": 3}),
]


async def main(url: str, token: str | None) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    failures = 0
    async with streamablehttp_client(url, headers=headers) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for name, args in CHECKS:
                res = await s.call_tool(name, args)
                data = res.structuredContent or json.loads(res.content[0].text)
                data = data.get("result", data)
                ok = not res.isError and not data.get("fehler") and data.get("gefunden", True) is not False
                failures += 0 if ok else 1
                print(f"{'OK  ' if ok else 'FEHL'} {name} {args}")
                print("     " + json.dumps(data, ensure_ascii=False)[:600])
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} Prüfungen ohne Fehler")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)))
