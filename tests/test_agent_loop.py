"""Testes do loop agêntico com cliente de chat falso (offline)."""

from __future__ import annotations

import json

from formiga.agent.chat import ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool
from formiga.agent.tools.shell import BashTool
from formiga.config import Config
from tests.fakes_agent import FakeChatClient, FakeOrchestrator, registry_of, tool_call


def _make_loop(tmp_path, responses, deep_search_fn=None, searcher=None, **overrides):
    cfg = Config()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    tools = [LsTool(tmp_path), BashTool(tmp_path)]
    from formiga.agent.tools.web import WebFetchTool, WebSearchTool

    tools.append(WebSearchTool(cfg, searcher=searcher))
    tools.append(WebFetchTool(cfg))
    if deep_search_fn is not None:
        from formiga.agent.tools.deepsearch import DeepSearchTool

        tools.append(DeepSearchTool(cfg, tmp_path / "research", run_fn=deep_search_fn))
    chat = FakeChatClient(responses)
    session = Session(tmp_path / "sessoes")
    return AgentLoop(chat, registry_of(*tools, config=cfg), session, cfg), chat


def test_turn_normal_executa_ferramenta_e_retorna_resposta(tmp_path):
    (tmp_path / "arquivo.txt").write_text("conteudo")
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="Resultado: arquivo.txt encontrado."),
        ],
    )
    resposta = loop.run("liste os arquivos")
    assert resposta == "Resultado: arquivo.txt encontrado."
    assert len(chat.calls) == 2  # uma com tool call, uma com texto final


def test_erro_de_parser_via_erro_no_contexto(tmp_path):
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(
                tool_calls=[
                    tool_call("ls", "{não é json válido")
                ]
            ),
            ChatResponse(content="Não consegui listar, mas segue a resposta."),
        ],
    )
    resposta = loop.run("liste os arquivos")
    assert "Não consegui listar" in resposta
    assert len(chat.calls) == 2


def test_anti_loop_quatro_chamadas_iguais_encerra_turno(tmp_path):
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="Desisti depois de tentativas repetidas."),
        ],
        agent_max_turns=24,
        agent_max_llm_calls=120,
    )
    resposta = loop.run("liste os arquivos")
    assert "Desisti depois" in resposta
    assert len(chat.calls) == 5


def test_orcamento_de_turnos_esgotado_retorna_parcial(tmp_path):
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
        ],
        agent_max_turns=1,
        agent_max_llm_calls=10,
    )
    resposta = loop.run("liste os arquivos")
    assert "esgotado" in resposta.lower()


def test_orcamento_de_chamadas_llm_esgotado(tmp_path):
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
        ],
        agent_max_turns=10,
        agent_max_llm_calls=1,
    )
    resposta = loop.run("liste os arquivos")
    assert "chamadas ao LLM" in resposta


def test_orcamento_deep_search_esgotado_retorna_erro(tmp_path):
    orchestrator = FakeOrchestrator()
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("deep_search", '{"question": "x"}')]),
            ChatResponse(tool_calls=[tool_call("deep_search", '{"question": "y"}')]),
            ChatResponse(tool_calls=[tool_call("deep_search", '{"question": "z"}')]),
            ChatResponse(content="Resposta depois dos orçamentos."),
        ],
        deep_search_fn=orchestrator,
        agent_max_deep_searches=2,
        agent_max_turns=24,
        agent_max_llm_calls=120,
    )
    resposta = loop.run("pesquise várias coisas")
    assert "Resposta depois dos orçamentos" in resposta
    assert len(chat.calls) == 4
    # O 3º deep_search deve ter sido bloqueado por orçamento.
    eventos = loop.session.events_path.read_text(encoding="utf-8")
    assert any(
        "budget_exhausted" in linha for linha in eventos.splitlines()
    ), f"Nenhum evento de orçamento esgotado em: {eventos}"
    assert loop.tool_budgets.used.get("deep_search", 0) == 2


def test_orcamento_web_search_esgotado_retorna_erro(tmp_path):
    from formiga.search import SearchResult
    from tests.fakes_agent import FakeSearchProvider

    searcher = FakeSearchProvider(
        {
            "a": [SearchResult(url="https://a.com", title="A", snippet="s")],
            "b": [SearchResult(url="https://b.com", title="B", snippet="s")],
            "c": [SearchResult(url="https://c.com", title="C", snippet="s")],
        }
    )
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("web_search", '{"query": "a"}')]),
            ChatResponse(tool_calls=[tool_call("web_search", '{"query": "b"}')]),
            ChatResponse(tool_calls=[tool_call("web_search", '{"query": "c"}')]),
            ChatResponse(content="Resposta."),
        ],
        searcher=searcher,
        agent_max_web_searches=2,
        agent_max_turns=24,
        agent_max_llm_calls=120,
    )
    loop.run("busque várias coisas")
    # O 3º web_search deve ter sido bloqueado por orçamento (evento gravado).
    eventos = loop.session.events_path.read_text(encoding="utf-8")
    tipos = [json.loads(linha)["type"] for linha in eventos.splitlines()]
    assert "tool_call" in tipos
    # O evento de tool_call esgotado deve estar presente
    assert any(
        "budget_exhausted" in linha for linha in eventos.splitlines()
    ), f"Nenhum evento de orçamento esgotado em: {eventos}"
    # E o orçamento foi consumido (2/2)
    assert loop.tool_budgets.used.get("web_search", 0) == 2


def test_orcamentos_reiniciados_por_mensagem(tmp_path):
    # Duas chamadas a `run` devem ter orçamentos independentes.
    loop, chat = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("web_search", '{"query": "a"}')]),
            ChatResponse(content="Resposta 1."),
        ],
        agent_max_web_searches=1,
        agent_max_turns=24,
        agent_max_llm_calls=120,
    )
    r1 = loop.run("mensagem 1")
    assert "Resposta 1." in r1

    # Nova mensagem → novo orçamento de web_search (1 disponível novamente)
    loop2, chat2 = _make_loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("web_search", '{"query": "b"}')]),
            ChatResponse(content="Resposta 2."),
        ],
        agent_max_web_searches=1,
        agent_max_turns=24,
        agent_max_llm_calls=120,
    )
    r2 = loop2.run("mensagem 2")
    assert "Resposta 2." in r2
    assert "esgotado" not in r2.lower()


def test_raciocinio_que_estoura_teto_nao_vira_sem_resposta(tmp_path):
    """Corte por thinking é abstenção explícita, não "(sem resposta)"."""
    loop, chat = _make_loop(
        tmp_path,
        [ChatResponse(content=None, truncated=True, reasoning="pensando muito...")],
    )
    resposta = loop.run("pergunta qualquer")
    assert "raciocínio" in resposta
    assert "limite de geração" in resposta
    assert resposta != "(sem resposta)"
    assert len(chat.calls) == 1
