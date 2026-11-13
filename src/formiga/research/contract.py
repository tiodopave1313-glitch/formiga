"""Document contract and length profiles.

A profile is *data*: it fixes the word band, the section skeleton, the research budget
and the deadline. Adding a profile must never require editing the core, so everything
here is a frozen table plus pure functions. ``lint`` is the machine-checkable half of
the contract and is the reason a report can never drift from its promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from formiga.research.report import RUNG_ORDER, Claim, ContractResult, Report

PROFILE_NAMES = ("short", "medium", "long", "thesis")
CITATION_STYLES = ("apa", "abnt", "ieee", "mla")

#: Section identifiers used by the skeleton table (``"*"`` means "n thematic sections").
ANSWER = "answer"
TLDR = "tldr"
OVERVIEW = "overview"
THEMATIC = "thematic"
COMPARISON = "comparison"
TIMELINE = "timeline"
CONFLICTS = "conflicts"
GAPS = "gaps"
RELATED = "related"
METHODOLOGY = "methodology"
RISKS = "risks"
SOURCES = "sources"
TRACE = "trace"

MANDATORY = "mandatory"
OPTIONAL = "optional"
ABSENT = "absent"


class ProfileUnsupported(ValueError):
    """Raised when a layout cannot honour a profile's promise."""

    def __init__(self, profile: str, *, allowed: tuple[str, ...], reason: str) -> None:
        self.profile = profile
        self.allowed = allowed
        self.reason = reason
        super().__init__(f"profile {profile!r} unsupported: {reason}")


@dataclass(frozen=True)
class ProfileSpec:
    """The complete promise of one length profile."""

    name: str
    words: tuple[int, int]
    sections: tuple[int, int]
    sources: tuple[int, int]
    sources_typical: int
    aspects: tuple[int, int]
    gap_rounds: tuple[int, int]
    llm_calls: tuple[int, int]
    prompt_tokens: tuple[int, int]
    output_tokens: tuple[int, int]
    deadline_dual_s: int
    deadline_single_s: int | None
    rung_ceiling: str = "bounded-edit"
    skeleton: dict[str, str] = field(default_factory=dict)
    claim_cap: int | None = None
    answer_box_max_words: int = 90

    @property
    def band(self) -> tuple[int, int]:
        """The ±10% enforced word band."""
        low, high = self.words
        return round(low * 0.9), round(high * 1.1)

    @property
    def typical_words(self) -> int:
        return (self.words[0] + self.words[1]) // 2

    def mandatory_sections(self) -> tuple[str, ...]:
        return tuple(name for name, kind in self.skeleton.items() if kind == MANDATORY)

    def allows(self, rung: str) -> bool:
        return RUNG_ORDER.index(rung) <= RUNG_ORDER.index(self.rung_ceiling)

    def deadline_for(self, layout: str) -> int | None:
        if layout in {"dual", "proxy"}:
            return self.deadline_dual_s
        if layout == "single-strong":
            return self.deadline_dual_s + 600
        return self.deadline_single_s


_COMMON_TAIL = {
    CONFLICTS: MANDATORY,
    GAPS: MANDATORY,
    SOURCES: MANDATORY,
    TRACE: MANDATORY,
}

DEFAULT_PROFILES: dict[str, ProfileSpec] = {
    "short": ProfileSpec(
        name="short",
        words=(250, 400),
        sections=(1, 2),
        sources=(2, 4),
        sources_typical=3,
        aspects=(2, 3),
        gap_rounds=(0, 0),
        llm_calls=(8, 12),
        prompt_tokens=(4500, 6000),
        output_tokens=(600, 900),
        deadline_dual_s=6 * 60,
        deadline_single_s=10 * 60,
        skeleton={
            ANSWER: MANDATORY,
            TLDR: MANDATORY,
            OVERVIEW: MANDATORY,
            THEMATIC: OPTIONAL,
            COMPARISON: OPTIONAL,
            TIMELINE: ABSENT,
            RELATED: OPTIONAL,
            RISKS: OPTIONAL,
            **_COMMON_TAIL,
        },
        answer_box_max_words=60,
    ),
    "medium": ProfileSpec(
        name="medium",
        words=(900, 1200),
        sections=(3, 5),
        sources=(8, 10),
        sources_typical=11,
        aspects=(4, 5),
        gap_rounds=(1, 2),
        llm_calls=(31, 45),
        prompt_tokens=(28400, 40000),
        output_tokens=(2600, 4000),
        deadline_dual_s=30 * 60,
        deadline_single_s=50 * 60,
        skeleton={
            ANSWER: MANDATORY,
            TLDR: MANDATORY,
            OVERVIEW: MANDATORY,
            THEMATIC: MANDATORY,
            COMPARISON: MANDATORY,
            TIMELINE: OPTIONAL,
            RELATED: MANDATORY,
            RISKS: OPTIONAL,
            **_COMMON_TAIL,
        },
    ),
    "long": ProfileSpec(
        name="long",
        words=(1800, 2600),
        sections=(5, 8),
        sources=(12, 16),
        sources_typical=14,
        aspects=(6, 8),
        gap_rounds=(2, 3),
        llm_calls=(48, 70),
        prompt_tokens=(44000, 62000),
        output_tokens=(4200, 6000),
        deadline_dual_s=45 * 60,
        deadline_single_s=None,
        rung_ceiling="anchored-rewrite",
        skeleton={
            ANSWER: MANDATORY,
            TLDR: MANDATORY,
            OVERVIEW: MANDATORY,
            THEMATIC: MANDATORY,
            COMPARISON: MANDATORY,
            TIMELINE: MANDATORY,
            RELATED: MANDATORY,
            METHODOLOGY: OPTIONAL,
            RISKS: MANDATORY,
            **_COMMON_TAIL,
        },
    ),
    "thesis": ProfileSpec(
        name="thesis",
        words=(4000, 8000),
        sections=(7, 12),
        sources=(20, 30),
        sources_typical=24,
        aspects=(8, 8),
        gap_rounds=(3, 4),
        llm_calls=(80, 120),
        prompt_tokens=(70000, 100000),
        output_tokens=(7000, 10000),
        deadline_dual_s=90 * 60,
        deadline_single_s=None,
        rung_ceiling="anchored-rewrite",
        skeleton={
            ANSWER: MANDATORY,
            TLDR: OPTIONAL,
            OVERVIEW: MANDATORY,
            THEMATIC: MANDATORY,
            COMPARISON: MANDATORY,
            TIMELINE: MANDATORY,
            RELATED: ABSENT,
            METHODOLOGY: MANDATORY,
            RISKS: MANDATORY,
            **_COMMON_TAIL,
        },
        claim_cap=6,
        answer_box_max_words=200,
    ),
}

#: Which profiles a layout may promise without ``--allow-heavy`` (PRD §8.2).
LAYOUT_PROFILES: dict[str, tuple[str, ...]] = {
    "single": ("short", "medium"),
    "single-strong": ("short", "medium", "long", "thesis"),
    "dual": ("short", "medium", "long", "thesis"),
    "proxy": ("short", "medium", "long", "thesis"),
}

DEFAULT_PROFILE = "medium"


def get_profile(name: str, *, overrides: dict[str, dict[str, Any]] | None = None) -> ProfileSpec:
    """Return the profile called ``name``, applying optional TOML overrides."""
    try:
        spec = DEFAULT_PROFILES[name]
    except KeyError as exc:
        raise ProfileUnsupported(name, allowed=PROFILE_NAMES, reason="unknown profile") from exc
    data = (overrides or {}).get(name)
    if not data:
        return spec
    allowed_fields = set(ProfileSpec.__dataclass_fields__)
    unknown = set(data) - allowed_fields
    if unknown:
        raise ProfileUnsupported(
            name, allowed=PROFILE_NAMES, reason=f"unknown profile keys: {sorted(unknown)}"
        )
    return replace(spec, **data)


def permitted_profiles(
    layout: str, *, ram_gb: float | None = None, allow_heavy: bool = False
) -> tuple[str, ...]:
    """Return the profiles a layout may run on a machine with ``ram_gb``."""
    base = LAYOUT_PROFILES.get(layout, ("short",))
    if not allow_heavy:
        return base
    if ram_gb is None or ram_gb >= 4:
        return PROFILE_NAMES
    return base


def validate_profile(
    name: str,
    *,
    layout: str,
    ram_gb: float | None = None,
    allow_heavy: bool = False,
) -> ProfileSpec:
    """Return the profile, or raise :class:`ProfileUnsupported` before a run starts."""
    spec = get_profile(name)
    allowed = permitted_profiles(layout, ram_gb=ram_gb, allow_heavy=allow_heavy)
    if name not in allowed:
        raise ProfileUnsupported(
            name,
            allowed=allowed,
            reason=f"layout {layout} does not permit it",
        )
    return spec


def _sections_present(report: Report, spec: ProfileSpec) -> set[str]:
    found: set[str] = set()
    if report.answer.strip():
        found.add(ANSWER)
    if report.tldr:
        found.add(TLDR)
    if report.sections:
        found.add(OVERVIEW)
    thematic = [section for section in report.sections if section.kind == "prose"]
    if thematic:
        found.add(THEMATIC)
    if any(table.get("kind") == "comparison" for table in report.tables):
        found.add(COMPARISON)
    if report.timeline:
        found.add(TIMELINE)
    if report.conflicts:
        found.add(CONFLICTS)
    if report.gaps:
        found.add(GAPS)
    if report.related_questions:
        found.add(RELATED)
    if report.methodology:
        found.add(METHODOLOGY)
    if any("risks" in section.id or "risks" in section.title.lower()
           for section in report.sections):
        found.add(RISKS)
    if report.sources:
        found.add(SOURCES)
    if report.budget:
        found.add(TRACE)
    return found


def _quoting_reuse(claims: list[Claim]) -> int:
    seen: dict[tuple[int, int], int] = {}
    for claim in claims:
        if not claim.citations:
            continue
        first = claim.citations[0]
        key = (first.source_id, first.note_id)
        seen[key] = seen.get(key, 0) + 1
    return max(seen.values(), default=0)


def _integrated_share(report: Report) -> float:
    if not report.sections:
        return 1.0
    integrated = sum(
        1
        for section in report.sections
        if any(len(claim.independent_sources()) >= 2 for claim in section.claims)
    )
    return integrated / len(report.sections)


def lint(
    report: Report,
    spec: ProfileSpec | None = None,
    *,
    threshold: float = 1.0,
) -> ContractResult:
    """Check the report against its profile. Never mutates a claim."""
    spec = spec or get_profile(report.profile)
    result = ContractResult(profile=spec.name, band=spec.band)

    def violation(check: str, detail: str) -> None:
        result.violations.append({"check": check, "detail": detail})

    words = report.renderable_words()
    low, high = spec.band
    if report.word_count and not low <= report.word_count <= high:
        violation("band", f"words {report.word_count} outside {low}-{high}")
    elif not report.word_count and not low <= words <= high:
        violation("band", f"words {words} outside {low}-{high}")

    present = _sections_present(report, spec)
    # These sections are rendered unconditionally by the composer, even when empty:
    # saying "no conflicts found" is a valid answer, so their absence is not a violation.
    always_rendered = {CONFLICTS, GAPS, TRACE, THEMATIC, COMPARISON, TIMELINE, RISKS}
    for section in spec.mandatory_sections():
        if section in always_rendered:
            continue
        if section not in present:
            violation("section", f"missing mandatory section: {section}")

    if spec.skeleton.get(THEMATIC) == MANDATORY:
        thematic = [section for section in report.sections if section.kind == "prose"]
        if not spec.sections[0] <= len(thematic) <= spec.sections[1]:
            violation(
                "thematic",
                f"{len(thematic)} thematic sections, "
                f"expected {spec.sections[0]}-{spec.sections[1]}",
            )

    if report.sources and len(report.sources) < spec.sources[0]:
        violation("sources", f"{len(report.sources)} sources, floor is {spec.sources[0]}")

    share = _integrated_share(report)
    if share < threshold:
        violation("integrated", f"{share:.0%} of sections carry a multi-source sentence")

    reuse = _quoting_reuse(report.all_claims())
    if reuse > 1:
        violation("quote_reuse", f"a note is cited {reuse} times")

    if spec.claim_cap is not None:
        for section in report.sections:
            if len(section.claims) > spec.claim_cap:
                violation("claim_cap", f"section {section.id} has {len(section.claims)} claims")

    result.ok = not result.violations
    return result


__all__ = [
    "ABSENT",
    "ANSWER",
    "CITATION_STYLES",
    "COMPARISON",
    "CONFLICTS",
    "DEFAULT_PROFILES",
    "DEFAULT_PROFILE",
    "GAPS",
    "LAYOUT_PROFILES",
    "MANDATORY",
    "METHODOLOGY",
    "OPTIONAL",
    "OVERVIEW",
    "PROFILE_NAMES",
    "ProfileSpec",
    "ProfileUnsupported",
    "RELATED",
    "RISKS",
    "SOURCES",
    "THEMATIC",
    "TIMELINE",
    "TLDR",
    "TRACE",
    "get_profile",
    "lint",
    "permitted_profiles",
    "validate_profile",
]
