"""Adaptadores falsos para testes offline: LLM, busca e fetch."""

from __future__ import annotations

import json
from pathlib import Path

from formiga.fetch import FetchedPage, FetchError
from formiga.llm import LLMResponse, TaskType
from formiga.search import SearchResult

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


class FakeLLM:
    """Devolve conteúdo scriptado por tipo de tarefa; o último item se repete.

    `overrides` permite injetar comportamento programático por tarefa.
    """

    def __init__(self, script: dict[TaskType, list[str]], overrides: dict | None = None) -> None:
        self.script = {t: list(v) for t, v in script.items()}
        self.overrides = overrides or {}
        self.calls: list[tuple[TaskType, str]] = []

    def complete(self, system: str, user: str, json_schema: dict | None = None) -> LLMResponse:
        task = self._current_task(user)
        self.calls.append((task, user))
        if task in self.overrides:
            return LLMResponse(content=self.overrides[task](user))
        items = self.script.get(task)
        if not items:
            raise AssertionError(f"FakeLLM sem script para tarefa {task}")
        content = items[0] if len(items) == 1 else items.pop(0)
        return LLMResponse(content=content, tokens=None)

    def _current_task(self, user: str) -> TaskType:
        # O usuário é identificado pela primeira linha do prompt ("Tarefa: ...").
        for task in TaskType:
            if user.startswith(_TASK_USER_PREFIX[task]):
                return task
        raise AssertionError("Não foi possível identificar a tarefa pelo prompt")

    def calls_for(self, task: TaskType) -> int:
        return sum(1 for t, _ in self.calls if t == task)


def _task_word(task: TaskType) -> str:
    return {
        TaskType.PLAN: "dividir a pergunta",
        TaskType.QUERY: "propor até 2 consultas",
        TaskType.EXTRACT: "extrair afirmações",
        TaskType.VERIFY: "avaliar se as evidências",
        TaskType.COMPARE: "comparar afirmações",
        TaskType.SYNTHESIZE: "redigir a seção",
        TaskType.AUDIT: "auditar afirmações",
    }[task]


_TASK_USER_PREFIX = {t: f"Tarefa: {_task_word(t)}" for t in TaskType}


class FakeSearch:
    def __init__(
        self,
        results_by_query: dict[str, list[SearchResult]],
        fail_queries: set[str] | None = None,
    ):
        self.results_by_query = results_by_query
        self.fail_queries = fail_queries or set()
        self.queries: list[str] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.queries.append(query)
        if query in self.fail_queries:
            raise RuntimeError("provedor indisponível")
        return self.results_by_query.get(query, [])[:max_results]


class FakeFetcher:
    def __init__(self, pages: dict[str, str], fail_urls: set[str] | None = None):
        self.pages = pages
        self.fail_urls = fail_urls or set()
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchedPage:
        self.fetched.append(url)
        if url in self.fail_urls or url not in self.pages:
            raise FetchError(url, "conexão recusada (simulada)")
        return FetchedPage(requested_url=url, final_url=url, content=self.pages[url])


def load_script(spec: dict[str, list[str]]) -> dict[TaskType, list[str]]:
    return {TaskType[k]: [fixture(n) for n in v] for k, v in spec.items()}


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
