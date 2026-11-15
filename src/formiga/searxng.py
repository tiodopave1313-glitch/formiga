"""Busca JSON do SearXNG configurado pelo usuário.

Snippets servem para seleção de páginas, nunca como evidência final.
Consultas enviadas são registradas nos eventos pelo orquestrador.
"""

from __future__ import annotations

import httpx

from formiga.config import Config
from formiga.search import SearchResult


class SearxngSearch:
    def __init__(self, config: Config, transport: httpx.BaseTransport | None = None) -> None:
        self.url = config.searxng_url.rstrip("/")
        self.timeout = config.network_timeout
        self._transport = transport

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.get(
                    f"{self.url}/search",
                    params={"q": query, "format": "json"},
                )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Falha ao consultar SearXNG: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"Resposta não-JSON do SearXNG: {exc}") from exc
        results: list[SearchResult] = []
        for item in data.get("results", []):
            url = item.get("url")
            if not url:
                continue
            results.append(
                SearchResult(url=url, title=item.get("title"), snippet=item.get("content"))
            )
            if len(results) >= max_results:
                break
        return results
