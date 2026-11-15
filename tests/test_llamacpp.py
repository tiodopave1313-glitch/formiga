"""Testes do cliente llama.cpp e da seleção de backend (offline, MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from formiga import prompts
from formiga.config import Config, ConfigError
from formiga.llamacpp import LlamaCppClient, LlamaCppError
from formiga.orchestrator import build_llm_client, run_research
from formiga.storage import load_state


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


class TestMaxTokens:
    def test_llamacpp_sends_max_tokens(self):
        captured: dict = {}
        client = make_client(capture_handler(captured))
        client.complete("s", "u", None, 256)
        import json

        body = json.loads(captured["body"].content)
        assert body["max_tokens"] == 256

    def test_ollama_sends_num_predict(self):
        import json

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "x"}, "eval_count": 1},
            )

        from formiga.ollama import OllamaClient

        client = OllamaClient(Config(), transport=httpx.MockTransport(handler))
        client.complete("s", "u", None, 256)
        assert captured["body"]["options"]["num_predict"] == 256

    def test_task_limits_are_sane(self):
        from formiga.llm import TASK_MAX_TOKENS, TaskType

        assert TASK_MAX_TOKENS[TaskType.QUERY] <= 128
        assert TASK_MAX_TOKENS[TaskType.SYNTHESIZE] <= 900
        assert all(v >= 64 for v in TASK_MAX_TOKENS.values())


class TestTransportFailureIsConservative:
    def test_llm_error_returns_none_and_consumes_budget(self, tmp_path):
        from formiga.llm import StructuredCaller, TaskType
        from formiga.schemas import QueryProposal

        class FailingClient:
            def complete(self, system, user, json_schema=None, max_tokens=None):
                from formiga.llm import LLMError

                raise LLMError("timed out")

        calls: list[tuple] = []
        caller = StructuredCaller(
            FailingClient(), on_call=lambda *args: calls.append(args)
        )
        result = caller.call(
            TaskType.QUERY,
            prompts.SYSTEM,
            prompts.query_prompt("Q", {"id": "Q1", "question": "sub?"}, []),
            QueryProposal,
        )
        assert result is None
        # Uma tentativa consumida, com falha registrada.
        assert len(calls) == 1
        task, ok, tokens, seconds = calls[0]
        assert task == TaskType.QUERY and ok is False
        assert seconds is not None and seconds >= 0.0

    def test_orchestrator_survives_llm_failure(self, tmp_path):
        from fakes import FakeFetcher, FakeLLM, FakeSearch, load_script

        class FlakyLLM(FakeLLM):
            def complete(self, system, user, json_schema=None, max_tokens=None):
                if user.startswith("Tarefa: propor"):
                    from formiga.llm import LLMError

                    raise LLMError("timed out")
                return super().complete(system, user, json_schema, max_tokens)

        llm = FlakyLLM(load_script({"PLAN": ["plan-basic"]}))
        config = Config(question="Q?", output=tmp_path / "out")
        result = run_research(
            config, client=llm, search=FakeSearch({}), fetcher=FakeFetcher({})
        )
        state = load_state(config.output)
        # Consultas falharam; questões esgotam sem progredir — mas o run termina.
        assert result.status == "bloqueada"
        assert state.questions
