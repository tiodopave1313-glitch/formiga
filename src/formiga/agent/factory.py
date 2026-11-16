"""Fábrica do stack do agente: chat client, ferramentas, loop e sessão.

Usada por CLI (`--print`) e TUI — regra do PRD §4: CLI e TUI usam os mesmos
schemas, limites e persistência.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from formiga.agent.chat import build_chat_client
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools import FILE_TOOLS
from formiga.agent.tools.deepsearch import DeepSearchTool
from formiga.agent.tools.shell import BashTool
from formiga.agent.tools.web import WebFetchTool, WebSearchTool
from formiga.config import Config


def build_agent(
    config: Config,
    session: Session,
    on_event: Callable[[str, dict], None] | None = None,
) -> AgentLoop:
    """Monta o `AgentLoop` com as oito ferramentas e o chat client do config."""
    chat_client = build_chat_client(config)
    workdir = Path(config.agent_workdir)
    tools = [
        BashTool(workdir),
        WebSearchTool(config),
        WebFetchTool(config),
        DeepSearchTool(config, session.research_dir),
        *(tool_cls(workdir) for tool_cls in FILE_TOOLS),
    ]
    return AgentLoop(chat_client, tools, session, config, on_event=on_event)
