# 001 · The pipeline is deterministic and the model only chooses

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

A 2B-4B model running on a 4-core CPU cannot be trusted to hold a multi-step plan
together, to compute offsets, to number citations, or to remember which URL it read. Every
one of those is a place where a small model silently produces plausible but wrong output,
and the failure is invisible in the prose.

## Decision

Every stage returns **ids or a small enum**, never prose and never a derived value.
The stages are fixed and ordered: `reuse → plan → search → fetch → select → extract → gaps →
synthesize → verify → compose` (PRD §5). The model is called at four points only - route,
plan (facets), read (sentence-id ranges), synthesize (ids + edit indices) - and each reply is
validated against a JSON Schema before the code acts on it.

All derived values are computed by code from data the code owns: quotes are the verbatim
concatenation of the selected segment ranges; offsets, pages, dates, numbers, citation
numbers and section order come from the database and the profile table. The model never
emits a citation marker, a URL, a file path or a Markdown document.

## Consequences

- A wrong model reply can only select the *wrong existing thing*; it cannot invent a quote,
  a URL or a number that survives verification.
- Stages are cacheable and resumable by construction: each one has an idempotency key over
  its inputs (ADR 005), so a re-run recomputes only what changed.
- The cost is that adding a genuinely new capability usually means adding a stage or an
  intent, not just changing a prompt.
- Tests can script the model (`FakeLLM`) and assert the code's decisions, which is why the
  suite runs offline in under a second.

## Alternatives considered

A free-form ReAct loop would need a strong model to stay coherent and would make every
failure a probabilistic one, with no place to put a deterministic guard.
