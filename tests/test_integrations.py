"""Testes de integração Ollama e SearXNG com transporte simulado (offline)."""

from __future__ import annotations

import json

import httpx
import pytest

from formiga.config import Config
from formiga.ollama import OllamaClient, OllamaError
from formiga.searxng import SearxngSearch


def config(**overrides) -> Config:
    return Config(**overrides)


class TestOllama:
    def _handler(self, payload_ok=True):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["format"] == "json"
            assert body["stream"] is False
            assert body["model"] == "llama3.1:8b"
            if not payload_ok:
                return httpx.Response(200, json={"nope": True})
            return httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": '{"queries": ["a"]}'},
                    "eval_count": 42,
                },
            )

        return handler

    def test_complete_returns_content_and_tokens(self):
        client = OllamaClient(
            config(), transport=httpx.MockTransport(self._handler())
        )
        response = client.complete("sistema", "usuário")
        assert response.content == '{"queries": ["a"]}'
        assert response.tokens == 42

    def test_tokens_unknown_when_absent(self):
        def handler(request: httpx.Request) -> httpx.Response:
            json.loads(request.content)
            return httpx.Response(
                200, json={"message": {"role": "assistant", "content": "ok"}}
            )

        client = OllamaClient(config(), transport=httpx.MockTransport(handler))
        assert client.complete("s", "u").tokens is None

    def test_backend_error_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        client = OllamaClient(config(), transport=httpx.MockTransport(handler))
        with pytest.raises(OllamaError):
            client.complete("s", "u")

    def test_missing_content_wrapped(self):
        client = OllamaClient(
            config(), transport=httpx.MockTransport(self._handler(payload_ok=False))
        )
        with pytest.raises(OllamaError):
            client.complete("s", "u")


class TestSearxng:
    def test_results_parsed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["format"] == "json"
            assert request.url.params["q"] == "teste"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": "https://a.example/x", "title": "A", "content": "snip"},
                        {"url": "", "title": "sem url"},
                        {"url": "https://b.example/y"},
                    ]
                },
            )

        search = SearxngSearch(config(), transport=httpx.MockTransport(handler))
        results = search.search("teste", 10)
        assert len(results) == 2
        assert results[0].title == "A"
        assert results[1].snippet is None

    def test_max_results(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"results": [{"url": f"https://x.example/{i}"} for i in range(10)]},
            )

        search = SearxngSearch(config(), transport=httpx.MockTransport(handler))
        assert len(search.search("q", 3)) == 3

    def test_http_error_wrapped(self):
        search = SearxngSearch(
            config(), transport=httpx.MockTransport(lambda r: httpx.Response(403))
        )
        with pytest.raises(RuntimeError):
            search.search("q", 5)
