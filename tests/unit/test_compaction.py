"""Compaction: metadata summary first, open instructions never dropped."""

from __future__ import annotations

from formiga.core.compaction import (
    TurnRecord,
    estimate_tokens,
    needs_model_summary,
    plan_compaction,
)


def _turns(count: int) -> list[TurnRecord]:
    return [
        TurnRecord(
            intent="answer",
            text=f"answer number {index}",
            run_id=f"run{index}" if index % 2 == 0 else None,
            note_ids=[index],
        )
        for index in range(count)
    ]


def test_empty_conversation_needs_no_plan() -> None:
    plan = plan_compaction([], budget_tokens=100)
    assert plan.verbatim == []
    assert plan.summary == ""


def test_tail_is_kept_verbatim() -> None:
    plan = plan_compaction(_turns(10), budget_tokens=1000, keep_turns=4)
    assert len(plan.verbatim) == 4
    assert plan.verbatim[-1].text == "answer number 9"
    assert len(plan.summarised) == 6


def test_summary_is_built_from_metadata_without_a_model_call() -> None:
    plan = plan_compaction(_turns(6), budget_tokens=1000, keep_turns=2)
    assert "summarised" in plan.summary
    assert "run2" in plan.summary
    assert not needs_model_summary(plan, budget_tokens=1000)


def test_open_instructions_are_never_dropped() -> None:
    turns = _turns(10)
    turns[0].open_questions = ["compare rosemary and thyme"]
    plan = plan_compaction(turns, budget_tokens=50, keep_turns=2)
    assert "compare rosemary and thyme" in plan.instructions
    assert turns[0] in plan.verbatim


def test_templated_summary_that_is_too_large_asks_for_a_model_pass() -> None:
    plan = plan_compaction(_turns(80), budget_tokens=10, keep_turns=0)
    assert needs_model_summary(plan, budget_tokens=10)


def test_token_estimate_is_word_based() -> None:
    assert estimate_tokens("one two three") == 3


def test_citations_stay_as_ids_in_the_summary() -> None:
    plan = plan_compaction(_turns(6), budget_tokens=1000, keep_turns=2)
    assert "notes" in plan.summary
