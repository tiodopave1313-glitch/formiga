# 014 · The report is a contract per length profile, checked by lint

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

'Write about 1000 words' is not a specification: without a band, a section skeleton and a
source floor, the output drifts with every run and cannot be accepted or rejected. A
user-facing promise that cannot be checked is not a promise.

## Decision

A profile is a frozen data row (`ProfileSpec`): word band ±10%, section-count band, source
floor, aspect count, gap rounds, LLM-call and token caps, and deadline per layout. The
skeleton marks each section mandatory, optional or absent.

`lint(report)` is deterministic and never mutates a claim. It checks the word band, the
mandatory sections, the thematic section count, the source floor, the integrated-section
share, one-quote-per-note reuse and the thesis claim cap. Sections rendered unconditionally
by the composer - conflicts, gaps, trace, risks - are not violations when empty, because
"no conflicts found" is a valid answer.

Adding a profile is a table row plus a config key; no core edit.

## Consequences

- The same report can be checked in a test, in `formiga lint`, and at the end of a run.
- `resize` re-cuts a document to another profile from `report.json` with no model call.

## Alternatives considered

A single hard-coded length was rejected because the PRD makes length a user choice; a
model-judged length check was rejected because it is neither reproducible nor free.
