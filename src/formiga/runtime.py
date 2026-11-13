"""Wiring: settings to a running chat session.

One place builds the backends, the budget, the cache and the router, so the CLI and the
tests construct the same object graph. Nothing here requires two endpoints.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from formiga.config import Settings
from formiga.core.budget import Budget
from formiga.core.chat import ChatSession
from formiga.core.citations import CitationLedger
from formiga.core.doctor import total_ram_gb
from formiga.core.init import init_home
from formiga.core.prompts import PROMPT_VERSION
from formiga.llm.cache import LLMCache
from formiga.llm.governed import GovernedLLM
from formiga.llm.router import RoleRouter
from formiga.research.contract import get_profile
from formiga.storage.db import connect, migrate


@dataclass
class Runtime:
    """Everything a single invocation needs, with explicit close."""

    settings: Settings
    router: RoleRouter
    llm: GovernedLLM
    budget: Budget
    cache: LLMCache
    connection: sqlite3.Connection
    session: ChatSession

    def close(self) -> None:
        self.connection.close()
        self.router.close()

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def ensure_state(settings: Settings) -> sqlite3.Connection:
    """Create the home and migrate the database before any command touches it."""
    home: Path = settings.paths.home
    if not home.exists() or not (home / "config.toml").exists():
        init_home(home=home, language=settings.language, ram_gb=total_ram_gb())
    connection = connect(settings.paths.db)
    migrate(connection, path=settings.paths.db)
    return connection


def build_runtime(
    settings: Settings,
    *,
    connection: sqlite3.Connection | None = None,
    profile: str | None = None,
) -> Runtime:
    """Build the object graph for one invocation."""
    connection = connection or ensure_state(settings)
    spec = get_profile(profile or settings.report.profile, overrides=settings.report.profiles)
    budget = Budget.from_profile(spec, layout=settings.layout.name)
    if settings.budget.max_llm_calls is not None:
        budget.max_llm_calls = settings.budget.max_llm_calls
    if settings.budget.max_output_tokens is not None:
        budget.max_output_tokens = settings.budget.max_output_tokens
    if settings.budget.deadline_s is not None:
        budget.deadline_s = settings.budget.deadline_s

    router = RoleRouter(layout=settings.layout)
    cache = LLMCache(connection, prompt_version=PROMPT_VERSION)
    llm = GovernedLLM(
        router.backends["fast"],
        budget,
        cache,
        prompt_version=PROMPT_VERSION,
    )
    session = ChatSession(
        llm=llm,
        router=router,
        ledger=CitationLedger(),
        language=settings.language,
        answer_temperature=settings.layout.fast.temperature_for("answerer"),
    )
    return Runtime(
        settings=settings,
        router=router,
        llm=llm,
        budget=budget,
        cache=cache,
        connection=connection,
        session=session,
    )


__all__ = ["Runtime", "build_runtime", "ensure_state"]
