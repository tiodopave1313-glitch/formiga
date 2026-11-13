"""The stage fixtures are contracts, so they are checked, not just committed.

Two things are pinned here:

1. every fixture has the shape the harness expects (``stage``, ``input``, ``expected``);
2. the ``lint`` fixtures reproduce the real verdict of :func:`formiga.research.contract.lint`,
   which is the one stage that exists today and therefore the one that can be checked end to end.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from formiga.research.contract import lint
from formiga.research.report import Citation, Claim, Report, Section, SourceRef

STAGES = Path(__file__).resolve().parents[1] / "fixtures" / "stages"
FIXTURES = sorted(path for path in STAGES.glob("*.json"))
STAGE_NAMES = {"plan", "extract", "notes", "synthesize", "lint"}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_fixture_has_the_harness_shape(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["stage"] in STAGE_NAMES
    assert isinstance(payload["input"], dict)
    assert isinstance(payload["expected"], dict)
    assert payload.get("note"), "a fixture without a note does not explain what it pins"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_extraction_fixtures_never_supply_text(path: Path) -> None:
    """Extraction and assembly return ids; only an anchored rewrite may return words."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["stage"] not in {"extract", "notes"}:
        return
    assert "text" not in payload["expected"], "the reader must never return prose"
    ranges = payload["expected"].get("segments")
    if ranges is not None:
        for start, end in ranges:
            assert start <= end, "a range must be closed and ordered"


def test_extraction_fixtures_across_the_suite_cover_all_three_verdicts() -> None:
    verdicts = {
        json.loads(path.read_text(encoding="utf-8"))["expected"].get("verdict")
        for path in FIXTURES
        if json.loads(path.read_text(encoding="utf-8"))["stage"] == "extract"
    }
    assert {"answers", "partial", "no"} <= verdicts


def test_synthesis_fixtures_cover_every_rung() -> None:
    rungs = {
        json.loads(path.read_text(encoding="utf-8")).get("rung")
        for path in FIXTURES
        if json.loads(path.read_text(encoding="utf-8"))["stage"] == "synthesize"
    }
    assert rungs == {"assemble", "bounded-edit", "anchored-rewrite"}


# --- the lint fixtures must reproduce the real verdict ---------------------------------


def _claim(claim_id: str, *, source_ids: tuple[int, ...]) -> Claim:
    return Claim(
        id=claim_id,
        text="Selected source sentence.",
        citations=[
            Citation(n=index + 1, source_id=source, note_id=100 + index)
            for index, source in enumerate(source_ids)
        ],
    )


def _report_from(inputs: dict[str, Any]) -> Report:
    """Build the smallest report that matches a fixture's summary numbers."""
    sections_count = int(inputs["sections"])
    sections = [
        Section(
            id=f"s{index}",
            title=f"Section {index}",
            claims=[_claim(f"c{index}", source_ids=(index * 2 + 1, index * 2 + 2))],
        )
        for index in range(1, sections_count + 1)
    ]
    sources = [
        SourceRef(n=n, url=f"https://example{n}.org/article")
        for n in range(1, int(inputs["sources"]) + 1)
    ]
    return Report(
        run_id="01FIXTURE",
        profile=inputs.get("profile", "medium"),
        title="Fixture",
        answer="Fixture answer.",
        tldr=["Fixture TL;DR."],
        sections=sections,
        tables=[{"kind": "comparison", "rows": []}],
        related_questions=["A related question?"],
        conflicts=[{"sources": [1, 2]}] if inputs.get("conflicts") else [],
        gaps=[{"facet": "costs"}] if inputs.get("gaps") else [],
        sources=sources,
        budget={"llm_calls": 3},
        word_count=int(inputs["word_count"]),
    )


@pytest.mark.parametrize(
    "path",
    [path for path in FIXTURES if path.name.startswith("lint-")],
    ids=lambda path: path.stem,
)
def test_lint_fixtures_match_the_real_contract(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = lint(_report_from(payload["input"]))
    expected = payload["expected"]
    assert result.ok is expected["ok"], result.violations
    found = {violation["check"] for violation in result.violations}
    assert found == set(expected["violations"])
