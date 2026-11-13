"""Response cache keyed by everything a stale hit would silently invalidate.

The key includes ``schema_version``, ``grammar_hash``, ``rung`` and ``prompt_version``.
Dropping any of them serves stale-but-valid JSON after a schema change, or an
``assemble`` answer to a ``bounded-edit`` request (PRD §6.4).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from formiga.llm.types import Completion, CompletionRequest
from formiga.storage.idempotency import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    canonical_json,
    llm_cache_key,
    sha256_text,
)


def request_prompt(request: CompletionRequest) -> str:
    """Flatten a request into the prompt material used by the cache key."""
    return canonical_json(request.cache_material())


class LLMCache:
    """SQLite-backed cache of model responses."""

    def __init__(
        self,
        connection: sqlite3.Connection | None = None,
        *,
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self._connection = connection
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self._memory: dict[str, Completion] = {}

    def key(
        self,
        request: CompletionRequest,
        *,
        model: str,
        temperature: float,
        grammar_hash: str = "",
        rung: str = "",
    ) -> str:
        return llm_cache_key(
            prompt=request_prompt(request),
            model=model,
            temperature=temperature,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            grammar_hash=grammar_hash,
            rung=rung,
        )

    def get(self, key: str) -> Completion | None:
        if self._connection is None:
            return self._memory.get(key)
        row = self._connection.execute(
            "SELECT response, input_tokens, output_tokens FROM llm_cache WHERE prompt_hash = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return Completion(
            content=row["response"],
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cached=True,
        )

    def put(
        self,
        key: str,
        completion: Completion,
        *,
        model: str,
        grammar_hash: str = "",
        rung: str = "",
    ) -> None:
        if self._connection is None:
            self._memory[key] = completion
            return
        self._connection.execute(
            "INSERT INTO llm_cache (prompt_hash, model, prompt_version, schema_version, "
            "grammar_hash, rung, response, input_tokens, output_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(prompt_hash) DO UPDATE SET response = excluded.response, "
            "input_tokens = excluded.input_tokens, output_tokens = excluded.output_tokens",
            (
                key,
                model,
                self.prompt_version,
                self.schema_version,
                grammar_hash,
                rung,
                completion.content,
                completion.input_tokens,
                completion.output_tokens,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )

    def clear(self) -> int:
        if self._connection is None:
            count = len(self._memory)
            self._memory.clear()
            return count
        cursor = self._connection.execute("DELETE FROM llm_cache")
        return cursor.rowcount or 0

    def size(self) -> int:
        if self._connection is None:
            return len(self._memory)
        row = self._connection.execute("SELECT COUNT(*) AS total FROM llm_cache").fetchone()
        return int(row["total"])


def stable_json(payload: Any) -> str:
    """Deterministic JSON used by prompts and fixtures."""
    return canonical_json(payload)


__all__ = ["LLMCache", "request_prompt", "sha256_text", "stable_json"]
