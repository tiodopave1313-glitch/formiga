"""Testes de sessão do agente."""

from __future__ import annotations

import json
from pathlib import Path

from formiga.agent.session import Session


def test_sessao_cria_dir_e_salva_mensagens(tmp_path: Path):
    base = tmp_path / "sessoes"
    s = Session(base_dir=base)
    assert s.dir.is_dir()
    s.save_messages([{"role": "user", "content": "oi"}])
    msgs = s.load_messages()
    assert msgs == [{"role": "user", "content": "oi"}]
    s.append_event("tool_call", {"tool": "ls", "ok": True})
    assert s.events_path.exists()


def test_sessao_eventos_jsonl(tmp_path: Path):
    s = Session(tmp_path / "sessoes")
    s.append_event("tool_call", {"tool": "ls", "ok": True})
    linha = s.events_path.read_text(encoding="utf-8").strip()
    evento = json.loads(linha)
    assert evento["type"] == "tool_call"
    assert evento["data"]["tool"] == "ls"
