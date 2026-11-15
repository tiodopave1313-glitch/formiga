"""Testes da verificação determinística de evidências (RF-06)."""

from __future__ import annotations

from pathlib import Path

from formiga.evidence import (
    load_page_text,
    save_page_text,
    verify_quote_literal,
)
from formiga.models import (
    Evidence,
    ExtractionStatus,
    Locator,
    Priority,
    Question,
    ResearchContract,
    ResearchState,
    Source,
)


def make_state() -> ResearchState:
    state = ResearchState(contract=ResearchContract(question="Q", objective="O"))
    state.sources.append(
        Source(
            id="S1",
            requested_url="https://example.com/a",
            extraction_status=ExtractionStatus.SUCCESS,
            text_hash="abc",
        )
    )
    state.questions.append(
        Question(
            id="Q1",
            question="sub",
            priority=Priority.HIGH,
            sufficiency="s",
        )
    )
    return state


PAGE_TEXT = (
    "A busca lexical exige correspondência exata de termos e falha com "
    "sinônimos em consultas que usam vocabulário diverso do documento."
)


def make_evidence(locator: Locator | None = None) -> Evidence:
    return Evidence(
        id="E1",
        source_id="S1",
        quote="correspondência exata de termos",
        locator=locator or Locator(chunk_index=0, char_start=0, char_end=len(PAGE_TEXT)),
        content_hash="abc",
        question_ids=["Q1"],
    )


def test_valid_evidence_passes(tmp_path: Path):
    out = tmp_path / "out"
    save_page_text(out, "S1", PAGE_TEXT)
    state = make_state()
    assert verify_quote_literal(state, out, make_evidence()) is None
    assert load_page_text(out, "S1") == PAGE_TEXT


def test_missing_source_text_fails(tmp_path: Path):
    state = make_state()
    problem = verify_quote_literal(state, tmp_path / "out", make_evidence())
    assert problem is not None and "não está armazenado" in problem


def test_quote_not_literal_fails(tmp_path: Path):
    out = tmp_path / "out"
    save_page_text(out, "S1", PAGE_TEXT)
    evidence = make_evidence()
    evidence.quote = "a busca lexical é rápida e perfeita"
    problem = verify_quote_literal(make_state(), out, evidence)
    assert problem is not None and "não aparece" in problem


def test_invalid_locator_fails(tmp_path: Path):
    out = tmp_path / "out"
    save_page_text(out, "S1", PAGE_TEXT)
    evidence = make_evidence(Locator(chunk_index=0, char_start=0, char_end=10))
    problem = verify_quote_literal(make_state(), out, evidence)
    assert problem is not None and "Localizador" in problem


def test_non_successful_extraction_fails(tmp_path: Path):
    out = tmp_path / "out"
    save_page_text(out, "S1", PAGE_TEXT)
    state = make_state()
    state.sources[0].extraction_status = ExtractionStatus.FAILED
    problem = verify_quote_literal(state, out, make_evidence())
    assert problem is not None and "extração" in problem


def test_nonexistent_source_fails(tmp_path: Path):
    out = tmp_path / "out"
    save_page_text(out, "S1", PAGE_TEXT)
    state = make_state()
    evidence = make_evidence()
    evidence.source_id = "S99"
    problem = verify_quote_literal(state, out, evidence)
    assert problem is not None and "inexistente" in problem


def test_whitespace_variation_passes(tmp_path: Path):
    out = tmp_path / "out"
    save_page_text(out, "S1", "trecho   com\nespaços  estranhos e fim")
    evidence = Evidence(
        id="E1",
        source_id="S1",
        quote="trecho com espaços estranhos",
        locator=Locator(chunk_index=0, char_start=0, char_end=35),
        content_hash="abc",
    )
    state = ResearchState(contract=ResearchContract(question="Q", objective="O"))
    state.sources.append(
        Source(
            id="S1",
            requested_url="https://example.com/a",
            extraction_status=ExtractionStatus.SUCCESS,
        )
    )
    assert verify_quote_literal(state, out, evidence) is None
