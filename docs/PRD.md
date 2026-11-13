# PRD — Formiga

**Version:** 5.3 · **Status:** ready for incremental implementation · **License:** MIT
**Code, docs and default UI:** English · **i18n:** multilingual-ready from day 1

**Codename:** Formiga (`formiga` command, `formiga-cli` distribution). Small workers foraging sources, bringing everything back to the nest.

> **v5.3 in one line:** the report gets a **contract** — a configurable length profile (`short | medium | long | thesis`) fixes structure, word band, source count and budget; and synthesis becomes a **three-rung ladder** (`assemble → bounded-edit → anchored-rewrite`) chosen per claim and verified by code, so the output can read like an integrated multi-source answer without ever letting a small model invent a fact.
>
> **v5.2 in one line:** the pipeline became **extractive-first** — small models only *choose* (sentence ids, note ids, intent), the code composes and verifies. Same depth of research, roughly half the tokens, and a report laid out like a long-form deep-research answer.

---

## 1. Vision & principles

A minimal, fully local **chat agent for the terminal** that answers questions and, when needed, runs deep multi-source research with verifiable citations — on old hardware, with free models. Built so new tools and skills can be added without touching the core.

**Principles** (tie-breakers for any design doubt):

1. **Small first.** Few dependencies, few tools per role, short prompts. Every context line costs seconds on an old CPU.
2. **State on disk, not in the prompt.** Conversation, plan, sources and notes live in SQLite/files; the model gets only the slice it needs.
3. **Small models choose, the code decides.** Every LLM call is a *selection* from a closed set: an intent, a facet, a sentence id, a claim id. The code performs actions, computes derived fields and assembles text. Applies to the chat loop too (§4.1) — the model picks intent and arguments, the code picks the sequence.
4. **Extractive before abstractive — and abstractive only inside a verified envelope.** Quoted text is chosen, never rewritten. Free rewriting is the last rung of a ladder (`assemble → bounded-edit → anchored-rewrite`, §5.1) that is entered incrementally, per claim, and only while the deterministic guard on that same claim stays clean.
5. **One model must be enough.** Every feature works with a single local model. A second model is an optimization for people who have the RAM, never a requirement.
6. **Budget is law.** Every run has caps on calls, prompt tokens, output tokens and wall-clock. On exhaustion: deliver a marked partial, never hang or crash.
7. **Cite or it doesn't exist.** Every factual claim points to a stored source, note and span. The citation is produced by code from a chosen id, never typed by the model.
8. **Extensible, not sprawling.** Tools and skills are plugins with a declarative registry. The core stays small.
9. **The report is a product, not an artifact.** Its length, structure and citation style are a declared contract (a profile), checked by code on every render. "Minimal" is a measurable band, not a vibe.
10. **Private and polite.** No telemetry, no cloud LLM. Respect `robots.txt`, cache, rate-limit, credit the origin.

---

## 2. Scope

### Goals (MVP)

- Conversational chat agent (REPL + one-shot), multi-turn, with follow-ups that reuse prior research.
- Two research paths: **quick** (interactive) and **deep** (background job, resumable).
- Web search + fetch (HTML and PDF text), source ledger, numbered citations.
- **Report length profiles** (`short | medium | long | thesis`), each fixing structure, word band, source count and budget; the profile is chosen at run time and can be changed on `--rebuild`.
- Structured report persisted as `report.json`, rendered to Markdown by a pure template plus a deterministic composition pass, validated against the **document contract** (§6.3).
- **Synthesis ladder**: `assemble`, `bounded-edit`, `anchored-rewrite` — selected per claim by measured guards, never by preference (§5.1).
- Deterministic verification of citations, quotes, numbers, lexical support and attribution overlap, including attribution overlap.
- Persistent memory across sessions.
- Tool registry and skill loader as documented extension points.
- **Role-based model routing** across one or two local `llama-server` endpoints — one model always works.
- English default; adding a language requires no code change.

### Non-goals (MVP)

GUI; bash/git/code execution (F4); MCP (F5); OCR and PDF layout; **document library, ingestion pipeline, embeddings or vector index**; cloud services; editing files outside the output directory; **macOS and Windows support** (see §9, platform); model training or fine-tuning.

### Success metrics

Measured on target hardware (§8) with the eval set in `tests/eval/` (defined in F0, see §11). The "16 GB" column is the **recommended `dual` layout** (`small` fast tier + `large`/`moe` strong tier); the "8 GB" column is the **extreme-compatibility `single` layout** (one `base`). All other rows hold in both.

| Metric | Target (16 GB) | Target (8 GB) | How measured |
|---|---|---|---|
| Quick research (`short`, 1–3 sources) | ≤ 6 min | ≤ 10 min | `run.budget.duration_s` |
| Deep research (8–16 sources), `medium` | ≤ 30 min | ≤ 50 min | `run.budget.duration_s` |
| Answer from history/cache | ≤ 15 s | ≤ 20 s | Wall-clock |
| Citation coverage (recall) | ≥ 90% | ≥ 90% | `report.citation_coverage` |
| **Citation precision** | **≥ 85%** | **≥ 85%** | `formiga verify` + eval |
| Attribution overlap | ≥ 0.60 mean | ≥ 0.60 mean | always-on check (§7) |
| **Lexical support (rewrite rungs)** | **≥ 0.75 mean** | **≥ 0.75 mean** | always-on check (§7 item 9) |
| **Synthesis ratio** (claims with ≥2 independent sources) | **≥ 0.30** | **≥ 0.25** | `report.synthesis_ratio` |
| **Integrated sections** (≥1 sentence citing ≥2 sources) | 100% | 100% | `formiga lint` |
| **Distinct domains** | ≥ 6 (`medium`), ≥ 10 (`long`) | ≥ 6 (`medium`) | `report.domains` |
| **Document length** | inside profile band ±10% | same | `formiga lint` |
| Valid citations | 100% | 100% | `formiga verify` |
| Literal quotes | 100% found by substring | 100% | `formiga verify` |
| Numeric guard | 0 unsourced numbers | 0 | `formiga verify` |
| Structured output | 0 repairs in ≥100 calls | 0 | `formiga bench` |
| Sentence-id fidelity | ≥ 98% of ids valid | ≥ 98% | `formiga bench` |
| Report readability | ≥ 3.5 / 5 | ≥ 3.0 / 5 | human rubric |
| Agent process RAM | < 1 GB | < 1 GB | peak RSS |
| Resume | no stage redone | same | F2 test |
| i18n | files-only locale | same | CI test |

> Coverage is measured **before** unsupported claims are stripped; measuring after makes the metric trivially 100%. Precision is measured separately — a model that cites everything scores well on coverage and badly on precision.
>
> **Synthesis ratio** is the share of claims (weighted by words) that carry **≥2 independent sources** — distinct registrable domains *and* distinct content hashes *and* MinHash distance ≥ 0.2. It is the measurable definition of "integrated answer" and the reason the ladder in §5.1 exists: an `assemble`-only report can score 0.95 coverage and 3.5 readability while reading like a mosaic. Integrated sections count a sentence with ≥2 citation markers that overlap a claim boundary; `formiga lint` checks it at render time for free.
>
> Time targets are derived from the budget model in §8.4, not aspirational. If `formiga bench` measures slower prefill, the deadlines are recomputed from the formula — never the other way round.
>
> Length targets are per profile (§6.3). `short` and `medium` are the ones in this table; `long` and `thesis` scale the source and section counts and use their own deadline formula in §8.4, because they are deeper research, not longer prose.

---

## 3. Language policy

**Everything written by developers is English:** identifiers, function/variable names, comments, docstrings, log messages, commit messages, DB tables/columns, JSON keys, file and directory names, `README`, `AGENTS.md`, ADRs and this PRD.

**Everything shown to users is translatable:**

| Layer | Mechanism |
|---|---|
| UI strings | `t("key", **kwargs)` reading `src/formiga/data/i18n/locales/en.json`. No hardcoded user-facing literals in `ui/` or CLI error paths. |
| Prompts | `src/formiga/data/prompts/en/*.md`, versioned by `prompt_version`. English only (see below). |
| Config | `language = "en"`, `search_languages = ["en"]`, `output_language = "en"` |
| CLI | `--lang` overrides UI language for one invocation |
| Reports | `output_language` is independent of UI `language` |
| Skills | `SKILL.md` may declare `language`; falls back to English |

Rules:
- Adding a UI language = add `locales/<tag>.json`. **No code change.** This is an acceptance criterion.
- A test scans `ui/` and CLI error paths for user-facing string literals outside the catalog and fails the build. The scan has an explicit allowlist (log calls, exception types, format specifiers) and does not cover `logger.*` messages, which are developer-facing and stay English (§13 rule 2).
- **Prompts are not localized.** Small models degrade outside English and N prompt trees drift. Research language is controlled by `search_languages` (what we search) and `output_language` (what the model is asked to select or write). Translating a prompt file requires an ADR with benchmark evidence.
- **Selection-only stages do not care about language at all.** Since stages 5 and 7 mostly return ids, `output_language` only affects the claim `text` in stage 7 (and only above the `assemble` rung) and the chat answer. This is a large part of why small models work here.
- **`assemble` cannot cross languages.** Verbatim extracts stay in the source language, so an extractive-only report is always in the **dominant source language** (§7 detection), regardless of `output_language`. When they differ, one of three paths is used, in this order:
  1. `output_language` matches the dominant source language → run as normal.
  2. User accepts a bilingual report → headers, TL;DR, gaps and conflicts are generated in `output_language`, quotes stay verbatim in the source language with a `[translated]` excerpt beside them (opt-in `report.bilingual = true`).
  3. Otherwise → the run is upgraded to at least `bounded-edit` (§5.1) for prose sections, which can rewrite inside the guard, and `formiga research` says so up front (`run.language.upgraded`).
  A run never silently emits a report in a language the user did not ask for; `doctor` warns when `output_language ≠ search_languages[0]` and the layout is `single`/`assemble`.
- `quote_original` is always **verbatim in the source language** and is the only field used for substring verification. Translations go in a separate optional field, labelled as free translation. Translating the verification quote would silently break the verifier.
- Dates and numbers are formatted per locale by a **table-driven formatter** (`i18n/format.py`), not the stdlib `locale` module — the latter is global, not thread-safe, and requires OS locales that minimal containers do not ship.
- `pt-BR` is the first additional locale, shipped as the proof that i18n works — not as the default.

---

## 4. The product: a chat agent that researches

### 4.1. Conversation is the core

The chat loop is the product; deep research is its flagship capability, invoked as a tool.

**One routing call per turn, one action per turn.** A small model cannot hold a multi-step ReAct loop together; it can reliably answer a 40-token classification. So:

```
user turn
  → 1 grammar-constrained call (router role, ~70 output tokens)
      {intent, query?, run_id?, section?, entities?, aspects?, profile?}
  → code dispatches deterministically (switch, not a loop)
  → if text is needed: 1 streaming answer call, citations injected by code
```

`intent ∈ {answer, recall, research_quick, research_deep, expand, more_sources, compare, resize, clarify, forget}` — ten values, all listed in the table below.
`profile ∈ {short, medium, long, thesis}` (§6.3); omitted means "keep the session default".

| Intent | Code action |
|---|---|
| `answer` | answer from the model + memory, marked **"no sources"** in the UI |
| `recall` | stage 0 over previous runs/cache; answer from stored notes only |
| `research_quick` | run quick pipeline inline, then answer |
| `research_deep` | ask for confirmation (naming the length profile and cost), start detached job |
| `expand` | re-render one section from existing notes with more detail; no fetch |
| `more_sources` | gap round on the named entity/topic for the current run only |
| `compare` | build a comparison table from stored claims; template only |
| `resize` | re-render the whole report at another length profile from `report.json`; no fetch, no LLM |
| `clarify` | ask the user a single question |
| `forget` | drop the named memory/session item after confirmation; never touches reports |

Rules:
- **At most 2 LLM calls per turn outside a research pipeline** (route + answer). A `research_quick` turn is the exception: it runs stages 0–9 inline and is bounded by the run budget, not by the turn budget. A retry is allowed only on a validation failure.
- **Repetition guard:** if two consecutive routing calls return the same intent and query, the second is replaced by a deterministic answer from stored state.
- **The model never writes `[n]`.** The answer call returns `{text, note_ids}`; the code numbers and injects. This removes the single largest citation error class for small models.
- **Streaming** for the answer call; the routing call is silent.
- **Answers without sources are labelled.** The UI prints `(no sources — model knowledge)`; the report writer never mixes sourced and unsourced claims without a flag.
- **Deep jobs are always confirmed**, because they cost up to 30–50 minutes.
- Notes and page text are **never** pasted wholesale into the conversation; the orchestrator sees structured notes only.

**Follow-ups are slots, not reasoning.** "expand section 2" → `{intent: expand, section: "s2"}`. "find two more sources on X" → `{intent: more_sources, query: "X"}`, which runs stages 2–5 for X only and re-renders the affected sections. Both are cheap, deterministic and reuse the current `run_id`.

**Compaction policy.** When the chat context exceeds `chat.context_budget` (default: 60% of the profile's *safe* context, see §8.3):

1. Keep the last `chat.keep_turns` (default 4) turns verbatim.
2. **Template the summary from stored turn metadata first** (`intent`, `run_id`, `note_ids`, `open_questions` are already in the DB). Only if the templated summary exceeds the budget does one grammar-constrained call compress it.
3. Keep citations by reference: the summary stores `run_id` / `note_id` / `[n]` triples, never the quoted text.
4. Compaction must never drop an unresolved user instruction; this is tested in F0.

### 4.2. Modes

| Mode | Permissions |
|---|---|
| `research` (default) | Web, memory, write only to output/run dirs |
| `plan` | Read-only, no writes, no network by default |
| `build` (F4) | Files, editing, bash under permissions |

### 4.3. Tool registry (extension point #1)

Declarative registration; adding a tool = one module + one registry entry, no core change.

```python
@tool(
    name="web_search",
    schema=WebSearchArgs,
    modes=("research",),
    permission="allow",
)
def web_search(query: str, max_results: int = 5) -> SearchResult: ...
```

MVP tools (exactly 8, callable by the chat layer through intent dispatch and by a future `orchestrator` role in F4): `web_search`, `web_fetch`, `deep_research`, `history_search`, `memory_save`, `memory_search`, `skill_load`, `write_file`.

- No MVP pipeline role holds a tool (§4.5). The registry exists because intent dispatch is a *typed* dispatch over the same 8 entries, and because F4/F5 roles and skills add tools.
- `skill_load(name)` is the progressive-loading entry point of §4.4.
- `deep_research` takes `{query, profile}` and is the only tool that spawns a job.
- `write_file` is restricted to the run/output directory (FR13).
- `read_file` is **not** in the MVP: under FR13 it could only read files the model already produced.

Later: `edit_file`, `glob`, `grep`, `bash`, `git`, MCP-provided tools — same registry.

**Privilege ceiling is server-side.** A role's tool set is defined in code; a sub-agent may request a *reduction*, never an expansion. Tool sets supplied by the model are rejected.

### 4.4. Skills (extension point #2)

Folder with `SKILL.md` (frontmatter: `name`, `description`, optional `template`, `mode`, `language`, `sections`, `profiles`, `min_rung`) plus assets. Progressive loading: only `name` + `description` enter the prompt (one line each); the body is read on demand via `skill_load(name)`.

Directories: `~/.formiga/skills/` and `./.formiga/skills/`; the repo ships built-ins in `src/formiga/data/skills/`.

Starter skills: `technical-report`, `comparison`, `executive-summary`, `source-review`.
**Render skills** point at a **stage-9 template**, declare a section skeleton, and change report format with **zero LLM calls**. Because composition is deterministic, a skill can reshape the report substantially — including adding auto-tables — without touching the model. Skills execute no code in the MVP.

A skill may **restrict** the length profile (`profiles: ["short","medium"]`) and **pin** the synthesis rung (`min_rung: "assemble"`); it may never widen a profile band or lower a rung below what `verify` allows.

### 4.5. Roles, tool exposure and model tier

| Role | Tools | Output | Tier | Calls (deep, `medium`) |
|---|---|---|---|---|
| `router` (chat) | via intent dispatch (8) | `{intent, args, profile?}` JSON | **fast** | 1 |
| `answerer` (chat text) | none | `{text, note_ids}` | **strong** or fast | 1 |
| `planner` | none | `{entities, aspects}` JSON | **fast** | 1 |
| `reader` (extract) | none | `{verdict, segment_ranges, stance}` | **fast** | 12 |
| `gap_queries` (optional) | none | query variants | **fast** | 0–2 |
| `synthesizer` | none | `[{ids}]` (`assemble`) / `[{ids, edits}]` (`bounded-edit`) / `[{ids, text}]` (`anchored-rewrite`) per section | **strong** | 4–8 |

`gap_checker` **returns search queries as JSON**; the pipeline executes them. No pipeline role holds a tool. Roles that read untrusted content have no tools at all — this, plus the quote/substring check of §7, is the prompt-injection defense.

> Tool isolation limits *actions*, not *content*: hostile text can still try to make a reader fabricate notes. With sentence-id extraction (§5, stage 5) this is structurally harder: the reader cannot emit text, only index numbers, and the code re-derives every quote from the indexed span. Do not relax §7 item 2 on the grounds that readers are tool-less.

**Tier is a mapping, not a requirement.** In the default single-model layout, `fast` and `strong` point at the same endpoint, and the synthesizer simply runs on the same model. Every role, prompt and validation works identically — only speed differs (§8.2).

### 4.6. User journeys

**J1 — Quick factual question, then a follow-up.**

```
$ formiga
> what ph does basil prefer?
  · cache hit (0 new fetches)
  basil grows best at pH 5.5–6.5 [1][2] (confidence: medium)
> and at what temperature?
  · follow-up → quick research (2 sources, ~80 s)
  18–30 °C, with 25 °C optimal [1] (confidence: medium)
```

**J2 — Deep job, SSH disconnects.**

```
> deep research on cold-hardiness of rosemary vs thyme, long
  Deep research (profile: long) will use ~45 min, up to 90 LLM calls, ~14 sources. Continue? [y/N] y
  started run 01J9... · progress: formiga runs 01J9... --follow
$ (connection closed, reconnects later)
$ formiga runs 01J9... --follow
  stage 7/10 synthesize by claim assembly · 4/6 sections · 21 of 45 min used
```

**J3 — Read while it runs.**

```
$ tail -f ~/formiga/reports/2026-11-13-rosemary-thyme-01J9.md
  # Cold hardiness of rosemary vs thyme
  > TL;DR (draft — 2 of 4 sections complete)
  ...
  ## 3. Synthesis   _[in progress]_
```

**J4 — Budget exhaustion.**

```
> research everything about soil pH for blueberries
  deadline reached at stage 6 (gaps) · report written with 2 open gaps
  ~/formiga/reports/2026-11-13-soil-ph-blueberries-01J9.md
  status: incomplete · exit code 2
```

**J5 — 8 GB machine, one model, and picking a length.**

```
$ formiga doctor
  layout   single             base (4B) @ 30/8 t/s (measured)
  ram      weights 2.6 GB + agent 0.3 GB → fits 8 GB
  synthesis rungs available: assemble, bounded-edit   (anchored-rewrite locked by probe)
  profiles permitted: short, medium                   (long, thesis need ~16 GB)
  note     deep deadline relaxed to 50 min for this layout

$ formiga research "cold hardiness of rosemary vs thyme" --profile long
  error: profile 'long' needs ≥10 sources and ~45 min; this layout tops out at 'medium'.
  hint:  formiga research ... --profile medium   (or add RAM: see formiga doctor)
```

**J6 — Same question, three lengths.** The research is done once; only the document contract changes.

```
> research "effects of cover crops on soil nitrogen" --profile medium
  ... 11 sources, 1,050 words, 4 min read · ~/formiga/reports/2026-11-13-cover-crops-01J9.md
> make it short
  intent: resize {profile: short} · re-render whole report from stored notes · 0 fetches · 0 LLM calls
> now a thesis version
  profile 'thesis' needs 20–30 sources; research further or convert what exists? [f/C] f
  started run 01JA... (profile: thesis, est. 90 min, incremental over run 01J9...)
```

`resize` is the one intent that changes the length profile without new research. It is pure code: the claim graph is re-filtered, sections are re-cut from `report.json`, and the same frozen `[n]` numbers are reused. A profile with a **larger** source or section floor (`long`, `thesis`) cannot be satisfied by `resize` alone; the user is offered an incremental run that inherits `run_sources` and only fetches the difference.

### 4.7. States and user-facing messages

Every non-happy path has a catalog key, so no stage improvises copy.

| State | Key | Notes |
|---|---|---|
| Budget exhausted | `run.incomplete.budget` | names the cap hit (calls/prompt/output/deadline) |
| Source unfetchable | `source.unfetchable` | reason (`robots`, `timeout`, `content-type`, `too-large`, `blocked-private-ip`) |
| Claim downgraded | `report.claim.unverified` | links to claim id and missing condition |
| Attribution overlap low | `report.claim.low_overlap` | flagged, not deleted |
| Conflict found | `report.conflict.found` | lists the two sources |
| Nothing extracted | `stage5.no_facts` | source kept in ledger, contributes nothing |
| Invalid segment ids | `stage5.invalid_ids` | reader output rejected, retried once |
| Run resumed | `run.resumed` | states last committed stage |
| Run interrupted | `run.interrupted` | suggests `formiga resume <id>` |
| Offline fallback | `run.offline.fallback` | says which stages are disabled |
| Endpoint degraded | `llm.endpoint.fallback` | a role fell back to the other tier |
| Single-model layout | `layout.single` | informs that quality/speed trade-offs apply |
| Profile not permitted | `run.profile.unsupported` | names required RAM/sources and the highest profile allowed |
| Profile resized | `run.profile.resized` | old → new, notes reused, 0 fetches |
| Language upgraded | `run.language.upgraded` | `assemble` cannot cross languages; rung raised (§3) |
| Rung locked | `report.rung.locked` | a claim fell back one rung; reason recorded |
| Contract violation | `report.contract.violation` | lint result: band, missing section, orphan citation |
| Sensitive-topic notice | `report.sensitive.notice` | fixed text, see §7 |

A run must be scriptable to force each state in tests.

---

## 5. Research pipeline

```
Question
  → 0 Reuse (history + cache)  ──sufficient──────────────┐
  → 1 Plan       facets (entities × aspects), closed set │
  → 2 Search     queries per facet × language × template │
  → 3 Fetch      HTML/PDF → text, segments, cache        │
  → 4 Select     FTS5/BM25 over segments, top-k          │
  → 5 Extract    LLM → {verdict, segment_ranges}  (~30 tok) │
  → 6 Gaps       coverage matrix (code) → more facets    │
  → 7 Synthesize claim assembly + synthesis ladder       │
  → 8 Verify     deterministic (citations, quotes, nums)◄┘
  → 9 Compose    contract lint + template → .md  (no LLM)
```

Ten stages, numbered 0–9; progress is printed as `stage N/10`. Three stages changed shape from v5.1 — 1, 5, 7 — because they were asking a small model to *generate*, and generation is exactly what it does badly. Stages 2, 3, 4, 8, 9 were already deterministic and stay. v5.3 changes stage 7 from one mode to a **ladder** (§5.1) and adds a contract check to stage 9 (§6.3).

**Stage 0 — Reuse.** Normalize the question, check previous runs and the page cache. If coverage is sufficient, answer immediately. `--offline` restricts the run to this stage plus synthesis.

**Stage 1 — Plan as facets, not prose sub-questions.**

```json
{"entities": ["rosemary", "thyme"],
 "aspects": ["definition", "quantities", "comparison", "risks"],
 "units_expected": ["°C"],
 "language": "en"}
```

`aspects` is a **closed enum**: `definition | mechanism | quantities | comparison | risks | authorities | recent | costs`. Sub-questions are the filtered cross-product `entities × aspects`, selected by a static applicability table in code (e.g. `costs` does not apply to a botanical definition), and then **sized by the length profile** (§6.3): `short` keeps 2–3 aspects, `medium` 4–5, `long` 6–8, `thesis` all applicable ones plus domain-specific extras from the skill. Output is ~70 tokens; the model cannot produce redundant or off-topic sub-questions.

The profile also decides **how many entities** are planned: `short` caps at 2, `thesis` allows up to 5 and asks the planner for subclassifications (the one place the thesis profile accepts an extra model call, capped at 1).

Two **free-form queries** are always added on top, generated in the user's language, so the taxonomy cannot blind the search (§12, facet bias).

**Stage 2 — Search.** For each facet, a query template in `search_languages`, sent through the provider chain (local SearXNG → DuckDuckGo lite → keyed provider). Templates are **per aspect and fully static code**, not model output:

| Aspect | Template sketch |
|---|---|
| `quantities` | `"<entity>" (dose OR mg OR "%" OR range)` + `site:` hints from config |
| `authorities` | `"<entity>" (guideline OR standard OR official OR "peer-reviewed")` |
| `recent` | `"<entity>" <year-1> OR <year>` |
| `definition` / `mechanism` | `"<entity>" explained` (no operators) |

Supported operators are `OR`, quoted phrases, `site:`, `filetype:pdf`, `intitle:` and `-term`; each provider adapter declares which it honours, and the template is degraded (operators stripped) for adapters that do not. A `filetype:pdf` template is issued once per deep run so the PDF acceptance criterion (F2) does not depend on luck. Raw results are recorded; nothing is a "source" yet.

**Stage 3 — Fetch and segment.** Fetch with allowlist of content types, 2 MB cap, charset detection, 20 s timeout, backoff, per-domain rate limit, `robots.txt`, **private/loopback/metadata IP block with re-check on every redirect** (FR16). Extract main text (HTML: `selectolax`; PDF: `pypdf` or `pdftotext`). Then **split into numbered segments** and persist them:

- **segmenter:** sentence splitting (abbreviation- and decimal-aware), falling back to paragraph units when the text is list-like, tabular or unpunctuated;
- every segment stores `(source_id, idx, text, start_char, end_char, page)`;
- indices are stable for a given cached text hash **and `segmenter_version`** — this is what makes stage 5 ids reusable across runs and resume. Bumping the segmenter version invalidates stages 5 and 7, never 3.

Fetch runs as a **bounded producer/consumer**: a fetch pool writes segments while the extraction stage consumes sources already segmented, so model time overlaps network time. On CPU there is one LLM slot, so the win is on the network side (search + fetch ≈ 4 min of a 24 min run); the pool is capped at `fetch.parallel` (default 4) and obeys the per-domain rate limit.

Failures become `unfetchable` with a reason. Dedup by normalized URL → content hash. **Near-duplicate sources** (syndicated copies, mirrors, press-release reprints) are detected at this stage by MinHash over 5-gram shingles (Jaccard ≥ 0.85) and collapsed into one source with an `aliases` list — this is required for the independence test in §7 and is **not** post-MVP.

**Stage 4 — Select (mandatory).** Score segments against the facet with **SQLite FTS5 `bm25()`** over `segments_fts`, expand each hit by ±1 segment of context for the prompt, cap ~400 tokens per passage, top 3 per source. Deterministic tie-break on `(source_id, idx)`. If FTS5 is unavailable in the linked SQLite build, fall back to normalized TF-IDF over the run's segment corpus (same interface, `selector.impl` recorded in the report). Full page text never reaches the LLM — the difference between ~24 and ~10 minutes for 12 sources.

**Stage 5 — Extract by segment id.** The reader receives numbered segments and returns ids only:

```json
{"verdict": "answers", "segments": [[112, 113], [119]], "stance": "supports"}
```

`segments` is a list of **contiguous id ranges** (each a closed interval), not an arbitrary set. This is a correctness requirement: `quote_original` is a substring of the cached text, and a non-contiguous selection could never be verified by substring (§7 item 2). The reader may return more than one range — that is how a model cites "two separate sentences from the same page". ~35 output tokens instead of ~300, and it changes the failure mode: the model can pick a wrong sentence, but it **cannot invent a quote, an offset, a page number or a publication date.**

| Note field | Produced by |
|---|---|
| `quote_original` | code — verbatim concatenation of the chosen ranges |
| `offset` | code — one `(start_char, end_char)` per range |
| `locator` | code — `(page, paragraph)` from the segment map |
| `numbers` | code — regex over the quote, with unit normalization |
| `published` | code — metadata/JSON-LD, else `null` |
| `language` | code — cheap n-gram heuristic |

`verdict ∈ {answers, partial, no}` gives the model an explicit **abstention** path. Without it, small models "find" something in every passage. `no` is a success, not a failure — it is recorded and the source contributes nothing.

**Notes are committed per `(source, facet)`**, in the same transaction as the reader call's stage row. A run killed after 9 of 12 readers resumes with those 9 done (§6.4).

**Stage 6 — Gaps as a coverage matrix, in code.** No model judgment:

- covered = facet has ≥1 claim whose note carries that facet;
- `units_expected` with no numeric note anywhere → gap;
- same quantity, different values across sources → **conflict** (normalized unit comparison);
- distinct registrable domains below the **profile floor** (§6.3) → diversity gap (this replaces the old hard-coded "fewer than 2");
- unsupported claim rate > threshold → re-read the weakest sources once (bounded).

Each gap already *is* a query, so the default is zero LLM calls. Optionally one call generates 2 variants per gap (~50 tokens); behind config, off by default. Max 2 rounds in deep, 0 in quick.

**Stage 7 — Synthesize by claim assembly, on a ladder.** For each section, the synthesizer receives 6–10 note candidates with ids. What it returns depends on the rung the run is allowed to use (§5.1). Default is `assemble`:

```json
[{"ids": [112, 113]}, {"ids": [119]}]
```

With `bounded-edit`:

```json
[{"ids": [112, 113], "del": [4, 5, 9], "ins": ["however", ", and"]}]
```

With `anchored-rewrite`:

```json
[{"ids": [112, 113], "text": "Rosemary survives to about −10 °C, while thyme tolerates −15 °C."}]
```

Validation runs in the same step, deterministically, and **the failure behaviour is identical on every rung**: the claim falls back one rung and is re-rendered from ids; it is never discarded for a stylistic reason and never repaired by another LLM call.

- every number in the final text must appear in the multiset of the cited quotes, or be covered by a `derivation`;
- every id must be in the section's candidate set → otherwise discard;
- **lexical support** (rewrite rungs only): ≥ 0.75 of the content words of the final text must come from the cited quotes ∪ the rung's allowed vocabulary (§7 item 9);
- attribution overlap ≥ 0.6 between final text and the concatenated quotes, else flag (§7);
- final text ≤ 30 words; longer is a split request, not a longer sentence;
- `bounded-edit` additionally: deleted tokens ≤ 20% of the claim, inserted tokens must be in the closed connector/function-word list, no token may be inserted inside a quoted number or an entity name.

### 5.1. Synthesis ladder

The ladder replaces the v5.2 `assemble | rewrite` binary. Rungs are entered **per claim**, and the run records which rung every claim used (`claim.rung`), so `verify` can report a distribution and `bench` can price each rung separately.

| Rung | Model output | Cost (out tokens) | Gate to enter |
|---|---|---|---|
| **`assemble`** | ids only | ~15 / claim | always available; the floor |
| **`bounded-edit`** | ids + `del` indices + `ins` from a closed list | ~35 / claim | probe: the model produces valid edit indices in ≥ 8/10 trials; no bench precision loss versus `assemble` |
| **`anchored-rewrite`** | ids + free `text` ≤ 30 words | ~60 / claim | probe: lexical support ≥ 0.85 and overlap ≥ 0.7 in 10/10 samples, **and** a readability gain of ≥ 0.5 on the human rubric |

Rules:

1. **Escalation is a config ceiling, not a model choice.** The profile and layout set `rung_ceiling` (a skill may pin `min_rung`); the model never decides to "write better". A rung below the ceiling is used only if the probe for that model passed.
2. **De-escalation is automatic and per claim.** Any guard failure drops that claim one rung for the final render; the rest of the section keeps its rung. A claim can therefore be `bounded-edit` in a report whose section is otherwise `anchored-rewrite`.
3. **`assemble` prefers cross-source adjacency.** When assembling, the composer orders claims so that adjacent claims come from different sources where possible, and inserts a connector only when the relation type is known (agreement, contrast, sequence) — never a generic "Furthermore".
4. **`bounded-edit` is the sweet spot for 8 GB.** It is the only rung that can produce a grammatical sentence out of two quotes without free generation: the model marks what to delete and picks a connector from ~40 entries; the code rebuilds the sentence and verifies the result. It is the default ceiling on `single` with a `base` model.
5. **`anchored-rewrite` is what makes a "Perplexity-like" paragraph possible** — several sources merged into one sentence — but it is the only rung where the model writes content words. It is therefore gated twice (probe + per-claim guard) and always reported: `report.rung_distribution` is part of the frontmatter.

Sections are **profile-sized**, not fixed: `short` 2–3, `medium` 3–5, `long` 5–8, `thesis` 7–12 (§6.3). Conflicts, gaps, risks and the TL;DR are always produced by code from the claim graph.

**Stage 8 — Verify.** Deterministic, always on (§7).

**Stage 9 — Compose and render.** Template + composition rules → Markdown. Zero LLM. Details in §6.2, including progressive publication while a deep run is still going.

**Quick mode:** expanded into the `short` profile — `0 → 1-lite → 2 → 3 → 4 → 5 → 7-lite → 8 → 9`. One round, ≤ 3 sources, ≤ 3 facets, no gap loop, 1–2 sections, no answer box requirement above a single paragraph. Verification always runs.

**Background jobs:** `--deep` spawns a detached subprocess (`start_new_session=True`) with a PID file; survives SSH disconnect. Progress via `events.jsonl` + DB. No daemon, no queue, no Redis.

**Startup recovery.** Any run with `status = 'running'` whose PID is absent (or whose `flock` is free) is marked `interrupted` on the next `runs`, `resume` or `doctor`. `formiga resume <id>` continues from the last committed stage, **without resetting the budget**.

**Numbering.** `[n]` is assigned in order of first appearance in the verified claim list and frozen at stage 8. Rebuilding with another template never renumbers. Required for byte-identical rendering.

---

## 6. Data & storage

### 6.1. Note (stage 5 output, built by code)

```json
{
  "source_id": 7,
  "run_id": "01J...",
  "facet": "quantities",
  "verdict": "answers",
  "stance": "supports",
  "segment_ranges": [[112, 113], [119, 119]],
  "quote_original": "grows best at pH 5.5 to 6.5. Lime raises it further.",
  "numbers": [{"value": "5.5-6.5", "unit": "pH"}],
  "offsets": [[10432, 10478], [10520, 10544]],
  "locator": {"page": 3, "paragraph": 7},
  "published": "2019-03",
  "language": "en",
  "derived_by": "code"
}
```

Only `verdict`, `segment_ranges`, `stance` come from the model. Everything else is computed — that asymmetry is the point. `segment_ranges` holds **contiguous closed intervals**; `quote_original` is their verbatim concatenation, which is why it is found by substring by construction. Two ranges mean "two separate sentences from the same page", not "any two ids".

### 6.2. Report (stage 7/9 output, schema 3)

```json
{
  "schema_version": 3,
  "run_id": "01J...",
  "profile": "medium",
  "rung_ceiling": "bounded-edit",
  "title": "...",
  "answer": "Short direct answer, 2–3 sentences [1][4].",
  "tldr": ["...", "..."],
  "sections": [{
    "id": "s1", "title": "...", "kind": "prose",
    "claims": [{
      "id": "a1",
      "text": "Rosemary survives to about −10 °C [1]; thyme to −15 °C [2].",
      "rung": "bounded-edit",
      "citations": [{"n": 1, "source_id": 7, "note_id": 42}],
      "critical": false,
      "flags": [],
      "overlap": 0.71,
      "lexical_support": 0.82,
      "derivation": null
    }]
  }],
  "tables": [{"kind": "comparison", "columns": ["entity", "value", "unit"], "rows": []}],
  "timeline": null,
  "related_questions": ["..."],
  "conflicts": [], "gaps": [], "warnings": [],
  "confidence": "medium",
  "citation_coverage": 0.93,
  "citation_precision": 0.88,
  "synthesis_ratio": 0.34,
  "domains": 9,
  "word_count": 1042,
  "reading_minutes": 4,
  "rung_distribution": {"assemble": 11, "bounded-edit": 6, "anchored-rewrite": 0},
  "contract": {"profile": "medium", "band": [900, 1200], "ok": true, "violations": []},
  "freshness": {"median_year": 2022, "stale_warning": false},
  "budget": {"llm_calls": 31, "prompt_tokens": 28400, "output_tokens": 2600, "duration_s": 1310, "exceeded": false}
}
```

`critical` is not the model's to decide downward: it may set `critical: true` on a claim the pipeline missed, never clear it. A deterministic topic list (dose, toxicity, health, animals, water treatment, process temperature) forces it regardless.

`derivation` is the only way a number can be absent from its cited sources: `{expr, inputs: [claim_ids]}` evaluated by a safe AST evaluator, with every input itself sourced. Prose is not accepted.

`profile`, `contract` and `word_count` are what `resize` rewrites; `sections`, `claims`, `notes`, `run_sources` are what it reads. Resizing therefore never changes a citation number or a quote.

**Composition rules (stage 9, no LLM).** These are what make an assembled report read like a written one:

1. **Answer box**: the highest-confidence claim covering the question's main facet, plus one contrast claim if a conflict exists. 2–3 sentences, capped at 90 words. This is the first thing rendered, and it is code-selected.
2. **TL;DR**: the highest-confidence claim of each section, capped at 5 for `medium` and 3 for `short` (7 for `long`/`thesis`), one line each, no claim repeated from the Answer box.
3. **Section body**: claims grouped by facet in the fixed order `definition → mechanism → quantities → comparison → risks → authorities → recent → costs`; connectors come from the template (`"By contrast,"`, `"Both sources agree that"`) chosen by *relation type between adjacent claims*, not by the model.
4. **Auto-tables**: any facet with ≥3 claims carrying `(entity, value, unit)` becomes a comparison table. Deterministic, high perceived quality, zero tokens.
5. **Auto-timeline**: if ≥3 claims carry `published` dates and events, emit a chronology list.
6. **No two adjacent claims start with the same word, and no source appears in more than 2 consecutive claims** — the composer reshuffles within a facet when a claim has ≥2 citations. Cheap, but kills the "one source, dumped" look.
7. **Dedup**: near-identical claims (MinHash of shingles, Jaccard ≥ 0.8) merge into one claim with multiple citations.
8. **Quote cap**: rendered quotes ≤ `report.max_quote_chars` (default 400) per citation **and** ≤ `report.max_quote_chars_per_source` (default 900) per source, always with URL and `accessed_at`, cut marked `…`. The per-source cap is the copyright control; the per-citation cap is the readability one.
9. **Related questions**: generated from the gap matrix (§5, stage 6) — one per open gap, at most 5, phrased by template. Zero LLM calls.
10. **Numbering frozen** at verify; render is pure.
11. **Contract lint**: before writing the final file, the composer checks the profile band and the mandatory-section list of §6.3; a violation is recorded in `report.contract` and printed as `report.contract.violation` — never silently accepted, never blocking the run.

Output shape (the canonical `medium` layout; §6.3 defines the per-profile skeleton):

```
# Title
> **Answer** — 2–3 sentences, 2–4 citations
> TL;DR — 3–5 bullets
**Confidence** medium · **Sources** 11 · **Words** 1,042 · **Read** 4 min · **Status** complete

## 1. Overview
## 2. ...            (prose: verified claims, [n] inline)
## Comparison       (auto-table)
## Timeline         (auto, if dates exist)
## Convergences and conflicts   (code, from §7)
## Gaps and what would change the answer
## Related questions            (from the gap matrix, 0 tokens)
## Risks and limitations        (sensitive topics)
## Sources          (table: #, domain, type, date, cites) + excerpts

<details> Research trace: facets · queries · fetched/rejected · rungs · budget </details>
```

**Progressive publication.** After each section, the renderer rewrites `report.md` atomically (temp file + `rename`) with `_[in progress]_` markers on pending sections. The final write drops the markers. `report.json` is written once at stage 8 so `--rebuild` never sees a half-verified document.

### 6.3. Document contract and length profiles

The `.md` is a **product deliverable with a contract**, not a dump of claims. A profile fixes the band, the skeleton and the research budget; everything else is shared. Four profiles ship:

| Profile | Words | Sections | Sources (min–typ) | Aspects | Rounds | LLM calls (cap) | Deadline `dual` / `single` | Typical use |
|---|---|---|---|---|---|---|---|---|
| `short` | 250–400 | 1–2 + box/TL;DR | 2–4 / 3 | 2–3 | 0 | 12 | 6 / 10 min | quick answer, "resuma isso" |
| `medium` (default) | 900–1,200 | 3–5 | 8–10 / 11 | 4–5 | 1 | 45 | 30 / 50 min | deep research, the Perplexity analogue |
| `long` | 1,800–2,600 | 5–8 | 12–16 / 14 | 6–8 | 2 | 70 | 45 / 75 min | briefing, decision memo |
| `thesis` | 4,000–8,000 | 7–12 | 20–30 / 24 | all + skill extras | 3 | 120 | 90 / 150 min* | TCC / literature review |

`*` `single`/8 GB does not permit `long` or `thesis` without `--allow-heavy`; the `single` column is the `--allow-heavy` deadline.

Bands are **±10%** and enforced by `formiga lint` and by `report.contract`. Word count is measured on the rendered prose, excluding the Sources section and the research trace.

**Mandatory sections per profile** (all profiles always include the ones marked `•`):

| Section | `short` | `medium` | `long` | `thesis` |
|---|---|---|---|---|
| Answer box | • | • | • | • (abstract, 120–200 words) |
| TL;DR | • | • | • | opt |
| Overview / Introduction | • | • | • | • |
| Thematic sections | — | 3–5 | 5–8 | 7–12 |
| Comparison table (if data) | opt | • | • | • |
| Timeline (if dates) | — | opt | • | • |
| Convergences and conflicts | • | • | • | • |
| Gaps and what would change the answer | • | • | • | • |
| Related questions | opt | • | • | — |
| Methodology | — | — | opt | • (search strategy, inclusion criteria, limitations) |
| Risks and limitations | if sensitive | if sensitive | • | • |
| References / Sources | • | • | • | • (numbered, full metadata) |
| Research trace | • | • | • | • |

**`thesis` profile specifics.** It is not "medium, but longer". It adds, all deterministically:

1. **Methodology section** built from the run's own trace: databases searched, query strings, date range, number of results screened vs included, exclusion reasons (`unfetchable`, `no` verdicts). This is the one section that makes a research document auditable — and it costs zero LLM tokens because the data already exists.
2. **Numbered reference list with a consistent citation style** (`report.citation_style = apa | abnt | ieee | mla`, default `abnt` for `pt-BR`, `apa` otherwise). Generated from stored metadata only. Missing fields are marked `[n.d.]`, never invented.
3. **Per-section claim caps** so the model cannot pad: 6 claims per section on `thesis`, and the composer prefers depth (quotes + numbers) over more claims.
4. **An "answerable vs open" split**: the gap matrix is partitioned into questions the collected evidence answers and questions it does not, which is exactly the "future work" section of a TCC.
5. **Deterministic glossary**: entities that appear with a definition facet ≥2 times get a two-line glossary entry taken from their defining quote.

**Delivery: how the contract is met by construction.** Every profile is a *reduction* of the same claim graph (§6.2). Nothing in the pipeline is profile-specific except:

- stage 1 aspect count (§5),
- stage 6 domain floor and round count,
- stage 7 section count and rung ceiling,
- the stage-9 skeleton and reference style,
- the budget row in §8.4.

That is why `resize` is free: it re-runs stages 9 (and 7 only if the rung changes) against the same `report.json`. `short` after `medium` is a re-render; `thesis` after `medium` is a new run in incremental mode (§4.1, J6).

**Configuration.**

```toml
[report]
profile = "medium"           # default when neither CLI nor chat specifies
citation_style = "apa"       # apa | abnt | ieee | mla
bilingual = false            # §3, path 2
max_quote_chars = 400
max_quote_chars_per_source = 900

[report.profiles.thesis]
words = [4000, 8000]
sections = [7, 12]
sources_min = 20
rounds = 3
rung_ceiling = "anchored-rewrite"   # still probe-gated
```

- CLI: `formiga research ... --profile long`, `formiga report <run> --rebuild --profile thesis`.
- Chat: `deep research on X, long` → router returns `profile: "long"`.
- A profile is **validated against the layout** before starting: `single` with 8 GB permits `short` and `medium`; `long`/`thesis` require ≥14 GB or an explicit `--allow-heavy` flag that prints the projected wall-clock. This is `run.profile.unsupported` (§4.7), not a silent downgrade.
- A skill may restrict the allowed profiles and pin `min_rung`, never the opposite (§4.4).

### 6.4. Storage

SQLite (WAL, `busy_timeout=5000`) + content-addressed file cache.

| Table | Purpose |
|---|---|
| `meta` | `schema_version`; migration runner from F0 |
| `sessions` | session id, timestamps, title, `language`, `output_language` |
| `messages` | session id, role, content, `intent`, `run_id`, `note_ids`, `token_count`, `compacted` |
| `runs` | question, mode, **profile**, layout, `prompt_version`, `segmenter_version`, status, deadline, pid, `report_path`, budget counters |
| `stage_runs` | stage, `input_hash`, status, tokens, duration, `tier` |
| `run_sources` | `run_id`, `n`, `source_id` — makes `[n] → source` stable per run |
| `sources` | global deduped source: url, normalized url, domain, hash, cache path, quality, status, `aliases` (MinHash near-dup merge) |
| `segments` | `source_id`, `idx`, text, `start_char`, `end_char`, `page` — the unit of extraction |
| `notes` | `source_id`, `run_id`, `facet`, verdict, stance, `segment_ranges`, quote, numbers, offsets, locator, `derived_by`, `commit_key` |
| `claims` | `run_id`, text, **`rung`**, flags, `critical`, `overlap`, `lexical_support`, `derivation` |
| `citations` | `claim_id`, `note_id`, `n` — lets `verify` run without re-reading `report.json` |
| `llm_cache` | prompt hash → response |
| `segments_fts` | FTS5 over `segments.text` (external-content table), `bm25()` for stage 4 |

- **Idempotency key:** `sha256(stage ‖ dependency_output_hashes ‖ layout ‖ prompt_version ‖ schema_version ‖ segmenter_version ‖ profile)`. Stage hashes form a DAG: changing stage 5 invalidates 7 but not 3; changing `segmenter_version` invalidates 5 and 7 but not 3; changing `profile` invalidates only 7 and 9.
- **LLM cache key:** `sha256(prompt ‖ model ‖ temperature ‖ prompt_version ‖ schema_version ‖ grammar_hash ‖ rung)`. Omitting schema/grammar serves stale-but-valid JSON after a schema change; omitting `rung` would serve an `assemble` answer to a `bounded-edit` request.
- **Page cache:** `cache/<hash[:2]>/<hash>.{html,txt,pdf}` + TTL, etag/last-modified.
- **Locking:** `flock` per run; a unit is `done` only when its output is committed in the same transaction. Units are `(source, facet)` for stage 5 and `(section)` for stage 7, so a resumed run loses at most one unit, not one stage.
- **Dedup:** normalized URL (strip tracking params, fragment, trailing slash, scheme/www) → content hash → **MinHash near-duplicate merge across sources** (Jaccard ≥ 0.85 over 5-gram shingles, §5 stage 3). Near-duplicate *claims* are merged at compose time (§6.2 rule 7).
- **`sources.quality`** is a deterministic 0–1 score, never a model judgment: `0.4 × domain_tier + 0.25 × has_date + 0.2 × has_author_or_org + 0.15 × length_band`, where `domain_tier` comes from a static tier file (`gov/edu/journal = 1.0`, `established news/org = 0.7`, `blog/forum = 0.3`, unknown = 0.5). It orders candidates in stage 4 and is reported per source.

Everything is open format (SQLite, JSON, Markdown). No external system integration.

### 6.5. Retention, privacy and copyright

| Item | Default | Control |
|---|---|---|
| Page cache | 30 days | `cache.ttl_days`; `formiga cache prune` |
| `events.jsonl` | rotated at 10 MB, last 3 kept | `logs.rotate_mb` |
| Chat history | kept | `formiga forget <session>` |
| Memory file | kept, user-editable | `memory_forget` / `formiga forget --memory` |
| Reports | kept | never deleted automatically |
| Run database | kept | `formiga prune --older-than 90d` |

- Everything lives under `~/.formiga/` (config, db, cache, logs, skills, memory) and `~/formiga/reports/`. `docs/uninstall.md` lists exact paths; uninstall is a documented `rm -rf`.
- **Secrets:** `memory_save`, `messages` and `notes` reject content matching a conservative secret pattern set (API-key shapes, `-----BEGIN * PRIVATE KEY-----`, `password=`), logging the rejection. A guard against accidents, not a security boundary — say so in the docs.
- **Copyright:** rendered quotes are capped at `report.max_quote_chars` (default 400) per citation and at `report.max_quote_chars_per_source` (default 900) per source, always with URL and `accessed_at`, linking the original. `report.json` keeps the full verified quote for auditing; only the human-facing copy is truncated. `thesis` raises the per-source cap only with an explicit user acknowledgement (`--allow-long-quotes`).

---

## 7. Verification & trust

Deterministic, always on:

1. Every `[n]` exists in the run ledger (`run_sources`).
2. Every quote is found by substring in cached text (whitespace/unicode normalized). With sentence-id extraction this is a **structural** guarantee, not a probabilistic one — the quote is the verbatim concatenation of contiguous ranges the code selected.
3. **Numeric guard:** every number, unit, dose or range in a claim must appear in the cited source, normalized (decimal comma/point, unit synonyms), **or** be justified by a valid `derivation`. Compare as a **multiset**: a number repeated twice in the claim requires two occurrences in the source.
4. Any URL not in the ledger is stripped — the model is never a source of URLs.
5. Unsupported claims are flagged or removed per config; coverage recorded before cleanup.
6. **Critical claims** require ≥2 **independent** sources (distinct registrable domains, distinct content hashes, MinHash source distance ≥ 0.2) and a clean numeric guard — otherwise downgraded to `[unverified]`.
7. **Attribution overlap:** content-word overlap between claim text and its cited quotes ≥ 0.60, else flag `low_overlap`. Mean overlap feeds `citation_precision`. This is the cheap, CPU-only proxy for entailment that keeps small-model synthesis honest.
8. **Claim dedup** by MinHash before numbering, so "two independent sources" means two sources, not two paraphrases of the same press release.
9. **Lexical support** (rungs above `assemble` only): fraction of content words in the final claim text that occur in the cited quotes ∪ the rung's allowed vocabulary (connectors, question terms, template nouns) must be ≥ 0.75. This is the generalization of the numeric guard from numbers to words, and it is the single check that makes `anchored-rewrite` safe. Below 0.75: the claim is re-rendered one rung down, `report.rung.locked` is emitted, and the value is recorded in `claim.lexical_support`.
10. **Provenance completeness:** every rendered `[n]` resolves to a source with a non-empty URL, a fetch timestamp and a cached text hash. A source that lost its cache entry is re-rendered as a footnote-only reference, never as an inline fact.
11. **Contract check** (§6.3) runs at stage 9 and records band, section and reference-style violations in `report.contract`. It never mutates a claim.

**Confidence** is computed: `high` = ≥3 independent sources, no unresolved conflict, guard clean; `medium` = 2 sources or minor conflict; `low` = single source or open conflict. Per section and aggregated. **Independence uses the merged source set** (§6.4), so three syndicated copies of one press release count as one.

**Document metrics**, computed at compose time and stored in `report.json` — they are part of verification because they are what the user actually judges:

| Metric | Definition | Fails when |
|---|---|---|
| `synthesis_ratio` | word-weighted share of claims with ≥2 independent sources | below the profile floor (§2) |
| `integrated_sections` | share of sections with ≥1 sentence carrying ≥2 citation markers | < 100% |
| `domains` | distinct registrable domains in the ledger | below profile floor |
| `word_count` | rendered prose words | outside the band ±10% |
| `reading_minutes` | `ceil(words / 220)` | > profile ceiling |
| `freshness.median_year` | median `published` year of cited sources | `recent` facet present and median > 3 years old |
| `quote_reuse` | max times one sentence is quoted across claims | > 1 |
| `rung_distribution` | claims per rung | `anchored-rewrite` > 40% while `assemble` output was possible |

`thesis` additionally requires `references_complete` (every cited source has author/org, title, year, URL — missing fields marked `[n.d.]`, never invented) and `methodology_present`.

Reports on sensitive topics carry a fixed *Risks and limitations* section and a notice that the summary does not replace a qualified professional.

**Failure philosophy.** The verifier flags; it deletes only when the citation chain is provably broken. A guard with false positives gets fixed, not worked around — removing legitimate content is worse than keeping a flagged claim.

---

## 8. Models, hardware & budgets

**Target:** old CPU (e.g. 4th-gen i5), 8–16 GB RAM, no GPU or a 1–2 GB GPU. Prefill is the real bottleneck. Everything is free and local: GGUF Q4_K_M on `llama-server`.

### 8.1. Model tiers

Model **ids are placeholders** and are maintained by `bench`, not by the core: the PRD names *shapes*, and the shipped `profiles/` directory maps each shape to the model ids available at release time. A model family is never hard-coded (§15).

| Alias | Shape | Weights (Q4_K_M) | Typical CPU speed (gen / prefill) | Best role |
|---|---|---|---|---|
| `small` | dense 2B | ~1.3–1.5 GB | ~15 / ~45 t/s | router, planner, reader |
| `base` | dense 4B | ~2.4–2.6 GB | ~8 / ~30 t/s | single-model default on 8 GB |
| `large` | dense 8B | ~4.7–5.0 GB | ~5 / ~18 t/s | synthesizer on 16 GB |
| `moe` | MoE 8B, ~1B active | ~4.5–5.0 GB | ~11 / ~35 t/s | fastest strong option at ~5 GB |

A shipped profile file binds the alias to a concrete GGUF, e.g. `small → qwen3-1.7b`, `base → qwen3-4b`, `large → qwen3-8b`, `moe → lfm2-8b-a1b`. **Confirm the exact repo/quant names before F0** and record them in `docs/benchmarks.md`; this document does not claim those artefacts exist under a specific tag.

Speeds are **placeholders until `formiga bench` measures them on the target machine**; the deadline formula in §8.4 consumes the measured values.

The asymmetry the design exploits: **extraction is ~80% of the calls and needs almost no output tokens**, so it runs on the cheapest, fastest model. Synthesis needs the best language but is short (~250 output tokens per section, 4 sections at `medium`). A 5 t/s 8B therefore costs about `4 × (1500/18 + 250/5)` = `4 × (83 + 50)` ≈ **9 min** of model time — affordable — while a 2B handles the other 24 calls in ~5 min.

The ladder widens that asymmetry rather than breaking it: `assemble` writes ~15 output tokens per claim, `bounded-edit` ~35, `anchored-rewrite` ~60. Raising the ceiling on 20 claims costs at most `20 × 45 / 5` ≈ 3 min on an 8B — visible, bounded, and the reason the rung is a budget line and not a toggle.

### 8.2. Layouts

| Layout | RAM | Endpoints | Roles |
|---|---|---|---|
| **`single`** (default, works everywhere) | **8 GB** | 1 × `base` (or `small` on very weak CPUs) | **all roles on the same model**; `rung_ceiling = bounded-edit` |
| **`dual`** (recommended) | **16 GB** | `small` :8080 + `large`/`moe` :8081 | fast tier + strong tier; `anchored-rewrite` allowed if the probe permits |
| `single-strong` | 16 GB | 1 × `large` / `moe` | all roles on the strong model; better text, slower routing |
| `proxy` | any of the above | 1 endpoint on :8090 | `formiga serve --proxy` multiplexes by model name for other clients |

**Profile support per layout** (enforced by `init`/`doctor`; `--allow-heavy` overrides with a printed estimate):

| Layout | `short` | `medium` | `long` | `thesis` |
|---|---|---|---|---|
| `single` 8 GB (`base`) | ✓ | ✓ | with `--allow-heavy` | — |
| `single` 8 GB (`small`) | ✓ | ✓ (slower) | — | — |
| `dual` 16 GB | ✓ | ✓ | ✓ | ✓ |
| `single-strong` 16 GB | ✓ | ✓ | ✓ | ✓ (slower) |

**The single-model layout is a first-class target, not a fallback.** It is what an 8 GB machine runs, what the test suite exercises by default, and what `formiga init` configures when it detects ≤10 GB of RAM. Nothing in the pipeline assumes two endpoints: `fast` and `strong` are keys in a mapping that may point to the same address.

**Recommended:** 16 GB with `dual` (`small` + `large`/`moe`), because it cuts deep-research wall-clock roughly in half, lets synthesis run on the best model available, and unlocks `long`/`thesis`. Two servers coexist comfortably: `small` (~1.5 GB) + `large` (~5 GB) ≈ 6.5 GB of weights.

**Extreme compatibility:** 8 GB with `single`. The 4B at ~8 t/s finishes a `medium` deep research in ~45–50 min instead of ~25–30, and `bounded-edit` keeps the report ordinary prose rather than a quote pile. Use `small` when the CPU cannot sustain the 4B. On such machines `formiga init --layout single --model base` writes a config with a relaxed deadline and caps the rung at `bounded-edit`.

```toml
# ~/.formiga/config.toml — minimal 8 GB setup
[layout]
name = "single"

[layout.fast]
endpoint = "http://127.0.0.1:8080"
model = "base"                   # alias → concrete GGUF via profiles/
context = 4096
tool_call_format = "text"        # native | text | none
supports_grammar = true
temperature = { router = 0.2, planner = 0.0, reader = 0.0, synthesizer = 0.3 }
rung_ceiling = "bounded-edit"
max_context_safe = 3072          # written by `doctor --probe`
```

```toml
# ~/.formiga/config.toml — recommended 16 GB setup
[layout]
name = "dual"

[layout.fast]
endpoint = "http://127.0.0.1:8080"
model = "small"
context = 4096
tool_call_format = "text"
supports_grammar = true
temperature = { router = 0.2, planner = 0.0, reader = 0.0 }

[layout.strong]
endpoint = "http://127.0.0.1:8081"
model = "large"                  # or "moe"
context = 4096
tool_call_format = "none"
supports_grammar = true
temperature = { synthesizer = 0.3, answerer = 0.4 }
rung_ceiling = "anchored-rewrite"   # still probe-gated per claim
```

`formiga serve` reads this file and launches the servers required by the layout; `formiga doctor` checks every configured endpoint. If the strong endpoint is down in `dual`, the router **falls back to the fast tier** (quality note in the report frontmatter) rather than failing the run.

### 8.3. Server tuning (documented, not hard-coded)

- `-ub 512 -b 1024`: the single biggest prefill gain on CPU. Verify against the build's `--help`.
- `-t` = physical cores (not logical) for prefill; `--parallel 1` on CPU; `--mlock` when RAM allows.
- **Prefix cache:** `cache_prompt: true`, and keep the system prompt **byte-identical** per role. No dates, no locale, no run ids in the prefix. Group calls by role so the slot stays warm. Different call types (different grammar) never share a slot.
- `--cache-type-k q8_0`, V in f16 (quantized V degrades more).
- **MoE note, corrected from v5.1:** an 8B MoE with ~1B active gains on *prefill* too, not only generation, because it activates ~1B per token and prefill dominates research cost. The risk is expert gather locality on DDR3. Measure both directions in `bench`; the layout choice depends on it.
- **Single-model layouts:** one server, one slot. Because the same process serves readers and the synthesizer, batch reader calls back-to-back to keep the KV prefix warm, then switch grammar once for synthesis.
- **Decoding parameters for small models:**

| Parameter | JSON stages | Prose stages |
|---|---|---|
| `temperature` | 0.0 (0.2 router) | 0.3–0.4 |
| `repeat_penalty` | **1.0** | 1.05 |
| `top_p` / `min_p` | 0.9 / 0.05 | 0.9 / 0.05 |
| `n_predict` | 2× expected | 2× expected |
| CoT | off | off |

`repeat_penalty > 1` in JSON mode corrupts field names on small models — a classic, hard-to-diagnose bug. Set it explicitly to 1.0.

- **Few-shot:** two byte-identical examples per stage. Bigger win on 2B/4B than on 8B, and it preserves the KV prefix.
- **Effective context:** keep prompts ≤ `max_context_safe` (probe-measured; typically 3–4k) even when the profile advertises more. "Lost in the middle" is severe on small models.
- **Per-rung decoding.** `assemble` and `bounded-edit` must run at `temperature 0.0` with `repeat_penalty 1.0`: they return ids and indices, and any sampling noise becomes an out-of-range index. Only `anchored-rewrite` uses prose settings (0.3, penalty 1.05). Because grammar differs per rung, **never share a slot between rungs** — switching grammar costs a re-prefill, and §8.4's `overhead_factor` already pays for it; do not pay for it twice by interleaving.
- **Batching by rung:** within stage 7, render all `assemble` claims, then all `bounded-edit` claims, then the rewrite claims. The grammar switch happens once or twice per section instead of once per claim.

### 8.4. Budgets

Governed at runtime; exceeding any cap yields `status: incomplete`, exit code 2. "Typical" is what a normal run uses; "cap" is what the governor will never exceed. **Budgets are per profile**: the profile (§6.3) is what selects the row.

| Parameter | `short` typ/cap | `medium` typ/cap | `long` typ/cap | `thesis` typ/cap |
|---|---|---|---|---|
| Sources | 3 / 4 | 11 / 16 | 14 / 20 | 24 / 30 |
| Facets | 3 / 4 | 8 / 12 | 12 / 18 | 20 / 28 |
| Gap rounds | 0 / 0 | 1 / 2 | 2 / 3 | 3 / 4 |
| Passages/source | 2 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |
| Tokens/passage | 400 | 400 | 400 | 400 |
| Sections | 2 / 2 | 4 / 6 | 6 / 8 | 9 / 12 |
| **LLM calls** | **8 / 12** | **31 / 45** | **48 / 70** | **80 / 120** |
| **Prompt tokens** | **4,500 / 6,000** | **28,400 / 40,000** | **44,000 / 62,000** | **70,000 / 100,000** |
| **Output tokens** | **600 / 900** | **2,600 / 4,000** | **4,200 / 6,000** | **7,000 / 10,000** |

Quick mode is always `short` (1–3 sources, 0 gap rounds) and is bounded by the `short` column.

Per-layout deadline overrides (set by `init`/`doctor`, never guessed). Only the profiles a layout supports appear:

| Layout | `short` deadline | `medium` deadline | `long` deadline | `thesis` deadline |
|---|---|---|---|---|
| `dual` (`small` + `large`/`moe`) | 6 min | 30 min | 45 min | 90 min |
| `single-strong` (`large`/`moe`) | 8 min | 40 min | 60 min | 120 min |
| `single` (`base`) | 10 min | 50 min | — (`--allow-heavy`: 75) | — |
| `single` (`small`) | 12 min | 60 min | — | — |

**Per-stage call allocation (`medium` deep):**

| Stage | Calls | Tier |
|---|---|---|
| route (chat) | 1 | fast |
| plan | 1 | fast |
| extract (readers) | 12 | fast |
| gap queries (optional, off by default) | 0–2 | fast |
| synthesize (`bounded-edit`, 4 sections) | 4–6 | strong (or fast in `single`) |
| reserve (retries, extra readers after gap round, rung fallbacks) | 14–25 | either |
| **cap** | **45** | |

`thesis` scales linearly: ~1 reader per (source × facet) but never more than 1 per source batch, ~1 synthesizer call per 1.5 sections (sections are capped at 6 claims each), plus 1 methodology call that is a *selection* (which trace rows to include), not generation. Unused calls roll into the reserve; the reserve is a ceiling, not a target.

**Deadline formula** (`bench` and `doctor` validate it against the measured speeds). The v5.2 formula omitted fixed per-call and per-restart overhead, which is why its estimates were ~2× optimistic on `single`. Corrected:

```
t = Σ_stages ( prompt_tokens_stage / prefill_tps_tier + output_tokens_stage / gen_tps_tier
               + call_overhead_s ) × overhead_factor
    + fetch_s
```

- `call_overhead_s` ≈ 0.25 s (HTTP + JSON parse + governor bookkeeping).
- `overhead_factor` accounts for retries, re-prefill after a grammar/slot switch, and KV evictions: **1.15** on `dual`, **1.9** on `single`. Measured by `bench`; not a guess to be tuned down.
- `fetch_s` is the **serialized** fetch/search time that does not overlap model time — search ~40 s, fetch ~180 s for `medium`, ~80 s for `short`.

```
medium, dual (small fast @45/15, large strong @18/5):
  fast:   17000/45 + 600/15 + 25×0.25 = 378 + 40 + 6   = 424 s
  strong: 10200/18 + 1600/5 + 8×0.25  = 567 + 320 + 2  =  889 s
  subtotal 1313 s × 1.15                            ≈ 1510 s
  fetch/search                                         ≈ 220 s
  total                                              ≈ 1730 s ≈ 28.8 min → deadline 30 min ✓

medium, single (base @30/8):
  all:    28400/30 + 2600/8 + 33×0.25 = 947 + 325 + 8 = 1280 s
  × 1.9                                              ≈ 2432 s
  fetch/search                                        ≈ 220 s
  total                                              ≈ 2652 s ≈ 44 min → deadline 50 min ✓

medium, single (small @45/15):
  all:    28400/45 + 2600/15 + 33×0.25 = 631 + 173 + 8 = 812 s
  × 1.9                                              ≈ 1543 s
  fetch/search                                        ≈ 220 s
  total                                              ≈ 1763 s ≈ 29 min → deadline 60 min
                                                     (headroom: weaker model, more retries)

short, dual:
  fast:    3400/45 + 250/15 + 9×0.25  =  76 + 17 + 2   =  95 s
  strong:  1500/18 + 400/5 + 2×0.25   =  83 + 80 + 1   = 164 s
  subtotal 259 s × 1.15                               ≈ 298 s
  fetch/search                                        ≈  60 s
  total                                              ≈ 358 s ≈ 6.0 min → deadline 6 min (tight; bench may set 7)
```

The `medium`/`dual` example lands at 28.8 min against a 30 min deadline with 1,600 output tokens (not the 2,600 cap) — that is the point of the table: the *typical* run fits, the *cap* run is allowed to hit the deadline and go `incomplete`. If `bench` measures slower prefill and the typical estimate exceeds the deadline, the profile drops a section (§6.3) rather than the deadline growing silently.

`thesis` on `dual`: ~70k prompt / 7k output → fast tier ≈ 1,700 s, strong ≈ 2,100 s, ×1.15 ≈ 4,370 s + 300 s ≈ 78 min, deadline 90 min. On `single-strong` the factor is 1.3 and the deadline is 120 min.

If the estimate exceeds the deadline, **the profile is reduced, never the guarantee**: the governor cuts sections first, then sources, and records `run.incomplete.budget` with the exact cap. A cache hit costs 0 tokens and 0 s but **still increments the call counter**, so a resume cannot loop forever.

**Resume and budget.** A resumed run continues its counters from the last committed stage (or last committed `(source, facet)` unit, §6.4); it does not reset them.

**Fallback.** If the strong tier is unavailable mid-run in `dual`, its remaining calls move to the fast tier, `rung_ceiling` drops one rung (`anchored-rewrite → bounded-edit → assemble`), and the report records `llm_endpoint: degraded`.

---

## 9. Architecture, stack, layout

```
Interfaces: CLI · REPL (rich) · --json · events.jsonl
        ↓
Core: router (intent → action) · modes · permissions · sessions
      compaction · BUDGET
        ↓
Tool registry ── Skills ── Research pipeline ── LLM router ── BUDGET
                                                (fast | strong endpoint,
                                                 may be the same one)
        ↓
Storage: SQLite WAL + FTS5 · segments · page cache · report.json · memory.md
External: web (search/fetch) · llama-server ×1..2
```

| Layer | Choice |
|---|---|
| Project | `uv` + `pyproject.toml` |
| CLI | `typer` |
| Terminal | `rich` + `prompt_toolkit` |
| HTTP | `httpx` (async, streaming) |
| HTML | `selectolax`; `html.parser` stdlib fallback |
| PDF | `pypdf`; `pdftotext` if present (web sources only, no OCR) |
| Data | `dataclasses` + `sqlite3` (FTS5) |
| Templates | `string.Template`-based renderer (~20 lines, no Jinja) |
| Config / i18n | TOML (`tomllib`) + JSON catalogs |
| Quality | `pytest` + `ruff` |

**Stdlib fallback path**, explicitly scoped: if a dependency has no wheel on the target distro, the tool must still run — `httpx` → `urllib.request`, `selectolax` → `html.parser`, `pypdf` → `pdftotext` binary, `rich`/`prompt_toolkit` → plain `input()` and `print()`. The fallback is **degraded but functional**, is exercised by one CI job (`FORMIGA_MINIMAL=1`), and does not cover `typer` (the CLI needs one dependency) — so "stdlib-only" means *no optional extras*, not *zero dependencies*.

**Platform.** Linux only for the MVP. `flock` and `start_new_session=True` semantics are premises, not portability goals. macOS/Windows are out of scope until an ADR says otherwise; `doctor` reports the platform as unsupported rather than failing obscurely.

**Packaged data.** `prompts/`, `templates/`, `skills/` and `i18n/locales/` live inside the package and are loaded with `importlib.resources`, so `uv tool install formiga-cli` ships them. User overrides in `~/.formiga/` and `./.formiga/` take precedence.

```
formiga/
├── AGENTS.md · README.md · LICENSE
├── docs/                 # PRD.md · adr/ · benchmarks.md · uninstall.md
├── src/formiga/
│   ├── cli.py · config.py
│   ├── data/             # prompts/en · templates · skills · i18n/locales/en.json
│   ├── i18n/             # t.py · format.py
│   ├── core/             # router · chat · modes · permissions · budget
│   │                     # session · compaction
│   ├── research/         # pipeline · reuse · planner · search · fetch
│   │                     # segmenter · selector · reader · gaps
│   │                     # synthesizer · ladder · verifier · composer · renderer
│   │                     # contract.py (profiles + lint)
│   ├── tools/            # registry · web · memory · files · skills
│   ├── llm/              # client · router (fast/strong) · grammar · cache
│   │                     # profiles/ · probe.py · serve.py
│   ├── ui/               # repl · progress · partial_report
│   └── storage/          # db · schema.sql · migrations/ · cache
├── compose/              # docker-compose.searxng.yml
└── tests/                # unit/ · fixtures/ · eval/ (eval set + rubric.md)
```

---

## 10. Requirements checklist

| ID | Requirement |
|---|---|
| FR1 | Chat loop = **one routing call + one answer call** per turn, intents per §4.1, repetition guard, streaming, compaction |
| FR2 | Pipeline stages use **grammar-constrained JSON**, no tools, ≤1 repair; semantic validation rejects rather than retries when repair is unlikely to help |
| FR3 | `web_search` with pluggable providers: local SearXNG (recommended), DuckDuckGo HTML/lite, optional keyed providers; fallback chain |
| FR4 | `web_fetch`: streaming with byte cap (2 MB text), content-type allowlist, charset detection, main-text extraction, HTML **and PDF**; `unfetchable` recorded with reason |
| FR5 | Courtesy: identifiable UA, `robots.txt`, per-domain rate limit, configurable timeout (20 s), backoff, run deadline |
| FR6 | Source ledger; chain `[n] → source → note → segment span`; stable per run (`run_sources`); near-duplicate sources merged (MinHash) and never counted as independent |
| FR7 | `deep_research` with quick/deep modes **and length profiles** (`short`/`medium`/`long`/`thesis`), detached background job, resume, cancel |
| FR8 | Budget governor over calls, prompt tokens, output tokens and deadline **per profile**; partial report; idempotent resume that continues counters; profile reduction (sections → sources) on overrun |
| FR9 | Memory: conversation (compacted) · `~/.formiga/memory.md` · history in SQLite+FTS5. `memory_save/search/forget`, `/memory`. Secret-shaped content rejected |
| FR10 | Reports: `report.json` (schema 3) + rendered `.md` with YAML frontmatter (run_id, profile, model(s), layout, `prompt_version`, language, output_language, status, confidence, coverage, precision, synthesis_ratio, words, sources, accessed_at, budget, rung_distribution) |
| FR11 | Tool registry and skill loader per §4; adding either requires no core change |
| FR12 | i18n per §3; no hardcoded UI strings; locale + literal-scan tests in CI |
| FR13 | Permissions: allow/ask/deny by tool and path; reads limited to run/output dirs; writes only to output |
| FR14 | CLI: `ask`, `research [--profile short\|medium\|long\|thesis] [--deep/--quick/--offline/--out/--force/--allow-heavy]`, `runs [--follow]`, `resume <id>`, `cancel`, `report --rebuild [--profile X]`, `lint <run>`, `verify`, `sources`, `logs`, `cache [prune]`, `bench`, `serve`, `doctor [--probe]`, `init [--layout single\|dual]`, `forget`, `prune`, `--lang`, `--version`, bare `formiga` for REPL |
| FR15 | Exit codes: `0` ok · `1` error · `2` partial (budget) · `130` interrupted |
| FR16 | `web_fetch` SSRF guard: http/https only; resolve host, reject private/loopback/link-local/CGNAT/metadata ranges (`127/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16`, `::1`, `fc00::/7`); re-check on every redirect (max 5); reject embedded credentials |
| FR17 | Deterministic citation numbering fixed at verify; identical `report.json` + template renders byte-identically |
| FR18 | **Segmenter:** sentence-level split with paragraph fallback; stable `(source_id, idx)`; page mapping for PDFs; list/table-safe |
| FR19 | **Extraction is id-only:** reader returns `{verdict, segment_ranges, stance}` with **contiguous** ranges; quote, offsets, page, numbers and dates are computed by code |
| FR20 | **LLM router:** role → endpoint mapping where both tiers may resolve to the same endpoint; health check; mid-run fallback; effective endpoint recorded in the report |
| FR21 | **Progressive publication:** `report.md` atomically rewritten per section with `[in progress]` markers during a deep run |
| FR22 | **Composition pass:** answer box, TL;DR, auto-tables, auto-timeline, related questions, claim dedup, adjacency polish, quote caps — all deterministic |
| FR23 | **Single-model parity:** every feature, prompt and acceptance test passes with one endpoint; `single` is the default layout in tests and on ≤10 GB machines |
| FR24 | **Synthesis ladder:** `assemble` / `bounded-edit` / `anchored-rewrite`, ceiling set by profile+layout+probe, escalation never chosen by the model, per-claim automatic de-escalation on guard failure; `claim.rung` recorded and reported |
| FR25 | **Lexical support guard:** rungs above `assemble` require ≥0.75 content-word support from cited quotes ∪ allowed vocabulary; below it, the claim re-renders one rung down and the event is logged |
| FR26 | **Length profiles:** `short`/`medium`/`long`/`thesis` fix word band, section skeleton, source floor, budget and deadline; validated against the layout before start; `resize` re-renders from `report.json` with 0 fetches and 0 LLM calls |
| FR27 | **Document contract + lint:** `formiga lint` and stage-9 check enforce band, mandatory sections, reference completeness, integrated sections and `quote_reuse`; violations land in `report.contract` |
| FR28 | **`thesis` extras:** methodology section from the run trace, references in a configurable style (`apa`/`abnt`/`ieee`/`mla`) with `[n.d.]` for missing fields, deterministic glossary, answerable/open gap split |
| FR29 | **Overlap of fetch and extraction:** bounded fetch pool feeds extraction without waiting for all sources; `fetch.parallel` configurable; per-domain limits still apply |
| FR30 | **Unit-level resume:** stage 5 commits per `(source, facet)`, stage 7 per section; a resumed run loses at most one unit |

**Non-functional.**

| Area | Requirement |
|---|---|
| RAM | Agent process < 1 GB excluding `llama-server`; `single` weights ≤ 2.6 GB (`base`) or ≤ 1.5 GB (`small`); `dual` ≤ 6.5 GB |
| Prompt stability | Stable prefix per role, byte-identical; variable content last |
| Runtime | Python 3.11+; `uv tool install`; stdlib-only fallback path |
| Platform | Linux (see §9) |
| Privacy | No telemetry, no cloud LLM |
| State | Resumable; startup marks dead-PID runs `interrupted` |
| Observability | Structured logs + `events.jsonl`, rotated (§6.5) |
| Testing | Mocked LLM; no network in unit tests; per-stage fixtures |
| Packaging | Data files inside the package via `importlib.resources` |
| Governance | MIT, SemVer, ADRs |
| Reproducibility | Same `report.json` + template → byte-identical `.md` |

---

## 11. Roadmap

| Phase | Deliverable | Acceptance |
|---|---|---|
| **F0 — Foundation** | Repo, config + layouts (`single` default), **profile/contract module + `lint` skeleton**, i18n catalog + formatter, storage + migrations (full §6 schema), LLM client with grammar + cache + **role router**, budget governor, router→action chat shell, compaction, eval set + rubric, `init`/`doctor`/`bench`/`serve` | `formiga ask "say hello"` works on a **single base model**; 0 repairs in 100 grammar-constrained calls per model; sentence-id fidelity ≥ 98%; `--lang pt-BR` changes UI with no code edit; `docs/benchmarks.md` records gen/prefill t/s and peak RSS for `small/base/large/moe` and validates §8.4 deadlines **and overhead factors** for `single` and `dual` |
| **F1 — Web + ledger** | Search providers + operator templates, fetch pool + segmenter, cache, ledger, URL + MinHash dedup, courtesy, SSRF guard, `sources.quality` | Deduplicated sources with clean text and stable segment ids; syndicated copies merged into one source; `unfetchable` recorded; private-IP and redirect-to-local probes rejected (test) |
| **F2 — Research pipeline** | Stages 0–9, quick/deep, **length profiles `short`/`medium`**, background, unit-level resume, `--offline`, verify, `report --rebuild`, `lint`, composer, **ladder `assemble`+`bounded-edit`** | Deep `medium` completes on an **8 GB single-model** machine; ≥7/10 eval questions score ≥1.5/2; `kill -9` resumes losing ≤1 unit; forced short deadline yields a legible partial; `medium` scores ≥3.0/5 readability and meets §6.3 bands |
| **F3 — Memory + skills + UI** | 3-layer memory, skill loader, templates, REPL progress panel, progressive report, **`long`, `thesis` profiles** | Restart and recall prior research; skill reshapes the report via `--rebuild` with zero LLM calls; `thesis` output has methodology + references in the configured style |
| **F4 — Full agent** | `build` mode, edit/patch, glob/grep, sandboxed bash, git, checkpoints + `/undo`, hooks, **`anchored-rewrite` rung** | Multi-file edit with working undo; `anchored-rewrite` passes the lexical-support guard on the eval set |
| **F5 — Ecosystem** | MCP client (stdio/SSE), Playwright scraping, tiny-distro package | External MCP tool usable through the same registry |

Each phase ends with tests, `formiga bench`, and updated docs.

### MVP acceptance (F0–F3)

1. Multi-turn chat: a follow-up expands a section using existing notes, no re-fetch; `resize` re-renders at another profile with 0 fetches and 0 LLM calls.
2. Deep `medium` research produces ≥8 independent sources, a conflicts section, 100% valid citations, clean numeric guard, correct frontmatter — **in ≤30 min on `dual` and ≤50 min on `single` (base)**.
3. Quick (`short`) research answers a factual question in ≤6 min (`dual`) / ≤10 min (`single`) with 1–3 citations.
4. At least one cited source is a PDF, cited with page number.
5. Interrupted run resumes without redoing committed units.
6. Budget exhaustion yields `status: incomplete` + gaps section + exit code 2.
7. Orchestrator context never contains full page text (asserted in test).
8. `report --rebuild` with another skill changes the `.md` with zero LLM calls and keeps `[n]` stable.
9. `--offline` works with network blocked (test-enforced).
10. Adding a locale and a tool each require **no core change** (test-enforced).
11. Agent process RAM < 1 GB during a deep run.
12. Critical claim without two independent sources is published as `[unverified]`, never as fact.
13. A derived number requires a valid `derivation`; an invented one is rejected (test).
14. A run killed while `running` is marked `interrupted` by `doctor` and resumed by `formiga resume` (test).
15. Rendered quotes never exceed `max_quote_chars` per citation or per source, always carry URL + access date.
16. Killing the strong endpoint mid-run in `dual` drops the rung one step, completes, and records `llm_endpoint: degraded` (test).
17. A reader returning out-of-range or non-contiguous ids is rejected and logged as `stage5.invalid_ids`, never crashes the stage (test).
18. **The full acceptance suite runs green in `single` layout with one model**, and `init` on a simulated 8 GB machine writes a `single` config with relaxed deadlines and `rung_ceiling = bounded-edit` (test).
19. **Length profiles:** each of `short`/`medium`/`long`/`thesis` renders inside its word band ±10%, with all mandatory sections present, on the eval set (test). `single`/8 GB rejects `thesis` unless `--allow-heavy`, with `run.profile.unsupported`.
20. **Lexical support:** a claim whose text drifts from its quotes is re-rendered down a rung, `report.rung.locked` is emitted, and no claim in the eval set ships with `lexical_support < 0.75` (test).
21. **Synthesis ratio:** `medium` reports reach `synthesis_ratio ≥ 0.30` and 100% integrated sections on the eval set; an `assemble`-only build is expected to fail this and that is the documented reason `bounded-edit` is the default ceiling on 8 GB (test).
22. **Independence:** three syndicated copies of one article produce `high` confidence only if a genuinely distinct source also cites them (test).

### Evaluation rubric (`tests/eval/rubric.md`, F0)

Each item is scored 0–2 on four axes; it passes with **≥1.5 average and no zero on *sources***.

| Axis | 0 | 1 | 2 |
|---|---|---|---|
| Correctness | wrong or unsupported | partly correct | correct and directly answers |
| Source use | no real sources | cited but thin | ≥2 independent, relevant, quoted |
| Integration | mosaic of quotes | some linking, mostly one-source sentences | sources genuinely compared and merged |
| Gap honesty | invents certainty | silent about gaps | names gaps and conflicts explicitly |
| Readability | unusable as prose | readable but list-like | organized, answer box + TL;DR + sections, tables where useful |
| Length fit | far off the profile | inside band, padded or thin | inside band, every section earns its place |

Eval set: 20 questions minimum — at least 2 requiring PDF sources, 2 with a known conflict, 2 sensitive-topic (forcing `critical`), 1 unanswerable (must report a gap, not fabricate), 1 multi-entity comparison (exercises auto-tables), 3 syndicated-source pairs (independence), 2 thesis-grade (methodology + references), 2 short-profile. Scored by a human; the LLM is never the judge. The set runs three times in CI: `single` (mock strong tier), `dual`, and `dual` with `thesis` on a subset.

**Per-stage harness** (`tests/fixtures/stages/`): `input → expected output` for stages 1, 5, 6, 7 (all three rungs), 9 (contract lint) with the LLM mocked, so a score drop identifies the regressing stage. End-to-end eval alone cannot do this.

**Capability probes** (`formiga doctor --probe`, run once per model, cached in `~/.formiga/profiles.json`):

| Probe | Decides |
|---|---|
| 20 JSON calls, schema compliance | `supports_grammar`, repair rate |
| 20 sentence-id copy tasks (contiguous ranges) | reader reliability; `max_segments_per_prompt` |
| 10 abstention prompts (answer not present) | whether `verdict: no` is usable |
| 10 tool-call/render-arg tasks | `tool_call_format` |
| Context ladder at 2k/4k/8k | `max_context_safe` |
| **10 edit-index tasks** (given a quote, mark deletions + pick a connector) | whether `bounded-edit` is unlocked |
| **10 free rewrites, scored by lexical support + overlap** | whether `anchored-rewrite` is unlocked |
| 10 claims in `output_language` | whether cross-language synthesis is possible at the current rung (§3) |
| 5 section-heading selections at `thesis` size | whether the model can handle 12 sections without drift |

---

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Invalid structured output from small models | High → Low | Id-only selection schemas, grammar, flat enums, repair reserve |
| Unstable tool calling | High → Low | Chat uses a 60-token router JSON, not free-form tool calls; text fallback per model |
| Slow prefill / context overflow | High | Mandatory lexical selection, segments not pages, ≤4k prompts, KV prefix cache, LLM cache, prompt-token budget |
| Run never finishes | High | Budget governor (calls + tokens + deadline); partial output; deadlines derived from `bench` per layout |
| Citation hallucination | High → Low | **Structural**: quotes are spans chosen by id, not written by the model |
| Hallucinated dose/number | High | Numeric multiset guard + `derivation` + two-source rule |
| Bad sentence segmentation on messy HTML, lists, tables | High | Paragraph fallback, list/table detection, fixtures with ugly real pages, `--no-segment` debug flag |
| Assembled report reads like stitched quotes | Medium | Composition rules (§6.2), cross-source adjacency, `bounded-edit` ceiling, `synthesis_ratio` and integrated-section acceptance tests |
| Facet taxonomy blinds the search | Medium | Two free-form queries always added; gap rounds can introduce new facets |
| Strong model too slow on weak CPU | Medium | Profile-sized sections, ≤250 output tokens/section, `assemble`/`bounded-edit` ceiling, per-layout deadline |
| 8 GB machine cannot fit a strong model | Medium | `single` layout is a first-class target; `base` default; `small` option; `bounded-edit` ceiling; `long`/`thesis` refused with a clear message |
| Two endpoints fight for CPU | Medium | Roles are serial (extract, then synthesize); only the fast model stays warm; alternatives are `single` and load-on-demand |
| SSRF via fetched URL / redirect | High | FR16 private-range blocklist, redirect re-check, scheme allowlist |
| Search provider blocks | Medium | Local SearXNG as recommended path; provider chain; fixtures; backoff |
| Prompt injection | Medium → Low | Tool-less readers + id-only output + span-derived quotes + lexical support guard |
| Scope creep | Medium | Phase gates; non-goals enforced; new deps require an ADR |
| Missing native wheels on tiny distros | Medium | Scoped stdlib fallback (§9); optional `pdftotext` |
| Cache serving stale schema | Medium | `schema_version` + `grammar_hash` + `rung` + `segmenter_version` in cache keys; DAG-chained stage hashes |
| **Assembled report reads like a mosaic** | **High** | Ladder with `bounded-edit` as the 8 GB default, cross-source adjacency rule, `synthesis_ratio` and integrated-section metrics as acceptance criteria (no longer only a readability rubric) |
| **`anchored-rewrite` drifts from its quotes** | High | Two-key gate (probe + per-claim lexical support ≥0.75), automatic one-rung fallback, `rung_distribution` reported, never applied to numbers/entities |
| **Syndicated sources inflate confidence** | High → Low | MinHash source dedup in F1 (was post-MVP), `aliases`, independence test in acceptance #22 |
| **Profile promise exceeds the budget** | Medium | Profile validated against layout before start; overrun reduces sections then sources and marks `incomplete`; deadlines derived from measured `bench` with an explicit overhead factor |
| **`thesis` output looks like padded prose** | Medium | Claim caps per section, methodology + answerable/open split generated from the trace, references style with `[n.d.]`, deterministic glossary |
| **Cross-language `assemble`** | Medium | Explicit three-path rule (§3), `run.language.upgraded`, `doctor` warning |
| **Generated `.md` diverges from the contract** | Medium | `formiga lint`, `report.contract`, contract fixtures per profile in CI |

---

## 13. Rules for the coding agent (`AGENTS.md`)

1. This PRD is the single source of truth; scope changes require editing it or writing an ADR.
2. **All code, identifiers, comments, logs, schema and repo docs in English.** No exceptions.
3. **No hardcoded user-facing strings.** Everything in `ui/` and CLI error paths goes through `t()` and `locales/en.json`. Logs are developer-facing and stay English.
4. Implement one phase at a time, in order. Do not anticipate F4/F5.
5. Prefer stdlib, small functions, type hints, short docstrings. New dependency requires an ADR.
6. Write tests alongside code; mock the LLM; no network in unit tests.
7. Never add telemetry or cloud LLM calls.
8. **Do not build a document library, ingestion pipeline, embeddings or vector index.** Lexical selection over segments is required.
9. Pipeline stages expose **no tools** to the model: grammar-constrained JSON only; the code performs actions.
10. **Never ask a small model to generate what the code can compute** — offsets, page numbers, dates, numbers, citations, section order, tables, word counts, reference lists. If a field can be derived, it is derived.
11. **Extraction returns ids, not text.** Do not introduce a "write the quote" prompt variant. Only contiguous ranges are valid.
12. Full page text never enters the orchestrator context — segments → notes, always.
13. Synthesis produces `report.json`; rendering and composition are pure code. Never emit Markdown straight from the LLM.
14. Every LLM call passes through the budget governor, the role router and the cache.
15. Tool sets are defined server-side per role; never accepted from the model.
16. Adding a tool, a skill, a model layout **or a length profile** must not require editing the core: profiles are data (§6.3).
17. **Every feature must work with a single endpoint.** Never introduce a code path that requires two models; `dual` is an optimization.
18. **The synthesis rung is never chosen by the model.** A rung is enabled by profile × layout × probe; a claim de-escalates on guard failure; no code path lets the model ask for "more freedom".
19. **No report ships without passing the contract lint.** Bands, mandatory sections and reference completeness are code, not guidelines. A failing lint is a bug in the composer or the profile, never a reason to relax the profile.
20. On phase completion: run tests, `formiga doctor --probe`, `formiga bench`, `formiga lint` on the eval runs, update `docs/`.

---

## 14. Glossary

| Term | Meaning |
|---|---|
| **Run** | One research job, identified by a ULID (`run_id`), owning a budget and a ledger. |
| **Session** | One chat conversation; owns messages and may spawn many runs. |
| **Layout** | Endpoint configuration: `single`, `dual`, `single-strong`, `proxy`. |
| **Tier** | `fast` or `strong` role mapping; both may resolve to the same endpoint. |
| **Source** | A fetched, cached document, deduplicated globally by normalized URL and content hash. |
| **`run_sources`** | The per-run mapping that gives a source its citation number `n`. |
| **Segment** | A numbered sentence (or paragraph fallback) of cached text; the unit of extraction and scoring. |
| **Facet** | One `(entity, aspect)` sub-question produced by stage 1 from a closed aspect enum. |
| **Note** | Structured record of what one source says about one facet (stage 5 output), with code-derived quote/offset/page. |
| **Claim** | A sentence in the report, with citations to notes, produced from selected note ids. |
| **Critical claim** | A claim on a high-stakes topic (§7 item 6) requiring two independent sources. |
| **Profile** | Report length contract: `short`, `medium`, `long`, `thesis`. Fixes word band, skeleton, source floor, budget and deadline. |
| **Contract** | The machine-checkable part of a profile: band, mandatory sections, reference completeness, integrated sections. Checked by `formiga lint`. |
| **Rung** | One step of the synthesis ladder: `assemble`, `bounded-edit`, `anchored-rewrite`. |
| **Rung ceiling** | The highest rung a run may use, set by profile × layout × probe. Not a model choice. |
| **Lexical support** | Fraction of content words in a rewritten claim that come from its cited quotes or the rung's allowed vocabulary; the guard that makes rewriting safe. |
| **Synthesis ratio** | Word-weighted share of claims with ≥2 independent sources; the measurable definition of "integrated answer". |
| **Integrated section** | A section containing at least one sentence with ≥2 citation markers. |
| **Answer box** | The 2–3 sentence direct answer below the title, code-selected from the claim graph. |
| **Resize** | Re-rendering an existing run at another profile from `report.json`; zero fetches, zero LLM calls. |
| **Coverage** | Fraction of claims carrying ≥1 valid citation, measured before cleanup. |
| **Precision** | Fraction of cited claims whose source actually supports them (overlap check). |
| **Confidence** | Deterministic label from source count and conflicts, never model self-assessment. |
| **Ledger** | The run's immutable record of sources, segments, notes, claims and citation numbers. |
| **Composer** | The deterministic stage-9 pass that orders claims, builds tables, the answer box and the TL;DR, then lints the contract. |

---

## 15. Closed decisions

| Question | Decision |
|---|---|
| Name | Command `formiga`, distribution `formiga-cli`. Check PyPI/GitHub availability before first release. |
| Output | `~/formiga/reports/YYYY-MM-DD-<slug>-<run8>.md`; overwrite requires confirmation or `--force` |
| TUI | `rich` + `prompt_toolkit`. Textual only if a real need appears; measure RAM first. |
| Model family | Aliases `small` / `base` / `large` / `moe` bound to concrete GGUFs by shipped `profiles/`. Core never hard-codes a model id; profiles are data and are updated by `bench`. |
| Default layout | **`single`** with one `base` — works on 8 GB. `init` detects RAM and suggests `dual` on ≥14 GB. |
| Recommended layout | **`dual`** on 16 GB: `small` for router/planner/reader, `large`/`moe` for synthesis |
| Model routing | Roles mapped to `fast` and `strong` keys; both may point to the same endpoint; in-process routing by default, `formiga serve --proxy` optional |
| Chat shape | One routing call + one answer call per turn; intents are a closed enum of ten |
| Extraction | Sentence-id selection only, **contiguous ranges**; all derived fields computed by code |
| Synthesis | **Ladder** `assemble → bounded-edit → anchored-rewrite`; ceiling from profile × layout × probe; per-claim fallback on guard failure |
| Report length | **Configurable profile** `short`/`medium`/`long`/`thesis`, default `medium`; `resize` re-renders for free |
| Report structure | Fixed contract per profile (§6.3) + `formiga lint`; answer box and related questions are mandatory above `short` |
| Languages | Code/UI/prompts English; `search_languages` and `output_language` configurable; `pt-BR` as second UI locale; `assemble` cannot cross languages (§3) |
| Claim independence | Distinct domain + distinct content hash + MinHash source distance ≥ 0.2; syndicated copies merged |
| Confidence | Deterministic rule (§7), never model self-assessment |
| Criticality | Model may raise, never lower; deterministic topic list also forces it |
| Platform | Linux only for MVP |
| Data location | Package data via `importlib.resources`; user data under `~/.formiga/` |
| License | MIT |

**ADRs to write in F0:** `001-deterministic-pipeline` · `002-grammar-over-tool-calling` · `003-mandatory-lexical-selection` · `004-report-json-and-rendering` · `005-budget-and-idempotency` · `006-english-code-i18n-ui` · `007-tool-and-skill-registries` · `008-web-fetch-safety` · `009-retention-and-privacy` · `010-extractive-first-pipeline` · `011-role-based-model-routing` · `012-capability-probes` · `013-single-model-parity` · `014-document-contract-and-length-profiles` · `015-synthesis-ladder-and-lexical-support` · `016-source-independence-and-near-dup`

---

## 16. Revision history

**5.3** — The report becomes a contract and synthesis becomes a ladder.

- **Length profiles** (`short | medium | long | thesis`) fix word band, section skeleton, source floor, budget and deadline. Configurable via `[report]`, `--profile`, or chat ("deep research on X, long"). `resize` re-renders from `report.json` with zero fetches and zero LLM calls. New §6.3, FR26–FR28, and a per-profile budget table in §8.4. `thesis` adds a trace-derived methodology section, styled references (`apa|abnt|ieee|mla`), an answerable/open gap split and a deterministic glossary.
- **Synthesis ladder** replaces `assemble | rewrite`: `assemble` → `bounded-edit` (delete ≤20% of tokens + insert from a closed connector list) → `anchored-rewrite` (free text ≤30 words). Per claim, ceiling from profile × layout × probe, automatic one-rung fallback. New §5.1, FR24–FR25, ADR 015. This is what makes a "Perplexity-like" integrated paragraph possible on modest hardware without giving up the structural guarantee.
- **Lexical support guard** (≥0.75 content-word support from quotes ∪ allowed vocabulary) generalizes the numeric guard from numbers to words; it is the check that makes rewriting safe. §7 item 9.
- **Document metrics are now acceptance criteria**: `synthesis_ratio`, integrated sections, distinct domains, word count, reading time, freshness, `quote_reuse`, `rung_distribution`. §7 and §2.
- **Answer box, related questions and a source table** added to the composition pass (all zero-token). §6.2 rules 1, 9 and output shape.
- **Independence fixed**: MinHash source near-dup merge moved from post-MVP into F1; syndicated copies no longer inflate confidence. §5 stage 3, §6.4, §7 item 6, acceptance #22.
- **Language blocker resolved**: `assemble` cannot cross languages; explicit three-path rule with `run.language.upgraded`. §3.
- **Budget formula corrected**: added `call_overhead_s` and an explicit per-layout `overhead_factor` (1.15 `dual`, 1.9 `single`); recomputed every example. The v5.2 estimate was ~2× optimistic on `single` and its MoE example was arithmetically wrong (9 min, not 6). §8.1, §8.4.
- **Model ids de-hardcoded** to shape aliases (`small/base/large/moe`) bound by shipped profile files; the PRD no longer asserts specific tags. §8.1, §15.
- **Consistency fixes**: intents listed = intents tabled (10, adding `resize`); "≤2 calls per turn" scoped to exclude inline research; the 8 tools are dispatched through intents, not by an undefined `orchestrator`; stage numbering 0–9 printed as N/10; `segments` are contiguous ranges (a non-contiguous set could never pass substring verification); FTS5/BM25 selected for stage 4; `notes.source_id`, `run_id` and `segmenter_version` added to schema and idempotency keys; per-source quote cap; search operator templates; `sources.quality` specified.
- **Resume granularity**: stage 5 commits per `(source, facet)`, stage 7 per section (FR30), so a kill loses at most one unit.
- **Fetch/extraction overlap**: bounded fetch pool feeds readers without waiting for every source (FR29).
- **`formiga lint`** added to the CLI and to every phase gate; the contract is a test, not a guideline.

**5.2** — Design review against small-model research literature; pipeline made extractive-first.

- Chat reduced from an 8-iteration ReAct loop to **one routing call + one answer call** per turn, with a closed intent enum and deterministic dispatch. Follow-ups became slots (`expand`, `more_sources`, `compare`).
- Model tiering: `router`, `planner`, `reader` on the fast tier; `synthesizer` on the strong tier. **Single-model layouts are first-class**: `single` (8 GB, one 4B or 2B) is the default, `dual` (16 GB, 2B + 8B/a1b) is the recommendation. Every feature and test works with one endpoint (FR23, ADR 013).
- Stage 1 replaced free-form sub-questions with **facets** (closed aspect enum × entities), plus two free-form queries to avoid taxonomy bias.
- Stage 5 changed to **sentence-id extraction** with `verdict`/`stance`; quote, offset, page, numbers and dates are now computed by code. New `segments` table, FTS5 over segments, new FR18–FR19.
- Stage 6 replaced the LLM coverage judge with a deterministic **coverage matrix**; the model only generates optional query variants (off by default).
- Stage 7 changed to **claim assembly from note ids** with `assemble`/`rewrite` modes chosen by probe; sections reduced to 3–4.
- Stage 9 gained a **composition pass**: TL;DR, auto-tables, auto-timeline, claim dedup, adjacency polish, quote cap; plus progressive publication of `report.md`.
- Verification gained **attribution overlap**, numeric **multiset** comparison, claim dedup, and `citation_precision` as a first-class metric.
- Budgets recomputed: deep 27 calls / 26.4k prompt / 2.1k output. Deadlines are now **per layout** (30 min `dual`, 50 min `single` 4B, 60 min `single` 2B), each validated by the formula.
- Server tuning documented (`-ub 512 -b 1024`, `cache_prompt`, `repeat_penalty 1.0` in JSON mode, no CoT); corrected the v5.1 claim that MoE helps only generation.
- Added per-stage test harness, capability probes, endpoint-degradation and invalid-id acceptance tests, and single-model parity acceptance test.

**5.1** — Consistency and feasibility pass before implementation: `gap_checker` lost its tool, `skill_load` entered the MVP set, budgets gained prompt tokens, storage completed (`sessions`, `messages`, `run_sources`, `citations`, `locator`), `critical` can only be raised, `derivation` became structured, SSRF guard added, cache keys fixed, resume/recovery defined, prompts made English-only, packaged data moved into the package, user journeys/states/glossary/retention/rubric added.

**5.0** — Reframed as a research-capable chat agent; language policy; RAG/ingestion removed; tool and skill registries promoted; two model profiles; roadmap trimmed.
