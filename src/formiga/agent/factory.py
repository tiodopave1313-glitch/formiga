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
from formiga.agent.extensions.budget import check_schema_budget, schema_tokens
from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.loop import AgentLoop
from formiga.agent.profiles import Profile, apply_profile, select_profile
from formiga.agent.session import Session
from formiga.config import Config


def build_agent(
    config: Config,
    session: Session,
    on_event: Callable[[str, dict], None] | None = None,
) -> AgentLoop:
    """Monta o agente por descoberta de extensões e entrega o registry ao loop."""
    # Perfil de modelo (seção 9.6 do PRD): aplica defaults do perfil apenas
    # em campos ainda em default do Formiga; CLI/env/arquivo sobrepõem.
    user_profiles = {
        nome: Profile(**settings)
        for nome, settings in config.profiles.items()
    }
    perfil = select_profile(
        config.model,
        model_hint=config.profile_model_hint,
        user_profiles=user_profiles,
    )
    if perfil is not None:
        apply_profile(config, perfil)
        config.active_profile = perfil.name

    chat_client = build_chat_client(config)
    registry = ExtensionRegistry()

    # Descoberta determinística (builtin → pip → global → projeto). Na Fase 1
    # somente builtin está ativa; pip/global/projeto entram na Fase 2.
    discover_extensions(config, session, registry)

    # Orçamento de schemas: exceder falha rápido no startup citando a
    # extensão responsável (seção 9.7 do PRD). Nunca "estoura e segue".
    total_schema_tokens = sum(
        schema_tokens(reg.tool.schema())
        for reg in registry.registrations.values()
        if not reg.lazy
    )
    check_schema_budget(
        total_schema_tokens,
        config.tool_schema_tokens,
        offender=None,
    )

    # Comandos builtin /tools e /ext, disponíveis em qualquer sessão.
    def _listar_tools(argumentos: str = "") -> str:
        linhas = ["Ferramentas registradas:"]
        if not registry.registrations:
            linhas.append("  (nenhuma)")
        for reg in registry.registrations.values():
            partes = [f"- {reg.tool.name} — {reg.tool.description}"]
            if reg.budget_per_message is not None:
                partes.append(f"orçamento {reg.budget_per_message}/mensagem")
            if reg.cap_chars is not None:
                partes.append(f"cap {reg.cap_chars} chars")
            partes.append(f"fonte {reg.source}")
            linhas.append("  " + " | ".join(partes))
        return "\n".join(linhas)

    def _listar_extensoes(argumentos: str = "") -> str:
        linhas = ["Extensões carregadas:"]
        if not registry.extensions:
            linhas.append("  (nenhuma)")
        for rec in registry.extensions:
            partes = [
                f"- {rec.name} ({rec.source}, ordem {rec.order}, {rec.status})"
            ]
            if rec.tools:
                partes.append(f"tools: {', '.join(rec.tools)}")
            if rec.commands:
                partes.append(f"comandos: {', '.join(rec.commands)}")
            if rec.error:
                partes.append(f"erro: {rec.error}")
            linhas.append("  " + " | ".join(partes))
        return "\n".join(linhas)

    registry.register_command(
        "tools", _listar_tools, extension="builtin", source="builtin"
    )
    registry.register_command(
        "ext", _listar_extensoes, extension="builtin", source="builtin"
    )

    return AgentLoop(
        chat_client,
        registry,
        session,
        config,
        on_event=on_event,
    )
