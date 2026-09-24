"""Gemeinsamer HTTP-Client mit Retry, Backoff und TTL-Cache."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .config import Settings


class QuelleNichtErreichbar(RuntimeError):
    """Die Datenquelle hat nicht oder fehlerhaft geantwortet."""


class TTLCache:
    def __init__(self, ttl_s: int, max_entries: int = 512) -> None:
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        hit = self._data.get(key)
        if not hit:
            return None
        ts, value = hit
        if time.monotonic() - ts > self.ttl_s:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._data) >= self.max_entries:
            oldest = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest, None)
        self._data[key] = (time.monotonic(), value)


class ApiClient:
    """Dünne Hülle um httpx.AsyncClient für eine Datenquelle."""

    def __init__(
        self,
        base_url: str,
        settings: Settings,
        name: str,
        extra_headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.settings = settings
        headers = {"User-Agent": settings.user_agent}
        if extra_headers:
            headers.update(extra_headers)
        self._client = httpx.AsyncClient(
            timeout=settings.timeout_s,
            headers=headers,
            follow_redirects=True,
            transport=transport,
        )
        self.cache = TTLCache(settings.cache_ttl_s)

    def url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        return f"{self.base_url}/{path_or_url.lstrip('/')}"

    async def _request(self, url: str, params: dict | None, accept: str) -> httpx.Response:
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        last_exc: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                resp = await self._client.get(url, params=params, headers={"Accept": accept})
            except httpx.HTTPError as exc:
                last_exc = exc
            else:
                if resp.status_code in (429, 502, 503, 504):
                    last_exc = QuelleNichtErreichbar(
                        f"{self.name}: HTTP {resp.status_code} für {resp.request.url}"
                    )
                else:
                    if resp.status_code >= 400:
                        raise QuelleNichtErreichbar(
                            f"{self.name}: HTTP {resp.status_code} für {resp.request.url}"
                        )
                    return resp
            if attempt < self.settings.max_retries:
                await asyncio.sleep(0.8 * (2**attempt))
        raise QuelleNichtErreichbar(f"{self.name} nicht erreichbar: {last_exc}")

    async def get_json(self, path: str, params: dict | None = None) -> Any:
        url = self.url(path)
        key = f"json|{url}|{sorted((params or {}).items())}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        resp = await self._request(url, params, "application/json")
        try:
            data = resp.json()
        except ValueError as exc:
            raise QuelleNichtErreichbar(f"{self.name}: keine gültige JSON-Antwort") from exc
        self.cache.set(key, data)
        return data

    async def get_text(self, path: str, params: dict | None = None, accept: str = "text/html") -> str:
        url = self.url(path)
        key = f"text|{url}|{sorted((params or {}).items())}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        resp = await self._request(url, params, accept)
        text = resp.text
        self.cache.set(key, text)
        return text

    async def aclose(self) -> None:
        await self._client.aclose()
