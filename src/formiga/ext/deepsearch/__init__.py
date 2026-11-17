"""Extensão builtin que expõe o motor de pesquisa profunda do Formiga."""

from __future__ import annotations

from formiga.agent.extensions.api import ExtensionAPI
from formiga.ext.deepsearch.tool import DeepSearchTool


def setup(pi: ExtensionAPI) -> None:
    """Registra deep_search como uma ferramenta comum do registry."""
    config = pi.runtime_config
    pi.register_tool(
        DeepSearchTool(config, pi.session.research_dir),
        budget_per_message=int(getattr(config, "agent_max_deep_searches", 2)),
        category="research",
    )


__all__ = ["DeepSearchTool", "setup"]
