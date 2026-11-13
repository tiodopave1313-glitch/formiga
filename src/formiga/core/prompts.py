"""Prompt loading from packaged data.

Prompts are English only and versioned by ``prompt_version``. The system prompt of a role
must be **byte-identical** across calls: no dates, no locale, no run ids in the prefix,
because a changed prefix throws away the server's KV cache (PRD §8.3).
"""

from __future__ import annotations

from functools import cache
from importlib import resources

PROMPTS_PACKAGE = "formiga.data.prompts.en"

#: Prompt version recorded in the cache key and the report frontmatter.
PROMPT_VERSION = "0.1.0"

ROLES = ("router", "answerer", "planner", "reader", "synthesizer", "gap_queries")


class PromptMissing(LookupError):
    """Raised when a role has no packaged prompt."""


@cache
def system_prompt(role: str) -> str:
    """Return the stable system prompt of ``role``, byte-identical across calls."""
    if role not in ROLES:
        raise PromptMissing(f"unknown prompt role: {role}")
    entry = resources.files(PROMPTS_PACKAGE).joinpath(f"{role}.md")
    if not entry.is_file():
        raise PromptMissing(f"missing prompt for role: {role}")
    return entry.read_text(encoding="utf-8").strip()


def prompt_version() -> str:
    return PROMPT_VERSION


__all__ = ["PROMPT_VERSION", "ROLES", "PromptMissing", "prompt_version", "system_prompt"]
