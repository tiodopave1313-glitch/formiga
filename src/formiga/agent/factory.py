"""Fábrica do stack do agente: chat client, ferramentas, loop e sessão.

Usada por CLI (`--print`) e TUI — regra do PRD §4: CLI e TUI usam os mesmos
schemas, limites e persistência.

A única porta do núcleo até as ferramentas é o `ExtensionRegistry`, populado
pela descoberta (`discover_extensions`). Nenhuma ferramenta concreta é
importada daqui.
"""

from __future__ import annotations

from collections.abc import Callable

from formiga.agent.chat import build_chat_client
from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.config import Config


def build_agent(
    config: Config,
    session: Session,
    on_event: Callable[[str, dict], None] | None = None,
) -> AgentLoop:
    """Monta o agente por descoberta de extensões e entrega o registry ao loop."""
    chat_client = build_chat_client(config)
    registry = ExtensionRegistry()

    # Descoberta determinística (builtin → pip → global → projeto). Na Fase 1
    # somente builtin está ativa; pip/global/projeto entram na Fase 2.
    discover_extensions(config, session, registry)

    return AgentLoop(
        chat_client,
        registry,
        session,
        config,
        on_event=on_event,
    )
