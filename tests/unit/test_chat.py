"""Chat turn: routing, deterministic dispatch, citation numbering and the repetition guard."""

from __future__ import annotations

import pytest

from formiga.config import Layout
from formiga.core.budget import Budget, BudgetExceeded
from formiga.core.chat import ChatSession
from formiga.core.citations import CitationLedger
from formiga.core.intents import CODE_ONLY_INTENTS, Intent, Route
from formiga.llm.fake import FakeLLM
from formiga.llm.governed import GovernedLLM
from formiga.llm.router import RoleRouter
from formiga.llm.types import Message


def _session(script, *, budget: Budget | None = None) -> ChatSession:
    backend = FakeLLM(script)
    router = RoleRouter(layout=Layout())
    router.backends["fast"] = backend
    llm = GovernedLLM(backend, budget or Budget(max_llm_calls=10, max_output_tokens=10_000))
    return ChatSession(llm=llm, router=router, ledger=CitationLedger(), language="en")


def test_answer_turn_routes_then_answers() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "what ph does basil prefer?"},
            {"text": "Basil prefers pH 5.5 to 6.5.", "note_ids": []},
        ]
    )
    turn = session.run_turn("what ph does basil prefer?")
    assert turn.intent is Intent.ANSWER
    assert "pH 5.5 to 6.5" in turn.text
    assert turn.llm_calls == 2
    assert not turn.sourced


def test_uncited_answer_is_labelled_with_the_catalog_string() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "hi"},
            {"text": "Hello there.", "note_ids": []},
        ]
    )
    turn = session.run_turn("hi")
    assert "(no sources" in turn.text


def test_note_ids_are_numbered_by_code_not_by_the_model() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "hi"},
            {"text": "See the note.", "note_ids": [7, 9, 7]},
        ]
    )
    turn = session.run_turn("hi")
    assert turn.text.endswith("[1][2]")
    assert turn.note_ids == [7, 9, 7]
    assert turn.sourced


def test_citation_numbers_are_frozen_across_turns() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "one"},
            {"text": "a", "note_ids": [7]},
            {"intent": "answer", "query": "two"},
            {"text": "b", "note_ids": [7, 8]},
        ]
    )
    first = session.run_turn("one")
    second = session.run_turn("two")
    assert first.text.endswith("[1]")
    assert second.text.endswith("[1][2]")


def test_research_intents_are_refused_with_a_phase_name() -> None:
    session = _session([{"intent": "research_deep", "query": "rosemary vs thyme"}])
    turn = session.run_turn("deep research on rosemary vs thyme")
    assert turn.intent is Intent.RESEARCH_DEEP
    assert "F2" in turn.text
    assert turn.llm_calls == 1


def test_clarify_asks_one_question_without_a_model_answer() -> None:
    session = _session([{"intent": "clarify", "query": "which plant?"}])
    turn = session.run_turn("which one?")
    assert turn.intent is Intent.CLARIFY
    assert turn.llm_calls == 1


def test_repetition_guard_marks_the_second_identical_route() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "hi"},
            {"text": "Hello.", "note_ids": []},
            {"intent": "answer", "query": "hi"},
            {"text": "Hello again.", "note_ids": []},
        ]
    )
    first = session.run_turn("hi")
    second = session.run_turn("hi")
    assert first.degraded is False
    assert second.degraded is True


def test_invalid_router_json_falls_back_to_answer() -> None:
    session = _session(["not json", "not json", '{"text": "ok", "note_ids": []}'])
    turn = session.run_turn("hello")
    assert turn.degraded is True
    assert turn.intent is Intent.ANSWER
    assert "ok" in turn.text


def test_code_only_intents_never_reach_the_model() -> None:
    session = _session([])
    for intent in CODE_ONLY_INTENTS:
        assert session.code_only(Route(intent=intent))


def test_history_is_forwarded_to_the_router() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "follow up"},
            {"text": "ok", "note_ids": []},
        ]
    )
    history = (Message(role="user", content="earlier"), Message(role="assistant", content="reply"))
    session.run_turn("follow up", history=history)
    first_request = session.llm.backend.requests[0]
    contents = [message.content for message in first_request.messages]
    assert "earlier" in contents
    assert contents[0].startswith("Classify one user turn")


def test_router_prompt_prefix_is_byte_identical_across_turns() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "a"},
            {"text": "b", "note_ids": []},
            {"intent": "answer", "query": "c"},
            {"text": "d", "note_ids": []},
        ]
    )
    session.run_turn("a")
    session.run_turn("c")
    first, second = session.llm.backend.requests[0], session.llm.backend.requests[2]
    assert first.messages[0].content == second.messages[0].content


def test_budget_exhaustion_propagates_to_the_caller() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "a"},
            {"text": "b", "note_ids": []},
        ],
        budget=Budget(max_llm_calls=1, max_output_tokens=1000),
    )
    with pytest.raises(BudgetExceeded):
        session.run_turn("a")


def test_two_calls_per_turn_is_the_ceiling() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "a"},
            {"text": "b", "note_ids": [1]},
        ]
    )
    turn = session.run_turn("a")
    assert turn.llm_calls == 2
