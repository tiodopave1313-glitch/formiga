"""Testes da CLI interativa padrão (offline, fakes — sem rede/modelo real)."""

from __future__ import annotations

import builtins

from formiga.agent.chat import ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool
from formiga.cli import main
from formiga.config import Config
from formiga.llm import LLMError
from tests.fakes_agent import FakeChatClient, registry_of, tool_call


def _make_loop(tmp_path, responses: list[ChatResponse]) -> tuple[AgentLoop, Session]:
    cfg = Config()
    session = Session(tmp_path / "sessoes")
    chat = FakeChatClient(responses)
    loop = AgentLoop(chat, registry_of(LsTool(tmp_path), config=cfg), session, cfg)
    return loop, session


def test_cli_interativa_fluxo(tmp_path, monkeypatch, capsys):
    """CLI interativa: pergunta -> stream -> tool -> resposta -> budget -> prompt -> Ctrl+D."""
    (tmp_path / "a.txt").write_text("x")
    responses = [
        ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
        ChatResponse(content="Encontrei a.txt.", deltas=["Encon", "trei a.txt."]),
    ]

    def fake_build(config):
        return FakeChatClient(responses)

    monkeypatch.setattr(
        __import__("formiga.agent.factory", fromlist=["x"]),
        "build_chat_client",
        fake_build,
    )

    # input: primeira pergunta + Ctrl+D (raise)
    input_calls = {"n": 0}

    def fake_input(prompt: str) -> str:
        input_calls["n"] += 1
        if input_calls["n"] == 1:
            return "liste os arquivos"
        raise EOFError

    monkeypatch.setattr(builtins, "input", fake_input)

    rc = main(
        [
            "agent",
            "--session-dir",
            str(tmp_path / "sessoes"),
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out

    # cabeçalho
    assert "formiga agent · sessão:" in out
    assert "Ctrl+C interrompe" in out

    # tool executada
    assert "⚙ ls — path=." in out
    assert "(0." in out and "s)" in out  # duração

    # resposta stream
    assert "Encontrei a.txt." in out

    # linha de orçamento entre turnos
    assert "turnos 1/" in out
    assert "llm " in out

    # despedida
    assert "Saindo. Sessão salva em" in out


def test_cli_interativa_funciona_sem_textual(tmp_path, monkeypatch):
    """CLI padrão funciona mesmo com textual quebrado (instalação base sem extra)."""
    import builtins

    real_import = builtins.__import__

    def quebra_textual(name, *a, **k):
        if name == "formiga.agent.tui" or name.startswith("formiga.agent.tui."):
            raise ImportError("No module named 'textual'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", quebra_textual)

    # input: Ctrl+D imediato (raise)
    def fake_input(prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr(builtins, "input", fake_input)

    from formiga.cli import main
    rc = main(["agent", "--session-dir", str(tmp_path / "sessoes")])

    assert rc == 0  # CLI padrão roda sem TUI


def test_cli_flag_tui_abre_app(tmp_path, monkeypatch):
    """`formiga agent --tui` abre a TUI Textual."""
    from formiga.cli import main

    aberto = {}

    class FakeApp:
        def __init__(self, config, session, initial_question=None) -> None:
            aberto["question"] = initial_question
            aberto["session_dir"] = str(session.base_dir)

        def run(self) -> None:
            aberto["ran"] = True

    import formiga.agent.tui as tui

    monkeypatch.setattr(tui, "AgentApp", FakeApp)

    rc = main(
        [
            "agent",
            "pergunta pré-preenchida",
            "--tui",
            "--session-dir",
            str(tmp_path / "sessoes"),
        ]
    )

    assert rc == 0
    assert aberto["ran"] is True
    assert aberto["question"] == "pergunta pré-preenchida"


def test_cli_tui_sem_extra_erro(tmp_path, monkeypatch):
    """Sem textual, `formiga agent --tui` falha com mensagem clara (não crash)."""
    import builtins

    real_import = builtins.__import__

    def quebra_textual(name, *a, **k):
        if name == "formiga.agent.tui" or name.startswith("formiga.agent.tui."):
            raise ImportError("No module named 'textual'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", quebra_textual)

    from formiga.cli import main

    rc = main(["agent", "--tui", "--session-dir", str(tmp_path / "sessoes")])

    assert rc == 1


def test_cli_interativa_llm_error_continua(tmp_path, monkeypatch, capsys):
    """Erro do modelo não derruba a CLI — continua no prompt."""
    # primeira chamada: erro; segunda: sucesso
    call_count = {"n": 0}

    class ChatQueFalhaUmaVez:
        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise LLMError("HTTP 400 do endpoint remoto: invalid request")
            # segunda chamada: simula streaming via on_delta
            if on_delta is not None:
                on_delta("funcionou na segunda.")
            return ChatResponse(content="funcionou na segunda.")

    def fake_build(config):
        return ChatQueFalhaUmaVez()

    monkeypatch.setattr(
        __import__("formiga.agent.factory", fromlist=["x"]),
        "build_chat_client",
        fake_build,
    )

    # input: primeira -> erro -> segunda -> Ctrl+D (raise)
    call_count_input = {"n": 0}

    def fake_input(prompt: str) -> str:
        call_count_input["n"] += 1
        if call_count_input["n"] == 1:
            return "pergunta que falha"
        if call_count_input["n"] == 2:
            return "pergunta que funciona"
        raise EOFError

    monkeypatch.setattr(builtins, "input", fake_input)

    rc = main(["agent", "--session-dir", str(tmp_path / "sessoes")])

    assert rc == 0
    out = capsys.readouterr().out
    assert "✗ erro: HTTP 400" in out
    assert "funcionou na segunda." in out


def test_cli_print_exit_interrupted(tmp_path, monkeypatch, capsys):
    """`--print` com KeyboardInterrupt retorna 130 e imprime parcial."""
    call_count = {"n": 0}

    class ChatQueInterrompe:
        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise KeyboardInterrupt()
            return ChatResponse(content="não chega aqui")

    def fake_build(config):
        return ChatQueInterrompe()

    monkeypatch.setattr(
        __import__("formiga.agent.factory", fromlist=["x"]),
        "build_chat_client",
        fake_build,
    )

    rc = main(
        [
            "agent",
            "pergunta",
            "--print",
            "--session-dir",
            str(tmp_path / "sessoes"),
        ]
    )

    assert rc == 130  # EXIT_INTERRUPTED
    out = capsys.readouterr().out
    assert "Interrompido pelo usuário" in out
    assert "Resposta parcial" in out