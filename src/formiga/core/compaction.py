"""Context compaction (PRD §4.1).

Template first: intents, run ids, note ids and open questions are already stored, so the
summary is built from metadata at zero token cost. A model call is used only when the
templated summary still exceeds the budget. Citations survive as references, never as
quoted text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from formiga.i18n import t

#: Metadata one compacted turn contributes.
KEEP_FIELDS = ("intent", "run_id", "note_ids", "open_questions")


@dataclass
class TurnRecord:
    """The part of a turn that survives compaction."""

    intent: str
    text: str
    run_id: str | None = None
    note_ids: list[int] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    compacted: bool = False


@dataclass
class CompactionPlan:
    """What to keep verbatim and what to summarise."""

    verbatim: list[TurnRecord]
    summarised: list[TurnRecord]
    summary: str
    instructions: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    return len(text.split())


def plan_compaction(
    turns: list[TurnRecord],
    *,
    budget_tokens: int,
    keep_turns: int = 4,
    locale: str = "en",
) -> CompactionPlan:
    """Split ``turns`` into a verbatim tail and a templated summary.

    An unresolved user instruction is always kept verbatim, even when it falls outside
    the tail: compaction must never drop an open request (PRD §4.1, tested).
    """
    if not turns:
        return CompactionPlan(verbatim=[], summarised=[], summary="")

    tail = turns[-keep_turns:] if keep_turns > 0 else []
    head = turns[: len(turns) - len(tail)]

    pinned = [turn for turn in head if turn.open_questions]
    summarisable = [turn for turn in head if not turn.open_questions]

    verbatim = [*pinned, *tail]
    summarisable = [turn for turn in summarisable if turn not in tail]

    summary = _template_summary(summarisable, locale=locale)
    return CompactionPlan(
        verbatim=verbatim,
        summarised=summarisable,
        summary=summary,
        instructions=[question for turn in pinned for question in turn.open_questions],
    )


def _summary_cost(turns: list[TurnRecord]) -> int:
    return estimate_tokens(_template_summary(turns))


def _template_summary(turns: list[TurnRecord], *, locale: str = "en") -> str:
    if not turns:
        return ""
    run_ids = {turn.run_id for turn in turns if turn.run_id}
    lines = [
        t("chat.compacted", locale=locale, turns=len(turns), run_ids=len(run_ids)),
        *(
            f"- {turn.intent}"
            + (f" · run {turn.run_id}" if turn.run_id else "")
            + (f" · notes {','.join(str(n) for n in turn.note_ids)}" if turn.note_ids else "")
            for turn in turns
        ),
    ]
    return "\n".join(lines)


def needs_model_summary(plan: CompactionPlan, *, budget_tokens: int) -> bool:
    """True when even the templated summary is too large and a model pass is required."""
    return estimate_tokens(plan.summary) > budget_tokens


__all__ = [
    "KEEP_FIELDS",
    "CompactionPlan",
    "TurnRecord",
    "estimate_tokens",
    "needs_model_summary",
    "plan_compaction",
]
