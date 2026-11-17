"""Testes das ferramentas de web: `web_search` e `web_fetch` (offline, fakes)."""

from __future__ import annotations

from formiga.agent.tools.web import WebFetchTool, WebSearchTool
from formiga.config import Config
from formiga.search import SearchResult
from tests.fakes_agent import FakeFetcher, FakeSearchProvider


def _config() -> Config:
    return Config(
        searxng_url="http://localhost:8080",
        max_http_bytes=2 * 1024 * 1024,
        network_timeout=20.0,
    )


def test_web_search_resultados(tmp_path):
    searcher = FakeSearchProvider(
        {
            "python": [
                SearchResult(
                    url="https://exemplo.com/a",
                    title="Python A",
                    snippet="snippet do A",
                ),
                SearchResult(
                    url="https://exemplo.com/b",
                    title="Python B",
                    snippet="snippet do B",
                ),
            ]
        }
    )
    tool = WebSearchTool(_config(), searcher=searcher)
    out = tool.execute("python", max_results=5)
    assert out.ok
    assert "Python A" in out.text
    assert "https://exemplo.com/a" in out.text
    assert "snippet do A" in out.text
    assert len(searcher.queries) == 1


def test_web_search_dedupe(tmp_path):
    searcher = FakeSearchProvider(
        {
            "python": [
                SearchResult(url="https://exemplo.com/a/", title="A", snippet="s1"),
                SearchResult(url="https://exemplo.com/a", title="A dup", snippet="s2"),
            ]
        }
    )
    tool = WebSearchTool(_config(), searcher=searcher)
    out = tool.execute("python")
    assert out.ok
    # A URL normalizada é a mesma, deve aparecer apenas uma vez
    assert out.text.count("exemplo.com") == 1


def test_web_search_vazio(tmp_path):
    searcher = FakeSearchProvider({})
    tool = WebSearchTool(_config(), searcher=searcher)
    out = tool.execute("coisa inexistente xyz")
    assert out.ok
    assert "sem resultados" in out.text


def test_web_search_falha_provedor(tmp_path):
    searcher = FakeSearchProvider(fail_queries={"quebra"})
    tool = WebSearchTool(_config(), searcher=searcher)
    out = tool.execute("quebra")
    assert not out.ok
    assert "ERRO" in out.text


def test_web_fetch_sucesso(tmp_path):
    html = "<html><body><h1>Titulo</h1><p>conteudo principal da pagina</p></body></html>"
    fetcher = FakeFetcher(pages={"https://exemplo.com/pagina": html})
    tool = WebFetchTool(_config(), fetcher=fetcher)
    out = tool.execute("https://exemplo.com/pagina")
    assert out.ok
    assert "Titulo" in out.text or "conteudo principal" in out.text
    assert len(fetcher.fetched) == 1


def test_web_fetch_url_invalida(tmp_path):
    fetcher = FakeFetcher()
    tool = WebFetchTool(_config(), fetcher=fetcher)
    out = tool.execute("ftp://exemplo.com")
    assert not out.ok
    assert "ERRO" in out.text


def test_web_fetch_erro_rede(tmp_path):
    fetcher = FakeFetcher(fail_urls={"https://exemplo.com/indisponivel"})
    tool = WebFetchTool(_config(), fetcher=fetcher)
    out = tool.execute("https://exemplo.com/indisponivel")
    assert not out.ok
    assert "ERRO" in out.text
