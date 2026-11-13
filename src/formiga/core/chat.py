"""The chat turn loop: one routing call, one deterministic dispatch, at most one answer.

Deep research is a later phase; in F0 every research intent returns a deterministic
message naming the phase that will provide it. That is deliberate: a half-wired research
path would be worse than an honest refusal, and the refusal is a catalog string, not
model output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from formiga.core.citations import CitationLedger
from formiga.core.intents import CODE_ONLY_INTENTS, Answer, Intent, Route
from formiga.core.prompts import system_prompt
from formiga.core.router import IntentRouter, RouterResult
from formiga.i18n import t
from formiga.llm.governed import CallContext, GovernedLLM
from formiga.llm.router import RoleRouter
from formiga.llm.types import CompletionRequest, Message

#: Intents that a later phase implements; each maps to the phase in the roadmap.
PENDING_INTENTS: dict[Intent, str] = {
    Intent.RECALL: "F2",
    Intent.RESEARCH_QUICK: "F2",
    Intent.RESEARCH_DEEP: "F2",
    Intent.EXPAND: "F3",
    Intent.MORE_SOURCES: "F2",
    Intent.COMPARE: "F3",
    Intent.RESIZE: "F3",
    Intent.FORGET: "F3",
}


@dataclass
class Turn:
    """The result of one user turn."""

    text: str
    intent: Intent
    note_ids: list[int] = field(default_factory=list)
    cached: bool = False
    degraded: bool = False
    llm_calls: int = 0

    @property
    def sourced(self) -> bool:
        return bool(self.note_ids)


@dataclass
class ChatSession:
    """Stateless turn runner; session persistence arrives with the REPL in F3."""

    llm: GovernedLLM
    router: RoleRouter
    ledger: CitationLedger = field(default_factory=CitationLedger)
    language: str = "en"
    answer_temperature: float = 0.4
    max_answer_tokens: int = 400
    _last_turn: Turn | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.intents = IntentRouter(self.llm, self.router, language=self.language)

    def run_turn(self, user_text: str, *, history: tuple[Message, ...] = ()) -> Turn:
        """Route and dispatch one turn. Never raises for a routing failure."""
        before = self.llm.calls
        decision: RouterResult = self.intents.route(user_text, history=history)
        if decision.reason.startswith("repetition guard") and self._last_turn is not None:
            # PRD §4.1: the second identical route is answered from stored state, not by
            # paying for the same model call again.
            turn = Turn(
                text=self._last_turn.text,
                intent=self._last_turn.intent,
                note_ids=list(self._last_turn.note_ids),
            )
            turn.degraded = True
            turn.llm_calls = self.llm.calls - before
            return turn
        turn = self._dispatch(decision.route, user_text)
        turn.degraded = turn.degraded or decision.degraded
        turn.llm_calls = self.llm.calls - before
        self._last_turn = turn
        return turn

    def _dispatch(self, route: Route, user_text: str) -> Turn:
        if route.intent in PENDING_INTENTS:
            return self._pending(route)
        if route.intent is Intent.CLARIFY:
            return Turn(
                text=t("chat.clarify", locale=self.language, query=route.query or user_text),
                intent=route.intent,
            )
        return self.answer(route.query or user_text)

    def answer(self, question: str, *, note_texts: tuple[str, ...] = ()) -> Turn:
        """The single answer call: text plus note ids, numbered by code."""
        request = CompletionRequest(
            messages=(
                Message(role="system", content=system_prompt("answerer")),
                Message(role="user", content=_answer_prompt(question, note_texts)),
            ),
            temperature=self.answer_temperature,
            max_tokens=self.max_answer_tokens,
            repeat_penalty=1.05,
        )
        reply = self.llm.complete_json(request, Answer, context=CallContext(role="answerer"))
        note_ids = list(reply.note_ids)
        text = reply.text.strip()
        if note_ids:
            text = f"{text} {self.ledger.markers(note_ids)}"
        else:
            text = t("ask.unsourced", locale=self.language, text=text,
                     label=t("chat.no_sources", locale=self.language))
        return Turn(text=text, intent=Intent.ANSWER, note_ids=note_ids)

    def _pending(self, route: Route) -> Turn:
        phase = PENDING_INTENTS[route.intent]
        return Turn(
            text=t("error.not_implemented", locale=self.language,
                   command=f"{route.intent.value} (phase {phase})"),
            intent=route.intent,
        )

    def code_only(self, route: Route) -> bool:
        """True when an intent must never reach the model."""
        return route.intent in CODE_ONLY_INTENTS or route.intent in PENDING_INTENTS


def _answer_prompt(question: str, note_texts: tuple[str, ...]) -> str:
    if not note_texts:
        return question
    joined = "\n".join(f"- {text}" for text in note_texts)
    return f"{question}\n\nNotes:\n{joined}"


__all__ = ["PENDING_INTENTS", "ChatSession", "Turn"]
