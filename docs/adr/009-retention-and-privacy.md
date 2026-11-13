# 009 · Local-only data with explicit retention and a rendered-quote cap

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

The product claim is "fully local, no telemetry, no cloud LLM". That claim has to be
verifiable from the filesystem, not just asserted. At the same time the run database stores
fetched text and verbatim quotes, which are other people's copyrighted words.

## Decision

- Everything lives under `~/.formiga/` and `~/formiga/reports/`; `docs/uninstall.md` lists
  the exact paths and uninstall is a documented `rm -rf`.
- Retention is per store and explicit (PRD §6.5): page cache 30 days, `events.jsonl` rotated
  at 10 MB keeping three, chat history and reports kept until the user removes them, run
  database pruned by `formiga prune --older-than`.
- Rendered quotes are capped at `max_quote_chars` per citation and
  `max_quote_chars_per_source` per source, always with URL and access timestamp and a link
  to the original. `report.json` keeps the full verified quote for auditing; only the
  human-facing copy is truncated.
- `memory_save`, messages and notes reject content matching a conservative secret pattern
  set, and log the rejection. This is an accident guard, not a security boundary, and the
  docs say so.
- There is no telemetry and no cloud backend; every model endpoint is a user-configured
  local URL.

## Consequences

- A user can audit what is stored and delete any store without breaking the others.
- Copyright exposure is bounded on the rendered artefact while the evidence stays auditable.

## Alternatives considered

Encrypting the local database was rejected: the threat model is a local user reading their
own disk, and key management would add a dependency and a failure mode without changing who
can read the data.
