"""Superfície entregue às extensões durante o setup."""

from __future__ import annotations

from typing import Protocol

from formiga.agent.tools.base import Tool


class ExtensionAPI(Protocol):
    """API estável inicial para declarar ferramentas e consultar o runtime."""

    config: object
    session: object
    ui: object

    def register_tool(
        self,
        tool: Tool,
        *,
        budget_per_message: int | None = None,
        category: str = "general",
    ) -> None:
        """Registra uma ferramenta opcionalmente limitada por mensagem."""
        ...
