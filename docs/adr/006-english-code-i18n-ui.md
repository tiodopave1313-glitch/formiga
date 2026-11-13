# 006 · Code and prompts in English, every user-facing string in a JSON catalog

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

The PRD fixes English for code, comments, logs, schema and docs (PRD §3). The UI must still
ship `pt-BR` as a second locale, and adding a third language must not touch code. Prompts are
a separate question: a small model degrades outside English, and translating prompt files
lets N trees drift apart.

## Decision

- Identifiers, docstrings, log messages, DB columns, JSON keys and ADRs are English.
- Every user-visible string is produced by `t(key, locale=...)` and lives in
  `src/formiga/data/i18n/locales/<tag>.json`. Missing keys fall back to English, and a key
  missing from both raises `MissingTranslation` so a typo fails a test instead of printing a
  raw key.
- Number and date formatting come from a locale table, not from the stdlib `locale` module,
  which is process-global and needs OS locale data.
- Prompts stay English and are selected by `search_languages` (what we search) and
  `output_language` (what the model is asked to write). Translating a prompt requires an ADR
  with benchmark evidence.
- A test walks the AST of `ui/` and fails on a user-facing literal outside `t()`.

## Consequences

- Adding a locale is one file plus one formatting row.
- The `--lang` flag changes the UI with no code edit, which is an F0 acceptance criterion.

## Alternatives considered

gettext/`.po` was rejected: it needs a build step and binary catalogs, and the catalog here
is a few hundred flat keys; localized prompts were rejected because they multiply the
surface a bench must cover.
