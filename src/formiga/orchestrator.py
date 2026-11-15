"""Orquestrador do loop de pesquisa (seção 8 do PRD).

Implementação completa na Etapa 2; a CLI já resolve este módulo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from formiga.config import Config


@dataclass
class ResearchResult:
    status: str
    report_path: Path | None
    state_path: Path | None


def run_research(
    config: Config,
    progress: Callable[[str], None] | None = None,
) -> ResearchResult:
    raise NotImplementedError("Loop de pesquisa implementado na Etapa 2.")
