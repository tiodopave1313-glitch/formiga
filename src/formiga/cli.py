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


def _settings(lang: str, *, profile: str | None = None,
              language_is_flag: bool = False) -> Settings:
    """Load settings for one command.

    ``--lang`` is a CLI choice and therefore outranks the config file (PRD §9
    precedence). Applying it only when the flag was actually passed keeps a config that
    sets ``language`` from being silently overridden by the default.
    """
    overrides: dict[str, Any] = {}
    if language_is_flag:
        overrides["language"] = lang
    if profile:
        overrides["report"] = {"profile": profile}
    return load_settings(cli_overrides=overrides)


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
        ctx.obj = {
            "lang": _resolve_language(lang),
            "lang_is_flag": lang is not None,
            "json": json_output,
        }
        if ctx.invoked_subcommand is None:
            raise typer.Exit(run_repl_command(lang=_resolve_language(lang),
                                              language_is_flag=lang is not None))

    @app.command("ask")
    def ask_command(
        ctx: typer.Context,
        question: str = typer.Argument(..., help=t("cli.ask_help")),
        profile: str = typer.Option(None, "--profile", help=t("cli.profile_help")),
    ) -> None:
        """Ask one question and print the answer."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_ask(question, lang=lang, profile=profile,
                                 language_is_flag=_lang_flag(ctx),
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
                                  language_is_flag=_lang_flag(ctx),
                                  json_output=(ctx.obj or {}).get("json", False)))

    @app.command("doctor")
    def doctor_command(
        ctx: typer.Context,
        probe: bool = typer.Option(False, "--probe", help=t("cli.probe_help")),
    ) -> None:
        """Check the environment."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_doctor_command(lang=lang, probe=probe,
                                            language_is_flag=_lang_flag(ctx),
                                            json_output=(ctx.obj or {}).get("json", False)))

    @app.command("bench")
    def bench_command(ctx: typer.Context) -> None:
        """Measure generation and prefill speed."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_bench(lang=lang, language_is_flag=_lang_flag(ctx),
                          json_output=(ctx.obj or {}).get("json", False)))

    @app.command("serve")
    def serve_command(
        ctx: typer.Context,
        dry_run: bool = typer.Option(False, "--dry-run", help=t("cli.serve_dry_run_help")),
    ) -> None:
        """Launch the servers the layout requires."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_serve(lang=lang, dry_run=dry_run, language_is_flag=_lang_flag(ctx),
                                   json_output=(ctx.obj or {}).get("json", False)))

    @app.command("lint")
    def lint_command(
        ctx: typer.Context,
        target: str = typer.Argument(None, help=t("cli.lint_help")),
    ) -> None:
        """Check a report against its profile contract."""
        lang = (ctx.obj or {}).get("lang", "en")
        raise typer.Exit(run_lint(target, lang=lang, language_is_flag=_lang_flag(ctx),
                                  json_output=(ctx.obj or {}).get("json", False)))

    for deferred in ("research", "runs", "resume", "cancel", "report", "verify",
                     "sources", "logs", "cache", "forget", "prune", "memory"):
        _register_deferred(app, deferred)

    return app


def _lang_flag(ctx: typer.Context) -> bool:
    """True when ``--lang`` was passed, so the config file cannot override it."""
    return bool((ctx.obj or {}).get("lang_is_flag", False))


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


def run_ask(question: str, *, lang: str, profile: str | None = None,
            language_is_flag: bool = False, json_output: bool = False) -> int:
    """One-shot question: route, dispatch, print."""

    def command() -> int:
        settings = _settings(lang, profile=profile, language_is_flag=language_is_flag)
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


def run_repl_command(*, lang: str, language_is_flag: bool = False) -> int:
    """Bare ``formiga``: the interactive loop."""

    def command() -> int:
        settings = _settings(lang, language_is_flag=language_is_flag)
        from formiga.runtime import build_runtime
        from formiga.ui.repl import run_repl

        with build_runtime(settings) as runtime:
            return run_repl(runtime.session, make_ui(lang))

    return run(command, locale=lang)


def run_init(*, lang: str, layout: str | None = None, force: bool = False,
             language_is_flag: bool = False, json_output: bool = False) -> int:
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


def run_doctor_command(*, lang: str, probe: bool = False,
                       language_is_flag: bool = False, json_output: bool = False) -> int:
    """Check the environment; failures exit 1 so CI can gate on it."""

    def command() -> int:
        settings = _settings(lang, language_is_flag=language_is_flag)
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


def run_bench(*, lang: str, language_is_flag: bool = False,
              json_output: bool = False) -> int:
    """Measure the endpoints and append the numbers to ``docs/benchmarks.md``."""

    def command() -> int:
        from formiga.core.bench import (
            BenchResult,
            BenchUnavailable,
            measure_endpoint,
            peak_rss_mb,
            write_benchmarks,
        )

        settings = _settings(lang, language_is_flag=language_is_flag)
        result = BenchResult(layout=settings.layout.name)
        for tier, endpoint in settings.layout.tiers.items():
            try:
                result.tiers[tier] = measure_endpoint(endpoint)
            except BenchUnavailable as exc:
                # A tier that is down must not abort the whole bench: the other tier's
                # numbers are still the input the deadline formula needs.
                result.failures[tier] = exc.reason
        result.peak_rss_mb = peak_rss_mb()
        ui = make_ui(lang)
        if not result.tiers:
            if json_output:
                print(json.dumps(result.as_dict(), ensure_ascii=False))
            else:
                ui.error(t("bench.no_tiers", locale=lang))
                for tier, reason in result.failures.items():
                    ui.error(t("bench.unavailable", locale=lang, tier=tier, reason=reason))
            return EXIT_ERROR

        docs = Path(__file__).resolve().parents[2] / "docs" / "benchmarks.md"
        write_benchmarks(docs, result)
        if json_output:
            print(json.dumps(result.as_dict(), ensure_ascii=False))
            return EXIT_OK
        for tier, reason in result.failures.items():
            ui.error(t("bench.unavailable", locale=lang, tier=tier, reason=reason))
        ui.say(t("bench.written", locale=lang, path=str(docs)))
        ui.say(json.dumps(result.as_dict(), ensure_ascii=False))
        return EXIT_OK if not result.failures else EXIT_PARTIAL

    return run(command, locale=lang, json_output=json_output)


def run_serve(*, lang: str, dry_run: bool = False, language_is_flag: bool = False,
              json_output: bool = False) -> int:
    """Start one ``llama-server`` per configured tier, or say why it cannot."""

    def command() -> int:
        from formiga.core.serve import launch, plan_server, port_of

        settings = _settings(lang, language_is_flag=language_is_flag)
        plans = [
            plan_server(tier, endpoint)
            for tier, endpoint in settings.layout.tiers.items()
        ]
        result = launch(plans, dry_run=dry_run)
        if json_output:
            print(json.dumps({
                "layout": settings.layout.name,
                "dry_run": dry_run,
                "started": [
                    {"tier": plan.tier, "port": port_of(plan.endpoint),
                     "command": plan.command}
                    for plan in result.started
                ],
                "skipped": [
                    {"tier": plan.tier, "reason": plan.skipped_reason}
                    for plan in result.skipped
                ],
            }, ensure_ascii=False))
            return EXIT_OK if result.started else EXIT_ERROR

        ui = make_ui(lang)
        ui.say(t("serve.title", locale=lang, layout=settings.layout.name))
        for plan in result.started:
            port = port_of(plan.endpoint)
            if dry_run:
                ui.say(t("serve.dry_run", locale=lang, tier=plan.tier, port=port,
                         command=" ".join(plan.command)))
            else:
                model = plan.command[plan.command.index("--model") + 1]
                ui.say(t("serve.started", locale=lang, tier=plan.tier, port=port,
                         model=model))
        for plan in result.skipped:
            ui.error(_serve_reason(plan, locale=lang))
        if not result.started:
            ui.error(t("serve.nothing_started", locale=lang))
            return EXIT_ERROR
        return EXIT_OK

    return run(command, locale=lang, json_output=json_output)


def _serve_reason(plan: Any, *, locale: str) -> str:
    reasons = {
        "binary_missing": "serve.binary_missing",
        "model_path_unset": "serve.model_path_unset",
        "model_missing": "serve.model_missing",
        "endpoint_unparsable": "serve.endpoint_unparsable",
    }
    key = reasons.get(plan.skipped_reason, "serve.model_path_unset")
    return t(key, locale=locale, tier=plan.tier, endpoint=plan.endpoint,
             path=plan.model_path or plan.endpoint)


def run_lint(target: str | None, *, lang: str,
             language_is_flag: bool = False, json_output: bool = False) -> int:
    """Run the document contract over a persisted report."""

    def command() -> int:
        from formiga.core.lint import LintError, find_report, lint_path

        settings = _settings(lang, language_is_flag=language_is_flag)
        try:
            path = find_report(target, settings.paths.reports)
            outcome = lint_path(path)
        except LintError as exc:
            if json_output:
                print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            else:
                make_ui(lang).error(t("lint.error", locale=lang, path=target or "reports",
                                      reason=str(exc)))
            return EXIT_ERROR

        if json_output:
            print(json.dumps({
                "ok": outcome.ok,
                "path": str(outcome.path),
                "profile": outcome.report.profile,
                "violations": outcome.violations,
            }, ensure_ascii=False))
            return EXIT_OK if outcome.ok else EXIT_ERROR

        ui = make_ui(lang)
        ui.say(t("lint.title", locale=lang, path=str(outcome.path)))
        if outcome.ok:
            ui.say(t("lint.ok", locale=lang, profile=outcome.report.profile))
            return EXIT_OK
        for violation in outcome.violations:
            ui.error(t("lint.violation", locale=lang, check=violation["check"],
                       detail=violation["detail"]))
        return EXIT_ERROR

    return run(command, locale=lang, json_output=json_output)


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
