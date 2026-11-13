# 005 · A per-run budget governor and stage idempotency keys

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

A `medium` run costs 31-45 calls and roughly 28-40k prompt tokens. On a CPU that is tens of
minutes of wall clock. A run that dies at stage 7 must not start over, and a run that is
allowed to ignore its caps will burn an afternoon and produce nothing.

## Decision

Two mechanisms, both mandatory.

**Budget.** Every LLM request passes through `GovernedLLM`, which charges the run's `Budget`
before sending. Caps for calls, prompt tokens, output tokens and wall clock come from the
profile row (PRD §8.4). Exhaustion raises `BudgetExceeded` once, the run is marked
`incomplete`, the partial report is still written, and the exit code is 2. A cache hit still
charges one call, so a resumed run cannot loop for free.

**Idempotency.** Each stage unit has a key over
`sha256(stage ‖ dependency hashes ‖ layout ‖ prompt_version ‖ schema_version ‖ segmenter_version ‖ profile)`.
The dependency DAG records what a change invalidates, so a segmenter bump re-runs `extract`
and downstream but not `fetch`, and switching profile never refetches a page. Committed
stages are replayed from `stage_runs`.

## Consequences

- `formiga resume` works because the keys, not the model, decide what is already done.
- The cache key includes `grammar_hash` and `rung`, so a schema or ladder change cannot serve
  an answer that no longer satisfies its contract.
- Budget accounting lives in one object; no stage is allowed to call a backend directly.

## Alternatives considered

A per-call timeout without a run budget, rejected because it bounds a single request and
not the run; recomputing every stage on resume, rejected because a 45-minute run would
restart at minute 44.
