"""``formiga bench``: measure what the deadline formula consumes.

The deadline in §8.4 is derived from measured generation and prefill speed, never from
the placeholders in the PRD. Speeds and the overhead factor are written to
``docs/benchmarks.md``; a slower machine relaxes the deadline, it never shrinks the
profile silently.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from formiga.config import Endpoint
from formiga.research.contract import DEFAULT_PROFILES

#: Prompts used to measure each direction; kept tiny so a bench run is not a run.
PREFILL_PROMPT = "Explain in one sentence what a soil pH buffer does. " * 24
GENERATE_PROMPT = "List three uses of lime in agriculture, one per line."


def prefill_probe() -> str:
    """The prefill prompt with a nonce, so the server cannot answer from its prompt cache.

    ``llama-server`` keeps a prefix cache by design (PRD §8.3). A bench that reuses the
    same prompt twice therefore measures a cache hit - the first run on this machine
    reported 225 t/s and an immediate re-run reported 1,888 t/s for the *same* endpoint.
    Both numbers were real; only one of them was prefill.
    """
    return f"[bench {uuid.uuid4().hex}] {PREFILL_PROMPT}"

CALL_OVERHEAD_S = 0.25
#: Overhead factors from PRD §8.4; measured, never tuned down to fit a deadline.
OVERHEAD_FACTOR = {"dual": 1.15, "single": 1.9, "single-strong": 1.3, "proxy": 1.15}
FETCH_SECONDS = {"short": 80, "medium": 220, "long": 300, "thesis": 300}


class BenchUnavailable(RuntimeError):
    """Raised when an endpoint cannot be measured because it is not answering."""

    def __init__(self, endpoint: str, reason: str) -> None:
        self.endpoint = endpoint
        self.reason = reason
        super().__init__(f"endpoint {endpoint} is not answering: {reason}")


@dataclass
class Speed:
    """One measurement of an endpoint."""

    generate_tps: float
    prefill_tps: float
    output_tokens: int = 0
    input_tokens: int = 0

    def as_dict(self) -> dict[str, float]:
        return {
            "generate_tps": round(self.generate_tps, 2),
            "prefill_tps": round(self.prefill_tps, 2),
        }


@dataclass
class BenchResult:
    """Speeds per tier plus peak RSS of the agent process."""

    tiers: dict[str, Speed] = field(default_factory=dict)
    peak_rss_mb: float = 0.0
    layout: str = "single"
    #: Tiers that could not be measured, mapped to the reason. A bench run is still
    #: useful with one tier down, so these are reported, never raised.
    failures: dict[str, str] = field(default_factory=dict)
    measured_on: str = field(default_factory=lambda: date.today().isoformat())

    def as_dict(self) -> dict[str, object]:
        return {
            "layout": self.layout,
            "measured_on": self.measured_on,
            "peak_rss_mb": round(self.peak_rss_mb, 1),
            "tiers": {tier: speed.as_dict() for tier, speed in self.tiers.items()},
            "failures": dict(self.failures),
        }


def estimate_seconds(
    profile: str,
    *,
    layout: str,
    speed: Speed,
    use_caps: bool = False,
) -> float:
    """Apply the corrected deadline formula of PRD §8.4."""
    spec = DEFAULT_PROFILES[profile]
    column = 1 if use_caps else 0
    prompt_tokens = spec.prompt_tokens[column]
    output_tokens = spec.output_tokens[column]
    calls = spec.llm_calls[column]
    model_s = (
        prompt_tokens / max(speed.prefill_tps, 0.01)
        + output_tokens / max(speed.generate_tps, 0.01)
        + calls * CALL_OVERHEAD_S
    )
    factor = OVERHEAD_FACTOR.get(layout, 1.9)
    return model_s * factor + FETCH_SECONDS.get(profile, 200)


def estimate_table(result: BenchResult, *, layout: str | None = None) -> dict[str, float]:
    """Estimated wall-clock per profile for the measured speeds."""
    layout = layout or result.layout
    speed = _slowest(result.tiers)
    if speed is None:
        return {}
    return {
        name: round(estimate_seconds(name, layout=layout, speed=speed))
        for name in DEFAULT_PROFILES
    }


def _slowest(tiers: dict[str, Speed]) -> Speed | None:
    if not tiers:
        return None
    return min(tiers.values(), key=lambda speed: speed.generate_tps)


def measure_endpoint(endpoint: Endpoint, *, client: object | None = None) -> Speed:
    """Measure prefill and generation speed with two short requests."""
    from formiga.llm.base import BackendUnavailable
    from formiga.llm.client import HTTPLLM
    from formiga.llm.types import CompletionRequest, Message

    backend = client if client is not None else HTTPLLM(endpoint, profile_name="bench")
    try:
        probe = prefill_probe()
        prefill_request = CompletionRequest(
            messages=(Message(role="user", content=probe),),
            temperature=0.0,
            max_tokens=1,
        )
        started = time.monotonic()
        prefill = backend.complete(prefill_request)  # type: ignore[attr-defined]
        prefill_elapsed = max(time.monotonic() - started, 1e-6)
        prompt_tokens = prefill.input_tokens or len(probe.split())

        generate_request = CompletionRequest(
            messages=(Message(role="user", content=GENERATE_PROMPT),),
            temperature=0.0,
            max_tokens=128,
            stop=("\n\n",),
        )
        started = time.monotonic()
        generated = backend.complete(generate_request)  # type: ignore[attr-defined]
        generate_elapsed = max(time.monotonic() - started, 1e-6)
        output_tokens = generated.output_tokens or len(generated.content.split())
        return Speed(
            generate_tps=output_tokens / generate_elapsed,
            prefill_tps=prompt_tokens / prefill_elapsed,
            output_tokens=output_tokens,
            input_tokens=prompt_tokens,
        )
    except BackendUnavailable as exc:
        raise BenchUnavailable(endpoint.endpoint, str(exc)) from exc
    finally:
        if client is None:
            backend.close()  # type: ignore[attr-defined]


def peak_rss_mb() -> float:
    """Peak resident set size of this process, in MB."""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def write_benchmarks(path: Path, result: BenchResult, *, locale: str = "en") -> Path:
    """Append a measurement section to ``docs/benchmarks.md``."""
    lines = [
        f"## {result.measured_on} · layout `{result.layout}`",
        "",
        f"- peak agent RSS: {result.peak_rss_mb:.1f} MB",
        "",
        "| tier | gen t/s | prefill t/s |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {tier} | {speed.generate_tps:.1f} | {speed.prefill_tps:.1f} |"
        for tier, speed in result.tiers.items()
    )
    if result.failures:
        lines.extend(["", "Unmeasured tiers:", ""])
        lines.extend(f"- `{tier}`: {reason}" for tier, reason in result.failures.items())
    estimates = estimate_table(result)
    if estimates:
        lines.extend(["", "| profile | estimated minutes |", "|---|---|"])
        lines.extend(f"| {name} | {seconds / 60:.1f} |" for name, seconds in estimates.items())
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Benchmarks\n"
    path.write_text(existing.rstrip() + "\n\n" + "\n".join(lines), encoding="utf-8")
    return path


def rss_env() -> dict[str, str]:
    """Environment for the benchmark subprocess; documented, not magic."""
    return {**os.environ, "FORMIGA_BENCH": "1"}


__all__ = [
    "CALL_OVERHEAD_S",
    "FETCH_SECONDS",
    "OVERHEAD_FACTOR",
    "BenchResult",
    "BenchUnavailable",
    "Speed",
    "estimate_seconds",
    "estimate_table",
    "measure_endpoint",
    "peak_rss_mb",
    "prefill_probe",
    "rss_env",
    "write_benchmarks",
]
