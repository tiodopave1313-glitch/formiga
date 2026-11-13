"""Every user-facing string comes from a JSON catalog in ``data/i18n/locales``.

Adding a language means adding a file; no code change is required. Missing keys fall
back to English, and a missing key in both raises :class:`MissingTranslation` so a typo
fails in tests instead of printing a raw key to a user.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

FALLBACK = "en"
LOCALES_PACKAGE = "formiga.data.i18n.locales"


class MissingTranslation(LookupError):
    """Raised when a key is missing from both the requested locale and English."""


def available_locales() -> list[str]:
    """Return the locale tags shipped inside the package."""
    root = resources.files(LOCALES_PACKAGE)
    return sorted(
        entry.name.removesuffix(".json")
        for entry in root.iterdir()
        if entry.name.endswith(".json")
    )


@cache
def _catalog_for(tag: str) -> dict[str, str]:
    entry = resources.files(LOCALES_PACKAGE).joinpath(f"{tag}.json")
    if not entry.is_file():
        return {}
    try:
        data = json.loads(entry.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - packaging error
        raise ValueError(f"invalid locale catalog: {tag}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"locale catalog must be a JSON object: {tag}")
    return {str(key): str(value) for key, value in data.items()}


def catalog(tag: str) -> dict[str, str]:
    """Return the merged catalog for ``tag``, English first."""
    merged = dict(_catalog_for(FALLBACK))
    if tag and tag != FALLBACK:
        merged.update(_catalog_for(tag))
    return merged


def t(key: str, /, *, locale: str = FALLBACK, **kwargs: object) -> str:
    """Translate ``key`` in ``locale`` and format it with ``kwargs``."""
    messages = catalog(locale)
    try:
        template = messages[key]
    except KeyError as exc:
        raise MissingTranslation(f"missing translation key: {key}") from exc
    if not kwargs:
        return template
    return template.format(**kwargs)


def clear_cache() -> None:
    """Drop memoized catalogs; used by tests that write temporary locales."""
    _catalog_for.cache_clear()


__all__ = ["FALLBACK", "MissingTranslation", "available_locales", "catalog", "clear_cache", "t"]
