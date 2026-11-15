"""Testes de segurança do fetcher: SSRF, redirecionamentos e limites (offline)."""

from __future__ import annotations

import httpx
import pytest

from formiga.config import Config
from formiga.fetch import FetchError
from formiga.fetcher import SafeFetcher


def make_fetcher(resolver_map: dict[str, list[str]], handler=None, **kwargs) -> SafeFetcher:
    config = Config()
    resolver = lambda host, port: resolver_map.get(host, ["93.184.216.34"])  # noqa: E731
    transport = httpx.MockTransport(handler) if handler else None
    return SafeFetcher(config, resolver=resolver, transport=transport, **kwargs)


def html_response(
    body: str | bytes, content_type: str = "text/html; charset=utf-8", status: int = 200
):
    content = body.encode() if isinstance(body, str) else body
    return httpx.Response(status, headers={"content-type": content_type}, content=content)


class TestBlockedDestinations:
    @pytest.mark.parametrize(
        "url,host,ip",
        [
            ("http://127.0.0.1:8080/x", "127.0.0.1", "127.0.0.1"),
            ("http://localhost/x", "localhost", "127.0.0.1"),
            ("http://10.1.2.3/x", "10.1.2.3", "10.1.2.3"),
            ("http://192.168.0.7/x", "192.168.0.7", "192.168.0.7"),
            ("http://172.16.5.5/x", "172.16.5.5", "172.16.5.5"),
            ("http://169.254.169.254/latest/meta-data/", "169.254.169.254", "169.254.169.254"),
            ("http://[::1]/x", "::1", "::1"),
        ],
    )
    def test_internal_addresses_blocked(self, url, host, ip):
        fetcher = make_fetcher({host: [ip]})
        with pytest.raises(FetchError, match="bloqueado"):
            fetcher.fetch(url)

    def test_reserved_address_blocked(self):
        fetcher = make_fetcher({"reserved.example": ["240.0.0.1"]})
        with pytest.raises(FetchError, match="bloqueado"):
            fetcher.fetch("http://reserved.example/x")

    @pytest.mark.parametrize(
        "url",
        ["ftp://example.com/x", "file:///etc/passwd", "http://user:pass@example.com/x"],
    )
    def test_scheme_and_credentials_blocked(self, url):
        fetcher = make_fetcher({})
        with pytest.raises(FetchError):
            fetcher.fetch(url)


class TestRedirects:
    def test_redirect_to_internal_is_blocked(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "external.example":
                return httpx.Response(
                    302, headers={"location": "http://internal.example/steal"}
                )
            return html_response("<p>internal</p>")

        fetcher = make_fetcher(
            {"external.example": ["93.184.216.34"], "internal.example": ["10.9.8.7"]},
            handler=handler,
        )
        with pytest.raises(FetchError, match="bloqueado"):
            fetcher.fetch("http://external.example/start")

    def test_redirect_chain_is_followed_and_revalidated(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/a":
                return httpx.Response(301, headers={"location": "/b"})
            if request.url.path == "/b":
                return httpx.Response(302, headers={"location": "http://ok.example/c"})
            return html_response("<p>chegou</p>")

        fetcher = make_fetcher(
            {"start.example": ["93.184.216.34"], "ok.example": ["93.184.216.35"]},
            handler=handler,
        )
        page = fetcher.fetch("http://start.example/a")
        assert "chegou" in page.content
        assert page.final_url == "http://ok.example/c"

    def test_too_many_redirects(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "/next"})

        fetcher = make_fetcher({"loop.example": ["93.184.216.34"]}, handler=handler)
        with pytest.raises(FetchError, match="redirecionamentos"):
            fetcher.fetch("http://loop.example/x")


class TestLimits:
    def test_content_too_large(self):
        body = "x" * (2 * 1024 * 1024 + 1)
        fetcher = make_fetcher(
            {"big.example": ["93.184.216.34"]},
            handler=lambda request: html_response(body),
        )
        with pytest.raises(FetchError, match="excede"):
            fetcher.fetch("http://big.example/x")

    def test_content_length_too_large_rejected_before_download(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html", "content-length": str(10 * 1024 * 1024)},
                content=b"small",
            )

        fetcher = make_fetcher({"big.example": ["93.184.216.34"]}, handler=handler)
        with pytest.raises(FetchError, match="excede"):
            fetcher.fetch("http://big.example/x")

    def test_disallowed_content_type(self):
        fetcher = make_fetcher(
            {"bin.example": ["93.184.216.34"]},
            handler=lambda request: html_response(
                b"\x00\x01", content_type="application/octet-stream"
            ),
        )
        with pytest.raises(FetchError, match="conteúdo"):
            fetcher.fetch("http://bin.example/x")

    def test_http_error_status(self):
        fetcher = make_fetcher(
            {"gone.example": ["93.184.216.34"]},
            handler=lambda request: httpx.Response(404, headers={"content-type": "text/html"}),
        )
        with pytest.raises(FetchError, match="404"):
            fetcher.fetch("http://gone.example/x")

    def test_timeout_respects_remaining_time(self):
        # O timeout efetivo é limitado ao tempo restante da execução.
        config = Config(network_timeout=20.0)
        fetcher = SafeFetcher(
            config, remaining_seconds=lambda: 0.3
        )
        assert fetcher._effective_timeout() == 0.3
        fetcher = SafeFetcher(config, remaining_seconds=lambda: 0.0)
        assert fetcher._effective_timeout() == 0.05  # piso mínimo positivo
        fetcher = SafeFetcher(config, remaining_seconds=lambda: 100.0)
        assert fetcher._effective_timeout() == 20.0


class TestSuccess:
    def test_normal_page(self):
        fetcher = make_fetcher(
            {"ok.example": ["93.184.216.34"]},
            handler=lambda request: html_response(
                "<html><head><title>Ok</title></head><body><p>conteúdo</p></body></html>"
            ),
        )
        page = fetcher.fetch("http://ok.example/pagina")
        assert "conteúdo" in page.content
        assert page.requested_url == "http://ok.example/pagina"
