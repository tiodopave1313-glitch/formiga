"""Guardrails do agente para modelos pequenos (seção 7 do PRD).

Controla orçamento (turnos, chamadas ao LLM, tempo), cap de resultados de
ferramenta e anti-loop (ladder: 2 chamadas idênticas → nudge; 4 → encerra turno).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class AgentBudget:
    """Orçamento global da sessão do agente."""

    max_turns: int = 24
    max_llm_calls: int = 120
    timeout_seconds: float = 1800.0

    turns_used: int = 0
    llm_calls_used: int = 0
    start_time: float = field(default_factory=time.monotonic)

    def remaining_turns(self) -> int:
        return max(0, self.max_turns - self.turns_used)

    def remaining_llm_calls(self) -> int:
        return max(0, self.max_llm_calls - self.llm_calls_used)

    def remaining_seconds(self) -> float:
        return max(0.0, self.timeout_seconds - (time.monotonic() - self.start_time))

    def can_start_turn(self) -> str | None:
        """Retorna uma mensagem de esgotamento ou `None` se pode continuar."""
        if self.turns_used >= self.max_turns:
            return f"Orçamento de turnos esgotado ({self.max_turns})."
        if self.llm_calls_used >= self.max_llm_calls:
            return f"Orçamento de chamadas ao LLM esgotado ({self.max_llm_calls})."
        if self.remaining_seconds() <= 0:
            return f"Tempo da sessão esgotado ({self.timeout_seconds:.0f} s)."
        return None

    def record_llm_call(self) -> None:
        self.llm_calls_used += 1

    def record_turn(self) -> None:
        self.turns_used += 1


@dataclass
class ToolResultCap:
    """Limite de tamanho do retorno de uma ferramenta."""

    default_chars: int = 4000
    bash_chars: int = 8000

    def cap_for(self, tool_name: str) -> int:
        return self.bash_chars if tool_name == "bash" else self.default_chars


@dataclass
class AntiLoop:
    """Detecta repetição de chamadas de ferramenta (ladder da seção 7)."""

    # chave (nome, argumentos-normalizados) -> número de chamadas consecutivas
    counts: dict[tuple[str, str], int] = field(default_factory=dict)
    last_key: tuple[str, str] | None = None

    def _key(self, tool_name: str, arguments: str) -> tuple[str, str]:
        return (tool_name, arguments)

    def register(self, tool_name: str, arguments: str) -> str | None:
        """
        Registra uma chamada. Retorna `None` se tudo bem, `"nudge"` após 2
        idênticas ou `"stop"` após 4 idênticas (encerra o turno).
        """
        key = self._key(tool_name, arguments)
        if key == self.last_key:
            self.counts[key] = self.counts.get(key, 0) + 1
        else:
            # nova chave: reinicia contadores (não acumula across diferentes)
            self.counts = {key: 1}
            self.last_key = key
        n = self.counts[key]
        if n >= 4:
            return "stop"
        if n >= 2:
            return "nudge"
        return None

    def nudge_message(self, tool_name: str) -> str:
        return (
            f"Você já chamou `{tool_name}` com os mesmos argumentos duas vezes "
            "sem progresso. Tente um caminho/argumento diferente ou responda ao usuário."
        )


@dataclass
class ToolBudgets:
    """Orçamentos de ferramentas web por mensagem do usuário (seção 7).

    Esgotar um orçamento devolve `ERRO:` orçamental ao modelo — não encerra
    a sessão. Reinicializado a cada nova mensagem (`AgentLoop.run`).
    """

    max_deep_searches: int = 2
    max_web_searches: int = 6
    max_web_fetches: int = 8

    deep_searches_used: int = 0
    web_searches_used: int = 0
    web_fetches_used: int = 0

    def consume(self, resource: str) -> str | None:
        """Consome uma unidade do orçamento. Retorna `ERRO:` se esgotado."""
        if resource == "deep_search":
            if self.deep_searches_used >= self.max_deep_searches:
                return (
                    f"ERRO: orçamento de deep_search esgotado "
                    f"({self.max_deep_searches} por mensagem)."
                )
            self.deep_searches_used += 1
        elif resource == "web_search":
            if self.web_searches_used >= self.max_web_searches:
                return (
                    f"ERRO: orçamento de web_search esgotado "
                    f"({self.max_web_searches} por mensagem)."
                )
            self.web_searches_used += 1
        elif resource == "web_fetch":
            if self.web_fetches_used >= self.max_web_fetches:
                return (
                    f"ERRO: orçamento de web_fetch esgotado "
                    f"({self.max_web_fetches} por mensagem)."
                )
            self.web_fetches_used += 1
        else:
            raise ValueError(f"Recurso desconhecido: {resource}")
        return None

    def remaining(self, resource: str) -> int:
        if resource == "deep_search":
            return max(0, self.max_deep_searches - self.deep_searches_used)
        if resource == "web_search":
            return max(0, self.max_web_searches - self.web_searches_used)
        if resource == "web_fetch":
            return max(0, self.max_web_fetches - self.web_fetches_used)
        raise ValueError(f"Recurso desconhecido: {resource}")

