"""Índice de memória de sessão (FTS5) — Fase 8 do PRD v2.

Índice SQLite+FTS5 em `~/.formiga/index.db` sobre o `messages.json` de
todas as sessões, com atualização incremental por mtime.

Não depende de nada do `agent/` núcleo. O cálculo de relevância usa `bm25`
do FTS5 quando disponível; senão, fallback `LIKE`.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Callable
from pathlib import Path

# Índice global da memória (Fase 8).
DEFAULT_INDEX_PATH = Path.home() / ".formiga" / "index.db"

# Tamanho máximo do trecho devolvido pelo recall (chars).
SNIPPET_CHARS = 400


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class MemoryIndex:
    """Índice FTS5 (ou LIKE como fallback) de conteúdos de sessão."""

    def __init__(
        self,
        db_path: Path | None = None,
        now_fn: Callable[[], str] = _now_iso,
    ) -> None:
        self.db_path = db_path or DEFAULT_INDEX_PATH
        self.now_fn = now_fn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        self._fts5 = self._supports_fts5()

    # -- schema ---------------------------------------------------------- #

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session TEXT NOT NULL,
                ts TEXT NOT NULL,
                path TEXT NOT NULL,
                text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_docs_session ON docs(session);
            """
        )
        self._conn.commit()

    def _supports_fts5(self) -> bool:
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5("
                "session, ts, path, text, content='docs', content_rowid=id)"
            )
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN "
                "INSERT INTO docs_fts(rowid, session, ts, path, text) "
                "VALUES (new.id, new.session, new.ts, new.path, new.text); END"
            )
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN "
                "INSERT INTO docs_fts(docs_fts, rowid, session, ts, path, text) "
                "VALUES ('delete', old.id, old.session, old.ts, old.path, old.text); END"
            )
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN "
                "INSERT INTO docs_fts(docs_fts, rowid, session, ts, path, text) "
                "VALUES ('delete', old.id, old.session, old.ts, old.path, old.text); "
                "INSERT INTO docs_fts(rowid, session, ts, path, text) "
                "VALUES (new.id, new.session, new.ts, new.path, new.text); END"
            )
            self._conn.commit()
            return True
        except sqlite3.DatabaseError:
            return False

    # -- indexação ------------------------------------------------------- #

    def _meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def _index_file(self, session: str, path: Path, ts: str) -> None:
        """Indexa (ou reindexa) um arquivo de uma sessão."""
        # Remove entradas antigas desse arquivo antes de reindexar.
        self._conn.execute(
            "DELETE FROM docs WHERE session = ? AND path = ?", (session, str(path))
        )
        if self._fts5:
            self._conn.execute(
                "DELETE FROM docs_fts WHERE rowid IN "
                "(SELECT id FROM docs WHERE session = ? AND path = ?)",
                (session, str(path)),
            )
        text = _read_text(path)
        if not text.strip():
            self._conn.commit()
            return
        self._conn.execute(
            "INSERT INTO docs(session, ts, path, text) VALUES (?, ?, ?, ?)",
            (session, ts, str(path), text),
        )
        self._conn.commit()

    def index_session(self, session_dir: Path) -> None:
        """Indexa `messages.json` de uma sessão."""
        if not session_dir.is_dir():
            return
        session = session_dir.name
        mtime = session_dir.stat().st_mtime
        ts = self.now_fn()
        self._index_file(session, session_dir / "messages.json", ts)
        # Marca a sessão como indexada até este mtime.
        prev = self._meta(f"session:{session}")
        if prev is None or float(prev) < mtime:
            self._set_meta(f"session:{session}", str(mtime))

    def index_sessions(self, base_dir: Path) -> None:
        """Varre `sessoes/*/` de `base_dir`, indexando só o que mudou.

        Incremental por mtime: sessões já indexadas com mtime igual são
        ignoradas; novas ou alteradas são (re)indexadas.
        """
        sessoes_dir = base_dir / "sessoes"
        if not sessoes_dir.is_dir():
            return
        for entry in sorted(sessoes_dir.iterdir()):
            if not entry.is_dir():
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            prev = self._meta(f"session:{entry.name}")
            if prev is not None and float(prev) >= mtime:
                continue  # já indexada, sem alteração
            self.index_session(entry)

    # -- busca ----------------------------------------------------------- #

    def recall(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        """Busca trechos relevantes de sessões passadas.

        Devolve lista de dicts com `session`, `ts`, `path`, `text` (trecho
        truncado) e `score` (relevância; menor bm25 = mais relevante).
        """
        limit = max(1, min(int(limit), 50))
        query = query.strip()
        if not query:
            return []

        resultados: list[dict[str, object]] = []
        if self._fts5:
            # Múltiplos termos -> OR (qualquer termo casa), não frase exata.
            termos = [t for t in query.split() if t]
            fts_query = " OR ".join(_fts_escape(t) for t in termos)
            rows = self._conn.execute(
                """
                SELECT d.session, d.ts, d.path, d.text, bm25(docs_fts) AS score
                FROM docs_fts
                JOIN docs d ON d.id = docs_fts.rowid
                WHERE docs_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            for session, ts, path, text, score in rows:
                resultados.append(
                    {
                        "session": session,
                        "ts": ts,
                        "path": path,
                        "text": _snippet(text, query),
                        "score": round(float(score), 4),
                    }
                )
        else:
            # Fallback LIKE: busca termos separados por espaço (OR).
            termos = [t for t in query.split() if t]
            like_clauses = " OR ".join("text LIKE ?" for _ in termos)
            params = [f"%{t}%" for t in termos]
            rows = self._conn.execute(
                f"SELECT session, ts, path, text FROM docs WHERE {like_clauses} LIMIT ?",
                (*params, limit),
            ).fetchall()
            for session, ts, path, text in rows:
                resultados.append(
                    {
                        "session": session,
                        "ts": ts,
                        "path": path,
                        "text": _snippet(text, query),
                        "score": None,
                    }
                )
        return resultados

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()


def _fts_escape(termo: str) -> str:
    """Escapa um termo para consulta FTS5 (envolve em aspas duplas)."""
    return '"' + termo.replace('"', '""') + '"'


def _snippet(text: str, query: str, chars: int = SNIPPET_CHARS) -> str:
    """Devolve um trecho de `text` centrado no primeiro termo de `query`."""
    termos = [t.lower() for t in query.split() if t]
    idx = -1
    for termo in termos:
        idx = text.lower().find(termo)
        if idx != -1:
            break
    if idx == -1:
        return text[:chars]
    inicio = max(0, idx - chars // 2)
    fim = min(len(text), idx + chars // 2)
    trecho = text[inicio:fim].replace("\n", " ").strip()
    if inicio > 0:
        trecho = "... " + trecho
    if fim < len(text):
        trecho = trecho + " ..."
    return trecho[:chars]


def index_path(base_dir: Path | str, db_path: Path | None = None) -> MemoryIndex:
    """Constrói um `MemoryIndex` e indexa todas as sessões de `base_dir`."""
    idx = MemoryIndex(db_path=db_path)
    idx.index_sessions(Path(base_dir))
    return idx
