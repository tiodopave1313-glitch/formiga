"""SQLite connection handling, migrations and capability detection."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any

SCHEMA_VERSION_KEY = "schema_version"
BUSY_TIMEOUT_MS = 5000
MIGRATIONS_PACKAGE = "formiga.storage.migrations"

#: Tables the F0 schema owns. Any other non-empty database is not ours.
FOUNDATION_TABLES = frozenset(
    {
        "meta",
        "sessions",
        "messages",
        "runs",
        "stage_runs",
        "sources",
        "run_sources",
        "segments",
        "segments_fts",
        "notes",
        "claims",
        "citations",
        "llm_cache",
    }
)


class StorageError(RuntimeError):
    """Raised when the database cannot be prepared."""


class ForeignSchema(StorageError):
    """Raised when the file exists but belongs to another application."""

    def __init__(self, path: Path, tables: tuple[str, ...]) -> None:
        self.path = path
        self.tables = tables
        super().__init__(f"{path} is not a Formiga database (tables: {', '.join(tables)})")


def migration_files() -> list[tuple[int, str, str]]:
    """Return ``(version, name, sql)`` for every bundled migration, ordered."""
    found: list[tuple[int, str, str]] = []
    root = resources.files(MIGRATIONS_PACKAGE)
    for entry in sorted(root.iterdir()):
        name = entry.name
        if not name.endswith(".sql"):
            continue
        try:
            version = int(name.split("_", 1)[0])
        except ValueError as exc:
            raise StorageError(f"migration name must start with a number: {name}") from exc
        found.append((version, name, entry.read_text(encoding="utf-8")))
    return found


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with the pragmas the pipeline depends on."""
    target = str(path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys = ON")
    if target != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def tables_in(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return tuple(sorted(row["name"] for row in rows))


def _meta_columns(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("PRAGMA table_info(meta)").fetchall()
    return {row["name"] for row in rows}


def has_manifest(connection: sqlite3.Connection) -> bool:
    """True when the file carries a ``meta(key, value)`` table, i.e. it is ours.

    Ownership is decided by the shape of the manifest, never by the presence of table
    names alone: an older build shipped a ``meta`` table with a single
    ``schema_version`` column and shared ``runs``/``sources``/``notes`` names, so a
    name-based check would happily adopt a database it cannot migrate.
    """
    if "meta" not in tables_in(connection):
        return False
    return {"key", "value"} <= _meta_columns(connection)


def has_foreign_schema(connection: sqlite3.Connection) -> bool:
    """True when the file holds tables but no manifest that belongs to Formiga."""
    if not tables_in(connection):
        return False
    return not has_manifest(connection)


def schema_version(connection: sqlite3.Connection) -> int:
    """Return the applied schema version, or 0 when the database is empty."""
    if not has_manifest(connection):
        return 0
    row = connection.execute(
        "SELECT value FROM meta WHERE key = ?", (SCHEMA_VERSION_KEY,)
    ).fetchone()
    return int(row["value"]) if row else 0


def supports_fts5(connection: sqlite3.Connection) -> bool:
    """Return whether the linked SQLite build provides FTS5."""
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.__fts5_probe USING fts5(x)")
    except sqlite3.OperationalError:
        return False
    connection.execute("DROP TABLE temp.__fts5_probe")
    return True


def migrate(connection: sqlite3.Connection, *, path: Path | None = None) -> int:
    """Apply every pending migration atomically and return the resulting version."""
    current = schema_version(connection)
    if current == 0 and has_foreign_schema(connection):
        raise ForeignSchema(path or Path("<memory>"), tables_in(connection))
    for version, name, sql in migration_files():
        if version <= current:
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            _execute_script(connection, sql)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION_KEY, str(version)),
            )
            connection.execute("COMMIT")
        except Exception as exc:
            connection.execute("ROLLBACK")
            raise StorageError(f"migration failed: {name}") from exc
        current = version
    return current


def _execute_script(connection: sqlite3.Connection, sql: str) -> None:
    """Execute a script statement by statement inside an open transaction.

    ``sqlite3.Cursor.executescript`` commits implicitly, which would break the wrapping
    transaction and leave a half-applied schema behind.
    """
    buffer = ""
    for line in sql.splitlines(keepends=True):
        if line.strip().startswith("--"):
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement:
                connection.execute(statement)
    if buffer.strip() and not buffer.strip().startswith("--"):
        connection.execute(buffer.strip())


@contextmanager
def open_database(path: Path | str, *, migrate_schema: bool = True) -> Iterator[sqlite3.Connection]:
    """Open, migrate and close a database, closing on error."""
    target = Path(path) if str(path) != ":memory:" else Path(":memory:")
    connection = connect(path)
    try:
        if migrate_schema:
            migrate(connection, path=None if str(path) == ":memory:" else target)
        yield connection
    finally:
        connection.close()


def fetch_one(
    connection: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> sqlite3.Row | None:
    return connection.execute(sql, params).fetchone()


def fetch_all(
    connection: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[sqlite3.Row]:
    return list(connection.execute(sql, params).fetchall())


__all__ = [
    "BUSY_TIMEOUT_MS",
    "FOUNDATION_TABLES",
    "ForeignSchema",
    "SCHEMA_VERSION_KEY",
    "StorageError",
    "connect",
    "fetch_all",
    "fetch_one",
    "has_foreign_schema",
    "has_manifest",
    "migrate",
    "migration_files",
    "open_database",
    "schema_version",
    "supports_fts5",
    "tables_in",
]
