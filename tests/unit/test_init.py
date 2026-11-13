"""``formiga init``: layout detection, idempotency and legacy-state migration.

A pre-v5 home is *moved aside*, never deleted and never half-read. These tests pin both
halves of that promise: the legacy files survive byte-identical under a ``.legacy``
suffix, and the directory ends up holding a working v5 database.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from formiga.config import ConfigError, load_settings
from formiga.core.init import init_home, init_messages, render_config
from formiga.storage.db import has_foreign_schema, has_manifest

#: A config in the format shipped before v5: Portuguese keys, ``[geral]``, ``[llm]``.
LEGACY_CONFIG = """\
[geral]
idioma = "pt-BR"
modelo = "qwen"

[saida]
diretorio = "~/formiga"

[llm]
endpoint = "http://127.0.0.1:8080"
ctx = 8192

[budget]
chamadas_llm = 40
tokens_saida = 4000

[[corpus.adaptadores]]
nome = "pasta"
caminho = "~/docs"
"""


def _legacy_database(path: Path) -> None:
    """Write a database whose ``meta`` and ``runs`` tables share our names but not our
    shape - the exact trap that fooled a name-based ownership check."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE meta (schema_version INTEGER NOT NULL);
        INSERT INTO meta VALUES (1);
        CREATE TABLE runs (id INTEGER PRIMARY KEY, pergunta TEXT);
        CREATE TABLE corpus_docs (id INTEGER PRIMARY KEY, text TEXT);
        """
    )
    connection.commit()
    connection.close()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_legacy_config_is_moved_aside_not_deleted(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config = home / "config.toml"
    config.write_text(LEGACY_CONFIG, encoding="utf-8")
    original = _digest(config)

    result = init_home(home=home, layout="single", ram_gb=8.0)

    assert result.config_written
    assert result.backups == [str(home / "config.toml.legacy")]
    assert _digest(home / "config.toml.legacy") == original
    assert "[[corpus.adaptadores]]" in (home / "config.toml.legacy").read_text()
    # The new config is ours and loads without a legacy error.
    assert load_settings(home=home, environ={}).layout.name == "single"


def test_backup_never_overwrites_a_previous_backup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml.legacy").write_text("first backup\n", encoding="utf-8")
    (home / "config.toml").write_text(LEGACY_CONFIG, encoding="utf-8")

    result = init_home(home=home, layout="single", ram_gb=8.0)

    assert (home / "config.toml.legacy").read_text() == "first backup\n"
    assert (home / "config.toml.legacy2").exists()
    assert result.backups == [str(home / "config.toml.legacy2")]


def test_legacy_database_is_moved_aside_and_replaced(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _legacy_database(home / "formiga.db")

    result = init_home(home=home, layout="single", ram_gb=8.0)

    assert result.database_created is True
    assert str(home / "formiga.db.legacy") in result.backups
    preserved = sqlite3.connect(home / "formiga.db.legacy")
    try:
        tables = {row[0] for row in preserved.execute("SELECT name FROM sqlite_master")}
    finally:
        preserved.close()
    assert {"corpus_docs", "runs"} <= tables

    fresh = sqlite3.connect(home / "formiga.db")
    fresh.row_factory = sqlite3.Row
    try:
        assert has_manifest(fresh)
        assert not has_foreign_schema(fresh)
        version = fresh.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()[0]
    finally:
        fresh.close()
    assert int(version) >= 1


def test_database_wal_siblings_are_moved_with_the_database(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _legacy_database(home / "formiga.db")
    (home / "formiga.db-wal").write_bytes(b"stale wal")

    init_home(home=home, layout="single", ram_gb=8.0)

    assert (home / "formiga.db-wal.legacy").read_bytes() == b"stale wal"
    assert not (home / "formiga.db-wal").exists()


def test_a_fresh_home_reports_no_backups(tmp_path: Path) -> None:
    result = init_home(home=tmp_path / "clean", layout="single", ram_gb=8.0)
    assert result.backups == []
    assert result.profiles == ("short", "medium")


def test_legacy_config_file_is_refused_by_the_loader(tmp_path: Path) -> None:
    """``load_settings`` never half-reads a pre-v5 file, even outside ``init``."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text(LEGACY_CONFIG, encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_settings(home=home, environ={})

    assert "legacy config format" in str(caught.value)
    assert caught.value.source == home / "config.toml"


def test_init_is_idempotent_on_a_v5_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = init_home(home=home, layout="single", ram_gb=8.0)
    second = init_home(home=home, layout="single", ram_gb=8.0)
    assert first.config_written
    assert first.database_created
    assert not second.config_written
    assert second.backups == []


def test_force_rewrites_the_config_without_a_backup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    init_home(home=home, layout="single", ram_gb=8.0)
    (home / "config.toml").write_text(
        render_config(layout="single", language="pt-BR"), encoding="utf-8"
    )
    forced = init_home(home=home, layout="dual", force=True, ram_gb=16.0)
    assert forced.config_written
    assert forced.backups == []


def test_init_messages_announce_the_backup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text(LEGACY_CONFIG, encoding="utf-8")
    result = init_home(home=home, layout="single", ram_gb=8.0)
    english = init_messages(result, locale="en")
    portuguese = init_messages(result, locale="pt-BR")
    assert any("config.toml.legacy" in message for message in english)
    assert any("config.toml.legacy" in message for message in portuguese)
