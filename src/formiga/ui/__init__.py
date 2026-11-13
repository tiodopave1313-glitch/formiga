"""Terminal output. Every user-visible string comes from the catalog via ``t()``."""

from __future__ import annotations

import os
from typing import Any, TextIO

from formiga.i18n import t


class Ui:
    """A thin wrapper over Rich that degrades to plain ``print`` with FORMIGA_MINIMAL=1.

    ``markup`` is off: user text and model output must never be parsed as Rich markup,
    or a stray ``[1]`` citation would be swallowed as a style tag.
    """

    def __init__(
        self,
        *,
        locale: str = "en",
        minimal: bool = False,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self.locale = locale
        self.minimal = minimal
        self._stdout = stdout
        self._stderr = stderr
        self._console: Any = None
        if not minimal:
            try:
                from rich.console import Console

                self._console = Console(file=stdout, highlight=False, markup=False)
            except ImportError:  # pragma: no cover - minimal environments
                self.minimal = True

    def say(self, message: str) -> None:
        self._write(message, stream="out")

    def error(self, message: str) -> None:
        self._write(message, stream="err")

    def ok(self, label: str, detail: str = "") -> None:
        if detail:
            self.say(f"{label}: {detail}")
            return
        self.say(t("doctor.check_ok", locale=self.locale, name=label))

    def failed(self, label: str, reason: str) -> None:
        self.say(t("doctor.check_fail", locale=self.locale, name=label, reason=reason))

    def _write(self, message: str, *, stream: str) -> None:
        if self._console is not None:
            self._console.print(message, markup=False, highlight=False)
            return
        handle = self._stderr if stream == "err" else self._stdout
        print(message, file=handle if handle is not None else None)


def make_ui(locale: str = "en", *, minimal: bool | None = None) -> Ui:
    """Build the UI, honouring ``FORMIGA_MINIMAL`` for the stdlib fallback path."""
    if minimal is None:
        minimal = os.environ.get("FORMIGA_MINIMAL", "") == "1"
    return Ui(locale=locale, minimal=minimal)


__all__ = ["Ui", "make_ui"]
