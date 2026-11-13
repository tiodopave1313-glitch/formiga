"""Message and response types shared by every LLM backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    """One conversation message."""

    role: Role
    content: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class CompletionRequest:
    """A single completion request.

    ``response_schema`` is a JSON Schema produced by :mod:`formiga.llm.grammar`; the
    backend turns it into grammar-constrained decoding.
    """

    messages: tuple[Message, ...]
    temperature: float = 0.0
    max_tokens: int | None = None
    response_schema: dict[str, Any] | None = None
    stop: tuple[str, ...] = ()
    repeat_penalty: float = 1.0

    def cache_material(self) -> dict[str, Any]:
        return {
            "messages": [message.as_dict() for message in self.messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_schema": self.response_schema,
            "stop": list(self.stop),
            "repeat_penalty": self.repeat_penalty,
        }


@dataclass(frozen=True)
class Completion:
    """A model reply."""

    content: str = ""
    output_tokens: int = 0
    input_tokens: int = 0
    finish_reason: str | None = None
    cached: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


__all__ = ["Completion", "CompletionRequest", "Message", "Role"]
