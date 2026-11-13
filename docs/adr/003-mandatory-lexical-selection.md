# 003 · Extraction is sentence-id selection and quote text is assembled from ids

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

Asking a model to quote a source invites paraphrase, truncation and the splicing of two
sentences into one. A quote that is not verbatim makes every downstream guarantee - the
substring check, the numeric guard, the attribution overlap - unverifiable.

## Decision

The reader stage sees numbered sentences and returns **contiguous closed ranges of ids**
plus a verdict and a stance. It never returns text. The code then builds the note's quote by
concatenating the exact segments those ids name, and records the character offsets.

The substring check in the verifier therefore becomes structural: the quote *is* the source
text, because the code copied it. Sentence-id fidelity (the share of returned ids that exist
and form valid ranges) is the F0 acceptance metric, targeted at ≥ 98%.

## Consequences

- Quoting is exact by construction; copyright caps can be applied to the rendered copy
  without touching the stored evidence (ADR 009).
- The segmenter becomes a versioned component: changing it invalidates `extract` and
  everything downstream but never a fetch (ADR 005).
- Multi-sentence claims are assembled from several ranges, never from a model-written
  sentence, until the synthesis ladder is allowed to rewrite (ADR 015).

## Alternatives considered

Ask for a quote and verify by substring, rejected because a model that paraphrases merely
fails the check after paying for the call, and a model that splices sentences can produce a
string that *is* a substring of a longer passage while meaning something else.
