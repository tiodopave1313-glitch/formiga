"""F0 paperwork is part of the deliverable, so it is checked like code.

The PRD names sixteen ADRs for F0 and three documents that a user must be able to find
without reading the source. A missing one is a phase-gate failure, not a documentation nit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
ADR_DIR = DOCS / "adr"

REQUIRED_ADRS = (
    "001-deterministic-pipeline",
    "002-grammar-over-tool-calling",
    "003-mandatory-lexical-selection",
    "004-report-json-and-rendering",
    "005-budget-and-idempotency",
    "006-english-code-i18n-ui",
    "007-tool-and-skill-registries",
    "008-web-fetch-safety",
    "009-retention-and-privacy",
    "010-extractive-first-pipeline",
    "011-role-based-model-routing",
    "012-capability-probes",
    "013-single-model-parity",
    "014-document-contract-and-length-profiles",
    "015-synthesis-ladder-and-lexical-support",
    "016-source-independence-and-near-dup",
)

#: The four headings every ADR must carry, so a decision is always readable the same way.
ADR_SECTIONS = ("## Context", "## Decision", "## Consequences", "## Alternatives considered")


def test_every_required_adr_exists() -> None:
    missing = [name for name in REQUIRED_ADRS if not (ADR_DIR / f"{name}.md").is_file()]
    assert not missing, f"missing ADRs: {missing}"


@pytest.mark.parametrize("name", REQUIRED_ADRS)
def test_adr_has_the_standard_sections(name: str) -> None:
    text = (ADR_DIR / f"{name}.md").read_text(encoding="utf-8")
    for heading in ADR_SECTIONS:
        assert heading in text, f"{name} is missing {heading!r}"
    assert text.startswith("# "), "an ADR starts with a level-1 title"
    assert "**Status:**" in text


@pytest.mark.parametrize("name", REQUIRED_ADRS)
def test_adr_number_matches_its_filename(name: str) -> None:
    text = (ADR_DIR / f"{name}.md").read_text(encoding="utf-8")
    title = text.splitlines()[0]
    number = name.split("-", 1)[0]
    assert number in title, f"{name}: title does not carry its number"


def test_the_adr_index_links_every_adr() -> None:
    index = (ADR_DIR / "README.md").read_text(encoding="utf-8")
    for name in REQUIRED_ADRS:
        assert f"({name}.md)" in index, f"index does not link {name}"


def test_adr_numbers_are_unique_and_contiguous() -> None:
    numbers = sorted(
        int(match.group(1))
        for path in ADR_DIR.glob("[0-9][0-9][0-9]-*.md")
        if (match := re.match(r"(\d{3})-", path.name))
    )
    assert numbers == list(range(1, len(numbers) + 1))


@pytest.mark.parametrize("name", ["benchmarks.md", "uninstall.md", "PRD.md"])
def test_user_facing_documents_exist(name: str) -> None:
    assert (DOCS / name).is_file()


def test_uninstall_lists_every_store_the_code_writes() -> None:
    text = (DOCS / "uninstall.md").read_text(encoding="utf-8")
    for entry in (
        "~/.formiga/config.toml",
        "~/.formiga/formiga.db",
        "~/.formiga/cache/",
        "~/.formiga/runs/",
        "~/.formiga/logs/",
        "~/.formiga/skills/",
        "~/.formiga/memory.md",
        "~/formiga/reports/",
    ):
        assert entry in text, f"uninstall.md does not document {entry}"


def test_benchmarks_document_records_the_shipped_constants() -> None:
    text = (DOCS / "benchmarks.md").read_text(encoding="utf-8")
    for constant in ("CALL_OVERHEAD_S", "OVERHEAD_FACTOR", "FETCH_SECONDS"):
        assert constant in text
    assert "1.90" in text
    assert "1.15" in text


def test_benchmark_constants_match_the_documentation() -> None:
    """The docs and the code must not drift: a deadline depends on these numbers."""
    from formiga.core.bench import CALL_OVERHEAD_S, FETCH_SECONDS, OVERHEAD_FACTOR

    text = (DOCS / "benchmarks.md").read_text(encoding="utf-8")
    assert f"{CALL_OVERHEAD_S:.2f}" in text
    for layout, factor in OVERHEAD_FACTOR.items():
        assert f"{factor:.2f}" in text, f"{layout} factor is undocumented"
    for profile, seconds in FETCH_SECONDS.items():
        assert f"{seconds} s" in text, f"{profile} fetch time is undocumented"


def test_rubric_defines_every_axis_and_the_source_zero_rule() -> None:
    text = (ROOT / "tests" / "eval" / "rubric.md").read_text(encoding="utf-8")
    for axis in ("Correctness", "Source use", "Integration", "Gap honesty", "Readability",
                 "Length fit"):
        assert axis in text
    collapsed = " ".join(text.split())
    assert "no zero on *Source use*" in collapsed
