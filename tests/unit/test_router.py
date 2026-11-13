"""The intent router: closed enum, terse replies, degradation and the repetition guard."""

from __future__ import annotations

import pytest

from formiga.config import Layout
from formiga.core.budget import Budget
from formiga.core.intents import CODE_ONLY_INTENTS, TEXT_INTENTS, Intent, Route
from formiga.core.router import ROUTER_MAX_TOKENS, IntentRouter, deterministic_route
from formiga.llm.fake import FakeLLM
from formiga.llm.governed import GovernedLLM
from formiga.llm.router import RoleRouter
from formiga.llm.types import CompletionRequest, Message


def _router(script, *, budget: Budget | None = None) -> tuple[IntentRouter, FakeLLM]:
    backend = FakeLLM(script)
    role_router = RoleRouter(layout=Layout())
    role_router.backends["fast"] = backend
    llm = GovernedLLM(backend, budget or Budget(max_llm_calls=10))
    return IntentRouter(llm, role_router), backend


def test_the_intent_enum_is_closed_and_stable() -> None:
    assert [member.value for member in Intent] == [
        "answer",
        "recall",
        "research_quick",
        "research_deep",
        "expand",
        "more_sources",
        "compare",
        "resize",
        "clarify",
        "forget",
    ]


def test_a_terse_route_needs_only_the_intent() -> None:
    route = Route(intent=Intent.ANSWER)
    assert route.query == ""
    assert route.entities == []
    assert route.normalized_profile() is None


def test_an_unknown_profile_in_a_route_is_ignored() -> None:
    assert Route(intent=Intent.RESIZE, profile="epic").normalized_profile() is None
    assert Route(intent=Intent.RESIZE, profile="long").normalized_profile() == "long"


def test_every_intent_has_a_dispatch_class() -> None:
    """An intent that is neither text nor code-only would silently do nothing."""
    assert not (TEXT_INTENTS & CODE_ONLY_INTENTS)
    dispatched = TEXT_INTENTS | CODE_ONLY_INTENTS | {
        Intent.RESEARCH_QUICK,
        Intent.RESEARCH_DEEP,
        Intent.EXPAND,
        Intent.MORE_SOURCES,
        Intent.CLARIFY,
    }
    assert dispatched == set(Intent)


def test_router_returns_the_parsed_route() -> None:
    router, backend = _router([{"intent": "research_deep", "query": "soil ph", "profile": "long"}])
    result = router.route("research soil ph deeply")
    assert result.route.intent is Intent.RESEARCH_DEEP
    assert result.route.query == "soil ph"
    assert result.route.normalized_profile() == "long"
    assert result.degraded is False
    backend.assert_exhausted()


def test_router_uses_a_bounded_output_budget() -> None:
    router, backend = _router([{"intent": "answer"}])
    router.route("hi")
    assert backend.requests[0].max_tokens == ROUTER_MAX_TOKENS
    assert ROUTER_MAX_TOKENS <= 200


def test_router_never_raises_on_invalid_json() -> None:
    router, backend = _router(["not json", "still not json"])
    result = router.route("hello there")
    assert result.degraded is True
    assert result.route.intent is Intent.ANSWER
    assert result.route.query == "hello there"
    assert "invalid JSON" in result.reason
    assert backend.call_count == 2, "exactly one repair attempt"


def test_router_marks_a_repeated_decision() -> None:
    router, _ = _router(
        [
            {"intent": "answer", "query": "hi"},
            {"intent": "answer", "query": "HI "},
        ]
    )
    first = router.route("hi")
    second = router.route("hi")
    assert first.degraded is False
    assert second.degraded is True
    assert "repetition guard" in second.reason


def test_a_different_intent_is_not_a_repetition() -> None:
    router, _ = _router(
        [
            {"intent": "answer", "query": "hi"},
            {"intent": "research_quick", "query": "hi"},
        ]
    )
    router.route("hi")
    assert router.route("hi").degraded is False


def test_history_is_prepended_before_the_user_turn() -> None:
    router, backend = _router([{"intent": "answer"}])
    history = (Message(role="user", content="earlier"),)
    router.route("now", history=history)
    messages = backend.requests[0].messages
    assert messages[0].role == "system"
    assert messages[1].content == "earlier"
    assert messages[-1].content == "now"


def test_router_temperature_comes_from_config_not_from_the_model() -> None:
    router, backend = _router([{"intent": "answer"}])
    router.route("hi")
    assert backend.requests[0].temperature == 0.2


def test_deterministic_route_skips_the_model() -> None:
    route = deterministic_route(Intent.CLARIFY, "which one?")
    assert route.intent is Intent.CLARIFY
    assert route.query == "which one?"


def test_router_budget_is_respected() -> None:
    from formiga.core.budget import BudgetExceeded

    router, _ = _router(
        [{"intent": "answer"}, {"intent": "answer"}],
        budget=Budget(max_llm_calls=1),
    )
    router.route("hi")
    with pytest.raises(BudgetExceeded):
        router.route("again")


def test_route_schema_is_the_prompt_contract() -> None:
    """The schema the model sees is the one the code validates - one source of truth."""
    from formiga.llm.schema import dataclass_schema

    schema = dataclass_schema(Route)
    assert schema["required"] == ["intent"]
    assert schema["properties"]["aspects"]["items"] == {"type": "string"}


def test_a_route_request_carries_no_run_id_from_the_model() -> None:
    """The router prompt states it must not invent a run id; an empty one is the default."""
    assert Route(intent=Intent.RECALL).run_id == ""


def test_router_accepts_an_empty_object_body_except_intent() -> None:
    router, _ = _router([{"intent": "answer", "entities": ["rosemary"], "aspects": ["risks"]}])
    route = router.route("what are the risks for rosemary?").route
    assert route.entities == ["rosemary"]
    assert route.aspects == ["risks"]


def test_request_shape_is_one_system_and_one_user_message() -> None:
    router, backend = _router([{"intent": "answer"}])
    router.route("hi")
    request: CompletionRequest = backend.requests[0]
    assert len(request.messages) == 2
    assert request.messages[0].content.startswith("Classify one user turn")
