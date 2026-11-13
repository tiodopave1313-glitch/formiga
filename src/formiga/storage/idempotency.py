"""Idempotency keys and the stage DAG.

A stage's key is ``sha256(stage ‖ dependency hashes ‖ layout ‖ prompt_version ‖
schema_version ‖ segmenter_version ‖ profile)``. The dependency edges encode what a
change invalidates, so bumping the segmenter never discards a fetch and changing a
profile never refetches a page.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

PROMPT_VERSION = "0.1.0"
SEGMENTER_VERSION = "1"
SCHEMA_VERSION = "3"

STAGES = (
    "reuse",
    "plan",
    "search",
    "fetch",
    "select",
    "extract",
    "gaps",
    "synthesize",
    "verify",
    "compose",
)

#: Downstream stages invalidated by each stage.
DEPENDENTS: dict[str, tuple[str, ...]] = {
    "reuse": ("plan",),
    "plan": ("search", "select", "extract", "gaps", "synthesize"),
    "search": ("fetch", "select", "extract", "gaps", "synthesize"),
    "fetch": ("select", "extract", "gaps", "synthesize"),
    "select": ("extract", "gaps", "synthesize"),
    "extract": ("gaps", "synthesize", "verify", "compose"),
    "gaps": ("search", "synthesize"),
    "synthesize": ("verify", "compose"),
    "verify": ("compose",),
    "compose": (),
}


def canonical_json(data: Any) -> str:
    """Serialise ``data`` deterministically so equal inputs hash equally."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stage_key(
    stage: str,
    *,
    dependency_hashes: Mapping[str, str] | Iterable[str] = (),
    layout: str = "single",
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    segmenter_version: str = SEGMENTER_VERSION,
    profile: str = "medium",
    extra: Any = None,
) -> str:
    """Return the idempotency key of one stage for one unit of work."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    deps: list[str]
    if isinstance(dependency_hashes, Mapping):
        deps = [f"{key}={value}" for key, value in sorted(dependency_hashes.items())]
    else:
        deps = sorted(dependency_hashes)
    material = canonical_json(
        {
            "stage": stage,
            "deps": deps,
            "layout": layout,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "segmenter_version": segmenter_version,
            "profile": profile,
            "extra": extra,
        }
    )
    return sha256_text(material)


def llm_cache_key(
    *,
    prompt: str,
    model: str,
    temperature: float,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    grammar_hash: str = "",
    rung: str = "",
) -> str:
    """Cache key for a model response (PRD §6.4).

    ``grammar_hash`` and ``rung`` are part of the key on purpose: without them a schema
    change serves stale-but-valid JSON and an ``assemble`` answer answers a
    ``bounded-edit`` request.
    """
    material = canonical_json(
        {
            "prompt": prompt,
            "model": model,
            "temperature": temperature,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "grammar_hash": grammar_hash,
            "rung": rung,
        }
    )
    return sha256_text(material)


def invalidated_by(stage: str) -> tuple[str, ...]:
    """Return every stage that a change to ``stage`` forces to re-run."""
    seen: list[str] = []
    queue = list(DEPENDENTS.get(stage, ()))
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.append(current)
        queue.extend(DEPENDENTS.get(current, ()))
    return tuple(seen)


__all__ = [
    "DEPENDENTS",
    "PROMPT_VERSION",
    "SCHEMA_VERSION",
    "SEGMENTER_VERSION",
    "STAGES",
    "canonical_json",
    "invalidated_by",
    "llm_cache_key",
    "sha256_text",
    "stage_key",
]
