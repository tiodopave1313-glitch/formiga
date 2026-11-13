"""The backend interface every model client implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from formiga.llm.types import Completion, CompletionRequest


class LLMError(RuntimeError):
    """Raised when a backend returns something unusable."""


class BackendUnavailable(LLMError):
    """Raised when the endpoint cannot be reached."""


class LLM(ABC):
    """A chat-completions backend bound to one endpoint."""

    profile_name: str = "default"

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier recorded in the cache key and the report frontmatter."""

    @abstractmethod
    def complete(self, request: CompletionRequest) -> Completion:
        """Return one non-streamed completion."""

    @abstractmethod
    def stream(self, request: CompletionRequest) -> Iterator[str]:
        """Yield content deltas."""

    def close(self) -> None:
        """Release transport resources. Backends without transport need no override."""
        return None

    def __enter__(self) -> LLM:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


__all__ = ["BackendUnavailable", "LLM", "LLMError"]
