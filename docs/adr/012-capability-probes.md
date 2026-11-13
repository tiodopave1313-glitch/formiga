# 012 · Capabilities are probed and the probe result lowers the ceiling

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

A layout is a promise about what the pipeline may do. An endpoint that rejects
`response_format`, or a model that cannot follow a strict JSON schema, quietly breaks the
guarantee the rest of the code assumes.

## Decision

`formiga doctor --probe` runs a small set of capability checks against each configured
endpoint: liveness, JSON-schema acceptance, grammar acceptance, and a short structured reply
that validates. The result is not advisory: a failed schema check drops the endpoint's rung
ceiling and is recorded in the run's diagnostics, so the report states the level of synthesis
it was actually able to guarantee.

## Consequences

- `doctor` gates a run; a degraded endpoint is visible before the run, not after.
- `HTTPLLM` flips `supports_grammar` to `False` for the process on the first rejected
  request, so a mid-run degradation is also recorded.

## Alternatives considered

Assuming capability from the model name was rejected: the PRD keeps model ids as
placeholders maintained by `bench` (ADR 013), so the name carries no guarantee.
