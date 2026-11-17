"""Endurecimento (Fase 4): anti-loop completo, caps, TUI pequena, credenciais.

Cobre os critérios de aceite do PRD (§13) que não tinham teste dedicado:
- nudge em 2 chamadas idênticas (encerramento em 4 já coberto em
  `test_agent_loop.py`);
- `web_fetch` com orçamento esgotado devolve `ERRO:` orçamental;
- relatório do `deep_search` persiste no disco (`sessoes/<sessão>/research/`);
- TUI funciona em terminais menores que 80×24;
- credenciais não aparecem em nenhum artefato do disco.
"""

from __future__ import annotations

from formiga.agent.chat import ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool, ReadTool
from formiga.agent.tools.shell import BashTool
from formiga.agent.tools.web import WebFetchTool
from formiga.config import Config
from tests.fakes_agent import (
    FakeChatClient,
    FakeFetcher,
    FakeOrchestrator,
    registry_of,
    tool_call,
)
from tests.test_agent_deepsearch import _config as deep_config


def _loop(tmp_path, responses, tools, **overrides):
    cfg = Config()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    chat = FakeChatClient(responses)
    session = Session(tmp_path / "sessoes")
    return AgentLoop(chat, registry_of(*tools, config=cfg), session, cfg), chat, session


def test_anti_loop_nudge_em_2_chamadas_iguais_via_loop(tmp_path):
    """Duas chamadas idênticas → nudge no contexto; caminho diferente passa."""
    (tmp_path / "a.txt").write_text("x")
    loop, chat, _ = _loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "a.txt"}')]),
            ChatResponse(content="Resolvi com caminho diferente."),
        ],
        tools=[LsTool(tmp_path)],
    )
    resposta = loop.run("liste")
    assert "Resolvi com caminho diferente" in resposta
    # o nudge (2ª chamada) chegou ao modelo como contexto de ferramenta
    segunda_chamada = chat.calls[1][0]
    mensagens = [m["content"] for m in segunda_chamada if m["role"] == "tool"]
    assert any("mesmos argumentos" in m for m in mensagens)


def test_web_fetch_orcamento_esgotado_retorna_erro_orcamental(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    fetcher = FakeFetcher(pages={"https://a.com/1": "<html>p1</html>"})
    cfg = Config()
    loop, chat, _ = _loop(
        tmp_path,
        [
            ChatResponse(tool_calls=[tool_call("web_fetch", '{"url": "https://a.com/1"}')]),
            # URL diferente: sem anti-loop, o bloqueio é orçamental
            ChatResponse(tool_calls=[tool_call("web_fetch", '{"url": "https://b.com/x"}')]),
            ChatResponse(content="Fim com orçamento respeitado."),
        ],
        tools=[WebFetchTool(cfg, fetcher=fetcher)],
        agent_max_web_fetches=1,
    )
    resposta = loop.run("busque a página")
    assert "Fim com orçamento respeitado" in resposta
    assert len(fetcher.fetched) == 1  # 2ª chamada bloqueada antes do fetch
    eventos = loop.session.events_path.read_text(encoding="utf-8")
    assert any("budget_exhausted" in linha for linha in eventos.splitlines())
    # o modelo recebeu o erro orçamental como contexto
    segunda = chat.calls[1][0]
    ultimas = [m["content"] for m in segunda if m["role"] == "tool"]
    assert any("orçamento de web_fetch esgotado" in m for m in ultimas)


def test_deep_search_relatorio_persistido_no_disco(tmp_path):
    orchestrator = FakeOrchestrator(
        sources=[{"title": "Fonte A", "requested_url": "https://a.com"}]
    )
    cfg = deep_config()
    session = Session(tmp_path / "sessoes")
    tools = [LsTool(tmp_path), DeepSearch(cfg, session.research_dir, orchestrator)]
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("deep_search", '{"question": "qual impacto X?"}')]),
            ChatResponse(content="Respondi com base no relatório."),
        ]
    )
    loop = AgentLoop(chat, registry_of(*tools, config=cfg), session, cfg)
    resposta = loop.run("pesquise X")
    assert "Respondi" in resposta
    reports = list(session.research_dir.glob("*/report.md"))
    assert reports, "relatório do deep_search não ficou no disco"
    assert "Relatório simulado" in reports[0].read_text(encoding="utf-8")
    assert loop.tool_budgets.used.get("deep_search", 0) == 1


from formiga.agent.tools.deepsearch import DeepSearchTool as DeepSearch  # noqa: E402


def test_tui_terminais_pequenos_nao_quebram(tmp_path):
    """60×20 e 40×12: a TUI compõe, streama e não levanta exceção."""
    import asyncio

    from textual.widgets import Input

    from formiga.agent.tui.app import AgentApp
    from formiga.agent.tui.controller import AgentController

    async def _run(size):
        cfg = Config()
        session = Session(tmp_path / f"sessoes-{size[0]}")
        chat = FakeChatClient([ChatResponse(content="resposta em tela pequena.")])
        loop = AgentLoop(chat, registry_of(ReadTool(tmp_path), config=cfg), session, cfg)
        controller = AgentController(cfg, session, loop=loop)
        app = AgentApp(cfg, session, controller=controller)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            inp = app.query_one("#input", Input)
            inp.value = "oi"
            await pilot.press("enter")
            for _ in range(80):
                if not inp.disabled:
                    break
                await asyncio.sleep(0.05)
                await pilot.pause()
            # transcript montado sem erro, entrada reabilitada
            texto = "\n".join(str(w.render()) for w in app.query_one("#transcript").children)
            assert "resposta em tela pequena." in texto
            assert not inp.disabled

    asyncio.run(_run((60, 20)))
    asyncio.run(_run((40, 12)))


def test_credenciais_nao_aparecem_em_artefatos(tmp_path):
    """A chave de API não vaza para messages.json, events.jsonl ou repr."""
    segredo = "sk-chave-muito-secreta-123"
    cfg = Config(openai_api_key=segredo, llm_backend="openai")
    tools = [LsTool(tmp_path), BashTool(tmp_path)]
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="fecho."),
        ]
    )
    session = Session(tmp_path / "sessoes")
    loop = AgentLoop(chat, registry_of(*tools, config=cfg), session, cfg)
    loop.run("liste")

    for arquivo in session.dir.iterdir():
        conteudo = arquivo.read_text(encoding="utf-8")
        assert segredo not in conteudo, f"credencial vazou em {arquivo.name}"
    # nem no repr dos clientes (logs com repr não podem expor a chave)
    from formiga.openai import OpenAIClient

    cliente = OpenAIClient(cfg)
    assert segredo not in repr(cliente)


# --------------------------------------------------------------------------
# CLI: `formiga agent` abre CLI interativa; `--tui` abre TUI; `--print` headless.


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


def test_cli_print_headless_com_fake(tmp_path, monkeypatch):
    from formiga.agent.factory import build_chat_client
    from formiga.cli import main

    def fake_build(config):
        return FakeChatClient([ChatResponse(content="resposta headless.")])

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
    assert rc == 0
    # o build original não foi quebrado (restaurado pelo monkeypatch)
    assert build_chat_client is not None


def test_cli_print_sem_pergunta_erro(tmp_path):
    from formiga.cli import main

    rc = main(["agent", "--print", "--session-dir", str(tmp_path / "sessoes")])
    assert rc == 2


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
