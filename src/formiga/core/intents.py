"""The closed set of chat intents (PRD §4.1).

A small model cannot hold a multi-step ReAct loop together, but it can answer a 40-token
classification. The intent enum is therefore *closed*: adding a value is a code change,
because every value has a deterministic action behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from formiga.research.contract import PROFILE_NAMES


class Intent(StrEnum):
    """The ten intents the router may return."""

    ANSWER = "answer"
    RECALL = "recall"
    RESEARCH_QUICK = "research_quick"
    RESEARCH_DEEP = "research_deep"
    EXPAND = "expand"
    MORE_SOURCES = "more_sources"
    COMPARE = "compare"
    RESIZE = "resize"
    CLARIFY = "clarify"
    FORGET = "forget"


@dataclass
class Route:
    """The router's decision. Every field is an id, a name or a short string.

    ``intent`` is required; everything else defaults so a terse reply
    (``{"intent":"answer","query":"what ph does basil prefer?"}``) validates.
    """

    intent: Intent
    query: str = ""
    run_id: str = ""
    section: str = ""
    profile: str = ""
    entities: list[str] = field(default_factory=list)
    aspects: list[str] = field(default_factory=list)

    def normalized_profile(self) -> str | None:
        """Return the requested profile when it is one of the known names."""
        return self.profile if self.profile in PROFILE_NAMES else None

    def signature(self) -> tuple[str, str]:
        """Identity used by the repetition guard."""
        return (self.intent.value, self.query.strip().lower())


#: Intents that need a text answer from the model after dispatch.
TEXT_INTENTS = frozenset({Intent.ANSWER, Intent.RECALL, Intent.CLARIFY})

#: Intents whose action is pure code and must not call the model at all.
CODE_ONLY_INTENTS = frozenset({Intent.RESIZE, Intent.COMPARE, Intent.FORGET})


@dataclass
class Answer:
    """What the answerer returns: text plus the note ids it used.

    The model never writes ``[n]`` - the code numbers the notes and injects the markers,
    which removes the single largest citation error class for small models.
    """

    text: str
    note_ids: list[int] = field(default_factory=list)


__all__ = [
    "CODE_ONLY_INTENTS",
    "TEXT_INTENTS",
    "Answer",
    "Intent",
    "Route",
]
