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
    }
)
