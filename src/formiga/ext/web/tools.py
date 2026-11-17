"""Ferramentas de web: `web_search` e `web_fetch` (seção 6.2 do PRD).

Pares leves de primeira intenção: `web_search` consulta o SearXNG configurado;
`web_fetch` baixa e extrai o texto principal de uma URL pública. Ambos têm
orçamentos próprios por mensagem do usuário, gerenciados pelos guardrails.
"""

from __future__ import annotations

from formiga.agent.tools.base import ToolResult
from formiga.config import Config
from formiga.extract import extract_main_text
from formiga.fetcher import FetchError, SafeFetcher
from formiga.search import dedupe_results
from formiga.searxng import SearxngSearch

WEB_CAP_CHARS = 4000


class WebSearchTool:
    budget_config_attr = "agent_max_web_searches"
    name = "web_search"
    description = (
        "Busca rápida na web (SearXNG). Retorna `título — url` + snippet por "
        "resultado, limitado a 4 000 chars. Use para checar 1–2 fatos."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Consulta de busca."},
            "max_results": {
                "type": "integer",
                "description": "Máximo de resultados (default 6).",
                "default": 6,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, config: Config, searcher=None) -> None:
        self.config = config
        self.budget_per_message = int(getattr(config, "agent_max_web_searches", 6))
        self._searcher = searcher or SearxngSearch(config)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, query: str, max_results: int = 6) -> ToolResult:
        if not query or not query.strip():
            return ToolResult(ok=False, text="ERRO: consulta vazia.", error="empty_query")
        max_results = max(1, min(max_results or 6, 20))
        try:
            results = self._searcher.search(query.strip(), max_results)
        except Exception as exc:  # falha de rede/provedor → ERRO ao modelo
            return ToolResult(
                ok=False, text=f"ERRO: falha na busca: {exc}", error=str(exc)
            )
        results = dedupe_results(results)
        if not results:
            return ToolResult(ok=True, text="(sem resultados para esta consulta)")
        lines = []
        for r in results:
            title = r.title or "(sem título)"
            snippet = (r.snippet or "").strip()
            if len(snippet) > 200:
                snippet = snippet[:200] + "…"
            lines.append(f"{title} — {r.url}")
            if snippet:
                lines.append(f"  {snippet}")
        text = "\n".join(lines)
        if len(text) > WEB_CAP_CHARS:
            text = text[:WEB_CAP_CHARS] + "\n…(truncado)"
        return ToolResult(ok=True, text=text)


class WebFetchTool:
    budget_config_attr = "agent_max_web_fetches"
    name = "web_fetch"
    description = (
        "Baixa e extrai o texto principal de uma URL pública (http/https). "
        "Bloqueia localhost e redes privadas. Retorno limitado a 4 000 chars."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL pública a buscar."},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, config: Config, fetcher=None) -> None:
        self.config = config
        self.budget_per_message = int(getattr(config, "agent_max_web_fetches", 8))
        self._fetcher = fetcher

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, url: str) -> ToolResult:
        if not url or not url.strip():
            return ToolResult(ok=False, text="ERRO: URL vazia.", error="empty_url")
        fetcher = self._fetcher or SafeFetcher(
            self.config,
            remaining_seconds=None,
        )
        try:
            page = fetcher.fetch(url.strip())
        except FetchError as exc:
            return ToolResult(
                ok=False, text=f"ERRO: não foi possível buscar a URL: {exc.reason}", error=str(exc)
            )
        except Exception as exc:  # pragma: no cover — defesa
            return ToolResult(ok=False, text=f"ERRO: falha ao buscar: {exc}", error=str(exc))
        try:
            text, title = extract_main_text(page.content)
        except Exception as exc:
            return ToolResult(
                ok=False, text=f"ERRO: não foi possível extrair o texto: {exc}", error=str(exc)
            )
        header = f"{title or page.final_url or url}\n{page.final_url or url}\n\n"
        body = header + text
        if len(body) > WEB_CAP_CHARS:
            body = body[:WEB_CAP_CHARS] + "\n…(truncado)"
        return ToolResult(ok=True, text=body)
