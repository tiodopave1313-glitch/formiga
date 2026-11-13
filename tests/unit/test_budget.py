"""Budget governor: per-profile rows, caps, resume and cache-hit accounting."""

from __future__ import annotations

import pytest

from formiga.core.budget import Budget, BudgetExceeded
from formiga.research.contract import get_profile


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_profile_row_sets_every_cap() -> None:
    medium = get_profile("medium")
    budget = Budget.from_profile(medium, layout="single")
    assert budget.max_llm_calls == 45
    assert budget.max_prompt_tokens == 40000
    assert budget.max_output_tokens == 4000
    assert budget.deadline_s == 50 * 60


def test_typical_column_is_available_for_bench() -> None:
    budget = Budget.from_profile(get_profile("short"), use_caps=False)
    assert budget.max_llm_calls == 8
    assert budget.max_output_tokens == 600


def test_dual_deadline_is_shorter() -> None:
    assert Budget.from_profile(get_profile("medium"), layout="dual").deadline_s == 30 * 60


def test_call_cap_raises_once_and_stays_exceeded() -> None:
    budget = Budget(max_llm_calls=1)
    budget.charge_call()
    with pytest.raises(BudgetExceeded) as caught:
        budget.charge_call()
    assert caught.value.reason == "llm_calls"
    assert budget.exhausted
    with pytest.raises(BudgetExceeded):
        budget.charge_call()


def test_output_token_cap_records_the_reason() -> None:
    budget = Budget(max_llm_calls=10, max_output_tokens=5)
    budget.charge_output_tokens(4)
    with pytest.raises(BudgetExceeded) as caught:
        budget.charge_output_tokens(4)
    assert caught.value.reason == "output_tokens"
    assert budget.output_tokens == 5


def test_prompt_token_cap() -> None:
    budget = Budget(max_llm_calls=10, max_prompt_tokens=100)
    budget.charge_prompt_tokens(60)
    with pytest.raises(BudgetExceeded) as caught:
        budget.charge_prompt_tokens(60)
    assert caught.value.reason == "prompt_tokens"


def test_deadline_is_checked_before_every_call() -> None:
    clock = FakeClock()
    budget = Budget(max_llm_calls=5, deadline_s=10.0, clock=clock)
    budget.charge_call()
    clock.advance(11)
    with pytest.raises(BudgetExceeded) as caught:
        budget.charge_call()
    assert caught.value.reason == "deadline"


def test_remaining_time_never_goes_negative() -> None:
    clock = FakeClock()
    budget = Budget(max_llm_calls=5, deadline_s=10.0, clock=clock)
    clock.advance(30)
    assert budget.remaining_s == 0.0


def test_restore_continues_counters_on_resume() -> None:
    budget = Budget(max_llm_calls=10, max_output_tokens=100)
    budget.restore({"llm_calls": 4, "prompt_tokens": 30, "output_tokens": 20})
    assert budget.llm_calls == 4
    assert budget.output_tokens == 20
    budget.charge_call()
    assert budget.llm_calls == 5


def test_snapshot_is_json_ready() -> None:
    budget = Budget(max_llm_calls=3)
    budget.charge_call()
    payload = budget.as_dict()
    assert payload["llm_calls"] == 1
    assert payload["exceeded"] is False
    assert "duration_s" in payload


def test_charging_zero_tokens_is_a_no_op() -> None:
    budget = Budget(max_llm_calls=1, max_output_tokens=1)
    budget.charge_output_tokens(0)
    budget.charge_prompt_tokens(0)
    assert budget.output_tokens == 0
    assert budget.prompt_tokens == 0
