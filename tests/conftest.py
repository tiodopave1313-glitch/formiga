"""Shared fixtures: an isolated home directory, a fake LLM and a runtime graph."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from formiga.config import Layout, Settings, load_settings
from formiga.core.budget import Budget
from formiga.llm.cache import LLMCache
from formiga.llm.router import RoleRouter
from formiga.storage.db import connect, migrate


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """An empty application home."""
    directory = tmp_path / "home"
    directory.mkdir()
    return directory


@pytest.fixture
def settings(home: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Single-layout settings pointed at ``home`` with no ambient env interference."""
    for name in (
        "FORMIGA_LANGUAGE",
        "FORMIGA_OUTPUT_LANGUAGE",
        "FORMIGA_PROFILE",
        "FORMIGA_LAYOUT",
        "FORMIGA_ENDPOINT",
        "FORMIGA_MODEL",
        "FORMIGA_RUNG_CEILING",
        "FORMIGA_ALLOW_HEAVY",
        "FORMIGA_HOME",
        "FORMIGA_REPORTS_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FORMIGA_HOME", str(home))
    monkeypatch.setenv("FORMIGA_REPORTS_DIR", str(home / "reports"))
    return load_settings(home=home, environ={})


@pytest.fixture
def connection(tmp_path: Path) -> Iterator:
    """A migrated in-file SQLite database."""
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    migrate(conn, path=db_path)
    yield conn
    conn.close()


@pytest.fixture
def budget() -> Budget:
    """A generous budget that never interferes with a test."""
    return Budget(max_llm_calls=50, max_output_tokens=100_000, deadline_s=600.0)


@pytest.fixture
def layout() -> Layout:
    return Layout()


@pytest.fixture
def router(layout: Layout) -> RoleRouter:
    return RoleRouter(layout=layout)


@pytest.fixture
def cache() -> LLMCache:
    return LLMCache()
