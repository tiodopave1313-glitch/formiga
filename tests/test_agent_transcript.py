"""Transcript legível da sessão (transcript.md) — toda a seção em arquivo.

O transcript grava, em Markdown, a mesma sequência que a TUI exibe:
pergunta do usuário, texto do agent (stream), linhas de ferramenta com
duração, progresso do deep_search, interrupções, respostas parciais e
erros do modelo.
"""

from __future__ import annotations

import json
import re

from formiga.agent.chat import ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool
from formiga.agent.tools.shell import BashTool
from formiga.config import Config
from formiga.llm import LLMError
from tests.fakes_agent import FakeChatClient, registry_of, tool_call


def _loop(tmp_path, chat, tools, **overrides):
    cfg = Config()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    session = Session(tmp_path / "sessoes")
    return AgentLoop(chat, registry_of(*tools, config=cfg), session, cfg), session


def test_transcript_tarefa_completa(tmp_path):
    """Você → Agent (stream) → tool com duração → Agent novamente."""
    (tmp_path / "a.txt").write_text("x")
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(content="Encontrei a.txt.", deltas=["Encon", "trei a.txt."]),
        ]
    )
    loop, session = _loop(tmp_path, chat, [LsTool(tmp_path)])
    loop.run("liste os arquivos")

    texto = session.transcript_path.read_text(encoding="utf-8")
    assert "## Você\nliste os arquivos" in texto
    assert "## Agent\nEncontrei a.txt." in texto  # deltas concatenados
    assert "⚙ ls — path=." in texto
    assert re.search(r"\(\d+\.\d+ s\)", texto)  # duração da ferramenta
    # o texto final aparece uma única vez (deltas, não run_final repetido)
    assert texto.count("Encontrei a.txt.") == 1


def test_transcript_interrupcao(tmp_path):
    events: list[tuple[str, dict]] = []
    chat = FakeChatClient([])
    loop, session = _loop(tmp_path, chat, [LsTool(tmp_path)])

    class ChatQueCancelaNoMeio:
        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            on_delta("pedaco parcial ")
            loop.cancel()
            on_delta("mais um pedaco")
            raise AssertionError("não deveria chegar aqui")

    loop.chat = ChatQueCancelaNoMeio()
    loop.on_event = lambda e, d: events.append((e, d))
    loop.run("responda algo")

    texto = session.transcript_path.read_text(encoding="utf-8")
    assert "## Você\nresponda algo" in texto
    assert "## Agent\npedaco parcial" in texto
    assert "mais um pedaco" not in texto  # delta pós-cancel não gravou
    assert "— interrompido pelo usuário —" in texto
    assert "Resposta parcial: a execução foi" in texto  # resposta parcial


def test_transcript_orcamento_esgotado(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    chat = FakeChatClient(
        [
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')]),
            ChatResponse(tool_calls=[tool_call("ls", '{"path": "a.txt"}')]),
        ]
    )
    loop, session = _loop(
        tmp_path, chat, [LsTool(tmp_path)], agent_max_llm_calls=2
    )
    resposta = loop.run("liste")
    assert "orçamento" in resposta.lower()

    texto = session.transcript_path.read_text(encoding="utf-8")
    assert "⚙ ls — path=." in texto
    assert "⚙ ls — path=a.txt" in texto
    assert "Resposta parcial: o orçamento da sessão foi esgotado" in texto


def test_transcript_erro_do_modelo(tmp_path):
    class FalhaSempre:
        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            raise LLMError("HTTP 400 do endpoint remoto: invalid request")

    loop, session = _loop(tmp_path, FalhaSempre(), [LsTool(tmp_path)])
    with __import__("pytest").raises(LLMError):
        loop.run("pergunta que falha")

    texto = session.transcript_path.read_text(encoding="utf-8")
    assert "## Você\npergunta que falha" in texto
    assert "✗ erro: HTTP 400" in texto


def test_transcript_comando_bash_e_multiplos_turnos(tmp_path):
    """Duas perguntas na mesma sessão: transcript acumula as seções."""
    chat = FakeChatClient(
        [
            ChatResponse(content="primeira resposta"),
            ChatResponse(tool_calls=[tool_call("bash", '{"command": "echo oi"}')]),
            ChatResponse(content="segunda resposta"),
        ]
    )
    loop, session = _loop(tmp_path, chat, [BashTool(tmp_path)])
    loop.run("pergunta 1")
    loop.run("pergunta 2")

    texto = session.transcript_path.read_text(encoding="utf-8")
    assert texto.count("## Você") == 2
    assert "pergunta 1" in texto and "pergunta 2" in texto
    assert "⚙ bash — command=echo oi" in texto
    assert "primeira resposta" in texto and "segunda resposta" in texto
    # mensagens.json segue íntegro com os dois turnos
    mensagens = json.loads(session.messages_path.read_text(encoding="utf-8"))
    assert len(mensagens) >= 5  # system + (user+assistant) × 2 + tool msgs
