"""Storage: SQLite metadata, segment and cache repositories."""

from __future__ import annotations

from formiga.storage.db import (
    ForeignSchema,
    StorageError,
    connect,
    open_database,
    schema_version,
    supports_fts5,
)
from formiga.storage.idempotency import (
    invalidated_by,
    llm_cache_key,
    stage_key,
)

__all__ = [
    "ForeignSchema",
    "StorageError",
    "connect",
    "invalidated_by",
    "llm_cache_key",
    "open_database",
    "schema_version",
    "stage_key",
    "supports_fts5",
]
