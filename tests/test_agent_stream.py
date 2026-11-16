"""Testes de streaming do chat (offline, MockTransport com SSE/NDJSON fake)."""

from __future__ import annotations

import json

import httpx
import pytest

from formiga.agent.chat import AgentCancelled, ChatResponse
from formiga.config import Config
from formiga.llamacpp import LlamaCppClient
from formiga.ollama import OllamaClient
from formiga.openai import OpenAIClient


def sse_body(deltas: list[dict], finish: str | None = None) -> bytes:
    """Monta um corpo SSE OpenAI-compatível a partir dos deltas."""
    chunks = [{"choices": [{"delta": d, "finish_reason": None}]} for d in deltas]
    if finish is not None:
        chunks.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
    body += "data: [DONE]\n\n"
    return body.encode("utf-8")


def json_body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_openai_chat_stream_entrega_deltas_e_monta_resposta():
    body = sse_body([{"content": "Ola "}, {"content": "mundo"}], finish="stop")

    def handler(request: httpx.Request) -> httpx.Response:
        assert json_body(request)["stream"] is True
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    config = Config(llm_backend="openai", openai_api_key="chave-teste", openai_url="https://api.teste/v1")
    client = OpenAIClient(config, transport=httpx.MockTransport(handler))
    received: list[str] = []
    response = client.chat([{"role": "user", "content": "oi"}], on_delta=received.append)
    assert received == ["Ola ", "mundo"]
    assert response.content == "Ola mundo"
    assert response.tool_calls is None


def test_openai_chat_stream_monta_tool_calls_fragmentados():
    body = sse_body(
        [
            {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "ls", "arguments": ""}}]},
            {"tool_calls": [{"index": 0, "function": {"arguments": '{"pa'}}]},
            {"tool_calls": [{"index": 0, "function": {"arguments": 'th": "."}'}}]},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    config = Config(llm_backend="openai", openai_api_key="chave-teste", openai_url="https://api.teste/v1")
    client = OpenAIClient(config, transport=httpx.MockTransport(handler))
    deltas: list[str] = []
    response = client.chat([{"role": "user", "content": "oi"}], on_delta=deltas.append)
    assert deltas == []
    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "ls"
    assert response.tool_calls[0].arguments == '{"path": "."}'


def test_openai_chat_stream_cancelamento_propaga():
    body = sse_body([{"content": "pedaco1"}, {"content": "pedaco2"}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    config = Config(llm_backend="openai", openai_api_key="chave-teste", openai_url="https://api.teste/v1")
    client = OpenAIClient(config, transport=httpx.MockTransport(handler))

    def on_delta(piece: str) -> None:
        raise AgentCancelled()

    with pytest.raises(AgentCancelled):
        client.chat([{"role": "user", "content": "oi"}], on_delta=on_delta)


def test_openai_chat_sem_stream_permanece_igual():
    """Sem `on_delta`, `stream` segue False e o corpo é JSON completo."""
    payload = {
        "choices": [
            {
                "message": {"content": "completo", "tool_calls": None},
                "finish_reason": "stop",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert json_body(request)["stream"] is False
        return httpx.Response(200, json=payload)

    config = Config(llm_backend="openai", openai_api_key="chave-teste", openai_url="https://api.teste/v1")
    client = OpenAIClient(config, transport=httpx.MockTransport(handler))
    response = client.chat([{"role": "user", "content": "oi"}])
    assert response.content == "completo"


def test_llamacpp_chat_stream():
    body = sse_body([{"content": "res"}, {"content": "posta"}], finish="stop")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    config = Config(llamacpp_url="http://127.0.0.1:8080")
    client = LlamaCppClient(config, transport=httpx.MockTransport(handler))
    received: list[str] = []
    response = client.chat([{"role": "user", "content": "oi"}], on_delta=received.append)
    assert received == ["res", "posta"]
    assert response.content == "resposta"


def test_ollama_chat_stream_ndjson():
    lines = [
        {"message": {"content": "par"}, "done": False},
        {"message": {"content": "cial"}, "done": False},
        {"message": {"content": ""}, "done": True},
    ]
    body = ("\n".join(json.dumps(line) for line in lines) + "\n").encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert json_body(request)["stream"] is True
        return httpx.Response(200, content=body, headers={"content-type": "application/x-ndjson"})

    config = Config(ollama_url="http://127.0.0.1:11434", model="m1")
    client = OllamaClient(config, transport=httpx.MockTransport(handler))
    received: list[str] = []
    response = client.chat([{"role": "user", "content": "oi"}], on_delta=received.append)
    assert received == ["par", "cial"]
    assert response.content == "parcial"


def test_ollama_chat_stream_com_tool_call():
    lines = [
        {"message": {"content": ""}, "done": False},
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {"id": "t1", "function": {"name": "read", "arguments": '{"path": "x.txt"}'}}
                ],
            },
            "done": False,
        },
        {"message": {"content": ""}, "done": True},
    ]
    body = ("\n".join(json.dumps(line) for line in lines) + "\n").encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/x-ndjson"})

    config = Config(ollama_url="http://127.0.0.1:11434", model="m1")
    client = OllamaClient(config, transport=httpx.MockTransport(handler))
    deltas: list[str] = []
    response = client.chat([{"role": "user", "content": "oi"}], on_delta=deltas.append)
    assert deltas == []
    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "read"
    assert response.tool_calls[0].arguments == '{"path": "x.txt"}'


def test_chat_response_deltas_atributo_opcional():
    """`deltas` é opcional para os fakes de teste da TUI."""
    response = ChatResponse(content="texto")
    assert getattr(response, "deltas", None) is None
