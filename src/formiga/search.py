"""Busca: provedor SearXNG (real na Etapa 3) e protocolo para adaptadores.

Snippets servem para seleção de páginas, nunca como evidência final.
Consultas enviadas ao provedor devem ser registradas nos eventos pelo orquestrador.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchResult:
    url: str
    title: str | None
    snippet: str | None


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class SearchError(Exception):
    """Falha ao consultar o provedor de busca."""


def normalize_url(url: str) -> str:
    """Normalização conservadora para dedupe de URLs repetidas."""
    url = url.strip()
    url = url.split("#", 1)[0]
    url = url.split("?", 1)[0]
    if url.endswith("/"):
        url = url[:-1]
    url = url.lower()
    return url


def dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    """Descarta URLs repetidas após normalização, preservando a primeira ocorrência."""
    seen: set[str] = set()
    kept: list[SearchResult] = []
    for r in results:
        key = normalize_url(r.url)
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    return kept


def normalize_query(query: str) -> str:
    """Normaliza consulta para detecção de repetição dentro da mesma questão."""
    return " ".join(query.lower().split())
