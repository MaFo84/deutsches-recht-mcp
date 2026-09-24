"""Konfiguration über Umgebungsvariablen."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    # Datenquellen
    neuris_base: str = field(
        default_factory=lambda: os.getenv(
            "NEURIS_BASE", "https://testphase.rechtsinformationen.bund.de"
        ).rstrip("/")
    )
    oldp_base: str = field(
        default_factory=lambda: os.getenv(
            "OLDP_BASE", "https://de.openlegaldata.io/api"
        ).rstrip("/")
    )
    oldp_api_token: str | None = field(default_factory=lambda: os.getenv("OLDP_API_TOKEN") or None)

    # HTTP-Verhalten
    timeout_s: float = field(default_factory=lambda: float(os.getenv("HTTP_TIMEOUT_S", "20")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("HTTP_MAX_RETRIES", "2")))
    cache_ttl_s: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL_S", "86400")))
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "USER_AGENT",
            "DeutschesRecht-MCP/1.0 (+https://github.com/MaFo84/deutsches-recht-mcp)",
        )
    )

    # Server
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    # Geheimer Pfadbestandteil: Endpunkt wird /<MCP_PATH_SECRET>/mcp
    path_secret: str | None = field(default_factory=lambda: os.getenv("MCP_PATH_SECRET") or None)
    # Optional zusätzlich: Bearer-Token (für Clients, die Header setzen können)
    bearer_token: str | None = field(default_factory=lambda: os.getenv("MCP_BEARER_TOKEN") or None)
    # DNS-Rebinding-Schutz: erlaubte Host-Header, z.B. "recht.fostec.com,localhost:*"
    allowed_hosts: list[str] = field(default_factory=lambda: _list("ALLOWED_HOSTS"))

    @property
    def mcp_path(self) -> str:
        return f"/{self.path_secret}/mcp" if self.path_secret else "/mcp"


settings = Settings()
