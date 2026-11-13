"""Schema derivation, coercion, grammar and governed calls."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from formiga.core.budget import Budget
from formiga.core.intents import Answer, Intent, Route
from formiga.llm.cache import LLMCache
from formiga.llm.coerce import CoercionError, from_dict
from formiga.llm.fake import FakeLLM
from formiga.llm.governed import CallContext, GovernedLLM, StructuredOutputError
from formiga.llm.grammar import gbnf_for
from formiga.llm.schema import dataclass_schema, schema_hash
from formiga.llm.types import CompletionRequest, Message


@dataclass
class Nested:
    name: str
    score: float = 0.0


@dataclass
class Shape:
    intent: str
    items: list[Nested] = field(default_factory=list)
    note: str | None = None
    tags: dict[str, int] = field(default_factory=dict)


def test_route_schema_is_flat_and_closed() -> None:
    schema = dataclass_schema(Route)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["intent"]
    assert schema["properties"]["intent"]["enum"] == [member.value for member in Intent]


def test_answer_schema_marks_text_required() -> None:
    schema = dataclass_schema(Answer)
    assert schema["required"] == ["text"]
    assert schema["properties"]["note_ids"]["type"] == "array"


def test_nested_and_optional_types_are_derived() -> None:
    schema = dataclass_schema(Shape)
    assert schema["properties"]["items"]["items"]["properties"]["name"]["type"] == "string"
    assert schema["properties"]["note"]["nullable"] is True
    assert schema["properties"]["tags"]["additionalProperties"] == {"type": "integer"}


def test_schema_hash_is_stable_and_sensitive() -> None:
    first = schema_hash(dataclass_schema(Answer))
    assert first == schema_hash(dataclass_schema(Answer))
    assert first != schema_hash(dataclass_schema(Route))


def test_unsupported_annotation_is_refused_early() -> None:
    @dataclass
    class Bad:
        value: complex

    with pytest.raises(TypeError):
        dataclass_schema(Bad)


def test_from_dict_builds_and_rejects_unknown_fields() -> None:
    route = from_dict(Route, {"intent": "answer", "query": "hi"})
    assert route.intent is Intent.ANSWER
    with pytest.raises(CoercionError):
        from_dict(Route, {"intent": "answer", "unexpected": 1})


def test_from_dict_rejects_an_unknown_enum_value() -> None:
    with pytest.raises(CoercionError):
        from_dict(Route, {"intent": "hallucinate"})


def test_from_dict_requires_a_required_field() -> None:
    with pytest.raises(CoercionError):
        from_dict(Answer, {})


def test_from_dict_walks_nested_lists() -> None:
    payload = {"intent": "answer", "items": [{"name": "a"}, {"name": "b", "score": 2}]}
    shape = from_dict(Shape, payload)
    assert [item.score for item in shape.items] == [0.0, 2.0]


def test_grammar_contains_the_enum_literals() -> None:
    grammar = gbnf_for(dataclass_schema(Route))
    assert "answer" in grammar
    assert "research_deep" in grammar
    assert "::=" in grammar
    assert "root ::=" in grammar


def test_grammar_is_valid_for_nested_shapes() -> None:
    grammar = gbnf_for(dataclass_schema(Shape))
    assert "root ::=" in grammar
    assert grammar.count("::=") > 3


def test_governed_call_charges_budget_and_fills_cache(budget: Budget) -> None:
    backend = FakeLLM.json({"text": "hello", "note_ids": [1, 2]})
    cache = LLMCache()
    llm = GovernedLLM(backend, budget, cache)
    request = CompletionRequest(messages=(Message(role="user", content="hi"),))

    first = llm.complete_json(request, Answer, context=CallContext(role="answerer"))
    assert first.text == "hello"
    assert budget.llm_calls == 1

    second = llm.complete_json(request, Answer, context=CallContext(role="answerer"))
    assert second.text == "hello"
    assert budget.llm_calls == 2, "a cache hit still consumes one call"
    assert llm.cache_hits == 1
    assert backend.call_count == 1


def test_cache_is_bypassed_when_the_rung_differs(budget: Budget) -> None:
    backend = FakeLLM.json({"text": "ok"}, count=2)
    llm = GovernedLLM(backend, budget, LLMCache())
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    llm.complete_json(request, Answer, context=CallContext(role="synthesizer", rung="assemble"))
    llm.complete_json(request, Answer, context=CallContext(role="synthesizer", rung="bounded-edit"))
    assert backend.call_count == 2


def test_invalid_json_is_repaired_once(budget: Budget) -> None:
    backend = FakeLLM(["not json", '{"text": "fixed"}'])
    llm = GovernedLLM(backend, budget)
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    answer = llm.complete_json(request, Answer)
    assert answer.text == "fixed"
    assert backend.call_count == 2


def test_two_failures_raise_structured_output_error(budget: Budget) -> None:
    backend = FakeLLM(["nope", "still nope"])
    llm = GovernedLLM(backend, budget)
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    with pytest.raises(StructuredOutputError):
        llm.complete_json(request, Answer)


def test_repair_can_be_disabled(budget: Budget) -> None:
    backend = FakeLLM(["nope"])
    llm = GovernedLLM(backend, budget, repair_enabled=False)
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    with pytest.raises(StructuredOutputError):
        llm.complete_json(request, Answer)
    assert backend.call_count == 1


def test_code_fences_are_stripped(budget: Budget) -> None:
    backend = FakeLLM(['```json\n{"text": "ok"}\n```'])
    llm = GovernedLLM(backend, budget)
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    assert llm.complete_json(request, Answer).text == "ok"


def test_request_gains_the_schema_before_hitting_the_backend(budget: Budget) -> None:
    backend = FakeLLM.json({"text": "ok"})
    llm = GovernedLLM(backend, budget)
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    llm.complete_json(request, Answer)
    assert backend.requests[0].response_schema is not None
    assert backend.requests[0].response_schema["required"] == ["text"]


def test_grammar_helper_returns_none_without_a_schema(budget: Budget) -> None:
    llm = GovernedLLM(FakeLLM(), budget)
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    assert llm.grammar(request) is None


def test_fake_llm_script_is_assertable() -> None:
    backend = FakeLLM(["a", "b"])
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    backend.complete(request)
    with pytest.raises(AssertionError):
        backend.assert_exhausted()


def test_fake_llm_can_simulate_a_backend_failure() -> None:
    from formiga.llm.base import BackendUnavailable

    backend = FakeLLM([BackendUnavailable("down")])
    request = CompletionRequest(messages=(Message(role="user", content="x"),))
    with pytest.raises(BackendUnavailable):
        backend.complete(request)
