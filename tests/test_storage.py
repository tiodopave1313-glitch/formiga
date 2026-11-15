"""Testes de persistência: escrita atômica, diretório existente e checkpoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from formiga.models import (
    Priority,
    Question,
    QuestionStatus,
    ResearchContract,
    ResearchState,
)
from formiga.storage import (
    OutputDirExists,
    append_event,
    load_state,
    prepare_output_dir,
    save_state,
)


def make_state() -> ResearchState:
    return ResearchState(
        contract=ResearchContract(question="Q?", objective="O"),
        questions=[
            Question(
                id="Q1",
                question="Subpergunta?",
                priority=Priority.HIGH,
                sufficiency="Duas fontes concordando.",
                status=QuestionStatus.OPEN,
            )
        ],
    )


def test_prepare_output_dir_creates(tmp_path: Path):
    target = tmp_path / "out"
    assert prepare_output_dir(target) == target
    assert target.is_dir()


def test_refuses_existing_dir_without_permission(tmp_path: Path):
    target = tmp_path / "out"
    target.mkdir()
    with pytest.raises(OutputDirExists):
        prepare_output_dir(target)
    # Com autorização explícita, prossegue.
    prepare_output_dir(target, overwrite=True)


def test_state_roundtrip(tmp_path: Path):
    out = prepare_output_dir(tmp_path / "out")
    state = make_state()
    save_state(out, state)
    loaded = load_state(out)
    assert loaded == state


def test_atomic_write_leaves_valid_checkpoint_on_failure(tmp_path: Path, monkeypatch):
    """Falha simulada durante a gravação não corrompe o checkpoint anterior."""
    out = prepare_output_dir(tmp_path / "out")
    save_state(out, make_state())
    valid = load_state(out)

    # Gravação interrompida: substitui os.replace por uma exceção.
    import os

    def broken_replace(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        save_state(out, make_state())

    # Checkpoint anterior permanece legível; resíduo temporário é tolerável.
    assert load_state(out) == valid


def test_events_jsonl_appends(tmp_path: Path):
    out = prepare_output_dir(tmp_path / "out")
    append_event(out, "round_started", {"round": 1})
    append_event(out, "search", {"query": "teste"})
    lines = (out / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "round_started"
    assert "ts" in first
