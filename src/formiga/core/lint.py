"""``formiga lint``: check a persisted report against its profile contract.

The contract check itself lives in :func:`formiga.research.contract.lint` and is
deterministic. This module only finds a ``report.json`` and turns the result into
messages: no model, no network, no rewriting of the report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from formiga.research.contract import lint as contract_lint
from formiga.research.report import Report, report_from_dict


class LintError(RuntimeError):
    """Raised when a report cannot be located or parsed."""


@dataclass
class LintOutcome:
    """One report, its parsed tree and the contract verdict."""

    path: Path
    report: Report
    ok: bool
    violations: list[dict[str, str]]


def find_report(target: str | None, reports_dir: Path) -> Path:
    """Resolve ``formiga lint <target>`` to a ``report.json``.

    ``target`` may be a file, a run id, a run directory, or a report stem. With no target
    the newest report in the reports directory is used, which is what a phase gate wants.
    """
    if target:
        candidate = Path(target).expanduser()
        if candidate.is_file():
            return candidate
        if candidate.is_dir():
            nested = candidate / "report.json"
            if nested.is_file():
                return nested
            raise LintError(f"no report.json in {candidate}")
        for pattern in (f"{target}.json", f"*{target}*report.json", f"*{target}*/report.json"):
            matches = sorted(reports_dir.glob(pattern))
            if matches:
                return matches[-1]
        raise LintError(f"no report matches {target!r} in {reports_dir}")

    if not reports_dir.is_dir():
        raise LintError(f"reports directory {reports_dir} does not exist")
    matches = sorted(reports_dir.rglob("report.json"))
    if not matches:
        raise LintError(f"no report.json under {reports_dir}")
    return max(matches, key=lambda path: path.stat().st_mtime)


def load_report(path: Path) -> Report:
    """Read ``report.json``; a schema the build does not know is an error, not a guess."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LintError(f"{path} does not exist") from exc
    except json.JSONDecodeError as exc:
        raise LintError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LintError(f"{path} does not contain a report object")
    try:
        return report_from_dict(payload)
    except (KeyError, ValueError, TypeError) as exc:
        raise LintError(f"{path} is not a readable report: {exc}") from exc


def lint_path(path: Path) -> LintOutcome:
    """Load one report and run the deterministic contract check over it."""
    report = load_report(path)
    result = contract_lint(report)
    return LintOutcome(
        path=path,
        report=report,
        ok=result.ok,
        violations=list(result.violations),
    )


__all__ = ["LintError", "LintOutcome", "find_report", "lint_path", "load_report"]
