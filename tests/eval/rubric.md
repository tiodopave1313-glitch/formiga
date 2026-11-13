# Evaluation rubric

The eval set scores *output*, never the model's opinion of its own output. The LLM is never
the judge: scoring is done by a human against the table below, and the deterministic checks
(the verifier and `lint`) run first so a human only judges what the code cannot.

## Scoring

Each item is scored **0-2** on six axes. An item passes with **≥ 1.5 average and no zero on
*Source use*** - a plausible-sounding report with no real sources fails regardless of how well
it reads.

| Axis | 0 | 1 | 2 |
|---|---|---|---|
| **Correctness** | wrong or unsupported | partly correct | correct and directly answers the question |
| **Source use** | no real sources | cited but thin | ≥2 independent, relevant, quoted sources |
| **Integration** | mosaic of quotes | some linking, mostly one-source sentences | sources genuinely compared and merged |
| **Gap honesty** | invents certainty | silent about gaps | names gaps and conflicts explicitly |
| **Readability** | unusable as prose | readable but list-like | organized: answer box, TL;DR, sections, tables where useful |
| **Length fit** | far off the profile | inside band, padded or thin | inside band, every section earns its place |

### What the deterministic checks cover before a human looks

| Check | Where | Failure means |
|---|---|---|
| Every `[n]` resolves to a ledger source | verifier | citation chain broken - automatic fail |
| Quote is a verbatim substring of cached text | verifier | extraction fabricated text - automatic fail |
| Numeric guard (multiset, normalized) | verifier | a number was invented - automatic fail |
| Attribution overlap ≥ 0.60 | verifier | the claim does not say what the source says - flag |
| Lexical support ≥ 0.75 | verifier | the rung drifted from its quotes - one-rung fallback |
| Critical claim has 2 independent sources | verifier | downgrade to `[unverified]` |
| Word band ±10%, mandatory sections, source floor | `lint` | contract violated - automatic fail |

A human scores only the items that survived those checks. This is deliberate: judging
correctness by eye is expensive and unreliable, so the code removes the cheap failure modes
first.

## Eval set composition

At least 20 questions, covering:

| Kind | Count | What it exercises |
|---|---|---|
| PDF-sourced | ≥ 2 | page-number citations, extraction from a PDF |
| Known conflict | ≥ 2 | the conflicts section, stance, confidence |
| Sensitive topic | ≥ 2 | the forced `critical` list, risks section, professional notice |
| Unanswerable | 1 | must report a gap, never fabricate |
| Multi-entity comparison | 1 | the auto-generated comparison table |
| Syndicated pair | ≥ 3 | independence: mirrors must merge, not inflate |
| Thesis-grade | ≥ 2 | methodology section, styled references, glossary |
| Short profile | ≥ 2 | the smallest band and source floor |

## How the set runs

Three times, in CI:

1. `single` layout with the strong tier mocked to the same endpoint.
2. `dual` layout.
3. `dual` with `thesis` on the subset that supports it.

Each run records: pass/fail per item, the deterministic check results, the document metrics
(`synthesis_ratio`, `integrated_sections`, `domains`, `word_count`, `reading_minutes`,
`quote_reuse`, `rung_distribution`), the budget snapshot and the contract result.

## Acceptance thresholds

| Metric | F0-F1 | F2 (MVP) | Notes |
|---|---|---|---|
| Items at ≥ 1.5 average | - | ≥ 7/10 | per batch |
| `synthesis_ratio` (`medium`) | - | ≥ 0.30 | below the profile floor is a fail |
| `integrated_sections` | - | 100% | every section needs one multi-source sentence |
| Citation coverage | 100% | 100% | every `[n]` resolves |
| Sentence-id fidelity | ≥ 98% | ≥ 98% | share of reader ids that exist and form valid ranges |
| Repairs in 100 grammar-constrained calls | 0 | 0 | per model, per probe |
| `lexical_support` on any shipped claim | - | ≥ 0.75 | else the claim dropped a rung |
| Peak agent RSS | < 1 GB | < 1 GB | measured by `bench` |

## Stage harness

`tests/fixtures/stages/` holds `input → expected output` pairs for stages 1 (plan), 5
(extract), 6 (notes), 7 (synthesize, all three rungs) and 9 (contract lint), with the LLM
mocked. An end-to-end eval alone cannot tell you *which* stage regressed; the harness can.

Each fixture is a small JSON file:

```json
{
  "stage": "extract",
  "input": { "facet": "mechanism", "segments": ["..."] },
  "expected": { "verdict": "answers", "segments": [[3, 5]], "stance": "supports" }
}
```

A fixture is a contract: if a prompt change alters the expected ids, the fixture changes in the
same commit, and the diff shows exactly which behaviour moved.
