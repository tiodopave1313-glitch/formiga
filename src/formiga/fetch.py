"""Fetch de páginas: protocolo e tipos (implementação segura na Etapa 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class FetchedPage:
    requested_url: str
    final_url: str | None
    content: str  # HTML bruto; extração do texto principal fica em extract.py.


class FetchError(Exception):
    """Página inacessível ou conteúdo rejeitado."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"{url}: {reason}")


class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...
