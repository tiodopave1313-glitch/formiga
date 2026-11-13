# 007 · Tools and skills are data-driven registries behind one permission guard

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

The PRD defines two extension points: tools (PRD §4.3) and skills (PRD §4.4). A registry that
each call site reaches into directly makes the mode table unenforceable, and a skill loader
that executes arbitrary code makes "fully local" a security claim we cannot keep.

## Decision

A tool is described by a declarative record - name, description, JSON Schema for its
arguments, and the modes that may call it. A skill is a directory with a prompt fragment and
a manifest, loaded as text, never executed. `Guard` (ADR per `formiga.core.modes`) is the
single place that answers "may this mode call this tool", and every tool call goes through
it. `plan` is read-only with no network; `research` may search, fetch, read memory and write
inside the output directory only.

Writes are confined by resolved path containment, so `out-evil` is not inside `out`.

## Consequences

- Adding a tool is a record plus an implementation; the mode table stays the only policy.
- Skills cannot escalate: they contribute text, and the tools they suggest still pass the
  guard.
- `build` (F4) is absent from the table, so it denies everything rather than half-allowing.

## Alternatives considered

A plugin system importing arbitrary Python packages was rejected for the MVP: it turns a
local agent into an execution surface and every dependency would need an ADR anyway.
