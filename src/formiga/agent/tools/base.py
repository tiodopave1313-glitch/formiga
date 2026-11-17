"""Contrato de ferramentas do agente (seção 6 do PRD)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ToolResult:
    """Resultado de uma execução de ferramenta."""

    ok: bool
    text: str  # conteúdo do sucesso ou a mensagem de erro (`ERRO: ...`)
    error: str | None = None  # exceção original, sem credenciais


@runtime_checkable
class Tool(Protocol):
    """Uma ferramenta disponível ao modelo."""

    name: str
    description: str
    parameters: dict  # JSON Schema dos parâmetros

    def schema(self) -> dict:
        """Esquema no formato OpenAI/Ollama/llama-server: {type, function}."""
        ...

    def execute(self, **kwargs) -> ToolResult:
        """Executa a ferramenta com os argumentos vindos do modelo."""
        ...
