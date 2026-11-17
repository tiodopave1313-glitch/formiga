"""Extensão builtin de busca e leitura da web."""

from __future__ import annotations

from formiga.agent.extensions.api import ExtensionAPI
from formiga.ext.web.tools import WebFetchTool, WebSearchTool


def setup(pi: ExtensionAPI) -> None:
    """Registra as ferramentas web e seus orçamentos por mensagem."""
    config = pi.runtime_config
    pi.register_tool(
        WebSearchTool(config),
        budget_per_message=int(getattr(config, "agent_max_web_searches", 6)),
        category="web",
    )
    pi.register_tool(
        WebFetchTool(config),
        budget_per_message=int(getattr(config, "agent_max_web_fetches", 8)),
        category="web",
    )


__all__ = ["WebFetchTool", "WebSearchTool", "setup"]
