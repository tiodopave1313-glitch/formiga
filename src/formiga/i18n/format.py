"""Table-driven date and number formatting.

The stdlib ``locale`` module is process-global, not thread-safe and requires OS locale
data that minimal containers do not ship. Locale conventions therefore live in a table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Conventions:
    """Separators used when formatting a number."""

    decimal_sep: str = "."
    thousands_sep: str = ","
    date_order: str = "mdy"
    date_sep: str = "/"


CONVENTIONS: dict[str, Conventions] = {
    "en": Conventions(decimal_sep=".", thousands_sep=",", date_order="mdy", date_sep="/"),
    "pt-BR": Conventions(decimal_sep=",", thousands_sep=".", date_order="dmy", date_sep="/"),
}


def conventions_for(tag: str) -> Conventions:
    """Return conventions for ``tag``, falling back to English."""
    return CONVENTIONS.get(tag, CONVENTIONS["en"])


def format_number(value: float, *, locale: str = "en", decimals: int = 0) -> str:
    """Format ``value`` with grouped thousands and locale separators."""
    rules = conventions_for(locale)
    grouped = f"{value:,.{decimals}f}"
    # ``format`` always emits ``,`` and ``.``; swap them through a placeholder so a
    # locale where both differ never collides.
    grouped = grouped.replace(",", "\x00").replace(".", rules.decimal_sep)
    return grouped.replace("\x00", rules.thousands_sep)


def format_date(value: date, *, locale: str = "en") -> str:
    """Format ``value`` in the locale's field order."""
    rules = conventions_for(locale)
    day, month, year = f"{value.day:02d}", f"{value.month:02d}", f"{value.year:04d}"
    parts = {"d": day, "m": month, "y": year}
    return rules.date_sep.join(parts[token] for token in rules.date_order)


__all__ = ["CONVENTIONS", "Conventions", "conventions_for", "format_date", "format_number"]
