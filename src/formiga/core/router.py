"""Router: one grammar-constrained call per turn, then a deterministic switch.

The model picks an intent and a few arguments; the code picks the sequence. Anything the
router does not name is left at its default, so a terse reply still validates.
"""

from __future__ import annotations

from dataclasses import dataclass

from formiga.core.intents import Intent, Route
from formiga.core.prompts import system_prompt
from formiga.llm.governed import CallContext, GovernedLLM, StructuredOutputError
from formiga.llm.router import RoleRouter
from formiga.llm.types import CompletionRequest, Message

#: Output budget of the routing call; ~70 tokens is what the PRD sizes the schema for.
ROUTER_MAX_TOKENS = 160


@dataclass
class RouterResult:
    """Outcome of routing, including whether it had to be replaced."""

    route: Route
    degraded: bool = False
    reason: str = ""


class IntentRouter:
    """Routes a user turn, with a repetition guard over the last decision."""

    def __init__(
        self,
        llm: GovernedLLM,
        router: RoleRouter,
        *,
        language: str = "en",
        temperature: float = 0.2,
    ) -> None:
        self.llm = llm
        self.router = router
        self.language = language
        self.temperature = temperature
        self._last: tuple[str, str] | None = None

    def route(self, user_text: str, *, history: tuple[Message, ...] = ()) -> RouterResult:
        """Return a decision for ``user_text``, never raising on a bad reply."""
        request = CompletionRequest(
            messages=(
                Message(role="system", content=system_prompt("router")),
                *history,
                Message(role="user", content=user_text),
            ),
            temperature=self.temperature,
            max_tokens=ROUTER_MAX_TOKENS,
        )
        try:
            route = self.llm.complete_json(request, Route, context=CallContext(role="router"))
        except StructuredOutputError:
            return RouterResult(
                route=Route(intent=Intent.ANSWER, query=user_text),
                degraded=True,
                reason="router produced invalid JSON",
            )

        if self._last is not None and route.signature() == self._last:
            return RouterResult(
                route=route,
                degraded=True,
                reason="repetition guard: identical intent and query twice",
            )
        self._last = route.signature()
        return RouterResult(route=route)


def deterministic_route(intent: Intent, text: str) -> Route:
    """Build a route without a model call; used by tests and by the repetition guard."""
    return Route(intent=intent, query=text)


__all__ = ["IntentRouter", "ROUTER_MAX_TOKENS", "RouterResult", "deterministic_route"]
