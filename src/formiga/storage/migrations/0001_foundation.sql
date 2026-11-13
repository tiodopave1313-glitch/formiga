-- F0 foundation schema (PRD §6.4).
-- Applied migrations are never rewritten; later phases append numbered files.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    title           TEXT,
    language        TEXT NOT NULL DEFAULT 'en',
    output_language TEXT NOT NULL DEFAULT 'en'
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content    TEXT NOT NULL DEFAULT '',
    intent     TEXT,
    run_id     TEXT,
    note_ids   TEXT,
    token_count INTEGER NOT NULL DEFAULT 0,
    compacted  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS runs (
    id                TEXT PRIMARY KEY,
    session_id        TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    question          TEXT NOT NULL,
    mode              TEXT NOT NULL DEFAULT 'research',
    profile           TEXT NOT NULL DEFAULT 'medium',
    layout            TEXT NOT NULL DEFAULT 'single',
    prompt_version    TEXT NOT NULL DEFAULT '0',
    segmenter_version TEXT NOT NULL DEFAULT '1',
    status            TEXT NOT NULL DEFAULT 'pending',
    deadline_s        REAL,
    pid               INTEGER,
    report_path       TEXT,
    llm_calls         INTEGER NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    output_tokens     INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, updated_at);

CREATE TABLE IF NOT EXISTS stage_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage       TEXT NOT NULL,
    unit        TEXT NOT NULL DEFAULT '',
    input_hash  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    tier        TEXT,
    prompt_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    duration_s  REAL NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    UNIQUE (run_id, stage, unit)
);

CREATE TABLE IF NOT EXISTS sources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT NOT NULL,
    normalized_url TEXT NOT NULL UNIQUE,
    domain         TEXT NOT NULL DEFAULT '',
    content_hash   TEXT,
    cache_path     TEXT,
    quality        REAL NOT NULL DEFAULT 0.5,
    status         TEXT NOT NULL DEFAULT 'new',
    aliases        TEXT NOT NULL DEFAULT '[]',
    title          TEXT,
    published      TEXT,
    accessed_at    TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);

CREATE TABLE IF NOT EXISTS run_sources (
    run_id    TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    n         INTEGER NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, n)
);

CREATE TABLE IF NOT EXISTS segments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    idx        INTEGER NOT NULL,
    text       TEXT NOT NULL,
    start_char INTEGER NOT NULL,
    end_char   INTEGER NOT NULL,
    page       INTEGER,
    UNIQUE (source_id, idx)
);

CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text,
    content='segments',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS notes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    run_id         TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    facet          TEXT NOT NULL,
    verdict        TEXT NOT NULL,
    stance         TEXT,
    segment_ranges TEXT NOT NULL,
    quote          TEXT NOT NULL,
    numbers        TEXT NOT NULL DEFAULT '[]',
    offsets        TEXT NOT NULL DEFAULT '[]',
    locator        TEXT NOT NULL DEFAULT '{}',
    derived_by     TEXT NOT NULL DEFAULT 'code',
    commit_key     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (run_id, source_id, facet, commit_key)
);

CREATE INDEX IF NOT EXISTS idx_notes_run ON notes(run_id, facet);

CREATE TABLE IF NOT EXISTS claims (
    id             TEXT NOT NULL,
    run_id         TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    section_id     TEXT NOT NULL,
    text           TEXT NOT NULL,
    rung           TEXT NOT NULL,
    flags          TEXT NOT NULL DEFAULT '[]',
    critical       INTEGER NOT NULL DEFAULT 0,
    overlap        REAL NOT NULL DEFAULT 1.0,
    lexical_support REAL NOT NULL DEFAULT 1.0,
    derivation     TEXT,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS citations (
    claim_id  TEXT NOT NULL,
    run_id    TEXT NOT NULL,
    note_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    n         INTEGER NOT NULL,
    PRIMARY KEY (run_id, claim_id, note_id, n),
    FOREIGN KEY (run_id, claim_id) REFERENCES claims(run_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash   TEXT PRIMARY KEY,
    model         TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '3',
    grammar_hash  TEXT NOT NULL DEFAULT '',
    rung          TEXT NOT NULL DEFAULT '',
    response      TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
