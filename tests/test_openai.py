"""Testes do cliente remoto OpenAI-compatível e da seleção de backend (offline)."""

from __future__ import annotations

import json

import httpx
import pytest

from formiga.config import Config, ConfigError
from formiga.openai import OpenAIClient, OpenAIError
from formiga.orchestrator import build_llm_client


def make_client(handler, **kwargs) -> OpenAIClient:
    defaults: dict = {
        "openai_url": "https://api.example.com/v1",
        "model": "test/model",
        "openai_api_key": "nvapi-test-key",
    }
    defaults.update(kwargs)
    return OpenAIClient(Config(**defaults), transport=httpx.MockTransport(handler))


def ok_response(content: str = '{"ok": true}', finish_reason: str = "stop"):
    return {
        "choices": [{"message": {"role": "assistant", "content": content},
                     "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 7},
    }


def capture_handler(captured: dict, status: int = 0):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = httpx.Request(
            method=request.method, url=request.url, headers=request.headers,
            content=request.read(),
        )
        captured["calls"] = captured.get("calls", 0) + 1
        if status:
            return httpx.Response(status, text="erro do servidor")
        return httpx.Response(200, json=ok_response())

    return handler


class TestOpenAIClient:
    def test_request_carries_model_auth_and_payload(self):
        captured: dict = {}
        client = make_client(capture_handler(captured))
        response = client.complete("sistema", "tarefa", None, 256)
        assert response.content == '{"ok": true}'
        assert response.tokens == 7
        assert response.truncated is False

        request = captured["request"]
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer nvapi-test-key"
        body = json.loads(request.content)
        assert body["model"] == "test/model"
        assert body["messages"][0] == {"role": "system", "content": "sistema"}
        assert body["messages"][1] == {"role": "user", "content": "tarefa"}
        assert body["temperature"] == 1.0
        assert body["stream"] is False
        assert body["max_tokens"] == 256
        # Thinking ligado (default do Nemotron Bolt): kwarg de chat template.
        assert body["chat_template_kwargs"] == {"enable_thinking": True}
        assert body["skip_special_tokens"] is False
        # Parâmetros específicos do llama.cpp não vão para endpoints remotos.
        assert "top_k" not in body
        assert body["response_format"] == {"type": "json_object"}

    def test_thinking_disabled_omits_kwargs(self):
        captured: dict = {}
        client = make_client(capture_handler(captured), llm_thinking=False)
        client.complete("s", "u")
        body = json.loads(captured["request"].content)
        assert "chat_template_kwargs" not in body
        assert "skip_special_tokens" not in body

    def test_base_url_without_v1_gets_chat_completions(self):
        captured: dict = {}
        client = make_client(capture_handler(captured), openai_url="https://api.example.com")
        client.complete("s", "u")
        assert captured["request"].url.path == "/chat/completions"

    def test_full_endpoint_url_used_as_is(self):
        captured: dict = {}
        client = make_client(
            capture_handler(captured),
            openai_url="https://api.example.com/v1/chat/completions",
        )
        client.complete("s", "u")
        assert captured["request"].url.path == "/v1/chat/completions"

    def test_json_schema_is_not_sent(self):
        captured: dict = {}
        client = make_client(capture_handler(captured))
        client.complete("s", "u", {"type": "object", "properties": {"ok": {}}})
        body = json.loads(captured["request"].content)
        assert "schema" not in json.dumps(body)

    def test_tokens_unknown_when_usage_absent(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "x"}}]},
            )

        client = make_client(handler)
        assert client.complete("s", "u").tokens is None

    def test_finish_reason_length_sets_truncated(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=ok_response('{"par', finish_reason="length"))

        client = make_client(handler)
        assert client.complete("s", "u").truncated is True

    def test_missing_content_truncated_when_length(self):
        """Raciocínio consumiu o teto: resposta truncada, não erro (cap dobra)."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "pensei muito...",
                        },
                        "finish_reason": "length",
                    }],
                    "usage": {"completion_tokens": 512},
                },
            )

        client = make_client(handler)
        response = client.complete("s", "u")
        assert response.truncated is True
        assert response.content == ""
        assert response.tokens == 512

    def test_missing_content_with_reasoning_hint(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "pensei muito...",
                        },
                        "finish_reason": "stop",
                    }],
                },
            )

        client = make_client(handler)
        with pytest.raises(OpenAIError, match="reasoning_content"):
            client.complete("s", "u")

    def test_missing_choices_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        client = make_client(handler)
        with pytest.raises(OpenAIError):
            client.complete("s", "u")

    def test_non_json_response_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="não é json")

        client = make_client(handler)
        with pytest.raises(OpenAIError):
            client.complete("s", "u")

    def test_timeout_capped_by_remaining_time(self):
        config = Config(
            openai_url="https://api.example.com", model="m", openai_api_key="k",
            llm_timeout=300.0,
        )
        client = OpenAIClient(config, remaining_seconds=lambda: 45.0)
        assert client._effective_timeout() == 45.0  # noqa: SLF001


class TestApiKeyResolution:
    def test_missing_key_raises_config_error(self, monkeypatch):
        monkeypatch.delenv("FORMIGA_TEST_MISSING_KEY", raising=False)
        config = Config(
            openai_url="https://api.example.com",
            model="m",
            openai_api_key_env="FORMIGA_TEST_MISSING_KEY",
        )
        with pytest.raises(ConfigError, match="FORMIGA_TEST_MISSING_KEY"):
            OpenAIClient(config)

    def test_key_from_env_var(self, monkeypatch):
        monkeypatch.setenv("FORMIGA_TEST_ENV_KEY", "env-key")
        captured: dict = {}
        client = make_client(
            capture_handler(captured),
            openai_api_key="",
            openai_api_key_env="FORMIGA_TEST_ENV_KEY",
        )
        client.complete("s", "u")
        assert captured["request"].headers["authorization"] == "Bearer env-key"

    def test_key_never_in_error_messages(self):
        client = make_client(lambda request: httpx.Response(401, text="unauthorized"))
        with pytest.raises(OpenAIError) as excinfo:
            client.complete("s", "u")
        # A chave nunca aparece na mensagem de erro (nem em headers ecoados).
        assert "nvapi-test-key" not in str(excinfo.value)


class TestRetries:
    def test_401_fails_fast_without_retry(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["calls"] = captured.get("calls", 0) + 1
            return httpx.Response(401, text="unauthorized")

        client = make_client(handler)
        with pytest.raises(OpenAIError, match="401"):
            client.complete("s", "u")
        assert captured["calls"] == 1

    def test_429_retries_with_retry_after(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("formiga.openai.time.sleep", lambda s: sleeps.append(s))
        retries: list[tuple] = []
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, text="lento")
            return httpx.Response(200, json=ok_response())

        client = make_client(handler)
        client.on_retry = lambda status, attempt, delay: retries.append((status, attempt, delay))
        response = client.complete("s", "u")
        assert response.content == '{"ok": true}'
        assert len(calls) == 2
        assert sleeps == [0.0]
        assert retries == [(429, 1, 0.0)]

    def test_500_retry_exhaustion(self, monkeypatch):
        monkeypatch.setattr("formiga.openai.time.sleep", lambda s: None)
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(500, text="boom")

        client = make_client(handler)  # max_retries default = 2
        with pytest.raises(OpenAIError, match="500"):
            client.complete("s", "u")
        assert len(calls) == 3  # 1 original + 2 retries

    def test_500_without_retries(self, monkeypatch):
        monkeypatch.setattr("formiga.openai.time.sleep", lambda s: None)
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(503, text="indisponível")

        client = make_client(handler, llm_max_retries=0)
        with pytest.raises(OpenAIError):
            client.complete("s", "u")
        assert len(calls) == 1

    def test_400_response_format_falls_back_without_it(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["calls"] = captured.get("calls", 0) + 1
            if captured["calls"] == 1:
                return httpx.Response(400, text="response_format not supported")
            captured["last_body"] = json.loads(request.read())
            return httpx.Response(200, json=ok_response())

        client = make_client(handler)
        response = client.complete("s", "u")
        assert response.content == '{"ok": true}'
        assert "response_format" not in captured["last_body"]

    def test_400_thinking_kwargs_fall_back_without_them(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["calls"] = captured.get("calls", 0) + 1
            if captured["calls"] == 1:
                return httpx.Response(400, text="chat_template_kwargs not supported")
            captured["last_body"] = json.loads(request.read())
            return httpx.Response(200, json=ok_response())

        client = make_client(handler)
        response = client.complete("s", "u")
        assert response.content == '{"ok": true}'
        assert "chat_template_kwargs" not in captured["last_body"]
        assert "skip_special_tokens" not in captured["last_body"]

    def test_400_thinking_fallback_keeps_response_format(self):
        """Fallback do thinking não pode descartar o `response_format` válido."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["calls"] = captured.get("calls", 0) + 1
            if captured["calls"] == 1:
                return httpx.Response(400, text="thinking not supported")
            captured["last_body"] = json.loads(request.read())
            return httpx.Response(200, json=ok_response())

        client = make_client(handler)
        client.complete("s", "u")
        assert captured["last_body"]["response_format"] == {"type": "json_object"}

    def test_transport_error_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusado", request=request)

        client = make_client(handler)
        with pytest.raises(OpenAIError, match="recusado"):
            client.complete("s", "u")


class TestBackendSelection:
    def test_openai_backend(self):
        client = build_llm_client(
            Config(
                llm_backend="openai",
                openai_url="https://api.example.com/v1",
                model="m",
                openai_api_key="k",
            )
        )
        assert isinstance(client, OpenAIClient)

    def test_no_fallback_by_default(self):
        from formiga.ollama import OllamaClient

        client = build_llm_client(Config())
        assert isinstance(client, OllamaClient)
        assert not isinstance(client, OpenAIClient)

    def test_openai_backend_requires_url(self):
        with pytest.raises(ConfigError):
            Config(llm_backend="openai", model="m").validate()

    def test_openai_backend_requires_model_placeholder_rejected(self):
        # model default existe, então apenas URL vazia deve falhar.
        assert Config(llm_backend="openai", openai_url="https://x/v1").model


class TestConfigFields:
    def test_invalid_fallback_backend_rejected(self):
        with pytest.raises(ConfigError):
            Config(fallback_backend="vllm").validate()

    def test_fallback_same_as_primary_rejected(self):
        with pytest.raises(ConfigError):
            Config(llm_backend="ollama", fallback_backend="ollama").validate()

    def test_fallback_requires_openai_url(self):
        with pytest.raises(ConfigError):
            Config(llm_backend="ollama", fallback_backend="openai").validate()

    def test_negative_retries_rejected(self):
        with pytest.raises(ConfigError):
            Config(llm_max_retries=-1).validate()

    def test_fallback_after_failures_must_be_positive(self):
        with pytest.raises(ConfigError):
            Config(fallback_after_failures=0).validate()

    def test_api_key_not_in_repr(self):
        config = Config(openai_api_key="nvapi-secret")
        assert "nvapi-secret" not in repr(config)

    def test_env_openai_url(self):
        config = Config.from_env({"FORMIGA_OPENAI_URL": "https://x/v1"})
        assert config.openai_url == "https://x/v1"

    def test_env_fallback_backend(self):
        config = Config.from_env({"FORMIGA_FALLBACK_BACKEND": "llamacpp"})
        assert config.fallback_backend == "llamacpp"

    def test_env_fallback_after_failures(self):
        config = Config.from_env({"FORMIGA_FALLBACK_AFTER_FAILURES": "3"})
        assert config.fallback_after_failures == 3
        with pytest.raises(ConfigError):
            Config.from_env({"FORMIGA_FALLBACK_AFTER_FAILURES": "muito"})
        with pytest.raises(ConfigError):
            Config.from_env({"FORMIGA_FALLBACK_AFTER_FAILURES": "0"})

    def test_cli_beats_env_for_openai_url(self):
        config = Config.from_env({"FORMIGA_OPENAI_URL": "https://env/v1"}).apply_args(
            type("Args", (), {"openai_url": "https://cli/v1"})
        )
        assert config.openai_url == "https://cli/v1"
