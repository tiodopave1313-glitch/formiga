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

    def to_dict(self) -> dict[str, Any]:
        """Serialise the tree to the JSON shape written to ``report.json``."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "profile": self.profile,
            "title": self.title,
            "answer": self.answer,
            "tldr": list(self.tldr),
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "kind": section.kind,
                    "claims": [_claim_to_dict(claim) for claim in section.claims],
                }
                for section in self.sections
            ],
            "sources": [
                {
                    "n": source.n,
                    "url": source.url,
                    "title": source.title,
                    "domain": source.domain,
                    "published": source.published,
                    "accessed_at": source.accessed_at,
                }
                for source in self.sources
            ],
            "tables": [dict(table) for table in self.tables],
            "timeline": None if self.timeline is None else [dict(row) for row in self.timeline],
            "related_questions": list(self.related_questions),
            "conflicts": [dict(row) for row in self.conflicts],
            "gaps": [dict(row) for row in self.gaps],
            "warnings": list(self.warnings),
            "methodology": self.methodology,
            "glossary": [dict(row) for row in self.glossary],
            "rung_ceiling": self.rung_ceiling,
            "confidence": self.confidence,
            "citation_coverage": self.citation_coverage,
            "citation_precision": self.citation_precision,
            "synthesis_ratio": self.synthesis_ratio,
            "domains": self.domains,
            "word_count": self.word_count,
            "reading_minutes": self.reading_minutes,
            "rung_distribution": dict(self.rung_distribution),
            "freshness": dict(self.freshness),
            "budget": dict(self.budget),
        }


def _claim_to_dict(claim: Claim) -> dict[str, Any]:
    return {
        "id": claim.id,
        "text": claim.text,
        "rung": claim.rung,
        "citations": [
            {"n": citation.n, "source_id": citation.source_id, "note_id": citation.note_id}
            for citation in claim.citations
        ],
        "critical": claim.critical,
        "flags": list(claim.flags),
        "overlap": claim.overlap,
        "lexical_support": claim.lexical_support,
        "derivation": claim.derivation,
    }


def report_from_dict(payload: dict[str, Any]) -> Report:
    """Rebuild a report from ``report.json``.

    Missing optional keys fall back to their defaults so a report written by an older
    schema version still loads; a *newer* schema version is refused rather than guessed.
    """
    version = int(payload.get("schema_version", SCHEMA_VERSION))
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"report schema {version} is newer than this build supports ({SCHEMA_VERSION})"
        )
    return Report(
        run_id=str(payload["run_id"]),
        profile=str(payload["profile"]),
        title=str(payload.get("title", "")),
        answer=str(payload.get("answer", "")),
        tldr=[str(item) for item in payload.get("tldr", [])],
        sections=[_section_from_dict(item) for item in payload.get("sections", [])],
        sources=[_source_from_dict(item) for item in payload.get("sources", [])],
        tables=[dict(item) for item in payload.get("tables", [])],
        timeline=None if payload.get("timeline") is None
        else [dict(item) for item in payload["timeline"]],
        related_questions=[str(item) for item in payload.get("related_questions", [])],
        conflicts=[dict(item) for item in payload.get("conflicts", [])],
        gaps=[dict(item) for item in payload.get("gaps", [])],
        warnings=[str(item) for item in payload.get("warnings", [])],
        methodology=payload.get("methodology"),
        glossary=[dict(item) for item in payload.get("glossary", [])],
        rung_ceiling=str(payload.get("rung_ceiling", "assemble")),
        confidence=str(payload.get("confidence", "low")),
        citation_coverage=float(payload.get("citation_coverage", 0.0)),
        citation_precision=float(payload.get("citation_precision", 0.0)),
        synthesis_ratio=float(payload.get("synthesis_ratio", 0.0)),
        domains=int(payload.get("domains", 0)),
        word_count=int(payload.get("word_count", 0)),
        reading_minutes=int(payload.get("reading_minutes", 0)),
        rung_distribution={
            str(key): int(value)
            for key, value in (payload.get("rung_distribution") or {}).items()
        },
        freshness=dict(payload.get("freshness") or {}),
        budget=dict(payload.get("budget") or {}),
        schema_version=version,
    )


def _section_from_dict(payload: dict[str, Any]) -> Section:
    return Section(
        id=str(payload["id"]),
        title=str(payload.get("title", "")),
        kind=str(payload.get("kind", "prose")),
        claims=[_claim_from_dict(item) for item in payload.get("claims", [])],
    )


def _claim_from_dict(payload: dict[str, Any]) -> Claim:
    return Claim(
        id=str(payload["id"]),
        text=str(payload.get("text", "")),
        rung=str(payload.get("rung", "assemble")),
        citations=[
            Citation(
                n=int(item["n"]),
                source_id=int(item["source_id"]),
                note_id=int(item["note_id"]),
            )
            for item in payload.get("citations", [])
        ],
        critical=bool(payload.get("critical", False)),
        flags=[str(item) for item in payload.get("flags", [])],
        overlap=float(payload.get("overlap", 1.0)),
        lexical_support=float(payload.get("lexical_support", 1.0)),
        derivation=payload.get("derivation"),
    )


def _source_from_dict(payload: dict[str, Any]) -> SourceRef:
    return SourceRef(
        n=int(payload["n"]),
        url=str(payload.get("url", "")),
        title=str(payload.get("title", "")),
        domain=str(payload.get("domain", "")),
        published=payload.get("published"),
        accessed_at=payload.get("accessed_at"),
    )


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
    "report_from_dict",
]
