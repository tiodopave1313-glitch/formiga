# 016 · Independence means a distinct domain, a distinct hash and a MinHash distance

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

Three syndicated copies of one press release are one source. A citation count that treats
them as three independent confirmations is a lie that the confidence rule then amplifies.

## Decision

Two sources are independent only when they differ in **registrable domain**, in **content
hash**, and in **MinHash source distance ≥ 0.2**. Near-duplicates below that distance are
merged, keeping the earliest retrieved copy and recording aliases.

Critical claims require at least two independent sources and a clean numeric guard, or they
are downgraded to `[unverified]`. Claims are deduplicated by MinHash before numbering, so
'two independent sources' means two sources, not two paraphrases.

Confidence is then computed deterministically from the merged set: high at ≥3 independent
sources with no open conflict, medium at 2 or a minor conflict, low otherwise.

## Consequences

- The numeric and lexical guards are cheap, but independence is what makes a corroborated
  claim actually corroborated.
- Merging keeps the ledger honest: one entry with aliases, not three entries inflating the
  source count.

## Alternatives considered

Counting distinct URLs was rejected as trivially gameable by mirrors and syndication;
running an entailment model per pair was rejected as a second model and a dependency.
