"""Testes dos guardrails: orçamento e anti-loop ladder."""

from __future__ import annotations

from formiga.agent.guardrails import AgentBudget, AntiLoop


def test_budget_esgota_turnos():
    b = AgentBudget(max_turns=2, max_llm_calls=100, timeout_seconds=3600)
    assert b.can_start_turn() is None
    b.record_turn()
    b.record_turn()
    msg = b.can_start_turn()
    assert msg is not None and "turnos" in msg


def test_budget_esgota_chamadas():
    b = AgentBudget(max_turns=100, max_llm_calls=2, timeout_seconds=3600)
    b.record_llm_call()
    assert b.can_start_turn() is None
    b.record_llm_call()
    msg = b.can_start_turn()
    assert msg is not None and "chamadas ao LLM" in msg


def test_anti_loop_nudge_em_2_stop_em_4():
    a = AntiLoop()
    # duas idênticas → nudge
    assert a.register("ls", ".") is None
    assert a.register("ls", ".") == "nudge"
    # chave diferente reinicia contagem
    assert a.register("ls", "src") is None
    assert a.register("ls", "src") == "nudge"
    assert a.register("ls", "src") == "nudge"  # 3ª ainda é nudge
    assert a.register("ls", "src") == "stop"  # 4ª encerra
