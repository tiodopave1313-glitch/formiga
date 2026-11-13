"""Schema, migrations, idempotency keys and run locks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from formiga.storage.db import (
    ForeignSchema,
    StorageError,
    connect,
    has_foreign_schema,
    migrate,
    migration_files,
    schema_version,
    supports_fts5,
    tables_in,
)
from formiga.storage.idempotency import (
    invalidated_by,
    llm_cache_key,
    sha256_text,
    stage_key,
)
from formiga.storage.lock import LockBusy, RunLock, is_locked


def test_migrations_are_ordered_and_numbered() -> None:
    files = migration_files()
    assert files
    versions = [version for version, _, _ in files]
    assert versions == sorted(versions)


def test_fresh_database_reaches_the_latest_version(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    connection = connect(db)
    try:
        version = migrate(connection, path=db)
        assert version == max(version for version, _, _ in migration_files())
        assert schema_version(connection) == version
    finally:
        connection.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "again.db"
    connection = connect(db)
    try:
        first = migrate(connection, path=db)
        second = migrate(connection, path=db)
        assert first == second
    finally:
        connection.close()


def test_every_contract_table_exists(connection: sqlite3.Connection) -> None:
    tables = set(tables_in(connection))
    expected = {
        "meta",
        "sessions",
        "messages",
        "runs",
        "stage_runs",
        "run_sources",
        "sources",
        "segments",
        "notes",
        "claims",
        "citations",
        "llm_cache",
    }
    assert expected <= tables


def test_fts5_is_available_and_indexes_segments(connection: sqlite3.Connection) -> None:
    assert supports_fts5(connection)
    connection.execute(
        "INSERT INTO sources (url, normalized_url, created_at) VALUES (?, ?, ?)",
        ("https://example.org/a", "example.org/a", "2026-01-01T00:00:00"),
    )
    connection.execute(
        "INSERT INTO segments (source_id, idx, text, start_char, end_char) "
        "VALUES (1, 0, 'rosemary tolerates dry cold', 0, 27)"
    )
    row = connection.execute(
        "SELECT text, bm25(segments_fts) AS score FROM segments_fts "
        "WHERE segments_fts MATCH 'rosemary'"
    ).fetchone()
    assert row is not None
    assert "rosemary" in row["text"]


def test_segments_fts_follows_updates_and_deletes(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO sources (url, normalized_url, created_at) VALUES (?, ?, ?)",
        ("https://example.org/b", "example.org/b", "2026-01-01T00:00:00"),
    )
    connection.execute(
        "INSERT INTO segments (source_id, idx, text, start_char, end_char) "
        "VALUES (1, 0, 'thyme prefers lean soil', 0, 22)"
    )
    connection.execute("UPDATE segments SET text = 'sage prefers dry soil' WHERE id = 1")
    assert connection.execute(
        "SELECT 1 FROM segments_fts WHERE segments_fts MATCH 'thyme'"
    ).fetchone() is None
    assert connection.execute(
        "SELECT 1 FROM segments_fts WHERE segments_fts MATCH 'sage'"
    ).fetchone() is not None
    connection.execute("DELETE FROM segments WHERE id = 1")
    assert connection.execute(
        "SELECT 1 FROM segments_fts WHERE segments_fts MATCH 'sage'"
    ).fetchone() is None


def test_run_sources_pins_the_citation_number(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO runs (id, question, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("01R", "q", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    connection.execute(
        "INSERT INTO sources (url, normalized_url, created_at) VALUES (?, ?, ?)",
        ("https://example.org/c", "example.org/c", "2026-01-01T00:00:00"),
    )
    connection.execute("INSERT INTO run_sources (run_id, n, source_id) VALUES ('01R', 1, 1)")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO run_sources (run_id, n, source_id) VALUES ('01R', 1, 1)")


def test_foreign_database_is_refused_not_repaired(tmp_path: Path) -> None:
    db = tmp_path / "alien.db"
    alien = sqlite3.connect(db)
    alien.execute("CREATE TABLE corpus_docs (id INTEGER PRIMARY KEY)")
    alien.commit()
    alien.close()

    connection = connect(db)
    try:
        assert has_foreign_schema(connection)
        with pytest.raises(ForeignSchema) as caught:
            migrate(connection, path=db)
        assert "corpus_docs" in str(caught.value)
    finally:
        connection.close()
    assert "corpus_docs" in {
        row[0] for row in sqlite3.connect(db).execute("SELECT name FROM sqlite_master")
    }


def test_stage_key_changes_with_every_component() -> None:
    base = stage_key("extract", dependency_hashes={"fetch": "abc"})
    assert base == stage_key("extract", dependency_hashes={"fetch": "abc"})
    assert base != stage_key("extract", dependency_hashes={"fetch": "abd"})
    assert base != stage_key("extract", dependency_hashes={"fetch": "abc"}, layout="dual")
    assert base != stage_key("extract", dependency_hashes={"fetch": "abc"}, profile="long")
    assert base != stage_key("extract", dependency_hashes={"fetch": "abc"},
                             segmenter_version="2")
    assert base != stage_key("extract", dependency_hashes={"fetch": "abc"},
                             prompt_version="9")


def test_unknown_stage_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        stage_key("summarise")


def test_segmenter_bump_does_not_invalidate_fetch() -> None:
    assert "fetch" not in invalidated_by("segmenter_version")
    assert "extract" in invalidated_by("extract")
    assert "compose" in invalidated_by("extract")
    assert invalidated_by("compose") == ()


def test_llm_cache_key_includes_rung_and_grammar() -> None:
    base = {"prompt": "p", "model": "m", "temperature": 0.0}
    reference = llm_cache_key(**base)
    assert reference != llm_cache_key(**base, rung="bounded-edit")
    assert reference != llm_cache_key(**base, grammar_hash="abc")
    assert reference != llm_cache_key(**base, schema_version="4")
    assert reference == llm_cache_key(**base)


def test_sha256_text_is_stable() -> None:
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")


def test_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    first = RunLock(path).acquire()
    try:
        with pytest.raises(LockBusy):
            RunLock(path).acquire()
        assert is_locked(path)
    finally:
        first.release()
    assert not is_locked(path)


def test_lock_records_the_pid(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    with RunLock(path):
        assert path.read_text().isdigit()


def test_connection_sets_wal_and_foreign_keys(tmp_path: Path) -> None:
    connection = connect(tmp_path / "pragmas.db")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_storage_error_is_raised_for_a_broken_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "formiga.storage.db.migration_files", lambda: [(1, "0001_bad.sql", "CREATE TABLE")]
    )
    connection = connect(":memory:")
    try:
        with pytest.raises(StorageError):
            migrate(connection)
    finally:
        connection.close()
