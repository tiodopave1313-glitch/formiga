"""Testes do cliente llama.cpp e da seleção de backend (offline, MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from formiga.config import Config, ConfigError
from formiga.llamacpp import LlamaCppClient, LlamaCppError
from formiga.orchestrator import build_llm_client


def make_client(handler, **kwargs) -> LlamaCppClient:
    return LlamaCppClient(
        Config(**kwargs), transport=httpx.MockTransport(handler)
    )


def capture_handler(captured: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = httpx.Request(
            method=request.method, url=request.url, headers=request.headers,
            content=request.read(),
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 7},
            },
        )

    return handler


class TestLlamaCppClient:
    def test_request_carries_response_format_and_schema(self):
        captured: dict = {}
        client = make_client(
            capture_handler(captured), llamacpp_url="http://127.0.0.1:9931"
        )
        response = client.complete(
            "sistema", "tarefa", {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        )
        assert response.content == '{"ok": true}'
        assert response.tokens == 7
        import json

        body = json.loads(captured["body"].content)
        assert body["response_format"]["type"] == "json_object"
        assert body["response_format"]["schema"]["properties"]["ok"] == {"type": "boolean"}
        assert body["messages"][0]["role"] == "system"
        assert body["temperature"] == 0.2
        assert captured["body"].url.path == "/v1/chat/completions"

    def test_no_schema_sent_when_absent(self):
        captured: dict = {}
        client = make_client(capture_handler(captured))
        client.complete("s", "u")
        import json

        body = json.loads(captured["body"].content)
        assert body["response_format"] == {"type": "json_object"}

    def test_tokens_unknown_when_absent(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "x"}}]},
            )

        client = make_client(handler)
        assert client.complete("s", "u").tokens is None

    def test_http_error_wrapped(self):
        client = make_client(lambda request: httpx.Response(500, text="boom"))
        with pytest.raises(LlamaCppError):
            client.complete("s", "u")

    def test_missing_content_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        client = make_client(handler)
        with pytest.raises(LlamaCppError):
            client.complete("s", "u")


class TestBackendSelection:
    def test_default_is_ollama(self):
        client = build_llm_client(Config())
        import formiga.ollama

        assert isinstance(client, formiga.ollama.OllamaClient)

    def test_llamacpp_backend(self):
        client = build_llm_client(Config(llm_backend="llamacpp"))
        assert isinstance(client, LlamaCppClient)

    def test_invalid_backend_rejected(self):
        with pytest.raises(ConfigError):
            Config(llm_backend="vllm").validate()

    def test_env_backend(self):
        config = Config.from_env({"FORMIGA_LLM_BACKEND": "llamacpp"})
        assert config.llm_backend == "llamacpp"

    def test_cli_beats_env(self):
        config = Config.from_env({"FORMIGA_LLM_BACKEND": "llamacpp"}).apply_args(
            type("Args", (), {"llm_backend": "ollama"})
        )
        assert config.llm_backend == "ollama"

    def test_llamacpp_url_validated(self):
        with pytest.raises(ConfigError):
            Config(llamacpp_url="nope").validate()


class TestLlmTimeout:
    def test_default_matches_generation_on_cpu(self):
        assert Config().llm_timeout == 120.0

    def test_env_timeout(self):
        config = Config.from_env({"FORMIGA_LLM_TIMEOUT": "300"})
        assert config.llm_timeout == 300.0

    def test_invalid_env_timeout(self):
        with pytest.raises(ConfigError):
            Config.from_env({"FORMIGA_LLM_TIMEOUT": "abc"})

    def test_client_uses_llm_timeout_not_network_timeout(self):
        config = Config(llm_timeout=300.0, network_timeout=5.0)
        client = build_llm_client(config)
        assert client._effective_timeout() == 300.0  # noqa: SLF001

    def test_client_capped_by_remaining_time(self):
        config = Config(llm_timeout=300.0)
        client = build_llm_client(config, remaining_seconds=lambda: 45.0)
        assert client._effective_timeout() == 45.0  # noqa: SLF001
