"""Nomes dos eventos encadeados e observacionais do runtime."""

CHAIN_EVENTS = frozenset(
    {"input", "before_agent_start", "context", "tool_call", "tool_result", "turn_end"}
)
OBSERVATION_EVENTS = frozenset(
    {
        "llm_call",
        "stream",
        "tool_start",
        "tool_end",
        "tool_progress",
        "budget",
        "interrupted",
        "extension_loaded",
        # Fase 7 (cron): disparo e conclusão de um job agendado.
        "job_start",
        "job_end",
        # Fase 8 (memória): fim de sessão — dispara nudge de memória curada.
        "session_end",
    }
)
