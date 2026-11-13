# 002 · Grammar-constrained JSON instead of native tool calling

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

`llama-server` exposes several ways to get structured output. Native tool calling depends on
a chat template the GGUF may not carry, and on the model having been trained for it; small
models frequently emit a malformed tool call that the server accepts as prose. Free-form JSON
with a "reply with JSON only" instruction fails at a rate that makes repairs expensive.

## Decision

Every structured request carries a JSON Schema derived from a dataclass
(`formiga.llm.schema`). The backend sends it as `response_format: json_schema` when the
endpoint accepts it, and falls back to a GBNF grammar built from the same schema
(`formiga.llm.grammar`) when it does not. The schema, not the prompt, is the contract.

The schema hash is part of the cache key and of the grammar, so a schema change can never
serve a stale-but-valid reply. Validation happens in code regardless: the grammar is a
latency and reliability optimisation, never the correctness boundary.

## Consequences

- One code path serves every backend capability; `doctor` reports when the endpoint fell
  back to grammar-only (`supports_grammar = False`).
- The supported schema subset is deliberately small - flat objects, closed string enums,
  `list[T]`, `dict[str, T]`, `Optional[T]` - because that is what a small model can hit.
- `dataclass_schema` refuses unions other than `Optional[T]` at build time, so an
  unsupported shape fails in a test rather than at 3 a.m. mid-run.

## Alternatives considered

Prompt-only JSON with a repair loop, rejected because two repairs per stage pushes a
`medium` run past its call budget (ADR 005); native tool calling, rejected because it is a
model- and template-specific capability the PRD does not let us assume.
