"""The only way the rest of the code talks to a model.

:class:`GovernedLLM` wraps a backend with the budget governor and the response cache.
Every request is charged before it is sent; a cache hit still charges one call, which is
what stops a resumed run from looping for free. Structured calls get exactly one repair
attempt - a third attempt costs more than it saves on a small model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypeVar

from formiga.core.budget import Budget
from formiga.llm.base import LLM
from formiga.llm.cache import LLMCache, request_prompt
from formiga.llm.grammar import gbnf_for
from formiga.llm.schema import dataclass_schema, schema_hash
from formiga.llm.types import Completion, CompletionRequest, Message

T = TypeVar("T")


class StructuredOutputError(RuntimeError):
    """Raised when a stage cannot produce valid JSON even after one repair."""

    def __init__(self, message: str, *, raw: str) -> None:
        self.raw = raw
        super().__init__(message)


@dataclass(frozen=True)
class CallContext:
    """Everything the cache and the report need to know about a call."""

    role: str
    rung: str = ""
    grammar_hash: str = ""


class GovernedLLM:
    """Budget- and cache-aware facade over a backend."""

    def __init__(
        self,
        backend: LLM,
        budget: Budget,
        cache: LLMCache | None = None,
        *,
        prompt_version: str = "0.1.0",
        repair_enabled: bool = True,
    ) -> None:
        self.backend = backend
        self.budget = budget
        self.cache = cache
        self.prompt_version = prompt_version
        self.repair_enabled = repair_enabled
        self.cache_hits = 0
        self.calls = 0

    def complete(
        self,
        request: CompletionRequest,
        *,
        context: CallContext | None = None,
    ) -> Completion:
        """Return a completion, charging the budget even on a cache hit."""
        context = context or CallContext(role="unknown")
        key = None
        if self.cache is not None:
            key = self.cache.key(
                request,
                model=self.backend.model,
                temperature=request.temperature,
                grammar_hash=context.grammar_hash,
                rung=context.rung,
            )
            cached = self.cache.get(key)
            if cached is not None:
                self.budget.charge_call()
                self.cache_hits += 1
                return cached

        self.budget.charge_call()
        self.calls += 1
        completion = self.backend.complete(request)
        self.budget.charge_prompt_tokens(completion.input_tokens)
        self.budget.charge_output_tokens(completion.output_tokens)

        if key is not None and self.cache is not None:
            self.cache.put(
                key,
                completion,
                model=self.backend.model,
                grammar_hash=context.grammar_hash,
                rung=context.rung,
            )
        return completion

    def complete_json(
        self,
        request: CompletionRequest,
        model: type,
        *,
        context: CallContext | None = None,
    ) -> Any:
        """Return an instance of ``model``, repairing at most once."""
        schema = dataclass_schema(model)
        grammar_hash = schema_hash(schema)
        context = CallContext(
            role=(context.role if context else "unknown"),
            rung=(context.rung if context else ""),
            grammar_hash=grammar_hash,
        )
        first_request = _with_schema(request, schema)
        completion = self.complete(first_request, context=context)
        parsed, error = _validate(completion.content, model)
        if parsed is not None or not self.repair_enabled:
            if parsed is None:
                raise StructuredOutputError(error or "invalid JSON", raw=completion.content)
            return parsed

        repair_request = CompletionRequest(
            messages=(
                *first_request.messages,
                Message(role="assistant", content=completion.content),
                Message(role="user", content=_repair_instruction(error or "invalid JSON")),
            ),
            temperature=0.0,
            max_tokens=first_request.max_tokens,
            response_schema=schema,
            stop=first_request.stop,
        )
        repaired = self.complete(repair_request, context=context)
        parsed, error = _validate(repaired.content, model)
        if parsed is None:
            raise StructuredOutputError(error or "invalid JSON", raw=repaired.content)
        return parsed

    def grammar(self, request: CompletionRequest) -> str | None:
        """Return the GBNF for a request's schema, or ``None`` when it has none."""
        if not request.response_schema:
            return None
        return gbnf_for(request.response_schema)

    def prompt_of(self, request: CompletionRequest) -> str:
        return request_prompt(request)


def _with_schema(request: CompletionRequest, schema: dict[str, Any]) -> CompletionRequest:
    return CompletionRequest(
        messages=request.messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        response_schema=schema,
        stop=request.stop,
        repeat_penalty=request.repeat_penalty,
    )


def _repair_instruction(error: str) -> str:
    return (
        "The previous reply did not match the required JSON schema. "
        f"Validation error: {error}. "
        "Reply with the corrected JSON object only, no prose and no code fences."
    )


def _validate(content: str, model: type) -> tuple[Any | None, str | None]:
    from formiga.llm.coerce import from_dict

    text = _strip_fences(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "top-level JSON value must be an object"
    try:
        return from_dict(model, payload), None
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


__all__ = ["CallContext", "GovernedLLM", "StructuredOutputError"]
