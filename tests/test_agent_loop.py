"""Testes do loop agêntico com cliente de chat falso (offline)."""

from __future__ import annotations

from formiga.agent.chat import ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool
from formiga.config import Config
from tests.fakes_agent import FakeChatClient, tool_call


def _make_loop(tmp_path, responses, **overrides):
    cfg = Config()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    tools = [LsTool(tmp_path)]
    chat = FakeChatClient(responses)
    session = Session(tmp_path / "sessoes")
    return AgentLoop(chat, tools, session, cfg), chat


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
