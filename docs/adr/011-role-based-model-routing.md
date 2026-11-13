# 011 · Roles map to two tiers and both tiers may be the same endpoint

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

Routing, extraction and synthesis have different costs and different quality needs. A
2B model routes and extracts well enough; synthesis benefits from a larger one. Hard-coding
that split into call sites would make the single-model layout a second code path.

## Decision

Each role names a tier: `router`, `planner`, `reader` and `gap_queries` on `fast`;
`synthesizer` and `answerer` on `strong`. A layout maps tiers to endpoints, and in the default
`single` layout both tiers resolve to the same endpoint. Nothing in the pipeline knows which.

If the strong tier dies mid-run, its remaining calls move to `fast`, the rung ceiling drops
one step, a `RoutingEvent` is recorded and the report records the degradation. Roles never
fail because a second endpoint is absent.

## Consequences

- Every feature and test runs against one endpoint, which is the F0 acceptance requirement.
- A layout is data: `single`, `dual`, `single-strong` and `proxy` differ only in what the
  tier mapping contains.

## Alternatives considered

A per-role model id in config was rejected: it turns the layout into an arbitrary matrix
that `doctor` and the deadline formula cannot reason about.
