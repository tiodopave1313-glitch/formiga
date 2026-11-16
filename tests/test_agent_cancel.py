"""Testes de cancelamento cooperativo e eventos do loop (offline, fakes)."""

from __future__ import annotations

from pathlib import Path

from formiga.agent.chat import AgentCancelled, ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool
from formiga.config import Config
from tests.fakes_agent import FakeChatClient, FakeOrchestrator, tool_call


def _make_loop(tmp_path, responses, events, extra_tools=(), **overrides):
    cfg = Config()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    tools = [LsTool(tmp_path), *extra_tools]
    chat = FakeChatClient(responses)
    session = Session(tmp_path / "sessoes")
    loop = AgentLoop(
        chat, tools, session, cfg, on_event=lambda e, d: events.append((e, d))
    )
    return loop, chat


def test_cancel_antes_da_primeira_chamada_retorna_interrompido(tmp_path):
    events: list[tuple[str, dict]] = []
    loop, chat = _make_loop(
        tmp_path,
        [ChatResponse(content="nunca chamado")],
        events,
    )
    loop.cancel()
    resposta = loop.run("liste os arquivos")
    assert "interrompido" in resposta.lower()
    assert len(chat.calls) == 0  # nenhuma chamada ao modelo
    tipos = [t for t, _ in events]
    assert "interrupted" in tipos


def test_cancel_durante_tool_para_apos_a_execucao(tmp_path):
    events: list[tuple[str, dict]] = []
    (tmp_path / "a.txt").write_text("x")

    class CancelandoTool(LsTool):
        """Chama loop.cancel() durante a execução (simula Esc com tool em curso)."""

        def __init__(self, base: Path, loop_ref: dict) -> None:
            super().__init__(base)
            self._loop_ref = loop_ref

        def execute(self, path: str = "."):
            self._loop_ref["loop"].cancel()  # ferramenta termina no próprio timeout
            return super().execute(path)

    holder: dict = {}
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="nunca chega"),
        ],
        events,
        extra_tools=[],
    )
    holder["loop"] = loop
    loop.tools["ls"] = CancelandoTool(tmp_path, holder)

    resposta = loop.run("liste os arquivos")
    assert "interrompido" in resposta.lower()
    assert len(chat.calls) == 1  # não há segunda chamada ao modelo
    tipos = [t for t, _ in events]
    assert "interrupted" in tipos


def test_cancel_durante_stream_interrupcao_confirmada_pelo_loop(tmp_path):
    events: list[tuple[str, dict]] = []
    loop, _ = _make_loop(tmp_path, [], events)

    class ChatQueCancelaNoMeio:
        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            on_delta("pedaco1 ")
            loop.cancel()  # Esc durante o stream
            on_delta("pedaco2")  # levanta AgentCancelled — não é engolida
            raise AssertionError("não deveria chegar aqui")

    loop.chat = ChatQueCancelaNoMeio()
    resposta = loop.run("responda algo")
    assert "interrompido" in resposta.lower()
    tipos = [t for t, _ in events]
    assert "stream" in tipos
    assert "interrupted" in tipos
    # conteúdo parcial transmitido antes do cancelamento está no histórico
    stream_texts = "".join(d.get("text", "") for t, d in events if t == "stream")
    assert "pedaco1 " in stream_texts
    assert "pedaco2" not in stream_texts


def test_eventos_de_ferramenta_em_ordem(tmp_path):
    events: list[tuple[str, dict]] = []
    (tmp_path / "a.txt").write_text("x")
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="feito", deltas=["fei", "to"]),
        ],
        events,
    )
    resposta = loop.run("liste")
    assert resposta == "feito"
    tipos = [t for t, _ in events]
    # llm_call → stream → tool_start → tool_end → llm_call → stream
    assert "llm_call" in tipos and "tool_start" in tipos and "tool_end" in tipos
    assert tipos.index("tool_start") < tipos.index("tool_end")
    stream_texts = "".join(d.get("text", "") for t, d in events if t == "stream")
    assert stream_texts == "feito"


def test_evento_budget_com_snapshot(tmp_path):
    events: list[tuple[str, dict]] = []
    loop, _ = _make_loop(
        tmp_path,
        [ChatResponse(content="pronto")],
        events,
        agent_max_turns=10,
        agent_max_llm_calls=20,
    )
    loop.run("olá")
    budgets = [d for t, d in events if t == "budget"]
    assert budgets, "nenhum evento budget"
    final = budgets[-1]
    assert final["max_turns"] == 10
    assert final["max_llm_calls"] == 20
    assert final["turns"] == 0  # resposta direta não consome turno
    assert final["llm_calls"] == 1


def test_tool_end_carrega_texto_capado(tmp_path):
    events: list[tuple[str, dict]] = []
    (tmp_path / "a.txt").write_text("conteudo")
    loop, _ = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="ok"),
        ],
        events,
    )
    loop.run("liste")
    tool_ends = [d for t, d in events if t == "tool_end"]
    assert tool_ends
    assert tool_ends[0]["ok"] is True
    assert "a.txt" in tool_ends[0]["text"]


def test_deep_search_reexpoe_progresso(tmp_path):
    events: list[tuple[str, dict]] = []
    from formiga.agent.tools.deepsearch import DeepSearchTool

    deep = DeepSearchTool(Config(), tmp_path / "research", run_fn=FakeOrchestrator())
    loop, _ = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("deep_search", '{"question": "x"}')]),
            ChatResponse(content="ok"),
        ],
        events,
        extra_tools=[deep],
    )
    loop.run("pesquise")
    progressos = [d for t, d in events if t == "deep_search_progress"]
    assert progressos, "progresso do motor não foi reexposto"
    mensagens = [p["message"] for p in progressos]
    assert "planejado" in mensagens


def test_agcancelled_e_agente_interrupcao(tmp_path: Path):
    """AgenteCancelled não é LLMError — não dispara fallback de chat."""
    from formiga.llm import LLMError

    assert not issubclass(AgentCancelled, LLMError)
