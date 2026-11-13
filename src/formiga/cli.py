"""Command-line entry point.

Exit codes are fixed by FR15: ``0`` ok, ``1`` error, ``2`` partial (budget), ``130``
interrupted. They are produced in one place, :func:`run`, so a subcommand can never invent
a new code.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from formiga import __version__
from formiga.config import ConfigError, Settings, load_settings
from formiga.core.budget import BudgetExceeded
from formiga.core.doctor import run_doctor, suggested_layout, total_ram_gb
from formiga.core.init import init_home, init_messages
from formiga.i18n import MissingTranslation, t
from formiga.ui import make_ui

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PARTIAL = 2
EXIT_INTERRUPTED = 130

ENV_LANGUAGE = "FORMIGA_LANGUAGE"


class CliContext:
    """Resolved settings plus the rendering helpers for one invocation."""

    def __init__(self, settings: Settings, *, json_output: bool = False) -> None:
        self.settings = settings
        self.json_output = json_output
        self.ui = make_ui(settings.language)

    @property
    def locale(self) -> str:
        return self.settings.language

    def emit(self, message: str) -> None:
        self.ui.say(message)

    def emit_json(self, payload: Any) -> None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _resolve_language(lang: str | None) -> str:
    return lang or os.environ.get(ENV_LANGUAGE) or "en"


def build_app() -> typer.Typer:
    """Build the Typer application."""
    app = typer.Typer(
        name="formiga",
        help=t("app.tagline", locale=_resolve_language(None)),
        add_completion=False,
        no_args_is_help=False,
        context_settings={"help_option_names": ["-h", "--help"]},
    )

    @app.callback(invoke_without_command=True)
    def main_callback(
        ctx: typer.Context,
        lang: str = typer.Option(None, "--lang", help=t("cli.lang_help")),
        json_output: bool = typer.Option(False, "--json", help=t("cli.json_help")),
        version: bool = typer.Option(False, "--version", is_eager=True),
    ) -> None:
        """Run the REPL when no subcommand is given."""
        if version:
            typer.echo(__version__)
            raise typer.Exit(EXIT_OK)
        ctx.obj = {"lang": _resolve_language(lang), "json": json_output}
        if ctx.invoked_subcommand is None:
            raise typer.Exit(run_repl_command(lang=_resolve_language(lang)))

    @app.command("ask")
    def ask_command(
        ctx: typer.Context,
        question: str = typer.Argument(..., help=t("cli.ask_help")),
        profile: str = typer.Option(None, "--profile", help=t("cli.profile_help")),
    ) -> None:
        """Ask one question and print the answer."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_ask(question, lang=lang, profile=profile,
                                 json_output=(ctx.obj or {}).get("json", False)))

    @app.command("init")
    def init_command(
        ctx: typer.Context,
        layout: str = typer.Option(None, "--layout", help=t("cli.layout_help")),
        force: bool = typer.Option(False, "--force", help=t("cli.force_help")),
    ) -> None:
        """Create the configuration directory and database."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_init(lang=lang, layout=layout, force=force,
                                  json_output=(ctx.obj or {}).get("json", False)))

    @app.command("doctor")
    def doctor_command(
        ctx: typer.Context,
        probe: bool = typer.Option(False, "--probe", help=t("cli.probe_help")),
    ) -> None:
        """Check the environment."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_doctor_command(lang=lang, probe=probe,
                                            json_output=(ctx.obj or {}).get("json", False)))

    @app.command("bench")
    def bench_command(ctx: typer.Context) -> None:
        """Measure generation and prefill speed."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_bench(lang=lang, json_output=(ctx.obj or {}).get("json", False)))

    @app.command("serve")
    def serve_command(ctx: typer.Context) -> None:
        """Launch the servers the layout requires."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_serve(lang=lang))

    for deferred in ("research", "runs", "resume", "cancel", "report", "lint", "verify",
                     "sources", "logs", "cache", "forget", "prune", "memory"):
        _register_deferred(app, deferred)

    return app


def _register_deferred(app: typer.Typer, name: str) -> None:
    """Register a later-phase command that fails loudly instead of pretending."""

    @app.command(name, help=f"(later phase) {name}")
    def _deferred(ctx: typer.Context) -> None:
        lang = (ctx.obj or {}).get("lang", "en")
        make_ui(lang).error(t("error.not_implemented", locale=lang, command=name))
        raise typer.Exit(EXIT_ERROR)


def run(
    command: Callable[[], int],
    *,
    locale: str = "en",
    json_output: bool = False,
) -> int:
    """Run one command, mapping every failure onto a fixed exit code."""
    try:
        return command()
    except BudgetExceeded as exc:
        _report_budget(exc, locale=locale, json_output=json_output)
        return EXIT_PARTIAL
    except ConfigError as exc:
        _fail(t("error.config_invalid", locale=locale, reason=str(exc)), locale, json_output)
        return EXIT_ERROR
    except MissingTranslation as exc:
        _fail(t("error.unknown", locale="en", reason=str(exc)), locale, json_output)
        return EXIT_ERROR
    except KeyboardInterrupt:
        make_ui(locale).error(t("error.interrupted", locale=locale))
        return EXIT_INTERRUPTED


def _report_budget(exc: BudgetExceeded, *, locale: str, json_output: bool) -> None:
    snapshot = exc.snapshot
    used = {
        "llm_calls": snapshot.llm_calls,
        "prompt_tokens": snapshot.prompt_tokens,
        "output_tokens": snapshot.output_tokens,
        "deadline": round(snapshot.elapsed_s),
    }
    if json_output:
        print(json.dumps({"status": "incomplete", "cap": exc.reason,
                          "used": used.get(exc.reason, 0), **snapshot.as_dict()}))
        return
    make_ui(locale).error(
        t("error.budget", locale=locale, cap=exc.reason,
          used=used.get(exc.reason, 0), unit=exc.reason.replace("_", " "))
    )


def _fail(message: str, locale: str, json_output: bool) -> None:
    if json_output:
        print(json.dumps({"status": "error", "message": message}))
        return
    make_ui(locale).error(message)


def _settings(lang: str, *, profile: str | None = None) -> Settings:
    overrides: dict[str, Any] = {}
    if profile:
        overrides["report"] = {"profile": profile}
    return load_settings(cli_overrides=overrides)


def run_ask(question: str, *, lang: str, profile: str | None = None,
            json_output: bool = False) -> int:
    """One-shot question: route, dispatch, print."""

    def command() -> int:
        settings = _settings(lang, profile=profile)
        from formiga.runtime import build_runtime

        with build_runtime(settings, profile=profile) as runtime:
            turn = runtime.session.run_turn(question)
        if json_output:
            print(json.dumps({
                "text": turn.text,
                "intent": turn.intent.value,
                "note_ids": turn.note_ids,
                "sourced": turn.sourced,
                "degraded": turn.degraded,
                "llm_calls": turn.llm_calls,
            }, ensure_ascii=False))
        else:
            make_ui(lang).say(turn.text)
        return EXIT_OK

    return run(command, locale=lang, json_output=json_output)


def run_repl_command(*, lang: str) -> int:
    """Bare ``formiga``: the interactive loop."""

    def command() -> int:
        settings = _settings(lang)
        from formiga.runtime import build_runtime
        from formiga.ui.repl import run_repl

        with build_runtime(settings) as runtime:
            return run_repl(runtime.session, make_ui(lang))

    return run(command, locale=lang)


def run_init(*, lang: str, layout: str | None = None, force: bool = False,
             json_output: bool = False) -> int:
    """Create the home directory, config and database."""

    def command() -> int:
        result = init_home(layout=layout, language=lang, force=force)
        if json_output:
            print(json.dumps(result.as_dict(), ensure_ascii=False))
        else:
            ui = make_ui(lang)
            for message in init_messages(result, locale=lang):
                ui.say(message)
        return EXIT_OK

    return run(command, locale=lang, json_output=json_output)


def run_doctor_command(*, lang: str, probe: bool = False, json_output: bool = False) -> int:
    """Check the environment; failures exit 1 so CI can gate on it."""

    def command() -> int:
        settings = _settings(lang)
        report = run_doctor(settings, probe_endpoints=probe)
        if json_output:
            print(json.dumps(report.as_dict(), ensure_ascii=False))
        else:
            ui = make_ui(lang)
            ui.say(t("doctor.title", locale=lang))
            for check in report.checks:
                if check.skipped or check.ok:
                    ui.say(f"{check.name}: {check.detail}")
                else:
                    ui.failed(check.name, check.detail)
            ui.say(t("doctor.profiles", locale=lang, profiles=", ".join(report.profiles)))
            ui.say(t("doctor.rungs", locale=lang, rungs=", ".join(report.rungs)))
            ui.say(t("doctor.all_ok" if report.ok else "doctor.some_failed",
                     locale=lang, count=len(report.failures)))
        return EXIT_OK if report.ok else EXIT_ERROR

    return run(command, locale=lang, json_output=json_output)


def run_bench(*, lang: str, json_output: bool = False) -> int:
    """Measure the endpoints and append the numbers to ``docs/benchmarks.md``."""

    def command() -> int:
        from formiga.core.bench import (
            BenchResult,
            measure_endpoint,
            peak_rss_mb,
            write_benchmarks,
        )

        settings = _settings(lang)
        result = BenchResult(layout=settings.layout.name)
        for tier, endpoint in settings.layout.tiers.items():
            result.tiers[tier] = measure_endpoint(endpoint)
        result.peak_rss_mb = peak_rss_mb()
        docs = Path(__file__).resolve().parents[2] / "docs" / "benchmarks.md"
        write_benchmarks(docs, result)
        if json_output:
            print(json.dumps(result.as_dict(), ensure_ascii=False))
        else:
            make_ui(lang).say(json.dumps(result.as_dict(), ensure_ascii=False))
        return EXIT_OK

    return run(command, locale=lang, json_output=json_output)


def run_serve(*, lang: str) -> int:
    """``serve`` needs a model path, which F0 does not bind yet."""
    make_ui(lang).error(t("error.not_implemented", locale=lang, command="serve"))
    return EXIT_ERROR


def main() -> None:
    """Console-script entry point."""
    app = build_app()
    exit_code = run(lambda: _invoke(app), locale=_resolve_language(None))
    raise SystemExit(exit_code)


def _invoke(app: typer.Typer) -> int:
    try:
        app()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_OK
        return code
    return EXIT_OK


__all__ = [
    "EXIT_ERROR",
    "EXIT_INTERRUPTED",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "build_app",
    "main",
    "run",
    "suggested_layout",
    "total_ram_gb",
]
