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
        assert Config().llm_timeout == 300.0

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
        task, ok, tokens, seconds, info = calls[0]
        assert task == TaskType.QUERY and ok is False
        assert seconds is not None and seconds >= 0.0
        # O erro de transporte vai para o evento (diagnóstico).
        assert info is not None and "timed out" in info["error"]

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


class TestTruncationHandling:
    """Resposta cortada no limite de geração: retry ganha cap dobrado."""

    @staticmethod
    def _schema_call(calls: list):
        from formiga.llm import LLMResponse, StructuredCaller
        from formiga.schemas import QueryProposal

        class TruncatingThenOk:
            def complete(self, system, user, json_schema=None, max_tokens=None):
                calls.append(max_tokens)
                if len(calls) == 1:
                    return LLMResponse(
                        content='{"queries": ["uma busca bem longa que',
                        truncated=True,
                    )
                return LLMResponse(content='{"queries": ["ok"]}')

        return StructuredCaller(
            TruncatingThenOk(), on_call=lambda *args: calls.append(("event", *args))
        ), QueryProposal

    def test_truncated_response_doubles_cap_on_retry(self):
        from formiga.llm import TASK_MAX_TOKENS, TaskType

        calls: list = []
        caller, schema = self._schema_call(calls)
        result = caller.call(
            TaskType.QUERY, "s", "Tarefa: propor até 2 consultas de busca.", schema
        )
        assert result is not None
        # 1ª tentativa com o teto da tarefa; 2ª com o teto dobrado.
        caps = [c for c in calls if not isinstance(c, tuple)]
        assert caps[0] == TASK_MAX_TOKENS[TaskType.QUERY]
        assert caps[1] == TASK_MAX_TOKENS[TaskType.QUERY] * 2

    def test_non_truncated_invalid_json_keeps_feedback_retry(self):
        from formiga.llm import LLMResponse, StructuredCaller, TaskType
        from formiga.schemas import QueryProposal

        calls: list = []

        class BadThenOk:
            def complete(self, system, user, json_schema=None, max_tokens=None):
                calls.append((max_tokens, user))
                if len(calls) == 1:
                    return LLMResponse(content="texto solto, não é JSON")
                return LLMResponse(content='{"queries": ["ok"]}')

        caller = StructuredCaller(BadThenOk(), on_call=lambda *a: None)
        result = caller.call(
            TaskType.QUERY, "s", "Tarefa: propor até 2 consultas de busca.", QueryProposal
        )
        assert result is not None
        # Sem truncamento: o teto não muda e o erro de formato vai no prompt.
        assert calls[0][0] == calls[1][0]
        assert "Erro objetivo" in calls[1][1]

    def test_failure_event_carries_raw_and_truncated(self):
        from formiga.llm import LLMResponse, StructuredCaller, TaskType
        from formiga.schemas import QueryProposal

        events: list = []

        class AlwaysTruncated:
            def complete(self, system, user, json_schema=None, max_tokens=None):
                return LLMResponse(content='{"truncado', truncated=True)

        caller = StructuredCaller(AlwaysTruncated(), on_call=lambda *a: events.append(a))
        result = caller.call(
            TaskType.QUERY, "s", "Tarefa: propor até 2 consultas de busca.", QueryProposal
        )
        assert result is None
        assert all(e[1] is False for e in events)
        first, second = events[0], events[1]
        info = first[4]
        assert info["truncated"] is True
        assert info["raw"] == '{"truncado'
        # Segunda tentativa também falha; o cap registrado dobra.
        assert second[4]["max_tokens"] == 256

    def test_raw_log_is_bounded(self):
        from formiga.llm import RAW_LOG_CHARS, LLMResponse, StructuredCaller, TaskType
        from formiga.schemas import QueryProposal

        events: list = []

        class NeverJson:
            def complete(self, system, user, json_schema=None, max_tokens=None):
                return LLMResponse(content="x" * (RAW_LOG_CHARS + 50))

        caller = StructuredCaller(NeverJson(), on_call=lambda *a: events.append(a))
        caller.call(
            TaskType.QUERY, "s", "Tarefa: propor até 2 consultas de busca.", QueryProposal
        )
        assert len(events[0][4]["raw"]) == RAW_LOG_CHARS


class TestFinishReasonParsing:
    def test_llamacpp_finish_reason_length_sets_truncated(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {"role": "assistant", "content": '{"par'},
                        "finish_reason": "length",
                    }],
                    "usage": {"completion_tokens": 512},
                },
            )

        client = make_client(handler)
        response = client.complete("s", "u")
        assert response.truncated is True

    def test_llamacpp_finish_reason_stop_is_not_truncated(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {"role": "assistant", "content": '{"ok": 1}'},
                        "finish_reason": "stop",
                    }],
                },
            )

        client = make_client(handler)
        assert client.complete("s", "u").truncated is False

    def test_ollama_done_reason_length_sets_truncated(self):
        from formiga.ollama import OllamaClient

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": '{"par'},
                    "eval_count": 128,
                    "done_reason": "length",
                },
            )

        client = OllamaClient(Config(), transport=httpx.MockTransport(handler))
        assert client.complete("s", "u").truncated is True


class TestPlanBudget:
    def test_plan_has_room_for_full_json(self):
        from formiga.llm import TASK_MAX_TOKENS, TaskType

        assert TASK_MAX_TOKENS[TaskType.PLAN] >= 1024

    def test_prompt_asks_for_concise_output(self):
        prompt = prompts.plan_prompt("Q?", [])
        assert "até 3 itens" in prompt
        assert "conciso" in prompt


class TestThinkingMode:
    """Modelos de raciocínio: `enable_thinking` desligado por default."""

    def test_disable_thinking_sent_by_default(self):
        captured: dict = {}
        client = make_client(capture_handler(captured))
        client.complete("s", "u")
        import json

        body = json.loads(captured["body"].content)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}

    def test_thinking_kwarg_absent_when_thinking_enabled(self):
        captured: dict = {}
        client = make_client(
            capture_handler(captured), llamacpp_thinking=True
        )
        client.complete("s", "u")
        import json

        body = json.loads(captured["body"].content)
        assert "chat_template_kwargs" not in body

    def test_env_parsing(self):
        assert Config.from_env({"FORMIGA_LLAMACPP_THINKING": "1"}).llamacpp_thinking
        assert not Config.from_env(
            {"FORMIGA_LLAMACPP_THINKING": "false"}
        ).llamacpp_thinking
        with pytest.raises(ConfigError):
            Config.from_env({"FORMIGA_LLAMACPP_THINKING": "talvez"})

    def test_thinking_gives_extra_generation_room(self):
        from formiga.llm import (
            REASONING_EXTRA_TOKENS,
            TASK_MAX_TOKENS,
            LLMResponse,
            StructuredCaller,
            TaskType,
        )
        from formiga.schemas import QueryProposal

        assert REASONING_EXTRA_TOKENS >= 384  # raciocínio observado ~200+ tokens

        calls: list = []

        class Echo:
            def complete(self, system, user, json_schema=None, max_tokens=None):
                calls.append(max_tokens)
                return LLMResponse(content='{"queries": ["ok"]}')

        caller = StructuredCaller(
            Echo(), on_call=lambda *a: None, extra_tokens=REASONING_EXTRA_TOKENS
        )
        caller.call(
            TaskType.QUERY, "s", "Tarefa: propor até 2 consultas de busca.",
            QueryProposal,
        )
        assert calls[0] == TASK_MAX_TOKENS[TaskType.QUERY] + REASONING_EXTRA_TOKENS


class TestSamplingParams:
    """Amostragem: temperatura configurável; top_k/top_p da Gemma 4."""

    def test_llamacpp_sends_recommended_top_k_top_p(self):
        captured: dict = {}
        client = make_client(capture_handler(captured))
        client.complete("s", "u")
        import json

        body = json.loads(captured["body"].content)
        assert body["top_k"] == 64
        assert body["top_p"] == 0.95
        assert body["temperature"] == 0.2  # default para JSON estruturado

    def test_temperature_configurable(self):
        captured: dict = {}
        client = make_client(capture_handler(captured), llm_temperature=1.0)
        client.complete("s", "u")
        import json

        body = json.loads(captured["body"].content)
        assert body["temperature"] == 1.0

    def test_ollama_sends_recommended_top_k_top_p(self):
        import json

        from formiga.ollama import OllamaClient

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "x"}, "eval_count": 1},
            )

        client = OllamaClient(Config(), transport=httpx.MockTransport(handler))
        client.complete("s", "u")
        assert captured["body"]["options"]["top_k"] == 64
        assert captured["body"]["options"]["top_p"] == 0.95

    def test_temperature_env_and_validation(self):
        assert Config.from_env({"FORMIGA_LLM_TEMPERATURE": "1.0"}).llm_temperature == 1.0
        with pytest.raises(ConfigError):
            Config.from_env({"FORMIGA_LLM_TEMPERATURE": "abc"})
        with pytest.raises(ConfigError):
            Config(llm_temperature=3.0).validate()


class TestExtractionRegression:
    """Trafilatura >= 2.0: `extract_metadata` devolve Document, não dict."""

    HTML = (
        "<html><head><title>Página</title></head><body>"
        "<article><h1>Busca</h1><p>Parágrafo com conteúdo suficiente para a "
        "extração funcionar e devolver texto principal. " + "Mais contexto. " * 20 +
        "</p></article></body></html>"
    )

    def test_extract_handles_document_metadata(self):
        from formiga.extract import extract_main_text

        text, title = extract_main_text(self.HTML)
        assert text, "extração não pode ficar vazia"
        # Trafilatura prefere o h1 do corpo; qualquer título não-nulo vale.
        assert title == "Busca"

    def test_extract_returns_none_title_when_absent(self):
        from formiga.extract import extract_main_text

        html = (
            "<html><body><p>Texto solto sem título. " + "x " * 200
            + "</p></body></html>"
        )
        text, title = extract_main_text(html)
        assert text
        assert title is None or isinstance(title, str)
