"""Fábrica do stack do agente: chat client, ferramentas, loop e sessão.

Usada por CLI (`--print`) e TUI — regra do PRD §4: CLI e TUI usam os mesmos
schemas, limites e persistência.

A única porta do núcleo até as ferramentas é o `ExtensionRegistry`, populado
pela descoberta (`discover_extensions`). Nenhuma ferramenta concreta é
importada daqui.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from formiga.agent.chat import build_chat_client
from formiga.agent.cron import JobStore
from formiga.agent.extensions.budget import check_schema_budget, schema_tokens
from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.loop import AgentLoop
from formiga.agent.profiles import Profile, apply_profile, select_profile
from formiga.agent.session import Session
from formiga.agent.ui import linhas_ajuda
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

    loop = AgentLoop(
        chat_client,
        registry,
        session,
        config,
        on_event=on_event,
    )

    # Comandos de orçamento e sessão, disponíveis em qualquer sessão.
    def _orcamento(_argumentos: str = "") -> str:
        b = loop._budget_snapshot()
        linhas = [
            "Orçamento da sessão:",
            f"  turnos {b['turns']}/{b['max_turns']}",
            f"  chamadas llm {b['llm_calls']}/{b['max_llm_calls']}",
            f"  contexto {b['context_tokens']}/{b['max_context_tokens']} tokens",
            f"  ferramentas ativas {b['ext']}",
            f"  descartados por eviction {b['evicted']}",
        ]
        if loop.tool_budgets.limits:
            linhas.append("  consumo por ferramenta:")
            for nome in sorted(loop.tool_budgets.limits):
                usado = loop.tool_budgets.used.get(nome, 0)
                limite = loop.tool_budgets.limits[nome]
                linhas.append(f"    {nome}: {usado}/{limite} por mensagem")
        return "\n".join(linhas)

    def _nova_sessao(argumentos: str = "") -> str:
        confirmado = argumentos.strip().lower() in {"sim", "confirmar", "yes"}
        if not confirmado:
            return (
                "Nova sessão não confirmada. Use /new sim para criar uma "
                "nova sessão (a anterior permanece em disco)."
            )
        loop.reset_session(Path(session.base_dir))
        return "Nova sessão iniciada."

    registry.register_command(
        "budget", _orcamento, extension="builtin", source="builtin"
    )
    registry.register_command(
        "new", _nova_sessao, extension="builtin", source="builtin"
    )

    def _listar_cron(_argumentos: str = "") -> str:
        """Lista as tarefas agendadas (cron) em ~/.formiga/jobs.json."""
        store = JobStore()
        jobs = store.load()
        if not jobs:
            return "Nenhuma tarefa agendada."
        linhas = ["Tarefas agendadas (cron):"]
        for jid in sorted(jobs):
            job = jobs[jid]
            status = f"{job.last_status or '—'}"
            if job.last_error:
                status += f" ({job.last_error[:60]})"
            linhas.append(
                f"  {jid:8} | {'ativado' if job.enabled else 'desabilitado':9} | "
                f"{job.schedule:24} | próximo: {job.next_run or '—'} | {status}"
            )
        return "\n".join(linhas)

    registry.register_command(
        "cron", _listar_cron, extension="builtin", source="builtin"
    )

    def _ajuda(_argumentos: str = "") -> str:
        """Lista comandos, skills e seções contribuídas pelas extensões."""
        return "\n".join(linhas_ajuda(registry))

    registry.register_command(
        "help", _ajuda, extension="builtin", source="builtin"
    )

    # pi.emit em linha: eventos custom de extensão (notification,
    # extension_status, tool_progress, ...) chegam à mesma on_event do
    # loop, que os espelha à CLI/TUI e ao transcript (seção 7.1 do PRD).
    # Lê loop.on_event dinamicamente para respeitar reatribuições posteriores.
    def _event_sink(event: str, data: dict | None = None) -> None:
        loop.on_event(event, data or {})

    registry.bind_runtime(session)
    registry.set_event_sink(_event_sink)

    return loop
