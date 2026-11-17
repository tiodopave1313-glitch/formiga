"""Extensão builtin de busca e leitura da web."""

from __future__ import annotations

from formiga.agent.extensions.api import ExtensionAPI
from formiga.ext.web.tools import WebFetchTool, WebSearchTool


def setup(pi: ExtensionAPI) -> None:
    """Registra as ferramentas web e seus orçamentos por mensagem."""
    pi.register_tool(
        WebSearchTool(pi.config),
        budget_per_message=int(getattr(pi.config, "agent_max_web_searches", 6)),
        category="web",
    )
    pi.register_tool(
        WebFetchTool(pi.config),
        budget_per_message=int(getattr(pi.config, "agent_max_web_fetches", 8)),
        category="web",
    )


__all__ = ["WebFetchTool", "WebSearchTool", "setup"]
