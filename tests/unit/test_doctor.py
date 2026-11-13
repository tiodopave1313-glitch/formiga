"""``formiga doctor``: must pass offline, must fail on a foreign database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from formiga.config import load_settings
from formiga.core.doctor import (
    MIN_PYTHON,
    diagnostics,
    run_doctor,
    suggested_layout,
    total_ram_gb,
)
from formiga.core.init import init_home
from formiga.research.report import RUNG_ORDER


@pytest.fixture
def ready(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    init_home(home=home, layout="single", ram_gb=8.0)
    return home


def _settings(home: Path, **env: str):
    return load_settings(home=home, environ=env)


def test_doctor_passes_offline(ready: Path) -> None:
    report = run_doctor(_settings(ready))
    assert report.ok, [check.as_dict() for check in report.failures]
    assert report.failures == []


def test_endpoints_are_skipped_without_probe(ready: Path) -> None:
    report = run_doctor(_settings(ready))
    endpoint_checks = [check for check in report.checks if "endpoint" in check.name.lower()]
    assert endpoint_checks
    assert all(check.skipped for check in endpoint_checks)
    assert all(check.ok for check in endpoint_checks)


def test_probe_reports_an_unreachable_endpoint_as_a_failure(ready: Path) -> None:
    settings = _settings(ready, FORMIGA_ENDPOINT="http://127.0.0.1:9", FORMIGA_LAYOUT="single")
    report = run_doctor(settings, probe_endpoints=True)
    assert not report.ok
    assert any("unreachable" in check.detail for check in report.failures)


def test_a_foreign_database_is_reported_not_repaired(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    init_home(home=home, layout="single", ram_gb=8.0)
    database = home / "formiga.db"
    database.unlink()
    alien = sqlite3.connect(database)
    alien.executescript("CREATE TABLE corpus_docs (id INTEGER PRIMARY KEY);")
    alien.commit()
    alien.close()

    report = run_doctor(_settings(home))
    assert not report.ok
    assert any("corpus_docs" in check.detail for check in report.failures)


def test_schema_version_is_reported(ready: Path) -> None:
    report = run_doctor(_settings(ready))
    schema = next(check for check in report.checks if check.name == "Schema version")
    assert schema.ok
    assert schema.detail.startswith("v")


def test_fts5_is_reported_as_available(ready: Path) -> None:
    report = run_doctor(_settings(ready))
    fts = next(check for check in report.checks if "FTS5" in check.name)
    assert fts.ok
    assert "bm25" in fts.detail


def test_permitted_profiles_follow_the_layout(ready: Path) -> None:
    report = run_doctor(_settings(ready))
    assert report.profiles == ("short", "medium")


def test_rungs_are_capped_by_the_layout_ceiling(ready: Path) -> None:
    report = run_doctor(_settings(ready))
    assert report.rungs == tuple(RUNG_ORDER[: RUNG_ORDER.index("bounded-edit") + 1])
    assert "anchored-rewrite" not in report.rungs


def test_python_floor_matches_the_packaging_metadata() -> None:
    from formiga.core.doctor import _check_python

    assert _check_python().ok
    assert MIN_PYTHON == (3, 11)


def test_suggested_layout_prefers_single_on_small_machines() -> None:
    assert suggested_layout(None) == "single"
    assert suggested_layout(8.0) == "single"
    assert suggested_layout(16.0) == "dual"


def test_ram_detection_returns_a_plausible_number() -> None:
    ram = total_ram_gb()
    assert ram is None or ram > 0


def test_report_is_json_ready(ready: Path) -> None:
    payload = run_doctor(_settings(ready)).as_dict()
    assert payload["ok"] is True
    assert isinstance(payload["checks"], list)
    assert payload["profiles"] == ["short", "medium"]


def test_diagnostics_are_recorded_for_the_frontmatter(ready: Path) -> None:
    payload = diagnostics(_settings(ready))
    assert payload["layout"] == "single"
    assert payload["layout_known"] is True
    assert "prompt_version" in payload
    assert "segmenter_version" in payload


def test_a_dead_strong_tier_degrades_instead_of_failing(ready: Path) -> None:
    """PRD §8.2: in ``dual`` a down strong endpoint falls back; it is not fatal."""
    settings = load_settings(
        home=ready,
        environ={
            "FORMIGA_LAYOUT": "dual",
            "FORMIGA_ENDPOINT": "http://127.0.0.1:8080",
            "FORMIGA_STRONG_ENDPOINT": "http://127.0.0.1:9",
        },
    )
    report = run_doctor(settings, probe_endpoints=True)
    strong = next(check for check in report.checks if check.name.endswith("strong"))
    assert strong.skipped
    assert "fall back to the fast tier" in strong.detail


def test_a_dead_single_layout_endpoint_is_a_failure(ready: Path) -> None:
    """``single`` has no fallback, so the only endpoint being down must fail."""
    settings = load_settings(
        home=ready,
        environ={"FORMIGA_LAYOUT": "single", "FORMIGA_ENDPOINT": "http://127.0.0.1:9"},
    )
    report = run_doctor(settings, probe_endpoints=True)
    assert not report.ok
    assert any("unreachable" in check.detail for check in report.failures)
