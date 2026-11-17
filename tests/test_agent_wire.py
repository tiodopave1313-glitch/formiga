"""Formato wire OpenAI nas mensagens do loop (bug do HTTP 400 no NIM).

O NIM rejeita com 400 `tool_calls` sem `type`/`function` e resultado de
ferramenta com `role != "tool"`. Estes testes capturam o payload real
enviado pelo `OpenAIClient` (MockTransport) e validam a estrutura, além de
um "servidor estrito" que reproduz a rejeição e um teste de rollback do
turno pendente após falha de LLM.
"""

from __future__ import annotations

import json

import httpx
import pytest

from formiga.agent.chat import ChatResponse
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool
from formiga.config import Config
from formiga.llm import LLMError
from formiga.openai import OpenAIClient
from tests.fakes_agent import FakeChatClient, registry_of, tool_call
from tests.test_agent_stream import sse_body


def _client(handler) -> OpenAIClient:
    cfg = Config(
        llm_backend="openai",
        openai_api_key="chave-teste",
        openai_url="https://api.teste/v1",
    )
    return OpenAIClient(cfg, transport=httpx.MockTransport(handler))


def test_loop_envia_tool_calls_no_formato_openai(tmp_path):
    """Payload capturado: `type`/`function` e resultado como `role: "tool"`."""
    (tmp_path / "a.txt").write_text("x")
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                content=sse_body(
                    [
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "ls", "arguments": '{"path": "."}'},
                                }
                            ]
                        }
                    ]
                ),
                headers={"content-type": "text/event-stream"},
            )
        # 2ª chamada: valida o formato wire das mensagens anteriores
        msgs = body["messages"]
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert tool_msgs, "resultado da tool deve ser role 'tool'"
        assert tool_msgs[0]["tool_call_id"] == "call_1"
        assert "a.txt" in tool_msgs[0]["content"]
        assistants = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        assert assistants, "assistant com tool_calls deve estar no histórico"
        tc = assistants[0]["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "ls"
        assert tc["function"]["arguments"] == '{"path": "."}'
        return httpx.Response(
            200,
            content=sse_body([{"content": "listei."}], finish="stop"),
            headers={"content-type": "text/event-stream"},
        )

    session = Session(tmp_path / "sessoes")
    loop = AgentLoop(
        _client(handler),
        registry_of(LsTool(tmp_path), config=Config()),
        session,
        Config(),
    )
    resposta = loop.run("liste os arquivos")
    assert resposta == "listei."
    assert len(requests) == 2
    # nenhum resultado de tool vazou como mensagem de usuário
    msgs = requests[1]["messages"]
    assert not any(
        m.get("role") == "user" and "a.txt" in m.get("content", "") for m in msgs
    )


def test_servidor_estrito_rejeita_formato_invalido(tmp_path):
    """Reproduz o bug: servidor OpenAI-estrito só aceita o formato correto.

    Antes do fix este teste devolvia HTTP 400 e o loop morria; com o fix,
    conclui normalmente.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        for m in body["messages"]:
            role = m.get("role")
            if role not in ("system", "user", "assistant", "tool"):
                return httpx.Response(
                    400, json={"error": f"role inválido: {role}"}
                )
            for tc in m.get("tool_calls") or []:
                if tc.get("type") != "function" or "function" not in tc:
                    return httpx.Response(
                        400, json={"error": "tool_calls sem type/function"}
                    )
            if role == "tool" and not m.get("tool_call_id"):
                return httpx.Response(
                    400, json={"error": "tool result sem tool_call_id"}
                )
        if not any(m.get("role") == "tool" for m in body["messages"]):
            return httpx.Response(
                200,
                content=sse_body(
                    [
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "ls", "arguments": '{"path": "."}'},
                                }
                            ]
                        }
                    ]
                ),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            content=sse_body([{"content": "servidor estrito aceitou."}], finish="stop"),
            headers={"content-type": "text/event-stream"},
        )

    session = Session(tmp_path / "sessoes")
    loop = AgentLoop(
        _client(handler),
        registry_of(LsTool(tmp_path), config=Config()),
        session,
        Config(),
    )
    resposta = loop.run("liste")
    assert resposta == "servidor estrito aceitou."


def test_rollback_do_turno_apos_falha_de_llm(tmp_path):
    """LLM falha após tool call: histórico não fica envenenado."""
    (tmp_path / "a.txt").write_text("x")

    class FalhaNaSegunda:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, messages, tools=None, max_tokens=None, on_delta=None):
            self.calls += 1
            if self.calls == 1:
                return ChatResponse(tool_calls=[tool_call("ls", '{"path": "."}')])
            raise LLMError("HTTP 400 do endpoint remoto: invalid request")

    session = Session(tmp_path / "sessoes")
    loop = AgentLoop(
        FalhaNaSegunda(),
        registry_of(LsTool(tmp_path), config=Config()),
        session,
        Config(),
    )
    with pytest.raises(LLMError):
        loop.run("liste os arquivos")

    # mensagens no disco: pergunta do usuário, sem turno incompleto
    mensagens = json.loads(session.messages_path.read_text(encoding="utf-8"))
    assert any(m["role"] == "user" and "liste os arquivos" in m["content"] for m in mensagens)
    assert not any(m.get("tool_calls") for m in mensagens)
    assert not any(m["role"] == "tool" for m in mensagens)

    # erro persistido nos eventos
    eventos = session.events_path.read_text(encoding="utf-8")
    assert any("llm_error" in linha for linha in eventos.splitlines())

    # próximo run recomeça do estado limpo e conclui
    chat2 = FakeChatClient([ChatResponse(content="funcionou agora.")])
    loop2 = AgentLoop(
        chat2,
        registry_of(LsTool(tmp_path), config=Config()),
        session,
        Config(),
    )
    loop2.messages = loop.messages  # mesmo histórico (já revertido)
    resposta = loop2.run("de novo")
    assert resposta == "funcionou agora."
    # a segunda chamada não viu mensagens de tool do turno falho
    segunda = chat2.calls[0][0]
    assert not any(m["role"] == "tool" for m in segunda)
    assert not any(m.get("tool_calls") for m in segunda)
