"""Smoke offline do MVP (critérios de aceite do PRD §13) — sem rede/modelo.

Tarefa mista com fakes: ler arquivo → rodar comando → web_search →
web_fetch → resposta direta, sem acionar `deep_search`; orçamentos de web
respeitados; sessão persistida no disco.
"""

from __future__ import annotations

import json

from formiga.agent.chat import ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool, ReadTool
from formiga.agent.tools.shell import BashTool
from formiga.agent.tools.web import WebFetchTool, WebSearchTool
from formiga.config import Config
from formiga.search import SearchResult
from tests.fakes_agent import (
    FakeChatClient,
    FakeFetcher,
    FakeSearchProvider,
    tool_call,
)


def _tools(tmp_path, cfg, searcher, fetcher):
    return [
        LsTool(tmp_path),
        ReadTool(tmp_path),
        BashTool(tmp_path),
        WebSearchTool(cfg, searcher=searcher),
        WebFetchTool(cfg, fetcher=fetcher),
    ]


def test_smoke_tarefa_mista_sem_deep_search(tmp_path):
    """ler → bash → web_search → web_fetch → resposta, tudo no disco."""
    (tmp_path / "notas.txt").write_text("identificador: formiga-42")

    searcher = FakeSearchProvider(
        {
            "formiga-42": [
                SearchResult(
                    url="https://exemplo.com/pagina",
                    title="Página do identificador",
                    snippet="menciona formiga-42",
                )
            ]
        }
    )
    fetcher = FakeFetcher(
        pages={
            "https://exemplo.com/pagina": (
                "<html><body><h1>Página</h1><p>Conteúdo relevante "
                "sobre formiga-42.</p></body></html>"
            )
        }
    )
    cfg = Config()
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("read", '{"path": "notas.txt"}')]),
            ChatResponse(tool_calls=[tool_call("bash", '{"command": "echo passo-2"}')]),
            ChatResponse(tool_calls=[tool_call("web_search", '{"query": "formiga-42"}')]),
            ChatResponse(
                tool_calls=[tool_call("web_fetch", '{"url": "https://exemplo.com/pagina"}')]
            ),
            ChatResponse(
                content=(
                    "Resposta fundamentada: identificador formiga-42 nas notas, "
                    "passo-2 executado e página consultada confirma o contexto."
                )
            ),
        ]
    )
    session = Session(tmp_path / "sessoes")
    loop = AgentLoop(chat, _tools(tmp_path, cfg, searcher, fetcher), session, cfg)
    resposta = loop.run("Tarefa mista: confira notas, rode um comando e pesquise o identificador.")

    assert "Resposta fundamentada" in resposta
    assert len(chat.calls) == 5

    # orçamentos: 1 web_search + 1 web_fetch; deep_search nunca acionado
    assert loop.tool_budgets.web_searches_used == 1
    assert loop.tool_budgets.web_fetches_used == 1
    assert loop.tool_budgets.deep_searches_used == 0

    # sessão persistida: mensagens com a resposta final; eventos com as tools
    mensagens = json.loads(session.messages_path.read_text(encoding="utf-8"))
    assert any("Resposta fundamentada" in m.get("content", "") for m in mensagens)
    eventos = [
        json.loads(linha)
        for linha in session.events_path.read_text(encoding="utf-8").splitlines()
    ]
    tools_executadas = [e["data"]["tool"] for e in eventos if e["type"] == "tool_call"]
    assert tools_executadas == ["read", "bash", "web_search", "web_fetch"]
    assert all(e["data"]["ok"] for e in eventos if e["type"] == "tool_call")


def test_smoke_orcamento_web_respeitado_na_tarefa_mista(tmp_path):
    """Com orçamento de web em 1, a 2ª chamada web devolve `ERRO:` orçamental."""
    searcher = FakeSearchProvider(
        {
            "a": [SearchResult(url="https://a.com", title="A", snippet="s")],
            "b": [SearchResult(url="https://b.com", title="B", snippet="s")],
        }
    )
    fetcher = FakeFetcher()
    cfg = Config()
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("web_search", '{"query": "a"}')]),
            ChatResponse(tool_calls=[tool_call("web_search", '{"query": "b"}')]),
            ChatResponse(content="Respondo com o que consegui."),
        ]
    )
    session = Session(tmp_path / "sessoes")
    # orçamento padrão: max_web_searches=6 → configuramos 1
    cfg.agent_max_web_searches = 1
    loop = AgentLoop(chat, _tools(tmp_path, cfg, searcher, fetcher), session, cfg)
    resposta = loop.run("busque a e b")
    assert "Respondo com o que consegui" in resposta
    assert loop.tool_budgets.web_searches_used == 1
    # o 2º web_search não executou; o contexto orçamental foi ao modelo
    segunda = chat.calls[1][0]
    ultimas = [m["content"] for m in segunda if m["role"] == "tool"]
    assert any("orçamento de web_search esgotado" in m for m in ultimas)
