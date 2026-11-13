# 015 · The synthesis ladder, guarded by lexical support

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

Pure extraction is faithful but reads as a list of quotes. Free rewriting reads better but
lets a small model introduce words the sources do not support, and the old numeric guard only
covered numbers.

## Decision

Three rungs, each with a bounded degree of freedom:

1. `assemble` - claim text is concatenated source sentences; zero freedom.
2. `bounded-edit` - the model may delete up to 20% of tokens and insert connectors from a
   closed list; it returns edit indices, not text.
3. `anchored-rewrite` - the model may write at most 30 words, anchored to the cited notes.

The ceiling per claim comes from profile × layout × capability probe. A guard failure drops
the claim one rung and emits `report.rung.locked`; it never silently accepts the higher rung.

The guard is **lexical support**: the share of content words in the final text that occur in
the cited quotes or in the rung's allowed vocabulary must be ≥ 0.75. It generalises the
numeric guard from numbers to words and is what makes `anchored-rewrite` safe.

## Consequences

- The rung is part of the cache key, so an `assemble` answer can never serve a
  `bounded-edit` request.
- `rung_distribution` is a document metric; `anchored-rewrite` above 40% while `assemble` was
  possible is a report failure.

## Alternatives considered

A single `rewrite` rung was rejected: it gives a small model unconditional freedom and the
old guard could not catch invented words.
