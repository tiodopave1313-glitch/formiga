"""The interactive REPL: bare ``formiga``.

Reads a line, runs one turn, prints the answer. Commands start with ``/`` so a question
that happens to be one word is never hijacked. Ctrl-C cancels the line, Ctrl-D exits.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from formiga.core.chat import ChatSession, Turn
from formiga.i18n import t
from formiga.ui import Ui


def run_repl(
    session: ChatSession,
    ui: Ui,
    *,
    read_line: Callable[[str], str] | None = None,
    history: list[tuple[str, str]] | None = None,
) -> int:
    """Run turns until EOF or ``/quit``. Returns the process exit code."""
    read = read_line or _reader(ui)
    ui.say(t("chat.greeting", locale=session.language))
    turns: list[tuple[str, str]] = list(history or ())

    while True:
        try:
            line = read(t("chat.prompt", locale=session.language)).strip()
        except (EOFError, KeyboardInterrupt):
            ui.say("")
            ui.say(t("chat.goodbye", locale=session.language))
            return 0

        if not line:
            ui.say(t("chat.empty_input", locale=session.language))
            continue
        if line.startswith("/"):
            code = _command(line, session, ui)
            if code is not None:
                return code
            continue

        turn = session.run_turn(line, history=_as_messages(turns))
        turns.append((line, turn.text))
        ui.say(format_turn(turn, session.language))


def _command(line: str, session: ChatSession, ui: Ui) -> int | None:
    name = line[1:].strip().lower()
    if name in {t("repl.quit", locale=session.language), "quit", "exit", "q"}:
        ui.say(t("chat.goodbye", locale=session.language))
        return 0
    if name in {t("repl.help", locale=session.language), "help", "h", ""}:
        ui.say(t("chat.help", locale=session.language))
        return None
    ui.say(t("chat.help", locale=session.language))
    return None


def _as_messages(turns: list[tuple[str, str]]) -> tuple:
    from formiga.llm.types import Message

    messages: list[Message] = []
    for user, assistant in turns:
        messages.append(Message(role="user", content=user))
        messages.append(Message(role="assistant", content=assistant))
    return tuple(messages)


def format_turn(turn: Turn, locale: str = "en") -> str:
    """Prefix a turn with the catalog label, never a hardcoded literal."""
    prefix = t("chat.reply_prefix", locale=locale)
    return f"{prefix}{turn.text}"


def _reader(ui: Ui) -> Callable[[str], str]:
    """Return a line reader: prompt_toolkit when available, else ``input()``."""
    if os.environ.get("FORMIGA_MINIMAL") == "1":
        return input
    try:
        from prompt_toolkit import PromptSession
    except ImportError:  # pragma: no cover - minimal environments
        return input
    prompt_session: PromptSession[str] = PromptSession()
    return prompt_session.prompt


def is_interactive() -> bool:
    return sys.stdin.isatty()


__all__ = ["format_turn", "is_interactive", "run_repl"]
