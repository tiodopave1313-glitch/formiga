"""Testes de orçamento: limites verificados antes das ações, reservas e prazo."""

from __future__ import annotations

import pytest

from formiga.budget import Budget, BudgetExhausted


def make_budget(**overrides) -> Budget:
    params = dict(
        max_rounds=2,
        max_searches=3,
        max_pages=5,
        pages_per_round=2,
        max_llm_calls=10,
        reserved_llm_calls=4,
        timeout_seconds=60.0,
        deadline=1.0e12,  # sem prazo na maior parte dos testes
    )
    params.update(overrides)
    return Budget(**params)


class TestRounds:
    def test_counts_and_stops(self):
        b = make_budget()
        b.start_round()
        b.start_round()
        assert b.rounds == 2
        with pytest.raises(BudgetExhausted):
            b.start_round()

    def test_cannot_start_past_limit(self):
        b = make_budget()
        b.start_round()
        b.start_round()
        assert not b.can_start_round()


class TestSearches:
    def test_counts_every_attempt(self):
        b = make_budget()
        for _ in range(3):
            b.consume_search()
        with pytest.raises(BudgetExhausted):
            b.consume_search()

    def test_checks_before_action(self):
        b = make_budget()
        assert b.can_search()
        b.consume_search()
        b.consume_search()
        b.consume_search()
        assert not b.can_search()


class TestPages:
    def test_global_limit_and_round_limit(self):
        b = make_budget()
        b.start_round()
        b.consume_page()
        b.consume_page()
        # Limite por rodada (2) atingido.
        assert b.pages_left_this_round() == 0
        b.start_round()
        assert b.pages_left_this_round() == 2
        b.consume_page()
        b.consume_page()
        # Limite global (5) atingido.
        assert b.pages_left_this_round() == 0


class TestLLM:
    def test_investigation_never_uses_reserved(self):
        b = make_budget()
        for _ in range(6):  # 10 - 4 reservadas
            b.consume_llm()
        assert b.investigation_calls_left() == 0
        with pytest.raises(BudgetExhausted):
            b.consume_llm()

    def test_reserved_calls_separate(self):
        b = make_budget()
        for _ in range(4):
            b.consume_llm(reserved=True)
        with pytest.raises(BudgetExhausted):
            b.consume_llm(reserved=True)
        # Reserva esgotada não afeta investigação.
        assert b.can_call_llm()

    def test_cannot_borrow_reserved_for_investigation(self):
        b = make_budget()
        for _ in range(6):
            b.consume_llm()
        with pytest.raises(BudgetExhausted):
            b.consume_llm(reserved=False)


class TestDeadline:
    def test_exhausted_deadline_blocks_actions(self):
        b = make_budget(deadline=0.0)
        assert b.remaining_seconds() == 0.0
        assert b.deadline_exceeded()
        assert not b.can_search()
        assert not b.can_fetch_page()
        assert not b.can_call_llm()
        assert not b.can_start_round()

    def test_remaining_never_negative(self):
        b = make_budget(deadline=-1.0e12)
        assert b.remaining_seconds() == 0.0


class TestSnapshot:
    def test_snapshot_reflects_state(self):
        b = make_budget()
        b.start_round()
        b.consume_search()
        b.consume_page()
        b.consume_llm()
        b.consume_llm(reserved=True)
        snap = b.snapshot()
        assert snap["rounds"] == 1
        assert snap["searches"] == 1
        assert snap["pages_fetched"] == 1
        assert snap["llm_investigation_calls"] == 1
        assert snap["llm_reserved_calls"] == 1
        assert snap["remaining_seconds"] >= 0.0
