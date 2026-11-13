"""Deterministic in-process backend used by every unit test.

Tests never touch the network. ``FakeLLM`` also lets a test force a capability probe
outcome, a repair failure or an endpoint death without patching httpx.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Iterator
from typing import Any

from formiga.llm.base import LLM, LLMError
from formiga.llm.types import Completion, CompletionRequest


def estimate_tokens(text: str) -> int:
    """Coarse token estimate: words, never a tokenizer call."""
    return max(1, len(text.split())) if text else 0


class FakeLLM(LLM):
    """Scripted backend.

    Each script entry is a string, a :class:`Completion`, a mapping (serialised as JSON)
    or a callable receiving the request. Runs out of script -> the fallback reply.
    """

    def __init__(self, script: Iterable[Any] | None = None, *, fallback: str = "echo") -> None:
        self._script: deque[Any] = deque(script or ())
        self.profile_name = "fake"
        self.fallback = fallback
        self.requests: list[CompletionRequest] = []
        self.call_count = 0
        self.closed = False

    @classmethod
    def echoing(cls) -> FakeLLM:
        """Reply with ``echo: <last user message>``."""
        return cls(fallback="echo")

    @classmethod
    def json(cls, payload: Any, count: int = 1) -> FakeLLM:
        """Reply with the same JSON payload ``count`` times."""
        return cls([json.dumps(payload)] * count)

    @property
    def model(self) -> str:
        return "fake-model"

    def push(self, *entries: Any) -> None:
        self._script.extend(entries)

    def complete(self, request: CompletionRequest) -> Completion:
        self.requests.append(request)
        self.call_count += 1
        if self._script:
            entry = self._script.popleft()
            if callable(entry):
                entry = entry(request)
            return self._coerce(entry)
        return self._coerce(self._fallback(request))

    def stream(self, request: CompletionRequest) -> Iterator[str]:
        completion = self.complete(request)
        yield completion.content

    def _fallback(self, request: CompletionRequest) -> str:
        last_user = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            "",
        )
        if self.fallback == "echo":
            return f"echo: {last_user}"
        return self.fallback

    def _coerce(self, entry: Any) -> Completion:
        if isinstance(entry, Completion):
            return entry
        if isinstance(entry, str):
            return Completion(content=entry, output_tokens=estimate_tokens(entry),
                              finish_reason="stop")
        if isinstance(entry, dict):
            text = json.dumps(entry, ensure_ascii=False)
            return Completion(content=text, output_tokens=estimate_tokens(text))
        if isinstance(entry, Exception):
            raise entry
        raise LLMError(f"unsupported fake script entry: {type(entry)!r}")

    def close(self) -> None:
        self.closed = True

    def assert_exhausted(self) -> None:
        """Fail when a test left part of its script unused."""
        if self._script:
            raise AssertionError(f"{len(self._script)} unused fake script entries")


__all__ = ["FakeLLM", "estimate_tokens"]
