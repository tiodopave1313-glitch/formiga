"""Persistência local: `state.json` atômico, `events.jsonl` e `report.md`.

Uma interrupção não deve corromper um checkpoint já salvo: `state.json`
é gravado em arquivo temporário no mesmo diretório e movido com `os.replace`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from formiga.models import ResearchState, utc_now

STATE_FILENAME = "state.json"
EVENTS_FILENAME = "events.jsonl"
REPORT_FILENAME = "report.md"


class StorageError(Exception):
    """Falha de persistência ou uso indevido do diretório de saída."""


class OutputDirExists(StorageError):
    """O diretório de saída já existe e não houve autorização para sobrescrever."""


def prepare_output_dir(path: Path, overwrite: bool = False) -> Path:
    """Cria o diretório de saída; recusa sobrescrever sem autorização explícita."""
    if path.exists():
        if not overwrite:
            raise OutputDirExists(
                f"Diretório de saída já existe: {path}. "
                "Remova-o ou use --overwrite para autorizar a sobrescrita."
            )
        if not path.is_dir():
            raise StorageError(f"O caminho de saída existe e não é um diretório: {path}.")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def state_path(output_dir: Path) -> Path:
    return output_dir / STATE_FILENAME


def events_path(output_dir: Path) -> Path:
    return output_dir / EVENTS_FILENAME


def report_path(output_dir: Path) -> Path:
    return output_dir / REPORT_FILENAME


def save_state(output_dir: Path, state: ResearchState) -> None:
    payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2)
    _atomic_write(state_path(output_dir), payload.encode("utf-8"))


def append_event(output_dir: Path, event_type: str, data: dict[str, Any] | None = None) -> None:
    event = {"ts": utc_now(), "type": event_type, "data": data or {}}
    line = json.dumps(event, ensure_ascii=False)
    with open(events_path(output_dir), "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def save_report(output_dir: Path, report: str) -> Path:
    target = report_path(output_dir)
    _atomic_write(target, report.encode("utf-8"))
    return target


def load_state(output_dir: Path) -> ResearchState:
    """Carrega um checkpoint para inspeção (execuções não são retomáveis no MVP)."""
    path = state_path(output_dir)
    if not path.exists():
        raise StorageError(f"Checkpoint não encontrado: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"Checkpoint corrompido: {path}") from exc
    return ResearchState.model_validate(raw)
