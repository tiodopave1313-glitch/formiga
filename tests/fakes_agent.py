"""Fakes para testes do agente (offline, sem rede nem modelo real)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from formiga.agent.chat import ChatResponse, ToolCall
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.config import Config
from formiga.fetch import FetchedPage, FetchError
from formiga.models import ResearchContract, ResearchState, Source
from formiga.orchestrator import ResearchResult
from formiga.search import SearchResult
from formiga.storage import append_event, save_report, save_state


class FakeChatClient:
    """Responde com roteiros scriptados: texto final ou chamada de ferramenta.

    Se a resposta tiver `deltas` (lista de strings), os pedaços são entregues
    via `on_delta` em ordem; o `content` final continua completo.
    """

    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict], list[dict] | None, int | None]] = []

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        on_delta=None,
    ) -> ChatResponse:
        self.calls.append((messages, tools, max_tokens))
        if not self.responses:
            raise AssertionError("FakeChatClient sem respostas restantes")
        response = self.responses.pop(0)
        if on_delta is not None:
            # Backends reais sempre entregam o content via on_delta; nos fakes,
            # usa os deltas roteirizados ou o content inteiro como um pedaço.
            deltas = response.deltas
            if deltas is None:
                deltas = [response.content] if response.content else []
            for piece in deltas:
                on_delta(piece)
        return response


def tool_call(name: str, arguments: str, call_id: str = "call_1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


# --------------------------------------------------------------------------
# Fake do orquestrador (para deep_search)


@dataclass
class FakeResearchResult:
    status: str = "suportada"
    report_path: Path = Path("research/run/report.md")
    state_path: Path = Path("research/run/state.json")


class FakeOrchestrator:
    """Substitui `run_research` em testes."""

    def __init__(
        self,
        result: FakeResearchResult | None = None,
        fail: bool = False,
        sources: list[dict] | None = None,
    ) -> None:
        self.result = result or FakeResearchResult()
        self.fail = fail
        self.sources = sources or []
        self.called_with: dict | None = None
        self.progress_messages: list[str] = []

    def __call__(
        self,
        config: Config,
        progress=None,
        **kwargs,
    ) -> ResearchResult:
        self.called_with = {
            "output": str(config.output),
            "question": config.question,
            "overwrite": config.overwrite,
        }
        if progress is not None:
            for m in ("planejado", "buscas", "síntese"):
                progress(m)
                self.progress_messages.append(m)
        if self.fail:
            raise RuntimeError("motor de pesquisa indisponível (simulado)")
        # grava report.md e state.json no diretório de saída para que a tool
        # consiga ler o estado (load_state)
        output_dir = config.output or Path("./formiga-out")
        output_dir.mkdir(parents=True, exist_ok=True)
        save_report(output_dir, "# Relatório simulado\n\nConteúdo do relatório.")
        # grava state.json com fontes para que a tool consiga listá-las
        state = ResearchState(
            contract=ResearchContract(question=config.question or "", objective="")
        )
        for i, s in enumerate(self.sources, start=1):
            state.sources.append(
                Source(
                    id=f"S{i}",
                    requested_url=s.get("requested_url", f"https://exemplo{i}.com"),
                    title=s.get("title"),
                )
            )
        save_state(output_dir, state)
        append_event(output_dir, "run_finished", {"status": self.result.status})
        return ResearchResult(
            status=self.result.status,
            report_path=output_dir / "report.md",
            state_path=output_dir / "state.json",
        )


def fake_run_research(result=None, fail=False, sources=None):
    return FakeOrchestrator(result=result, fail=fail, sources=sources)


# --------------------------------------------------------------------------
# Fake de busca (SearXNG)


class FakeSearchProvider:
    def __init__(
        self,
        results_by_query: dict[str, list[SearchResult]] | None = None,
        fail_queries: set[str] | None = None,
    ) -> None:
        self.results_by_query = results_by_query or {}
        self.fail_queries = fail_queries or set()
        self.queries: list[str] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.queries.append(query)
        if query in self.fail_queries:
            raise RuntimeError("provedor indisponível (simulado)")
        return self.results_by_query.get(query, [])[:max_results]


# --------------------------------------------------------------------------
# Fake de fetch


class FakeFetcher:
    def __init__(
        self,
        pages: dict[str, str] | None = None,
        fail_urls: set[str] | None = None,
    ) -> None:
        self.pages = pages or {}
        self.fail_urls = fail_urls or set()
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchedPage:
        self.fetched.append(url)
        if url in self.fail_urls or url not in self.pages:
            raise FetchError(url, "conexão recusada (simulada)")
        return FetchedPage(requested_url=url, final_url=url, content=self.pages[url])


# --------------------------------------------------------------------------
# Helper: constrói um registry a partir de ferramentas instanciadas.
#
# Os testes do agente (v1) constroem `AgentLoop(chat, [tools], session, cfg)`.
# Na Fase 1 do v2 o loop requer um `ExtensionRegistry`, então este helper
# registra cada tool lendo seu orçamento declarado (`budget_per_message` ou
# `budget_config_attr` lido do `config`) e o cap default do agente.


def registry_of(
    *tools,
    config: Config | None = None,
    default_cap_chars: int = 4000,
) -> ExtensionRegistry:
    """Registra ferramentas em um `ExtensionRegistry` e o retorna.

    `config` é usado para resolver `budget_config_attr` quando a tool não
    declara `budget_per_message` diretamente, e para sobrescrever o valor
    capturado no `budget_per_message` da tool quando `budget_config_attr`
    estiver presente (o orçamento efetivo é lido do config no registro).
    """
    registry = ExtensionRegistry()
    for tool in tools:
        budget = getattr(tool, "budget_per_message", None)
        config_attr = getattr(tool, "budget_config_attr", None)
        if config is not None and config_attr:
            budget = int(getattr(config, config_attr))
        cap_chars = getattr(tool, "cap_chars", None)
        prompt_hint = getattr(tool, "prompt_hint", None)
        registry.register_tool(
            tool,
            budget_per_message=budget,
            cap_chars=cap_chars,
            prompt_hint=prompt_hint,
        )
    return registry

