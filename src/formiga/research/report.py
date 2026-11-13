"""Report shape (schema 3). Built by code, never emitted by the model.

The report is the synthesis artifact: stage 7 produces claims, stage 9 renders. Keeping
it a plain dataclass tree means ``resize`` can re-cut a document without touching the
model or the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 3

RUNG_ORDER = ("assemble", "bounded-edit", "anchored-rewrite")
ASPECT_ORDER = (
    "definition",
    "mechanism",
    "quantities",
    "comparison",
    "risks",
    "authorities",
    "recent",
    "costs",
)


@dataclass(frozen=True)
class Citation:
    """A frozen pointer from a claim to a note and its run-level number."""

    n: int
    source_id: int
    note_id: int


@dataclass
class Claim:
    """One sentence of the report, assembled from selected notes."""

    id: str
    text: str
    rung: str = "assemble"
    citations: list[Citation] = field(default_factory=list)
    critical: bool = False
    flags: list[str] = field(default_factory=list)
    overlap: float = 1.0
    lexical_support: float = 1.0
    derivation: dict[str, Any] | None = None

    def independent_sources(self) -> set[int]:
        return {citation.source_id for citation in self.citations}


@dataclass
class Section:
    """A thematic section holding claims in facet order."""

    id: str
    title: str
    kind: str = "prose"
    claims: list[Claim] = field(default_factory=list)


@dataclass
class SourceRef:
    """The rendered metadata of one ledger source."""

    n: int
    url: str
    title: str = ""
    domain: str = ""
    published: str | None = None
    accessed_at: str | None = None


@dataclass
class ContractResult:
    """Outcome of the deterministic document-contract check."""

    profile: str
    band: tuple[int, int]
    ok: bool = True
    violations: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "band": list(self.band),
            "ok": self.ok,
            "violations": list(self.violations),
        }


@dataclass
class Report:
    """The whole document, independent of any template."""

    run_id: str
    profile: str
    title: str
    answer: str = ""
    tldr: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, str]] | None = None
    related_questions: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    methodology: dict[str, Any] | None = None
    glossary: list[dict[str, str]] = field(default_factory=list)
    rung_ceiling: str = "assemble"
    confidence: str = "low"
    citation_coverage: float = 0.0
    citation_precision: float = 0.0
    synthesis_ratio: float = 0.0
    domains: int = 0
    word_count: int = 0
    reading_minutes: int = 0
    rung_distribution: dict[str, int] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def all_claims(self) -> list[Claim]:
        return [claim for section in self.sections for claim in section.claims]

    def renderable_words(self) -> int:
        """Word count of rendered prose: sections plus answer box, minus the sources."""
        parts = [self.answer, *(claim.text for claim in self.all_claims())]
        return sum(len(part.split()) for part in parts if part)


__all__ = [
    "ASPECT_ORDER",
    "RUNG_ORDER",
    "SCHEMA_VERSION",
    "Citation",
    "Claim",
    "ContractResult",
    "Report",
    "Section",
    "SourceRef",
]
