# 013 · One endpoint is a first-class layout, not a degraded one

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

The target machine is an old CPU with 8 GB of RAM. Requiring two models would exclude the
majority of the users this product is for, and would make every test need two fakes.

## Decision

`single` is the default layout and `init` chooses it unless RAM suggests otherwise. The
pipeline never requires a second endpoint: roles that map to `strong` fall back to `fast`,
and the rung ceiling drops accordingly (ADR 011). Every feature, every test and every F0
acceptance criterion is exercised against one endpoint. `dual` relaxes deadlines and raises
the ceiling; it never unlocks a feature that `single` lacks.

## Consequences

- Profiles are limited on `single` (`short`, `medium`) because the deadline, not the code,
  is what cannot be met; `--allow-heavy` is an explicit override with a longer clock.
- The test suite has one fake backend and stays fast.

## Alternatives considered

Requiring `dual` for research was rejected as excluding the stated target hardware.
