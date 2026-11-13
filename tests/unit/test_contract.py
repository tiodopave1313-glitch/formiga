"""The document contract: profile table, validation and lint."""

from __future__ import annotations

import pytest

from formiga.research.contract import (
    ANSWER,
    CONFLICTS,
    DEFAULT_PROFILES,
    GAPS,
    PROFILE_NAMES,
    THEMATIC,
    ProfileUnsupported,
    get_profile,
    lint,
    permitted_profiles,
    validate_profile,
)
from formiga.research.report import Citation, Claim, Report, Section, SourceRef


def _claim(claim_id: str, *, sources: tuple[int, ...] = (1,), note: int = 10) -> Claim:
    return Claim(
        id=claim_id,
        text="Rosemary survives to about -10 C and thyme to -15 C.",
        citations=[Citation(n=index + 1, source_id=source, note_id=note + index)
                   for index, source in enumerate(sources)],
    )


def _report(**overrides) -> Report:
    defaults = {
        "run_id": "01TEST",
        "profile": "medium",
        "title": "Cold hardiness",
        "answer": "Rosemary is hardier than thyme in dry cold.",
        "tldr": ["Rosemary survives -10 C."],
        "sections": [
            Section(id="s1", title="Overview", claims=[_claim("a1", sources=(1, 2))]),
            Section(id="s2", title="Details", claims=[_claim("a2", sources=(3, 4), note=20)]),
            Section(id="s3", title="More", claims=[_claim("a3", sources=(5, 6), note=30)]),
        ],
        "tables": [{"kind": "comparison", "rows": []}],
        "related_questions": ["What about sage?"],
        "sources": [SourceRef(n=n, url=f"https://example{n}.org/a") for n in range(1, 9)],
        "budget": {"llm_calls": 3},
        "word_count": 1000,
    }
    defaults.update(overrides)
    return Report(**defaults)


def test_every_profile_is_in_the_table() -> None:
    assert set(DEFAULT_PROFILES) == set(PROFILE_NAMES)


@pytest.mark.parametrize(
    ("name", "words", "sections", "sources", "calls"),
    [
        ("short", (250, 400), (1, 2), (2, 4), (8, 12)),
        ("medium", (900, 1200), (3, 5), (8, 10), (31, 45)),
        ("long", (1800, 2600), (5, 8), (12, 16), (48, 70)),
        ("thesis", (4000, 8000), (7, 12), (20, 30), (80, 120)),
    ],
)
def test_profile_rows_match_prd_section_6_3(name, words, sections, sources, calls) -> None:
    spec = get_profile(name)
    assert spec.words == words
    assert spec.sections == sections
    assert spec.sources == sources
    assert spec.llm_calls == calls


def test_band_is_ten_percent_wider_than_the_promise() -> None:
    medium = get_profile("medium")
    assert medium.band == (810, 1320)


def test_short_deadlines_and_single_support() -> None:
    short = get_profile("short")
    assert short.deadline_for("dual") == 360
    assert short.deadline_for("single") == 600
    assert get_profile("long").deadline_for("single") is None


def test_unknown_profile_is_rejected_with_the_allowed_list() -> None:
    with pytest.raises(ProfileUnsupported) as caught:
        get_profile("epic")
    assert caught.value.allowed == PROFILE_NAMES


def test_overrides_are_applied_and_unknown_keys_rejected() -> None:
    spec = get_profile("medium", overrides={"medium": {"words": (1000, 1400)}})
    assert spec.words == (1000, 1400)
    with pytest.raises(ProfileUnsupported):
        get_profile("medium", overrides={"medium": {"wordz": (1, 2)}})


def test_single_layout_permits_only_short_and_medium() -> None:
    assert permitted_profiles("single") == ("short", "medium")
    assert permitted_profiles("single", allow_heavy=True) == PROFILE_NAMES
    assert "thesis" in permitted_profiles("dual")


def test_validate_profile_raises_before_a_run_starts() -> None:
    assert validate_profile("medium", layout="single").name == "medium"
    with pytest.raises(ProfileUnsupported):
        validate_profile("thesis", layout="single")


def test_lint_accepts_a_report_that_meets_its_contract() -> None:
    result = lint(_report())
    assert result.ok, result.violations
    assert result.profile == "medium"
    assert result.band == (810, 1320)


def test_lint_flags_a_word_count_outside_the_band() -> None:
    result = lint(_report(word_count=200))
    assert not result.ok
    assert any(violation["check"] == "band" for violation in result.violations)


def test_lint_flags_a_missing_mandatory_section() -> None:
    result = lint(_report(related_questions=[]))
    assert any("related" in violation["detail"] for violation in result.violations)


def test_lint_flags_sections_without_a_multi_source_sentence() -> None:
    sections = [Section(id="s1", title="Overview", claims=[_claim("a1", sources=(1,))])]
    result = lint(_report(sections=sections, sources=[]))
    checks = {violation["check"] for violation in result.violations}
    assert "integrated" in checks


def test_lint_flags_a_note_quoted_twice() -> None:
    sections = [
        Section(id="s1", title="Overview", claims=[_claim("a1", sources=(1, 2))]),
        Section(id="s2", title="Again",
                claims=[Claim(id="a2", text="Repeat.", citations=[
                    Citation(n=1, source_id=1, note_id=10)])]),
        Section(id="s3", title="More", claims=[_claim("a3", sources=(4, 5), note=30)]),
    ]
    result = lint(_report(sections=sections))
    assert any(violation["check"] == "quote_reuse" for violation in result.violations)


def test_thesis_enforces_its_claim_cap() -> None:
    spec = get_profile("thesis")
    claims = [_claim(f"a{index}", sources=(index, index + 1), note=index * 2)
              for index in range(1, 8)]
    sections = [Section(id=f"s{index}", title="T", claims=claims) for index in range(7)]
    report = _report(profile="thesis", sections=sections, word_count=5000,
                     sources=[SourceRef(n=n, url=f"https://x{n}.org") for n in range(1, 31)],
                     methodology={"queries": []})
    result = lint(report, spec)
    assert any(violation["check"] == "claim_cap" for violation in result.violations)


def test_contract_result_is_json_ready() -> None:
    payload = lint(_report()).as_dict()
    assert payload["profile"] == "medium"
    assert payload["ok"] is True
    assert payload["band"] == [810, 1320]


def test_answer_and_conflicts_are_recognised_as_present() -> None:
    report = _report(conflicts=[{"sources": [1, 2]}])
    result = lint(report)
    assert not any(ANSWER in v["detail"] for v in result.violations)
    assert not any(CONFLICTS in v["detail"] for v in result.violations)


def test_thematic_section_count_is_checked() -> None:
    sections = [Section(id="s1", title="Only", claims=[_claim("a1", sources=(1, 2))])]
    result = lint(_report(sections=sections))
    assert any(violation["check"] == THEMATIC for violation in result.violations)


def test_gap_and_conflict_sections_have_no_mandatory_content_requirement() -> None:
    """An empty conflicts list is honest, not a contract violation."""
    result = lint(_report(conflicts=[], gaps=[]))
    assert not any(GAPS in violation["detail"] for violation in result.violations)
