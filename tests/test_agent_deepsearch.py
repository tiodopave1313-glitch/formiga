"""Testes da ferramenta `deep_search` (offline, orquestrador fake)."""

from __future__ import annotations

from formiga.agent.tools.deepsearch import DeepSearchTool
from formiga.config import Config
from tests.fakes_agent import FakeOrchestrator


def _config() -> Config:
    return Config(
        searxng_url="http://localhost:8080",
        max_searches=12,
        max_pages=18,
        max_llm_calls=40,
        timeout_seconds=900,
    )


def test_deep_search_retorna_resumo_e_fontes(tmp_path):
    research_dir = tmp_path / "research"
    orchestrator = FakeOrchestrator(
        sources=[
            {"title": "Fonte A", "requested_url": "https://a.com"},
            {"title": "Fonte B", "requested_url": "https://b.com"},
        ]
    )
    tool = DeepSearchTool(_config(), research_dir, run_fn=orchestrator)
    out = tool.execute("qual o impacto da mudança de X?")
    assert out.ok
    assert "Status: suportada" in out.text
    assert "Fonte A" in out.text
    assert "https://a.com" in out.text
    assert "Relatório completo" in out.text
    assert len(orchestrator.progress_messages) == 3  # planejado, buscas, síntese


def test_deep_search_pergunta_vazia(tmp_path):
    tool = DeepSearchTool(_config(), tmp_path / "research")
    out = tool.execute("")
    assert not out.ok
    assert "vazia" in out.text.lower()


def test_deep_search_falha_motor_nao_encerra_sessao(tmp_path):
    research_dir = tmp_path / "research"
    orchestrator = FakeOrchestrator(fail=True)
    tool = DeepSearchTool(_config(), research_dir, run_fn=orchestrator)
    out = tool.execute("qualquer coisa")
    assert not out.ok
    assert "ERRO" in out.text
    assert "deep_search falhou" in out.text
