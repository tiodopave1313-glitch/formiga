"""Testes da TUI com Textual pilot (offline, fakes — PRD §12)."""

from __future__ import annotations

import asyncio
import threading

from textual.containers import VerticalScroll
from textual.widgets import Input

from formiga.agent.chat import ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool
from formiga.agent.tui.app import AgentApp, ToolDetailsScreen
from formiga.agent.tui.controller import AgentController
from formiga.config import Config
from tests.fakes_agent import FakeChatClient, tool_call


def _app(tmp_path, chat, initial_question=None):
    cfg = Config()
    session = Session(tmp_path / "sessoes")
    loop = AgentLoop(chat, [LsTool(tmp_path)], session, cfg)
    controller = AgentController(cfg, session, loop=loop)
    app = AgentApp(cfg, session, initial_question=initial_question, controller=controller)
    return app, controller


async def _esperar_idle(app, controller, piloto, timeout=5.0):
    """Aguarda o fim da execução: entrada é reabilitada no `run_done`."""
    entrada = app.query_one("#input", Input)
    for _ in range(int(timeout / 0.05)):
        if not entrada.disabled:
            break
        await asyncio.sleep(0.05)
        await piloto.pause()


def transcript_text(app) -> str:
    container = app.query_one("#transcript", VerticalScroll)
    return "\n".join(str(w.render()) for w in container.children)


async def test_abertura_com_boas_vindas_e_aviso(tmp_path):
    app, _ = _app(tmp_path, FakeChatClient([]))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        texto = transcript_text(app)
        assert "formiga agent" in texto
        assert "Aviso" in texto
        assert "chave de api nunca aparece" in texto.lower()


async def test_no_color_funciona(tmp_path, monkeypatch):
    """NO_COLOR=1: a TUI roda e o texto permanece legível."""
    monkeypatch.setenv("NO_COLOR", "1")
    chat = FakeChatClient([ChatResponse(content="resposta sem cores.")])
    app, controller = _app(tmp_path, chat)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "oi"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        texto = transcript_text(app)
        assert "resposta sem cores." in texto
        status = str(app.query_one("#status").render())
        assert "turnos" in status  # estado transmitido sem depender de cor


async def test_pergunta_pre_preenchida(tmp_path):
    app, _ = _app(tmp_path, FakeChatClient([]), initial_question="Minha pergunta")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.query_one("#input", Input).value == "Minha pergunta"


async def test_stream_visivel_no_transcript(tmp_path):
    chat = FakeChatClient([ChatResponse(content="Resposta final.", deltas=["Resposta", " final."])])
    app, controller = _app(tmp_path, chat)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "oi"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        texto = transcript_text(app)
        assert "Você" in texto
        assert "Agent" in texto
        assert "Resposta final." in texto


async def test_evento_de_ferramenta_em_linha(tmp_path):
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="listei."),
        ]
    )
    app, controller = _app(tmp_path, chat)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "liste"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        texto = transcript_text(app)
        assert "⚙ ls — path=." in texto


async def test_esc_com_confirmacao_interrompe(tmp_path):
    release = threading.Event()

    class ChatBloqueante:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            self.calls += 1
            release.wait(timeout=5.0)
            return ChatResponse(content="pronto")

    app, controller = _app(tmp_path, ChatBloqueante())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "tarefa longa"
        await pilot.press("enter")
        # execução em curso
        for _ in range(50):
            if controller.running:
                break
            await asyncio.sleep(0.02)
            await pilot.pause()
        assert controller.running

        # 1ª Esc: armazena interrupção, padrão continuar
        await pilot.press("escape")
        status = str(app.query_one("#status").render())
        assert "interrompendo" in status
        # timer de confirmação ainda não passou; confirma com a 2ª Esc
        await pilot.press("escape")
        assert app.controller.loop.cancelled

        # libera o modelo; o loop confirma a interrupção na fronteira
        release.set()
        await _esperar_idle(app, controller, pilot)
        texto = transcript_text(app)
        assert "interrompido pelo usuário" in texto.lower()
        assert app.query_one("#input", Input).disabled is False


async def test_esc_sem_confirmacao_volta_a_executar(tmp_path):
    release = threading.Event()

    class ChatBloqueante:
        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            release.wait(timeout=5.0)
            return ChatResponse(content="pronto")

    app, controller = _app(tmp_path, ChatBloqueante())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "tarefa"
        await pilot.press("enter")
        for _ in range(50):
            if controller.running:
                break
            await asyncio.sleep(0.02)
            await pilot.pause()
        await pilot.press("escape")
        # expira o timer de confirmação (3 s) — padrão: continuar
        await asyncio.sleep(3.2)
        await pilot.pause()
        assert not app.controller.loop.cancelled
        status = str(app.query_one("#status").render())
        assert "executando" in status
        release.set()
        await _esperar_idle(app, controller, pilot)


async def test_ctrl_o_mostra_ultimo_resultado(tmp_path):
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="ok."),
        ]
    )
    (tmp_path / "arquivo.txt").write_text("conteudo")
    app, controller = _app(tmp_path, chat)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "liste"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, ToolDetailsScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ToolDetailsScreen)


async def test_historico_setas_na_entrada(tmp_path):
    chat = FakeChatClient([ChatResponse(content="r1"), ChatResponse(content="r2")])
    app, controller = _app(tmp_path, chat)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one("#input", Input)
        inp.value = "primeira"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        inp.value = "segunda"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        assert inp.value == ""
        await pilot.press("up")  # última do histórico
        assert inp.value == "segunda"
        await pilot.press("up")
        assert inp.value == "primeira"
        await pilot.press("down")
        assert inp.value == "segunda"


async def test_entrada_desabilitada_durante_execucao(tmp_path):
    release = threading.Event()

    class ChatBloqueante:
        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            release.wait(timeout=5.0)
            return ChatResponse(content="pronto")

    app, controller = _app(tmp_path, ChatBloqueante())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one("#input", Input)
        inp.value = "tarefa"
        await pilot.press("enter")
        for _ in range(50):
            if controller.running:
                break
            await asyncio.sleep(0.02)
            await pilot.pause()
        assert inp.disabled is True
        release.set()
        await _esperar_idle(app, controller, pilot)
        assert inp.disabled is False


async def test_barra_de_status_orcamento(tmp_path):
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="ok"),
        ]
    )
    app, controller = _app(tmp_path, chat)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.query_one("#input", Input).value = "liste"
        await pilot.press("enter")
        await _esperar_idle(app, controller, pilot)
        status = str(app.query_one("#status").render())
        # turnos e chamadas refletindo o loop (1 tool call + resposta final)
        assert "chamadas 2/" in status
        assert "ocioso" in status
