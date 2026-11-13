# Architecture Decision Records

Every decision that would be expensive to reverse is recorded here before the code that
depends on it lands. An ADR is *superseded*, never edited into a different decision; a new
ADR replaces it and both stay on disk.

The rules the ADRs enforce, in one line each:

| # | Decision | Why it matters |
|---|---|---|
| [001](001-deterministic-pipeline.md) | The model chooses, the code decides | A wrong reply can only select the wrong existing thing |
| [002](002-grammar-over-tool-calling.md) | Schema-derived grammar, not native tool calling | One path, no template assumption, validated anyway |
| [003](003-mandatory-lexical-selection.md) | Extraction returns contiguous sentence ids | The quote check becomes structural, not probabilistic |
| [004](004-report-json-and-rendering.md) | `report.json` plus a pure renderer | `resize` and re-styling cost zero tokens |
| [005](005-budget-and-idempotency.md) | Budget governor plus stage keys | A 45-minute run resumes instead of restarting |
| [006](006-english-code-i18n-ui.md) | English code, catalog UI, English prompts | New locale = one file; prompts stay benchmarkable |
| [007](007-tool-and-skill-registries.md) | Registries behind one permission guard | The mode table is the only policy |
| [008](008-web-fetch-safety.md) | Bounded fetches over search-supplied URLs | SSRF by construction, not by blocklist |
| [009](009-retention-and-privacy.md) | Local data, explicit retention, quote caps | The "fully local" claim is auditable |
| [010](010-extractive-first-pipeline.md) | Extract by default | Faithfulness before fluency on small models |
| [011](011-role-based-model-routing.md) | Roles → tiers → endpoints | Layout is data; a dead tier degrades |
| [012](012-capability-probes.md) | Probe, then lower the ceiling | A degraded endpoint is visible before the run |
| [013](013-single-model-parity.md) | `single` is first-class | 8 GB machines are the target, not a fallback |
| [014](014-document-contract-and-length-profiles.md) | Profiles as data plus `lint` | A length promise is checkable |
| [015](015-synthesis-ladder-and-lexical-support.md) | `assemble → bounded-edit → anchored-rewrite` | Bounded freedom, guarded by lexical support |
| [016](016-source-independence-and-near-dup.md) | Domain + hash + MinHash distance | Three copies of one press release are one source |

## Writing a new ADR

1. Copy the structure of the closest existing ADR: *Context*, *Decision*, *Consequences*,
   *Alternatives considered*, plus a status and the phase it belongs to.
2. Name it `NNN-short-slug.md` with the next free number.
3. Add the row to the table above.
4. A new runtime dependency always needs an ADR; so does a change to the language policy, the
   schema, or a PRD non-goal.
