"""The REPL and the UI layer: no markup swallowing, no hardcoded literals, clean exit."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from formiga.config import Layout
from formiga.core.budget import Budget
from formiga.core.chat import ChatSession
from formiga.core.citations import CitationLedger
from formiga.core.intents import Intent
from formiga.i18n import t
from formiga.llm.fake import FakeLLM
from formiga.llm.governed import GovernedLLM
from formiga.llm.router import RoleRouter
from formiga.ui import Ui, make_ui
from formiga.ui.repl import format_turn, run_repl


class _ScriptedReader:
    """Feeds lines one at a time, then raises EOF - exactly like a real terminal."""

    def __init__(self, *lines: str) -> None:
        self._lines = list(lines)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


def _session(script) -> ChatSession:
    backend = FakeLLM(script)
    router = RoleRouter(layout=Layout())
    router.backends["fast"] = backend
    llm = GovernedLLM(backend, Budget(max_llm_calls=20, max_output_tokens=10_000))
    return ChatSession(llm=llm, router=router, ledger=CitationLedger(), language="en")


def _ui(locale: str = "en") -> tuple[Ui, io.StringIO]:
    buffer = io.StringIO()
    return Ui(locale=locale, minimal=True, stdout=buffer), buffer


def test_a_question_gets_an_answer_and_the_loop_ends_on_eof() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "hi"},
            {"text": "Hello.", "note_ids": []},
        ]
    )
    ui, out = _ui()
    code = run_repl(session, ui, read_line=_ScriptedReader("hi"))
    assert code == 0
    text = out.getvalue()
    assert t("chat.greeting", locale="en") in text
    assert "Hello." in text
    assert t("chat.goodbye", locale="en") in text


def test_slash_quit_exits_without_a_model_call() -> None:
    session = _session([])
    ui, out = _ui()
    code = run_repl(session, ui, read_line=_ScriptedReader("/quit"))
    assert code == 0
    assert session.llm.calls == 0
    assert t("chat.goodbye", locale="en") in out.getvalue()


def test_slash_help_prints_the_catalog_help() -> None:
    session = _session([])
    ui, out = _ui()
    run_repl(session, ui, read_line=_ScriptedReader("/help", "/quit"))
    assert t("chat.help", locale="en") in out.getvalue()


def test_a_bare_slash_is_help_not_a_question() -> None:
    session = _session([])
    ui, out = _ui()
    run_repl(session, ui, read_line=_ScriptedReader("/", "/quit"))
    assert t("chat.help", locale="en") in out.getvalue()
    assert session.llm.calls == 0


def test_empty_input_is_not_sent_to_the_model() -> None:
    session = _session([])
    ui, out = _ui()
    run_repl(session, ui, read_line=_ScriptedReader("   ", "/quit"))
    assert t("chat.empty_input", locale="en") in out.getvalue()
    assert session.llm.calls == 0


def test_keyboard_interrupt_at_the_prompt_exits_cleanly() -> None:
    session = _session([])
    ui, _ = _ui()

    def interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    assert run_repl(session, ui, read_line=interrupt) == 0


def test_the_prompt_comes_from_the_catalog() -> None:
    session = _session([])
    ui, _ = _ui()
    reader = _ScriptedReader("/quit")
    run_repl(session, ui, read_line=reader)
    assert reader.prompts[0] == t("chat.prompt", locale="en")


def test_the_prompt_follows_the_session_language() -> None:
    session = _session([])
    session.language = "pt-BR"
    ui, _ = _ui("pt-BR")
    reader = _ScriptedReader("/quit")
    run_repl(session, ui, read_line=reader)
    assert reader.prompts[0] == t("chat.prompt", locale="pt-BR")
    assert reader.prompts[0] != t("chat.prompt", locale="en")


def test_previous_turns_are_forwarded_as_history() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "second"},
            {"text": "Second reply.", "note_ids": []},
        ]
    )
    ui, _ = _ui()
    run_repl(
        session,
        ui,
        read_line=_ScriptedReader("second", "/quit"),
        history=[("first question", "first reply")],
    )
    contents = [message.content for message in session.llm.backend.requests[0].messages]
    assert "first question" in contents
    assert "first reply" in contents


def test_turns_accumulate_within_the_session() -> None:
    session = _session(
        [
            {"intent": "answer", "query": "one"},
            {"text": "Reply one.", "note_ids": []},
            {"intent": "answer", "query": "two"},
            {"text": "Reply two.", "note_ids": []},
        ]
    )
    ui, _ = _ui()
    run_repl(session, ui, read_line=_ScriptedReader("one", "two", "/quit"))
    contents = [message.content for message in session.llm.backend.requests[2].messages]
    assert "one" in contents
    assert any(content.startswith("Reply one.") for content in contents)


def test_format_turn_prefixes_with_the_catalog_label() -> None:
    from formiga.core.chat import Turn

    turn = Turn(text="answer text", intent=Intent.ANSWER)
    rendered = format_turn(turn, "en")
    assert rendered == f"{t('chat.reply_prefix', locale='en')}answer text"


# --- UI -------------------------------------------------------------------------------


def test_ui_does_not_parse_rich_markup() -> None:
    """A citation marker ``[1]`` must survive; Rich would eat it as a style tag."""
    buffer = io.StringIO()
    ui = Ui(locale="en", minimal=False, stdout=buffer)
    ui.say("see [1] and [bold]not bold[/bold]")
    text = buffer.getvalue()
    assert "[1]" in text
    assert "[bold]" in text


def test_minimal_ui_writes_to_the_injected_stream() -> None:
    buffer = io.StringIO()
    Ui(locale="en", minimal=True, stdout=buffer).say("plain")
    assert buffer.getvalue().strip() == "plain"


def test_ui_error_goes_to_the_error_stream() -> None:
    out, err = io.StringIO(), io.StringIO()
    Ui(locale="en", minimal=True, stdout=out, stderr=err).error("boom")
    assert out.getvalue() == ""
    assert err.getvalue().strip() == "boom"


def test_ui_ok_uses_the_catalog_string() -> None:
    buffer = io.StringIO()
    Ui(locale="en", minimal=True, stdout=buffer).ok("Database")
    assert t("doctor.check_ok", locale="en", name="Database") in buffer.getvalue()


def test_ui_failed_uses_the_catalog_string() -> None:
    buffer = io.StringIO()
    Ui(locale="en", minimal=True, stdout=buffer).failed("Database", "broken")
    assert "failed (broken)" in buffer.getvalue()


def test_make_ui_honours_formiga_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORMIGA_MINIMAL", "1")
    assert make_ui("en").minimal is True
    monkeypatch.delenv("FORMIGA_MINIMAL")
    assert make_ui("en").minimal is False


def test_make_ui_takes_an_explicit_override() -> None:
    assert make_ui("en", minimal=True).minimal is True


def test_the_repl_never_requires_a_tty(tmp_path: Path) -> None:
    """``run_repl`` is driven by an injected reader, so piping works and CI can run it."""
    session = _session([])
    ui, _ = _ui()
    assert run_repl(session, ui, read_line=_ScriptedReader("/quit")) == 0
