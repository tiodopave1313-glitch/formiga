"""Role to endpoint routing.

Roles map to a *tier* (``fast`` or ``strong``) and a tier maps to an endpoint. In the
default ``single`` layout both tiers resolve to the same endpoint, which is why nothing
here may require two models (PRD §13 rule 17). If a strong endpoint dies mid-run its
remaining calls move to the fast tier, the rung ceiling drops one step and the report
records ``llm_endpoint: degraded``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from formiga.config import Layout
from formiga.llm.base import LLM, BackendUnavailable
from formiga.research.report import RUNG_ORDER

Tier = Literal["fast", "strong"]

ROLE_TIER: dict[str, Tier] = {
    "router": "fast",
    "planner": "fast",
    "reader": "fast",
    "gap_queries": "fast",
    "synthesizer": "strong",
    "answerer": "strong",
}

#: Roles whose prose may run on the fast tier when no strong endpoint exists.
PROSE_ROLES = frozenset({"synthesizer", "answerer"})


@dataclass
class RoutingEvent:
    """One recorded degradation, surfaced in the report and in ``events.jsonl``."""

    role: str
    from_tier: Tier
    to_tier: Tier
    reason: str


@dataclass
class RoleRouter:
    """Resolves each role to a backend, degrading instead of failing."""

    layout: Layout
    backends: dict[Tier, LLM] = field(default_factory=dict)
    events: list[RoutingEvent] = field(default_factory=list)
    degraded: bool = False

    def __post_init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Re-resolve tiers from the layout, honouring live backends."""
        for tier, endpoint in self.layout.tiers.items():
            key: Tier = "strong" if tier == "strong" else "fast"
            backend = self.backends.get(key)
            if backend is None or getattr(backend, "endpoint_config", None) != endpoint:
                from formiga.llm.client import HTTPLLM

                self.backends[key] = HTTPLLM(endpoint, profile_name=key)

    def tier_for(self, role: str) -> Tier:
        return ROLE_TIER.get(role, "fast")

    def backend_for(self, role: str) -> LLM:
        """Return the backend a role should use, falling back to ``fast``."""
        tier = self.tier_for(role)
        backend = self.backends.get(tier)
        if backend is not None:
            return backend
        fast = self.backends["fast"]
        self._degrade(role, tier, "tier unavailable")
        return fast

    def mark_unavailable(self, tier: Tier, *, reason: str) -> None:
        """Move every role off ``tier`` after a transport failure."""
        self.degraded = True
        for role, mapped in ROLE_TIER.items():
            if mapped == tier:
                self._degrade(role, tier, reason)

    def _degrade(self, role: str, from_tier: Tier, reason: str) -> None:
        if from_tier == "fast":
            return
        self.degraded = True
        self.events.append(
            RoutingEvent(role=role, from_tier=from_tier, to_tier="fast", reason=reason)
        )

    def execute(self, role: str, action: object) -> object:
        """Run ``action(backend)``, retrying once on the fast tier if the strong one died."""
        backend = self.backend_for(role)
        try:
            return action(backend)  # type: ignore[operator]
        except BackendUnavailable as exc:
            if backend is self.backends.get("fast"):
                raise
            self.mark_unavailable("strong", reason=str(exc))
            return action(self.backends["fast"])  # type: ignore[operator]

    def rung_ceiling(self) -> str:
        """The layout ceiling, dropped one step when the run degraded."""
        ceiling = self.layout.rung_ceiling()
        if not self.degraded:
            return ceiling
        index = RUNG_ORDER.index(ceiling)
        return RUNG_ORDER[max(0, index - 1)]

    def effective_endpoints(self) -> dict[str, str]:
        return {
            tier: getattr(backend, "url", "") or backend.model
            for tier, backend in self.backends.items()
        }

    def close(self) -> None:
        for backend in self.backends.values():
            backend.close()


__all__ = ["PROSE_ROLES", "ROLE_TIER", "RoleRouter", "RoutingEvent", "Tier"]
