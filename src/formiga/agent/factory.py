"""Fábrica do stack do agente: chat client, ferramentas, loop e sessão.

Usada por CLI (`--print`) e TUI — regra do PRD §4: CLI e TUI usam os mesmos
schemas, limites e persistência.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

from formiga.agent.chat import build_chat_client
from formiga.agent.extensions.registry import ExtensionContext, ExtensionRegistry
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.config import Config


def build_agent(
    config: Config,
    session: Session,
    on_event: Callable[[str, dict], None] | None = None,
) -> AgentLoop:
    """Monta o agente por extensões builtin e entrega tools pelo registry."""
    chat_client = build_chat_client(config)
    registry = ExtensionRegistry()
    extension_api = ExtensionContext(registry, config, session)

    # A ordem é explícita e determinística. A descoberta externa é fase 2.
    available = ("core", "web", "deepsearch")
    enabled = tuple(getattr(config, "extensions_enabled", available))
    unknown = set(enabled) - set(available)
    if unknown:
        raise ValueError(f"extensões builtin desconhecidas: {sorted(unknown)}")
    for name in available:
        if name in enabled:
            extension = import_module(f"formiga.ext.{name}")
            extension.setup(extension_api)

    return AgentLoop(
        chat_client,
        list(registry.tools.values()),
        session,
        config,
        on_event=on_event,
        registry=registry,
    )
