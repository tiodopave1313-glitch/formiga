"""CLI: exit codes, init, doctor, the one-shot ask and the F0 phase gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from formiga.cli import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARTIAL,
    build_app,
    run,
    run_ask,
    run_doctor_command,
    run_init,
)
from formiga.config import ConfigError
from formiga.core.budget import Budget
from formiga.core.init import init_home, render_config


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FORMIGA_HOME", str(home))
    monkeypatch.setenv("FORMIGA_REPORTS_DIR", str(home / "reports"))
    monkeypatch.setenv("FORMIGA_MINIMAL", "1")
    monkeypatch.setenv("FORMIGA_ENDPOINT", "http://127.0.0.1:9")
    return home


def test_version_flag_prints_the_version(isolated_home: Path) -> None:
    result = CliRunner().invoke(build_app(), ["--version"])
    assert result.exit_code == EXIT_OK
    assert result.stdout.strip().count(".") == 2


def test_lang_flag_switches_the_ui(isolated_home: Path) -> None:
    runner = CliRunner()
    english = runner.invoke(build_app(), ["init"])
    portuguese = runner.invoke(build_app(), ["--lang", "pt-BR", "init"])
    assert "Created" in english.stdout or "already exists" in english.stdout
    assert "criado" in portuguese.stdout or "existe" in portuguese.stdout


def test_init_writes_a_config_and_a_database(isolated_home: Path) -> None:
    result = init_home(home=isolated_home, layout="single", ram_gb=8.0)
    assert result.config_written
    assert (isolated_home / "config.toml").exists()
    assert (isolated_home / "formiga.db").exists()
    assert result.profiles == ("short", "medium")


def test_init_on_a_large_machine_chooses_dual(tmp_path: Path) -> None:
    result = init_home(home=tmp_path / "big", ram_gb=16.0)
    assert result.layout == "dual"
    assert "layout.strong" in render_config(layout="dual")


def test_init_is_idempotent_without_force(isolated_home: Path) -> None:
    first = init_home(home=isolated_home, ram_gb=8.0)
    second = init_home(home=isolated_home, ram_gb=8.0)
    assert first.config_written is True
    assert second.config_written is False


def test_init_command_renders_the_layout(isolated_home: Path) -> None:
    assert run_init(lang="en") == EXIT_OK


def test_doctor_passes_without_a_running_server(isolated_home: Path) -> None:
    init_home(home=isolated_home, ram_gb=8.0)
    assert run_doctor_command(lang="en") == EXIT_OK


def test_doctor_json_is_machine_readable(isolated_home: Path, capsys) -> None:
    init_home(home=isolated_home, ram_gb=8.0)
    assert run_doctor_command(lang="en", json_output=True) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["profiles"] == ["short", "medium"]


def test_ask_json_reports_the_intent(isolated_home: Path, capsys,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """``ask --json`` is scriptable: the reply carries the intent and the call count."""
    init_home(home=isolated_home, ram_gb=8.0)

    from formiga.config import Layout
    from formiga.core.budget import Budget
    from formiga.core.chat import ChatSession
    from formiga.core.citations import CitationLedger
    from formiga.llm.fake import FakeLLM
    from formiga.llm.governed import GovernedLLM
    from formiga.llm.router import RoleRouter

    backend = FakeLLM(
        [{"intent": "answer", "query": "say hello"}, {"text": "hello", "note_ids": []}]
    )
    router = RoleRouter(layout=Layout())
    router.backends["fast"] = backend
    session = ChatSession(
        llm=GovernedLLM(backend, Budget(max_llm_calls=5)),
        router=router,
        ledger=CitationLedger(),
    )

    class _Runtime:
        def __init__(self) -> None:
            self.session = session
            self.router = router

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

    monkeypatch.setattr("formiga.runtime.build_runtime", lambda *a, **kw: _Runtime())
    assert run_ask("say hello", lang="en", json_output=True) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["intent"] == "answer"
    assert payload["llm_calls"] == 2


def test_run_maps_budget_exhaustion_to_exit_code_two() -> None:
    def command() -> int:
        budget = Budget(max_llm_calls=0)
        budget.charge_call()
        return EXIT_OK

    assert run(command, locale="en") == EXIT_PARTIAL


def test_run_maps_config_errors_to_exit_code_one() -> None:
    def command() -> int:
        raise ConfigError("bad value")

    assert run(command, locale="en") == EXIT_ERROR


def test_run_maps_keyboard_interrupt_to_130() -> None:
    def command() -> int:
        raise KeyboardInterrupt

    assert run(command, locale="en") == 130


def test_deferred_commands_fail_loudly(isolated_home: Path) -> None:
    result = CliRunner().invoke(build_app(), ["research"])
    assert result.exit_code == EXIT_ERROR
    assert "not available yet" in result.stdout


def test_serve_reports_the_phase_gap(isolated_home: Path) -> None:
    from formiga.cli import run_serve

    assert run_serve(lang="en") == EXIT_ERROR
