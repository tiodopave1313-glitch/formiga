# Stage fixtures

`input -> expected output` for the pipeline stages that consume a model reply, with the LLM
mocked (see `tests/eval/rubric.md`, "Stage harness").

A fixture is a contract. When a prompt or a schema changes the expected ids, the fixture
changes in the same commit, so the diff shows exactly which behaviour moved.

| File | Stage | Pins |
|---|---|---|
| `plan-basic.json` | 1 | facets come from the closed aspect list, entities are preserved |
| `plan-comparison.json` | 1 | a comparison question adds `comparison` |
| `extract-answers.json` | 5 | contiguous closed ranges, ids only |
| `extract-partial.json` | 5 | two separate ranges, not an arbitrary pair |
| `extract-abstain.json` | 5 | `verdict: no` on an absent facet instead of a near neighbour |
| `note-built-by-code.json` | 6 | quote/numbers/derived_by are computed, never generated |
| `synthesize-assemble.json` | 7 | zero freedom: ids only, text concatenated by code |
| `synthesize-bounded-edit.json` | 7 | deletions are indices, insertions are connector ids |
| `synthesize-anchored-rewrite.json` | 7 | <=30 words with the lexical-support floor recorded |
| `lint-medium-ok.json` | 9 | a good medium report lints clean |
| `lint-medium-band.json` | 9 | the word band is enforced |
| `lint-medium-sources.json` | 9 | the source floor is enforced |
