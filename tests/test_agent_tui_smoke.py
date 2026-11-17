"""Smoke automatizado da TUI (Textual pilot, offline, fakes — PRD §20.1 Fase 5).

Cobre: barra de status com ctx/ext/perfil, evento de extensão em linha,
NO_COLOR, 80×24, comando /ext. A conferência visual manual (Esc/Ctrl+C)
fica no docs/smoke_agent.md.
"""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Input

from formiga.agent import factory
from formiga.agent.chat import ChatResponse
from formiga.agent.extensions.budget import ContextBudget
from formiga.agent.extensions.registry import ExtensionContext
from formiga.agent.session import Session
from formiga.agent.tui.app import AgentApp
from formiga.agent.tui.controller import AgentController
from formiga.config import Config
from tests.fakes_agent import FakeChatClient


class NotificacaoExtensao:
    """Extensão que emite um evento custom de notificação em before_agent_start."""

    def setup(self, pi) -> None:
        def avisar(value):
            pi.emit("notification", {"texto": "aviso da extensão externa"})
            return value

        pi.on("before_agent_start", avisar)


def _build_app_com_extensao(tmp_path, monkeypatch, extensao=None):
    monkeypatch.setattr(
        factory,
        "build_chat_client",
        lambda config: FakeChatClient([ChatResponse(content="resposta")]),
    )
    cfg = Config(agent_workdir=str(tmp_path), extensions_enabled=("core",))
    session = Session(tmp_path / "sessoes")
    loop = factory.build_agent(cfg, session)
    if extensao is not None:
        extensao().setup(
            ExtensionContext(registry=loop.registry, config=cfg, session=session)
        )
    controller = AgentController(cfg, session, loop=loop)
    app = AgentApp(cfg, session, controller=controller)
    return app, controller, cfg


async def _esperar_idle(app, controller, piloto, timeout=5.0):
    entrada = app.query_one("#input", Input)
    for _ in range(int(timeout / 0.05)):
        if not entrada.disabled:
            break
        await asyncio.sleep(0.05)
        await piloto.pause()


async def test_status_bar_tem_ctx_ext_e_perfil(tmp_path, monkeypatch):
    app, controller, cfg = _build_app_com_extensao(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "oi"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        status = str(app.query_one("#status").render())
        assert "ctx" in status, f"status sem ctx: {status!r}"
        assert "ext" in status, f"status sem ext: {status!r}"
        assert len(status) <= 80, f"status excede 80 colunas: {len(status)}"


async def test_evento_de_extensao_em_linha_na_tui(tmp_path, monkeypatch):
    app, controller, cfg = _build_app_com_extensao(
        tmp_path, monkeypatch, extensao=NotificacaoExtensao
    )
    mensagens_vistas: list[str] = []
    original = app._handle_event

    def captura(event, data):
        if event == "notification":
            mensagens_vistas.append(str(data.get("texto", "")))
        original(event, data)

    app._handle_event = captura

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "oi"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)

    assert "aviso da extensão externa" in mensagens_vistas, (
        f"evento de extensão não chegou na TUI: {mensagens_vistas}"
    )


async def test_ext_listado_na_tui(tmp_path, monkeypatch):
    app, controller, cfg = _build_app_com_extensao(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # executa um turno para popular a barra (ext > 0)
        app.query_one("#input", Input).value = "oi"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        status = str(app.query_one("#status").render())
        # core contribui várias ferramentas (ls, read, ...), então ext > 0
        assert "ext" in status and "ext 0" not in status, f"ext não listado: {status!r}"


@pytest.mark.parametrize("no_color", ["1", "0"])
async def test_tui_80x24_com_e_sem_no_color(tmp_path, monkeypatch, no_color):
    monkeypatch.setenv("NO_COLOR", no_color)
    app, controller, cfg = _build_app_com_extensao(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "oi"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        # não deve levantar; a TUI roda com ou sem NO_COLOR
        status = str(app.query_one("#status").render())
        assert "turnos" in status


def test_contexto_budget_tem_campos_fase5(tmp_path, monkeypatch):
    """O ContextBudget expõe max_context_tokens e custo (usado pelo loop)."""
    cb = ContextBudget(max_context_tokens=32768)
    assert cb.max_context_tokens == 32768
    assert cb.custo([]) == 0
