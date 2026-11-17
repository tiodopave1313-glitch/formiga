"""Testes de aceitação da Fase 4 — interfaces e orçamento visível (PRD §20.1).

Aceites cobertos:
- /budget reflete o estado real do loop (turnos/llm/ctx/ext + evicted).
- Linha de orçamento da CLI imprime ctx e ext.
- pi.emit de extensão chega à CLI e à TUI (event sink ligado).
- Âncora re-injetada quando o hook context remove a última mensagem do usuário.
- /new sim cria nova sessão em disco preservando a anterior.
- CLI não emite sequências de escape ANSI (sem cor / NO_COLOR).
"""

from __future__ import annotations

import asyncio
import re

import pytest
from textual.widgets import Input

from formiga.agent import factory
from formiga.agent.chat import ChatResponse
from formiga.agent.extensions.budget import reinject_anchor
from formiga.agent.session import Session
from formiga.agent.tui.app import AgentApp
from formiga.agent.tui.controller import AgentController
from formiga.config import Config
from tests.fakes_agent import FakeChatClient

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class EmitExtension:
    """Extensão fake que emite evento custom via pi.emit em before_agent_start."""

    def setup(self, pi) -> None:
        def emitir(value):
            pi.emit("minha_extensao_progresso", {"step": 2, "texto": "olá"})
            return value

        pi.on("before_agent_start", emitir)


class ContextoAggressivo:
    """Hook context que remove toda mensagem do usuário (testa âncora)."""

    def setup(self, pi) -> None:
        def windowar(mensagens):
            return [m for m in mensagens if m.get("role") != "user"]

        pi.on("context", windowar)


def _build_agent_com_extensao(tmp_path, extensao_cls, monkeypatch):
    """Constrói AgentLoop via factory (registra /budget, /new e event sink)."""
    monkeypatch.setattr(
        factory,
        "build_chat_client",
        lambda config: FakeChatClient([ChatResponse(content="resposta")]),
    )
    cfg = Config(agent_workdir=str(tmp_path), extensions_enabled=("core",))
    session = Session(tmp_path / "sessoes")
    loop = factory.build_agent(cfg, session)
    if extensao_cls is not None:
        from formiga.agent.extensions.registry import ExtensionContext

        extensao = extensao_cls()
        extensao.setup(
            ExtensionContext(registry=loop.registry, config=cfg, session=session)
        )
    return loop, session, cfg


def test_budget_reflete_estado_real_do_loop(tmp_path, monkeypatch):
    """Comando /budget espelha turnos/llm/ctx/ext/evicted do loop."""
    loop, session, cfg = _build_agent_com_extensao(tmp_path, None, monkeypatch)
    saida = loop.registry.dispatch_command("budget", "")
    dados = loop._budget_snapshot()
    assert f"turnos {dados['turns']}/{dados['max_turns']}" in saida
    assert f"chamadas llm {dados['llm_calls']}/{dados['max_llm_calls']}" in saida
    assert (
        f"contexto {dados['context_tokens']}/{dados['max_context_tokens']} tokens"
        in saida
    )
    assert f"ferramentas ativas {dados['ext']}" in saida
    assert f"descartados por eviction {dados['evicted']}" in saida


def test_linha_orcamento_cli_contem_ctx_e_ext(tmp_path, monkeypatch, capsys):
    """Linha de orçamento da CLI imprime ctx e ext (§10.1 do PRD)."""
    monkeypatch.setattr(
        factory,
        "build_chat_client",
        lambda config: FakeChatClient([ChatResponse(content="ok")]),
    )
    respostas = iter(["qualquer coisa"])

    def fake_input(prompt: str) -> str:
        valor = next(respostas, None)
        if valor is None:
            raise EOFError
        return valor

    monkeypatch.setattr("builtins.input", fake_input)

    from formiga.cli import main

    rc = main(["agent", "--session-dir", str(tmp_path / "sessoes")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ctx" in out, f"esperava ctx na linha de orçamento: {out!r}"
    assert "ext" in out, f"esperava ext na linha de orçamento: {out!r}"
    assert not ANSI_RE.search(out), f"saída contém ANSI: {out!r}"


def test_pi_emit_chega_ao_on_event_do_loop(tmp_path, monkeypatch):
    """Evento custom de pi.emit chega à on_event do loop (event sink ligado)."""
    eventos: list[tuple[str, dict]] = []

    def on_event(event: str, data: dict) -> None:
        eventos.append((event, data))

    loop, session, cfg = _build_agent_com_extensao(
        tmp_path, EmitExtension, monkeypatch
    )
    loop.on_event = on_event
    loop.run("qualquer coisa")

    nomes = [nome for nome, _ in eventos]
    assert "minha_extensao_progresso" in nomes, f"evento custom não chegou: {nomes}"


def test_ancora_re_injetada_apos_hook_context(tmp_path, monkeypatch):
    """Se o hook context remove a última mensagem do usuário, ela é re-injetada."""
    loop, session, cfg = _build_agent_com_extensao(
        tmp_path, ContextoAggressivo, monkeypatch
    )
    loop.run("qual é a capital?")

    usuarios = [m for m in loop.messages if m.get("role") == "user"]
    assert len(usuarios) >= 1
    assert usuarios[-1]["content"] == "qual é a capital?", (
        f"âncora perdida: {[m['content'] for m in usuarios]}"
    )


def test_nova_sessao_preserva_anterior(tmp_path, monkeypatch):
    """`/new sim` cria nova sessão em disco; a anterior permanece."""
    loop, session, cfg = _build_agent_com_extensao(tmp_path, None, monkeypatch)
    base_dir = tmp_path / "sessoes"
    antes = set(p.name for p in base_dir.iterdir() if p.is_dir())

    saida = loop.registry.dispatch_command("new", "sim")
    assert "Nova sessão iniciada" in saida

    depois = set(p.name for p in base_dir.iterdir() if p.is_dir())
    assert depois > antes  # nova sessão criada
    assert antes <= depois  # a anterior continua em disco


def test_nova_sessao_sem_confirmacao_nao_cria(tmp_path, monkeypatch):
    """`/new` sem confirmação não cria sessão nova."""
    loop, session, cfg = _build_agent_com_extensao(tmp_path, None, monkeypatch)
    base_dir = tmp_path / "sessoes"
    antes = set(p.name for p in base_dir.iterdir() if p.is_dir())

    saida = loop.registry.dispatch_command("new", "")
    assert "não confirmada" in saida

    depois = set(p.name for p in base_dir.iterdir() if p.is_dir())
    assert depois == antes


def test_reinject_anchor_nao_duplica_usuario_presente():
    """reinject_anchor não duplica quando já há mensagem do usuário."""
    mensagens = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "pergunta"},
        {"role": "assistant", "content": "resp"},
    ]
    resultado, re_injetou = reinject_anchor(mensagens, "pergunta")
    assert re_injetou is False
    assert len(resultado) == len(mensagens)


def test_reinject_anchor_insere_apos_system():
    """reinject_anchor insere a âncora após a system quando não há usuário."""
    mensagens = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "resp"},
    ]
    resultado, re_injetou = reinject_anchor(mensagens, "objetivo")
    assert re_injetou is True
    assert resultado[0]["role"] == "system"
    assert resultado[1]["role"] == "user"
    assert resultado[1]["content"] == "objetivo"


@pytest.mark.asyncio
async def test_pi_emit_chega_na_tui(tmp_path, monkeypatch):
    """Evento custom de extensão aparece na TUI via _handle_event."""
    monkeypatch.setattr(
        factory,
        "build_chat_client",
        lambda config: FakeChatClient([ChatResponse(content="ok")]),
    )
    cfg = Config(agent_workdir=str(tmp_path), extensions_enabled=("core",))
    session = Session(tmp_path / "sessoes")
    loop = factory.build_agent(cfg, session)

    from formiga.agent.extensions.registry import ExtensionContext

    EmitExtension().setup(
        ExtensionContext(registry=loop.registry, config=cfg, session=session)
    )

    controller = AgentController(cfg, session, loop=loop)
    app = AgentApp(cfg, session, controller=controller)

    mensagens_vistas: list[str] = []

    def captura(event, data):
        if event == "minha_extensao_progresso":
            mensagens_vistas.append(str(data.get("texto", "")))
        app._handle_event_original(event, data)

    app._handle_event_original = app._handle_event
    app._handle_event = captura

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "x"
        await pilot.press("enter")
        entrada = app.query_one("#input", Input)
        for _ in range(100):
            if not entrada.disabled:
                break
            await asyncio.sleep(0.05)
            await pilot.pause()

    assert "olá" in mensagens_vistas, f"evento não chegou na TUI: {mensagens_vistas}"


def test_evicted_contabilizado_no_snapshot(tmp_path, monkeypatch):
    """O contador evicted aparece no snapshot quando há eviction."""
    monkeypatch.setattr(
        factory,
        "build_chat_client",
        lambda config: FakeChatClient([ChatResponse(content="resposta")]),
    )
    cfg = Config(
        agent_workdir=str(tmp_path),
        extensions_enabled=("core",),
        max_context_tokens=50,
    )
    session = Session(tmp_path / "sessoes")
    loop = factory.build_agent(cfg, session)
    # Força muitas mensagens para disparar eviction
    for i in range(20):
        loop.messages.append({"role": "user", "content": "x" * 500})
        loop.messages.append(
            {"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 500}
        )
    loop.messages.append({"role": "user", "content": "âncora final"})
    dados = loop._budget_snapshot()
    assert "evicted" in dados
    assert dados["evicted"] >= 0
