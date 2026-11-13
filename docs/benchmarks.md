# Benchmarks

Measured, never estimated. The numbers below feed the deadline formula in PRD §8.4, and the
formula is the reason a run's clock is what it is.

`formiga bench` appends a section to this file every time it runs. Nothing here is edited by
hand except the *deterministic check* at the bottom, which validates that the shipped
constants still reproduce the PRD's worked examples.

## What `formiga bench` measures

Two short requests per configured endpoint:

| Measurement | How | Why |
|---|---|---|
| **prefill t/s** | one request with a ~1.2k-token prompt and `max_tokens = 1` | Prefill is the real bottleneck on CPU; extraction is mostly prompt |
| **generate t/s** | one request capped at 128 output tokens | Synthesis is bounded by generation |
| **peak RSS** | `VmHWM` of the agent process at the end | The PRD promises the agent stays under 1 GB |

The two speeds plus the fixed per-call overhead and the per-layout overhead factor produce the
estimate:

```
t = Σ_stages ( prompt_tokens_stage / prefill_tps + output_tokens_stage / gen_tps
               + call_overhead_s ) × overhead_factor
    + fetch_s
```

Constants shipped in `formiga.core.bench`:

| Constant | Value | Source |
|---|---|---|
| `CALL_OVERHEAD_S` | 0.25 s | HTTP + JSON parse + governor bookkeeping (PRD §8.4) |
| `OVERHEAD_FACTOR["dual"]` | 1.15 | retries, re-prefill after grammar/slot switch, KV evictions |
| `OVERHEAD_FACTOR["single"]` | 1.90 | the same, plus tier switching on one server |
| `OVERHEAD_FACTOR["single-strong"]` | 1.30 | strong model, no tier switching |
| `OVERHEAD_FACTOR["proxy"]` | 1.15 | same as `dual` |
| `FETCH_SECONDS["short"]` | 80 s | search + fetch, non-overlapping with model time |
| `FETCH_SECONDS["medium"]` | 220 s | |
| `FETCH_SECONDS["long"]` | 300 s | |
| `FETCH_SECONDS["thesis"]` | 300 s | |

A profile is *supportable* on a layout when the estimate fits the deadline with headroom. When
it does not, the profile is reduced (sections first, then sources) and `run.incomplete.budget`
is recorded with the exact cap - **the guarantee is never quietly shrunk**.

## Measured on the reference machine

Two consecutive runs of `formiga bench` on 2026-11-13, `dual` layout, 4-core CPU,
15.5 GB RAM, `llama-server` on :8080 and nothing listening on :8081:

| tier | gen t/s | prefill t/s | status |
|---|---|---|---|
| `fast` (`small`) | 15.2 / 15.5 | 65.4 / 63.0 | measured, reproducible |
| `strong` (`large`) | — | — | not running at the time |
| peak agent RSS | — | — | **40.5 MB** (budget: < 1 GB) |

Estimates from the first run (15.2 gen / 65.4 prefill t/s) against the §8.4 deadlines:

| profile | estimate | `dual` deadline | headroom |
|---|---|---|---|
| `short` | 3.5 min | 6 min | ✓ |
| `medium` | 15.4 min | 30 min | ✓ |
| `long` | 23.4 min | 45 min | ✓ |
| `thesis` | 34.7 min | 90 min | ✓ |

### Three things this bench taught us

**Prefill is fast, generation is not.** 63-65 t/s of prefill against 15 t/s of generation
on a 4-core CPU means the per-profile cost is driven by **output tokens and per-call
overhead**, not by prompt length. That is the premise the extraction-heavy design rests
on, and it held: at 15 t/s of generation every `dual` profile fits its deadline with
room to spare.

**A benchmark can silently measure the prompt cache.** The first run reported **225
prefill t/s** and an immediate re-run reported **1,888 t/s** for the same endpoint: both
were prefix-cache hits, because `llama-server` keeps a prefix cache by design (PRD §8.3).
`bench` now prefixes the probe with a random nonce (`prefill_probe()`), and
`tests/unit/test_bench.py` fails if that nonce ever becomes deterministic again. **Any
number recorded before that fix is an upper bound, not a measurement.**

**A tier being down does not abort the bench.** `formiga bench` records the failure,
measures what it can, appends the section and exits **2** (partial) - the same contract as
a budget-exhausted run. Nothing is ever written for a tier that was not measured.

Re-run `formiga bench` after changing models or thread counts: every number above is a
measurement of one machine on one day, not a specification.

## Model aliases

Ids are placeholders maintained by this file and by `profiles/`, never by the core (PRD §8.1).
The PRD names shapes; a release binds each alias to a concrete GGUF and records it here.

| Alias | Shape | Weights (Q4_K_M) | Reference gen / prefill | Status |
|---|---|---|---|---|
| `small` | dense 2B | ~1.3-1.5 GB | ~15 / ~45 t/s | placeholder - no artefact confirmed yet |
| `base` | dense 4B | ~2.4-2.6 GB | ~8 / ~30 t/s | placeholder - no artefact confirmed yet |
| `large` | dense 8B | ~4.7-5.0 GB | ~5 / ~18 t/s | placeholder - no artefact confirmed yet |
| `moe` | MoE 8B, ~1B active | ~4.5-5.0 GB | ~11 / ~35 t/s | placeholder - no artefact confirmed yet |

**Open item (F0 gate):** confirm the exact repository and quant tag for each alias before a
release claims them. Until then `doctor` reports
`model alias <alias> is not bound to a concrete GGUF yet` and no speed in this table is a
measurement.

## Measurements

_Sections below are appended by `formiga bench` on the machine that ran it. A section records
the date, the layout, the speeds per tier and the resulting estimate per profile._

## Deterministic check of the shipped constants

`tests/unit/test_bench.py` pins the formula against the PRD's worked examples without touching
a model: monotonicity across profiles, `single` costing more than `dual`, a slower generation
rate raising the estimate, zero speeds not dividing by zero, fetch time dominating the
`short` profile, and the prefill probe carrying a fresh nonce. If someone changes a constant
to make a deadline fit, that test is the place where the change becomes visible in review.
