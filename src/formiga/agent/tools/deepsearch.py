"""Ferramenta `deep_search` (seção 6.1 do PRD).

Encapsula `orchestrator.run_research` — o motor de pesquisa atual — sem
alterá-lo. É uma ação pesada: `MAX_DEEP_SEARCHES` por mensagem do usuário.
O orçamento de buscas/páginas/chamadas é o da pesquisa, não o da sessão.

Retorno para o modelo (cap 4K): status (suficiente/parcial/bloqueada),
resumo do relatório, lista de fontes `[S#] título — url` e caminho do
`report.md`. O relatório completo fica no disco sob
`sessoes/<sessão>/research/<n>-<slug>/`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from pathlib import Path

from formiga.agent.tools.base import ToolResult
from formiga.config import Config
from formiga.orchestrator import run_research
from formiga.storage import load_state

DEEP_SEARCH_CAP_CHARS = 4000
MAX_SOURCES_LISTED = 6


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "pesquisa"


class DeepSearchTool:
    name = "deep_search"
    description = (
        "Pesquisa profunda controlada pelo programa (até 12 buscas, 18 páginas). "
        "Retorna resumo + fontes `[S#]` + caminho do `report.md`. Use quando a "
        "pergunta pedir uma resposta fundamentada com referências."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Pergunta a pesquisar profundamente."},
        },
        "required": ["question"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        config: Config,
        research_dir: Path,
        run_fn=None,
    ) -> None:
        self.config = config
        self.research_dir = research_dir
        self.research_dir.mkdir(parents=True, exist_ok=True)
        self.run_fn = run_fn or run_research

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, question: str) -> ToolResult:
        if not question or not question.strip():
            return ToolResult(ok=False, text="ERRO: pergunta vazia.", error="empty_question")
        question = question.strip()

        # Cada deep_search grava em um subdiretório próprio dentro de research/.
        run_dir = self.research_dir / f"{uuid.uuid4().hex[:8]}-{_slugify(question)[:40]}"

        # Config derivada: output aponta para o subdiretório, overwrite=True
        # (cada run é um diretório novo, mas garante não falhar se existir).
        research_config = replace(
            self.config,
            output=run_dir,
            overwrite=True,
        )
        # Desliga fallback para não complicar o orçamento da pesquisa leve.
        research_config = replace(research_config, fallback_backend=None)

        events: list[str] = []

        def progress(message: str) -> None:
            events.append(message)

        try:
            result = self.run_fn(research_config, progress=progress)
        except Exception as exc:  # falha do motor → ERRO ao modelo, não encerra sessão
            return ToolResult(
                ok=False,
                text=f"ERRO: deep_search falhou: {exc}",
                error=str(exc),
            )

        # Monta o resumo capado a partir do estado persistido e do relatório.
        try:
            state = load_state(run_dir)
        except Exception:
            state = None

        status = result.status or (state.status if state else "desconhecido")
        summary_lines = [f"Status: {status}"]
        if events:
            # Últimos eventos como "progresso": planejado, rodadas, etc.
            summary_lines.append("Progresso: " + " | ".join(events[-6:]))

        # Fontes e resumo do relatório, se disponíveis.
        sources_text = ""
        if state and state.sources:
            lines_src = []
            for i, s in enumerate(state.sources, start=1):
                title = s.title or s.requested_url
                lines_src.append(f"[S{i}] {title} — {s.requested_url}")
            sources_text = "\nFontes:\n" + "\n".join(lines_src[:MAX_SOURCES_LISTED])

        report_path_str = str(result.report_path)
        summary = "\n".join(summary_lines) + sources_text
        summary += f"\n\nRelatório completo: {report_path_str}"

        if len(summary) > DEEP_SEARCH_CAP_CHARS:
            summary = summary[:DEEP_SEARCH_CAP_CHARS] + "\n…(truncado)"

        return ToolResult(ok=True, text=summary)
