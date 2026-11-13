# 010 · Extractive first: the report is built from selected source sentences

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

Generative summarisation from a small model is the failure mode this project exists to
avoid: fluent, confident, and untraceable. On 8-16 GB of RAM with a 2B-4B model, fluency and
faithfulness are not simultaneously affordable.

## Decision

The default synthesis rung is `assemble`: a claim is built from one or more selected notes,
so its text is source text and its citations are the notes it was built from. Selection,
not generation, is what the model does. Higher rungs (`bounded-edit`, `anchored-rewrite`) are
available only when the profile, the layout and the capability probe all permit them, and
each is guarded (ADR 015).

Every claim carries the citations of the notes it used, and the verifier can therefore check
attribution overlap, numeric support and lexical support without trusting the model.

## Consequences

- The default output reads as curated evidence rather than as an essay. That is the honest
  trade on this hardware, and the ladder exists to improve it where the machine allows.
- `assemble` cannot cross languages: it can only concatenate sentences that exist in the
  source language, which the docs state plainly.

## Alternatives considered

Summarise-then-cite was rejected because a citation added after the fact certifies nothing;
abstractive summary with a claim-level entailment model was rejected as a second model and a
dependency the PRD does not allow.
