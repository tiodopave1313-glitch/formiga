"""``formiga lint`` and the ``report.json`` round-trip it depends on.

The point of `lint` is that it is *free*: it reads a persisted tree and applies the
contract. These tests therefore never construct a model or a network client.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from formiga.core.lint import LintError, find_report, lint_path, load_report
from formiga.research.report import (
    SCHEMA_VERSION,
    Citation,
    Claim,
    Report,
    Section,
    SourceRef,
    report_from_dict,
)


def _medium_report(*, words: int = 1010, sources: int = 9) -> Report:
    sections = [
        Section(
            id=f"s{index}",
            title=f"Section {index}",
            claims=[
                Claim(
                    id=f"c{index}",
                    text=" ".join(["word"] * (words // 3)),
                    citations=[
                        Citation(n=2 * index - 1, source_id=2 * index - 1, note_id=10 * index),
                        Citation(n=2 * index, source_id=2 * index, note_id=10 * index + 1),
                    ],
                )
            ],
        )
        for index in range(1, 4)
    ]
    return Report(
        run_id="01GATE",
        profile="medium",
        title="Gate report",
        answer="A short answer.",
        tldr=["Point one."],
        sections=sections,
        sources=[SourceRef(n=n, url=f"https://example{n}.org/x") for n in range(1, sources + 1)],
        tables=[{"kind": "comparison", "rows": []}],
        related_questions=["And then?"],
        gaps=[{"facet": "costs"}],
        budget={"llm_calls": 5},
        word_count=words,
    )


def _write(path: Path, report: Report) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False), encoding="utf-8")
    return path


# --- round trip ---------------------------------------------------------------------


def test_report_survives_a_json_round_trip() -> None:
    original = _medium_report()
    restored = report_from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored.to_dict() == original.to_dict()
    assert restored.schema_version == SCHEMA_VERSION


def test_round_trip_keeps_citation_identity() -> None:
    restored = report_from_dict(_medium_report().to_dict())
    first = restored.all_claims()[0]
    assert [(c.n, c.source_id, c.note_id) for c in first.citations] == [(1, 1, 10), (2, 2, 11)]


def test_a_newer_schema_is_refused_rather_than_guessed() -> None:
    payload = _medium_report().to_dict()
    payload["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="newer than this build"):
        report_from_dict(payload)


def test_an_older_schema_loads_with_defaults() -> None:
    payload = _medium_report().to_dict()
    del payload["schema_version"]
    del payload["warnings"]
    restored = report_from_dict(payload)
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.warnings == []


# --- locating a report --------------------------------------------------------------


def test_an_explicit_file_path_wins(tmp_path: Path) -> None:
    path = _write(tmp_path / "custom" / "report.json", _medium_report())
    assert find_report(str(path), tmp_path / "reports") == path


def test_a_directory_resolves_to_its_report_json(tmp_path: Path) -> None:
    path = _write(tmp_path / "reports" / "run" / "report.json", _medium_report())
    assert find_report(str(path.parent), tmp_path / "reports") == path


def test_a_run_id_prefix_matches(tmp_path: Path) -> None:
    path = _write(tmp_path / "reports" / "2026-11-13-soil-01GATE" / "report.json",
                  _medium_report())
    assert find_report("01GATE", tmp_path / "reports") == path


def test_no_target_picks_the_newest_report(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    older = _write(reports / "old" / "report.json", _medium_report())
    newer = _write(reports / "new" / "report.json", _medium_report())
    past = time.time() - 1000
    import os

    os.utime(older, (past, past))
    assert find_report(None, reports) == newer


def test_a_missing_reports_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(LintError, match="does not exist"):
        find_report(None, tmp_path / "nowhere")


def test_an_empty_reports_directory_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    with pytest.raises(LintError, match="no report.json"):
        find_report(None, tmp_path / "reports")


def test_an_unmatched_target_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    with pytest.raises(LintError, match="no report matches"):
        find_report("nope", tmp_path / "reports")


def test_invalid_json_is_reported_not_raised_raw(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LintError, match="not valid JSON"):
        load_report(path)


def test_a_json_array_is_not_a_report(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(LintError, match="does not contain a report object"):
        load_report(path)


def test_a_report_missing_required_fields_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"profile": "medium"}), encoding="utf-8")
    with pytest.raises(LintError, match="not a readable report"):
        load_report(path)


# --- lint verdicts ------------------------------------------------------------------


def test_a_conforming_report_passes(tmp_path: Path) -> None:
    outcome = lint_path(_write(tmp_path / "report.json", _medium_report()))
    assert outcome.ok
    assert outcome.violations == []
    assert outcome.report.profile == "medium"


def test_a_word_band_violation_is_named(tmp_path: Path) -> None:
    outcome = lint_path(_write(tmp_path / "report.json", _medium_report(words=50)))
    assert not outcome.ok
    assert {violation["check"] for violation in outcome.violations} == {"band"}


def test_a_source_floor_violation_is_named(tmp_path: Path) -> None:
    outcome = lint_path(_write(tmp_path / "report.json", _medium_report(sources=3)))
    assert not outcome.ok
    assert {violation["check"] for violation in outcome.violations} == {"sources"}


def test_lint_never_mutates_the_report(tmp_path: Path) -> None:
    path = _write(tmp_path / "report.json", _medium_report())
    before = path.read_bytes()
    lint_path(path)
    assert path.read_bytes() == before
