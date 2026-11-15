"""Orçamentos da execução.

Toda tentativa — inclusive falha e correção de formato — consome orçamento.
Os limites são verificados antes de iniciar cada ação. O prazo total usa
relógio monotônico.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExhausted(Exception):
    """Orçamento correspondente se esgotou."""

    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(f"Orçamento esgotado: {resource}")


@dataclass
class Budget:
    """Contabiliza consumo de recursos verificados antes de cada ação."""

    max_rounds: int
    max_searches: int
    max_pages: int
    pages_per_round: int
    max_llm_calls: int
    reserved_llm_calls: int
    timeout_seconds: float
    deadline: float = field(default_factory=lambda: time.monotonic())

    # Consumo acumulado.
    rounds: int = 0
    searches: int = 0
    pages_fetched: int = 0
    pages_this_round: int = 0
    llm_investigation_calls: int = 0
    llm_reserved_calls: int = 0

    @classmethod
    def from_config(cls, config: object) -> Budget:
        return cls(
            max_rounds=config.max_rounds,  # type: ignore[attr-defined]
            max_searches=config.max_searches,  # type: ignore[attr-defined]
            max_pages=config.max_pages,  # type: ignore[attr-defined]
            pages_per_round=config.pages_per_round,  # type: ignore[attr-defined]
            max_llm_calls=config.max_llm_calls,  # type: ignore[attr-defined]
            reserved_llm_calls=config.reserved_llm_calls,  # type: ignore[attr-defined]
            timeout_seconds=config.timeout_seconds,  # type: ignore[attr-defined]
            deadline=time.monotonic() + config.timeout_seconds,  # type: ignore[attr-defined]
        )

    # --- tempo -----------------------------------------------------------

    def remaining_seconds(self) -> float:
        """Tempo restante no prazo total; nunca negativo."""
        return max(0.0, self.deadline - time.monotonic())

    def start_deadline(self) -> None:
        """(Re)inicia o prazo com relógio monotônico."""
        self.deadline = time.monotonic() + self.timeout_seconds

    def deadline_exceeded(self) -> bool:
        return self.remaining_seconds() <= 0.0

    # --- rodadas ---------------------------------------------------------

    def can_start_round(self) -> bool:
        return self.rounds < self.max_rounds and not self.deadline_exceeded()

    def start_round(self) -> None:
        if self.rounds >= self.max_rounds:
            raise BudgetExhausted("rounds")
        self.rounds += 1
        self.pages_this_round = 0

    # --- buscas ----------------------------------------------------------

    def can_search(self) -> bool:
        return self.searches < self.max_searches and not self.deadline_exceeded()

    def consume_search(self) -> None:
        if self.searches >= self.max_searches:
            raise BudgetExhausted("searches")
        self.searches += 1

    # --- páginas ---------------------------------------------------------

    def pages_left_this_round(self) -> int:
        left_global = self.max_pages - self.pages_fetched
        left_round = self.pages_per_round - self.pages_this_round
        return max(0, min(left_global, left_round))

    def can_fetch_page(self) -> bool:
        return self.pages_left_this_round() > 0 and not self.deadline_exceeded()

    def consume_page(self) -> None:
        if self.pages_left_this_round() <= 0:
            raise BudgetExhausted("pages")
        self.pages_fetched += 1
        self.pages_this_round += 1

    # --- chamadas ao LLM -------------------------------------------------

    def investigation_calls_left(self) -> int:
        return max(0, self.max_llm_calls - self.reserved_llm_calls - self.llm_investigation_calls)

    def can_call_llm(self, reserved: bool = False) -> bool:
        if self.deadline_exceeded():
            return False
        if reserved:
            return self.llm_reserved_calls < self.reserved_llm_calls
        return self.investigation_calls_left() > 0

    def consume_llm(self, reserved: bool = False) -> None:
        """Registra uma chamada ao modelo.

        Chamadas reservadas (síntese e auditoria) são contadas separadamente
        e não podem ser usadas na investigação.
        """
        if reserved:
            if self.llm_reserved_calls >= self.reserved_llm_calls:
                raise BudgetExhausted("llm_reserved")
            self.llm_reserved_calls += 1
            return
        if self.investigation_calls_left() <= 0:
            raise BudgetExhausted("llm_investigation")
        self.llm_investigation_calls += 1

    # --- snapshot --------------------------------------------------------

    def snapshot(self) -> dict[str, int | float]:
        return {
            "rounds": self.rounds,
            "max_rounds": self.max_rounds,
            "searches": self.searches,
            "max_searches": self.max_searches,
            "pages_fetched": self.pages_fetched,
            "max_pages": self.max_pages,
            "llm_investigation_calls": self.llm_investigation_calls,
            "llm_reserved_calls": self.llm_reserved_calls,
            "max_llm_calls": self.max_llm_calls,
            "reserved_llm_calls": self.reserved_llm_calls,
            "remaining_seconds": round(self.remaining_seconds(), 3),
        }
