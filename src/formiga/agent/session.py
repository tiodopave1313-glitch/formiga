"""Gerência de sessão do agente: diretório, `messages.json` e `events.jsonl`.

Cada sessão fica em `sessoes/<AAAA-MM-DD_HHMMSS_<id>>/` e é inspecionável mas
não retomável no MVP (igual ao `prd.md`). `messages.json` é salvo atomicamente
a cada turno.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from formiga.storage import StorageError, _atomic_write

_SESSION_RE = re.compile(r"^sessoes/(\d{4}-\d{2}-\d{2}_\d{6})_([0-9a-f]{4})$")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Session:
    """Diretório de sessão com persistência de mensagens e eventos."""

    def __init__(self, base_dir: Path, session_id: str | None = None) -> None:
        self.base_dir = base_dir
        if session_id is None:
            ts = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
            session_id = f"{ts}_{uuid.uuid4().hex[:4]}"
        self.session_id = session_id
        self.dir = base_dir / session_id
        self.dir.mkdir(parents=True, exist_ok=True)

    @property
    def messages_path(self) -> Path:
        return self.dir / "messages.json"

    @property
    def events_path(self) -> Path:
        return self.dir / "events.jsonl"

    @property
    def research_dir(self) -> Path:
        """Diretório `research/` dentro da sessão para saídas de deep_search."""
        return self.dir / "research"

    @property
    def transcript_path(self) -> Path:
        """Transcript legível da sessão (o que a TUI exibe, em Markdown)."""
        return self.dir / "transcript.md"

    def append_transcript(self, text: str) -> None:
        """Anexa um trecho ao transcript.md (append atômico por write).

        Deltas de stream chegam sem quebra de linha e são concatenados;
        eventos (tools, interrupções) incluem a própria quebra de linha.
        """
        with open(self.transcript_path, "a", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

    def save_messages(self, messages: list[dict]) -> None:
        """Salva `messages[]` atomicamente (indented, UTF-8)."""
        payload = json.dumps(messages, ensure_ascii=False, indent=2)
        _atomic_write(self.messages_path, payload.encode("utf-8"))

    def load_messages(self) -> list[dict]:
        if not self.messages_path.exists():
            return []
        try:
            return json.loads(self.messages_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StorageError(f"messages.json corrompido: {self.messages_path}") from exc

    def append_event(self, event_type: str, data: dict | None = None) -> None:
        event = {"ts": utc_now(), "type": event_type, "data": data or {}}
        line = json.dumps(event, ensure_ascii=False)
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    @classmethod
    def list_sessions(cls, base_dir: Path) -> list[Session]:
        sessions: list[Session] = []
        if not base_dir.is_dir():
            return sessions
        for entry in sorted(base_dir.iterdir()):
            if entry.is_dir() and _SESSION_RE.match(f"sessoes/{entry.name}"):
                sessions.append(cls(base_dir, entry.name))
        return sessions
