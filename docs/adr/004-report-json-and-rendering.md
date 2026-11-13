# 004 · A report.json tree rendered by a pure template

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

The report must be previewable, resizable to another length profile, re-rendered in another
citation style, and linted against a contract - all without the network and without another
model call. A Markdown string produced once cannot do any of that.

## Decision

The document is a dataclass tree (`formiga.research.report`): `Report` → `Section` →
`Claim` → `Citation`, plus sources, tables, timeline, conflicts, gaps and metrics. It is
serialised to `report.json` (schema version 3) at the end of synthesis.

Markdown is produced by a pure renderer over that tree, with no model involvement. `resize`,
citation-style changes, and `lint` operate on the JSON and are therefore free: zero fetches,
zero LLM calls. Word counts, reading time and the contract band are computed from the tree.

## Consequences

- `formiga resize` and a second citation style are O(document) CPU work.
- The renderer is testable by comparing strings, and the tree is testable by asserting
  structure - neither test needs a model.
- Schema changes require a migration note, because `report.json` outlives a run.

## Alternatives considered

Streaming Markdown straight from the model was rejected: it cannot be resized, cannot be
linted before rendering, and hands the model control of citation numbering.
