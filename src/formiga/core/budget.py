"""Runtime budget governor.

Every LLM call passes through one object that owns the caps for the current profile:
calls, prompt tokens, output tokens and wall-clock. Exhaustion raises
:class:`BudgetExceeded` once and the caller turns it into ``status: incomplete`` plus exit
code 2. Time is injected so deadline tests never sleep.

A cache hit still increments the call counter (PRD §8.4): a resumed run must not loop
forever on free responses.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from formiga.research.contract import ProfileSpec

CAP_NAMES = ("llm_calls", "prompt_tokens", "output_tokens", "deadline")


class BudgetExceeded(RuntimeError):
    """Raised when a run exhausts its calls, tokens or wall-clock budget."""

    def __init__(self, reason: str, snapshot: BudgetSnapshot) -> None:
        self.reason = reason
        self.snapshot = snapshot
        super().__init__(f"budget exceeded: {reason}")


@dataclass(frozen=True)
class BudgetSnapshot:
    """Immutable view of budget consumption."""

    llm_calls: int
    prompt_tokens: int
    output_tokens: int
    elapsed_s: float
    max_llm_calls: int
    max_prompt_tokens: int
    max_output_tokens: int
    deadline_s: float
    exceeded: bool = False
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "duration_s": round(self.elapsed_s, 3),
            "exceeded": self.exceeded,
            "reason": self.reason,
        }


@dataclass
class Budget:
    """Counters and a monotonic deadline."""

    max_llm_calls: int
    max_prompt_tokens: int = 10**9
    max_output_tokens: int = 10**9
    deadline_s: float = 10**9
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    llm_calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    _started: float = field(init=False, repr=False)
    _exceeded: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._started = self.clock()

    @classmethod
    def from_profile(
        cls,
        spec: ProfileSpec,
        *,
        layout: str = "single",
        clock: Callable[[], float] | None = None,
        use_caps: bool = True,
    ) -> Budget:
        """Build the budget of a run from its profile row (PRD §8.4).

        ``use_caps=False`` uses the *typical* column, which is what
        ``formiga bench`` replays; production runs use the cap column.
        """
        column = 1 if use_caps else 0
        deadline = spec.deadline_for(layout)
        return cls(
            max_llm_calls=spec.llm_calls[column],
            max_prompt_tokens=spec.prompt_tokens[column],
            max_output_tokens=spec.output_tokens[column],
            deadline_s=float(deadline) if deadline is not None else 10**9,
            clock=clock or time.monotonic,
        )

    @property
    def elapsed_s(self) -> float:
        return self.clock() - self._started

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.deadline_s - self.elapsed_s)

    @property
    def exhausted(self) -> bool:
        return self._exceeded is not None

    @property
    def reason(self) -> str | None:
        return self._exceeded

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            llm_calls=self.llm_calls,
            prompt_tokens=self.prompt_tokens,
            output_tokens=self.output_tokens,
            elapsed_s=self.elapsed_s,
            max_llm_calls=self.max_llm_calls,
            max_prompt_tokens=self.max_prompt_tokens,
            max_output_tokens=self.max_output_tokens,
            deadline_s=self.deadline_s,
            exceeded=self.exhausted,
            reason=self._exceeded,
        )

    def restore(self, counters: dict[str, Any]) -> None:
        """Continue counters from the last committed stage of a resumed run."""
        self.llm_calls = int(counters.get("llm_calls") or 0)
        self.prompt_tokens = int(counters.get("prompt_tokens") or 0)
        self.output_tokens = int(counters.get("output_tokens") or 0)

    def _fail(self, reason: str) -> BudgetExceeded:
        if self._exceeded is None:
            self._exceeded = reason
        return BudgetExceeded(self._exceeded, self.snapshot())

    def check_deadline(self) -> None:
        """Raise when the wall-clock deadline has passed."""
        if self._exceeded is not None:
            raise self._fail(self._exceeded)
        if self.elapsed_s >= self.deadline_s:
            raise self._fail("deadline")

    def charge_call(self) -> None:
        """Account for one LLM request before it is sent."""
        self.check_deadline()
        if self.llm_calls + 1 > self.max_llm_calls:
            raise self._fail("llm_calls")
        self.llm_calls += 1

    def charge_prompt_tokens(self, tokens: int) -> None:
        """Account for the prompt of a request after the response arrives."""
        if tokens <= 0:
            return
        if self.prompt_tokens + tokens > self.max_prompt_tokens:
            self.prompt_tokens = self.max_prompt_tokens
            raise self._fail("prompt_tokens")
        self.prompt_tokens += tokens

    def charge_output_tokens(self, tokens: int) -> None:
        """Account for generated tokens after the response arrives."""
        if tokens <= 0:
            return
        if self.output_tokens + tokens > self.max_output_tokens:
            self.output_tokens = self.max_output_tokens
            raise self._fail("output_tokens")
        self.output_tokens += tokens

    def as_dict(self) -> dict[str, Any]:
        return self.snapshot().as_dict()


__all__ = ["CAP_NAMES", "Budget", "BudgetExceeded", "BudgetSnapshot"]
