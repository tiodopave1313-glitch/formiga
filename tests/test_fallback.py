"""Testes do failover opt-in (circuit breaker) e do evento llm_fallback."""

from __future__ import annotations

import pytest

from formiga.config import Config
from formiga.fallback import FallbackLLMClient
from formiga.llm import LLMError, LLMResponse
from formiga.orchestrator import build_llm_client, run_research
from formiga.storage import load_state


class FailingClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self, system: str, user: str, json_schema: dict | None = None, max_tokens: int | None = None
    ) -> LLMResponse:
        self.calls += 1
        raise LLMError("backend indisponível")


class OkClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self, system: str, user: str, json_schema: dict | None = None, max_tokens: int | None = None
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content="ok")


class TestFallbackLLMClient:
    def test_fallback_assumes_after_first_failure(self):
        events: list = []
        primary, backup = FailingClient(), OkClient()
        client = FallbackLLMClient(primary, backup, on_fallback=events.append)
        response = client.complete("s", "u")
        assert response.content == "ok"
        assert client.using_fallback is True
        assert len(events) == 1 and "indisponível" in str(events[0])
        assert primary.calls == 1 and backup.calls == 1

    def test_circuit_breaker_keeps_fallback_for_rest_of_run(self):
        primary, backup = FailingClient(), OkClient()
        client = FallbackLLMClient(primary, backup)
        client.complete("s", "u")
        client.complete("s", "u")
        client.complete("s", "u")
        # O principal não é retestado após a migração.
        assert primary.calls == 1
        assert backup.calls == 3

    def test_after_failures_two_requires_two_failures(self):
        primary, backup = FailingClient(), OkClient()
        client = FallbackLLMClient(primary, backup, after_failures=2)
        with pytest.raises(LLMError):
            client.complete("s", "u")
        assert client.using_fallback is False
        assert backup.calls == 0
        response = client.complete("s", "u")
        assert response.content == "ok"
        assert client.using_fallback is True
        assert primary.calls == 2

    def test_fallback_failure_propagates(self):
        client = FallbackLLMClient(FailingClient(), FailingClient())
        with pytest.raises(LLMError):
            client.complete("s", "u")
        assert client.using_fallback is True


class TestBuildLLMClient:
    def test_openai_with_ollama_fallback(self):
        client = build_llm_client(
            Config(
                llm_backend="openai",
                openai_url="https://api.example.com/v1",
                model="m",
                openai_api_key="nvapi-test-key",
                fallback_backend="ollama",
            )
        )
        assert isinstance(client, FallbackLLMClient)
        from formiga.ollama import OllamaClient
        from formiga.openai import OpenAIClient

        assert isinstance(client.fallback, OllamaClient)
        assert isinstance(client._primary, OpenAIClient)  # noqa: SLF001

    def test_no_fallback_when_not_configured(self):
        from formiga.ollama import OllamaClient
        from formiga.openai import OpenAIClient

        config = Config(
            llm_backend="openai",
            openai_url="https://api.example.com/v1",
            model="m",
            openai_api_key="nvapi-test-key",
        )
        assert isinstance(build_llm_client(config), OpenAIClient)
        assert not isinstance(build_llm_client(config), FallbackLLMClient)
        assert isinstance(build_llm_client(Config()), OllamaClient)


class TestOrchestratorFallbackEvent:
    def test_llm_fallback_event_recorded(self, tmp_path):
        from fakes import FakeFetcher, FakeLLM, FakeSearch, load_script

        fallback = FakeLLM(load_script({"PLAN": ["plan-basic"], "QUERY": ["query-q1"]}))
        client = FallbackLLMClient(FailingClient(), fallback)
        config = Config(question="Q?", output=tmp_path / "out")
        result = run_research(
            config, client=client, search=FakeSearch({}), fetcher=FakeFetcher({})
        )
        events = (config.output / "events.jsonl").read_text(encoding="utf-8")
        assert '"llm_fallback"' in events
        assert "indisponível" in events
        assert result.report_path.exists()

    def test_no_fallback_event_without_option(self, tmp_path):
        from fakes import FakeFetcher, FakeLLM, FakeSearch, load_script

        llm = FakeLLM(load_script({"PLAN": ["plan-basic"], "QUERY": ["query-q1"]}))
        config = Config(question="Q?", output=tmp_path / "out")
        run_research(config, client=llm, search=FakeSearch({}), fetcher=FakeFetcher({}))
        events = (config.output / "events.jsonl").read_text(encoding="utf-8")
        assert '"llm_fallback"' not in events

    def test_fallback_state_recorded_and_run_completes(self, tmp_path):
        from fakes import FakeFetcher, FakeLLM, FakeSearch, load_script

        fallback = FakeLLM(load_script({"PLAN": ["plan-basic"], "QUERY": ["query-q1"]}))
        client = FallbackLLMClient(FailingClient(), fallback)
        config = Config(question="Q?", output=tmp_path / "out")
        run_research(config, client=client, search=FakeSearch({}), fetcher=FakeFetcher({}))
        state = load_state(config.output)
        assert state.questions  # planejamento veio do backup
