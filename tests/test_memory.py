"""Testes da Fase 8 — Memória estilo Hermes (PRD §13).

Cobre o aceite da §13.2/§13.3/§13.4:
- recall encontra fato de sessão antiga (FTS5).
- nudge aparece no fim de sessão (session_end) com sugestões pendentes.
- memory_save apenas stageia (não grava MEMORY.md sem /memory save).
- USER.md aparece como seção do prompt via before_agent_start.
- MEMORY.md corrompido gera aviso e não derruba a sessão.
- teto de tokens de memória respeitado (truncamento determinístico).
- entrada com formato inválido e credencial são recusadas.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import formiga.ext.memory.memory as mem_mod
from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.session import Session
from formiga.config import Config
from formiga.ext.memory.index import MemoryIndex

# ---------------------------------------------------------------------- #
# Helpers                                                                #
# ---------------------------------------------------------------------- #


def _monta_sessao(base: Path, session_id: str, transcript: str) -> Path:
    """Cria `base/sessoes/<session_id>/` com messages.json e transcript.md."""
    sdir = base / "sessoes" / session_id
    sdir.mkdir(parents=True)
    (sdir / "messages.json").write_text(
        json.dumps(
            [
                {"role": "user", "content": "qual é a capital do brasil?"},
                {"role": "assistant", "content": "Brasília é a capital."},
            ]
        ),
        encoding="utf-8",
    )
    (sdir / "transcript.md").write_text(transcript, encoding="utf-8")
    return sdir


def _carrega_extensao(base: Path, session_id: str = "sess_001") -> ExtensionRegistry:
    cfg = Config(agent_workdir=base, extensions_enabled=("memory",))
    session = Session(base / "sessoes", session_id=session_id)
    registry = ExtensionRegistry()
    discover_extensions(cfg, session, registry)
    return registry


def _iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------- #
# Fixture de caminhos de memória em tmp_path                               #
# ---------------------------------------------------------------------- #


@pytest.fixture
def memoria_tmp(tmp_path, monkeypatch):
    """Redireciona MEMORY_DIR/MEMORY_PATH/USER_PATH/PENDING_PATH para tmp_path."""
    mem_dir = tmp_path / "memory"
    monkeypatch.setattr(mem_mod, "MEMORY_DIR", mem_dir)
    monkeypatch.setattr(mem_mod, "MEMORY_PATH", mem_dir / "MEMORY.md")
    monkeypatch.setattr(mem_mod, "USER_PATH", mem_dir / "USER.md")
    monkeypatch.setattr(mem_mod, "PENDING_PATH", mem_dir / "pending.json")
    db = tmp_path / "index.db"
    monkeypatch.setattr(mem_mod, "DEFAULT_INDEX_PATH", db)
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


# ---------------------------------------------------------------------- #
# Recall                                                                 #
# ---------------------------------------------------------------------- #


def test_recall_encontra_fato_de_sessao_antiga(tmp_path, memoria_tmp):
    """recall encontra fato indexado de sessão passada."""
    _monta_sessao(tmp_path, "sess_001", "Brasília é a capital do Brasil.")
    registry = _carrega_extensao(tmp_path, "sess_001")
    recall = registry.tools["recall"]
    resultado = recall.execute("capital brasil", limit=5)
    assert "Brasília" in resultado.text or "capital" in resultado.text.lower()


def test_recall_sem_resultado_nao_erra(tmp_path, memoria_tmp):
    _monta_sessao(tmp_path, "sess_001", "outro assunto qualquer.")
    registry = _carrega_extensao(tmp_path, "sess_001")
    recall = registry.tools["recall"]
    resultado = recall.execute("inexistente xyz", limit=5)
    assert "nenhum trecho relevante" in resultado.text


# ---------------------------------------------------------------------- #
# memory_save: staging (não grava sem aprovação)                          #
# ---------------------------------------------------------------------- #


def test_memory_save_apenas_staging_nao_grava_memoria(tmp_path, memoria_tmp):
    """memory_save grava pending.json, não MEMORY.md (aprovação humana)."""
    registry = _carrega_extensao(tmp_path, "sess_001")
    save = registry.tools["memory_save"]
    resultado = save.execute(
        categoria="preferência",
        texto="usuário gosta de chá",
        sessao="sess_001",
        data=_iso(),
    )
    assert resultado.ok
    # pendente existe
    pendentes = registry.dispatch_command("memory", "pending")
    assert "gosta de chá" in pendentes
    # MEMORY.md não contém o fato (sem aprovação)
    memoria = (
        mem_mod.MEMORY_PATH.read_text(encoding="utf-8")
        if mem_mod.MEMORY_PATH.exists()
        else ""
    )
    assert "gosta de chá" not in memoria


def test_memory_save_aplica_apos_somente_com_save(tmp_path, memoria_tmp):
    """Só /memory save grava o fato em MEMORY.md."""
    registry = _carrega_extensao(tmp_path, "sess_001")
    save = registry.tools["memory_save"]
    save.execute(
        categoria="preferência",
        texto="usuário gosta de chá",
        sessao="sess_001",
        data=_iso(),
    )
    registry.dispatch_command("memory", "save")
    memoria = mem_mod.MEMORY_PATH.read_text(encoding="utf-8")
    assert "gosta de chá" in memoria
    assert "sessão sess_001" in memoria


# ---------------------------------------------------------------------- #
# Nudge                                                                  #
# ---------------------------------------------------------------------- #


def test_nudge_aparece_no_session_end(tmp_path, memoria_tmp):
    """session_end emite notificação com sugestões pendentes (nudge)."""
    registry = _carrega_extensao(tmp_path, "sess_001")
    save = registry.tools["memory_save"]
    save.execute(
        categoria="preferência",
        texto="usuário gosta de chá",
        sessao="sess_001",
        data=_iso(),
    )
    notificacoes: list[tuple[str, dict]] = []
    registry._event_sink = lambda event, data: notificacoes.append((event, data))
    registry.observe("session_end", {"session": "sess_001", "turns": 3})
    nudges = [n for n in notificacoes if n[0] == "notification"]
    assert any("chá" in n[1]["text"] for n in nudges), nudges


def test_nudge_sem_pendentes_nao_notifica(tmp_path, memoria_tmp):
    registry = _carrega_extensao(tmp_path, "sess_001")
    notificacoes: list[tuple[str, dict]] = []
    registry._event_sink = lambda event, data: notificacoes.append((event, data))
    registry.observe("session_end", {"session": "sess_001", "turns": 3})
    assert not any(n[0] == "notification" for n in notificacoes)


# ---------------------------------------------------------------------- #
# Injeção de seções no prompt (before_agent_start)                        #
# ---------------------------------------------------------------------- #


def test_usuario_aparece_como_secao_no_prompt(tmp_path, memoria_tmp):
    """USER.md é injetada como seção 'Perfil do usuário'."""
    mem_mod.USER_PATH.write_text(
        "## perfil\n- gosta de chá · fonte: sessão s1 · "
        + _iso()
        + "\n",
        encoding="utf-8",
    )
    try:
        registry = _carrega_extensao(tmp_path, "sess_001")
        secoes: dict[str, str] = {}
        secoes = registry.chain("before_agent_start", secoes)
        assert "Perfil do usuário" in secoes
        assert "chá" in secoes["Perfil do usuário"]
    finally:
        mem_mod.USER_PATH.unlink(missing_ok=True)


def test_memoria_aparece_como_secao_com_cabecalho_nao_confiavel(tmp_path, memoria_tmp):
    """MEMORY.md é injetada com cabeçalho de dado não confiável."""
    mem_mod.MEMORY_PATH.write_text(
        "## geral\n- fato antigo · fonte: sessão s0 · " + _iso() + "\n",
        encoding="utf-8",
    )
    try:
        registry = _carrega_extensao(tmp_path, "sess_001")
        secoes: dict[str, str] = {}
        secoes = registry.chain("before_agent_start", secoes)
        assert "Memória" in secoes
        assert "dado não confiável" in secoes["Memória"]
    finally:
        mem_mod.MEMORY_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------- #
# Guardrails                                                             #
# ---------------------------------------------------------------------- #


def test_memoria_corrompida_nao_derruba_sessao(tmp_path, memoria_tmp):
    """MEMORY.md com linhas fora do formato gera aviso e sessão segue."""
    mem_mod.MEMORY_PATH.write_text(
        "linha aleatória sem formato\noutra linha ruim\n", encoding="utf-8"
    )
    try:
        registry = _carrega_extensao(tmp_path, "sess_001")  # não levanta
        secoes: dict[str, str] = {}
        secoes = registry.chain("before_agent_start", secoes)  # sessão segue
        # não deve ter explodido; seções podem vir vazias
    finally:
        mem_mod.MEMORY_PATH.unlink(missing_ok=True)


def test_teto_memoria_respeitado(tmp_path, memoria_tmp):
    """Excesso de memória é truncado determinicamente (não estoura a janela)."""
    linhas = "\n".join(
        f"- fato {i} · fonte: sessão s{i} · {_iso()}" for i in range(200)
    )
    mem_mod.MEMORY_PATH.write_text("## geral\n" + linhas + "\n", encoding="utf-8")
    try:
        registry = _carrega_extensao(tmp_path, "sess_001")
        secoes: dict[str, str] = {}
        secoes = registry.chain("before_agent_start", secoes)
        sec = secoes.get("Memória", "")
        # teto: 1000 tokens * 4 chars = 4000 + cabeçalho; folga razoável
        assert len(sec) < 4500, f"seção muito longa: {len(sec)}"
    finally:
        mem_mod.MEMORY_PATH.unlink(missing_ok=True)


def test_entrada_com_segredo_é_recusada(tmp_path, memoria_tmp):
    """memory_save recusa entrada com possível credencial (guardrail 4)."""
    registry = _carrega_extensao(tmp_path, "sess_001")
    save = registry.tools["memory_save"]
    resultado = save.execute(
        categoria="credenciais",
        texto="api_key = sk-1234567890",
        sessao="sess_001",
        data=_iso(),
    )
    assert resultado.ok is False
    assert "credencial" in resultado.text.lower()
    resposta = registry.dispatch_command("memory", "pending")
    assert "Nenhuma sugestão pendente" in resposta


def test_entrada_formato_invalido_ignorada_na_leitura(tmp_path, memoria_tmp):
    """Linha fora do formato é ignorada com aviso, não derruba."""
    mem_mod.MEMORY_PATH.write_text("## geral\ntexto solto sem formato\n", encoding="utf-8")
    try:
        entradas, avisos = mem_mod._parse_memoria(mem_mod.MEMORY_PATH.read_text(encoding="utf-8"))
        assert entradas == []
        assert avisos  # aviso gerado
    finally:
        mem_mod.MEMORY_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------- #
# Índice FTS5 (reuso direto, já coberto em testes manuais)               #
# ---------------------------------------------------------------------- #


def test_index_incremental_por_mtime(tmp_path, memoria_tmp):
    index = MemoryIndex(db_path=memoria_tmp.parent / "index.db")
    try:
        _monta_sessao(tmp_path, "sess_001", "fato alfa único.")
        index.index_sessions(tmp_path)
        res = index.recall("alfa", limit=5)
        assert any("alfa" in r["text"].lower() for r in res)
        # segunda indexação sem alteração não duplica
        antes = len(index.recall("alfa", limit=50))
        index.index_sessions(tmp_path)
        depois = len(index.recall("alfa", limit=50))
        assert antes == depois
    finally:
        index.close()
