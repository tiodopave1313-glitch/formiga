"""Local model client: schema, grammar, cache and role routing."""

from __future__ import annotations

from formiga.llm.base import LLM, BackendUnavailable, LLMError
from formiga.llm.cache import LLMCache, request_prompt, stable_json
from formiga.llm.client import HTTPLLM
from formiga.llm.coerce import CoercionError, from_dict
from formiga.llm.fake import FakeLLM
from formiga.llm.governed import CallContext, GovernedLLM, StructuredOutputError
from formiga.llm.router import RoleRouter, RoutingEvent, Tier
from formiga.llm.schema import dataclass_schema, schema_hash
from formiga.llm.types import Completion, CompletionRequest, Message

__all__ = [
    "BackendUnavailable",
    "CallContext",
    "CoercionError",
    "Completion",
    "CompletionRequest",
    "FakeLLM",
    "GovernedLLM",
    "HTTPLLM",
    "LLM",
    "LLMCache",
    "LLMError",
    "Message",
    "RoleRouter",
    "RoutingEvent",
    "StructuredOutputError",
    "Tier",
    "dataclass_schema",
    "from_dict",
    "request_prompt",
    "schema_hash",
    "stable_json",
]
