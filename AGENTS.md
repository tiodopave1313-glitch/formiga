# AGENTS.md

## Repository state

Phase **F0 (foundation)** of the roadmap in `docs/PRD.md` is implemented. The package builds,
the CLI runs, and the suite is green. Later phases are registered as *deferred* commands that
fail loudly instead of pretending to work.

`docs/PRD.md` (v5.3) is the single source of truth. Read the sections relevant to your task
before writing code: §13 (rules), §9 (stack/layout), §11 (roadmap + acceptance), and the spec
section for the feature. Scope changes require editing the PRD or writing an ADR — never
silent drift. `prd.md` at the repo root is the same document; keep the copy in sync if you
edit one.

## Commands

- Setup: `uv sync`
- Test: `uv run pytest` — single test: `uv run pytest tests/unit/test_file.py::test_name`
- Lint: `uv run ruff check .` (and `uv run ruff format --check .`)
- CLI: `uv run formiga ...` / installed as `formiga-cli`
- Phase gate (PRD §13 rule 20): tests, `formiga doctor --probe`, `formiga bench`,
  `formiga lint` on eval runs, update `docs/`

`formiga serve` launches one `llama-server` per configured tier from `layout.*.model_path`
(a `--dry-run` flag prints the command). It never downloads weights and never guesses a
path: a tier without `model_path` is reported, not started. `FORMIGA_LLAMA_SERVER` points
at a binary outside `PATH`.

`formiga lint [target]` reads a persisted `report.json` (file, run directory, run-id
substring, or the newest report) and applies `research.contract.lint`. It is free: no
model, no network, and it never mutates the report.

Do not invent alternate tooling (no Poetry, no pip-tools, no `unittest`, no black). Tests
never touch the network and never call a real model: `formiga.llm.fake.FakeLLM` is the backend
for every test, and `tests/unit/test_docs.py` fails if the F0 paperwork disappears.

## Architecture (PRD §9)

`src/formiga/` layers: `cli.py` / `config.py` / `runtime.py` → `core/` (router, chat, modes,
intents, budget, citations, compaction, prompts, doctor, init, bench, serve, lint) → `llm/` (client,
schema, grammar, coerce, cache, governed, router, fake) → `research/` (contract, report) →
`storage/` (db, migrations, idempotency, lock) → `ui/` (Ui, repl). Packaged data lives in
`src/formiga/data/` (`prompts/en`, `templates`, `skills`, `i18n/locales`) and must load via
`importlib.resources`. User state: `~/.formiga/`, then `./.formiga.toml`, then `FORMIGA_*`.
Linux only.

Pipeline is extractive-first: stages return ids (sentence ranges, note ids, intents); code
computes quotes, offsets, pages, dates, numbers, citations, tables and section order. Reports
are `report.json` → deterministic renderer; the LLM never emits Markdown.

## Rules that are easy to break

- `docs/PRD.md` §13 is binding. Read it in full; these are the ones agents most often violate:
  - All code, identifiers, comments, logs, schema, commits and repo docs in **English**. UI
    strings only through `t()`; prompts are English-only.
  - Implement **one roadmap phase at a time** (F0 → F5). No F4/F5 features early. A deferred
    command must refuse with `error.not_implemented`, never half-work.
  - New dependency or new scope requires an ADR. Prefer stdlib; tests mock the LLM and never
    touch the network.
  - No document library, ingestion pipeline, embeddings or vector index.
  - Pipeline stages expose **no tools**; grammar-constrained JSON only.
  - Extraction returns ids, never generated text; only contiguous ranges are valid. Full page
    text never enters orchestrator context.
  - Every LLM call goes through budget governor + role router + cache. A cache hit still
    charges one call.
  - Every feature must work with a single endpoint (`single` layout is the default); `dual` is
    an optimization.
  - The synthesis rung is set by profile × layout × probe, never by the model.
  - A report that fails `formiga lint` / the document contract is a composer/profile bug;
    never relax the profile.
- `quote_original` must stay verbatim in the source language — it is the only field used for
  substring verification.
- Prompt/schema/cache keys include `schema_version`, `grammar_hash`, `rung`,
  `segmenter_version`; do not drop them.
- A pre-v5 `~/.formiga` is **moved aside** (`*.legacy`), never deleted and never half-read.
  That includes a foreign `formiga.db` and its `-wal`/`-shm` siblings. Ownership is decided
  by manifest *shape* (`meta(key, value)`), never by table names.
- `--lang` is a CLI choice and outranks the config file (PRD §9 precedence); the flag is
  threaded through as `language_is_flag` so an unset flag never overrides `language`.
- In `dual`, a dead `strong` tier is a **degradation** (calls fall back to `fast`), not a
  doctor failure. A dead `single` endpoint is a failure, because there is no fallback.
- `bench` reports an unreachable tier instead of raising, and exits **2** (partial) when
  only some tiers were measured. Its prefill probe carries a random nonce
  (`prefill_probe()`); without it the run measures `llama-server`'s prefix cache, which
  once made the same endpoint look 8x faster. Never make it deterministic.
- `docs/benchmarks.md`'s measured estimate table is checked against the formula by
  `tests/unit/test_docs.py`; a hand-edit that disagrees with `estimate_table` fails.

Useful references: `docs/adr/` (16 ADRs listed in PRD §15, indexed in `docs/adr/README.md`),
`docs/benchmarks.md` for measured deadlines and the shipped constants, `docs/uninstall.md` for
the exact data paths, `tests/eval/rubric.md` for the human-scored eval, `tests/fixtures/stages/`
for the per-stage contracts.

## Request budget

The main model is limited to 3 requests per minute. Each round-trip costs ~20 seconds. Your
goal is to finish the task in the fewest steps.

**Always batch**
- Read all the files you need in one message, in parallel. Never read one file, stop, then
  read another.
- Apply all edits for a task in a single message.
- Run verification commands (tests, lint) together at the end, not after each edit.

**Delegate reading**
- Code search, grep, structure mapping: delegate to the `explore` subagent. It runs on another
  model with its own quota, so it is free for you.
- Do not open other subagents.
