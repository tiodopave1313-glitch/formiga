"""Environment and endpoint checks.

``doctor`` must pass without a running ``llama-server``: the endpoint check reports a
missing server as *not configured* rather than as a failure, because a laptop that is
offline is still a valid development environment.
"""

from __future__ import annotations

import platform
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from formiga.config import LAYOUT_NAMES, Settings
from formiga.i18n import t
from formiga.research.contract import permitted_profiles
from formiga.research.report import RUNG_ORDER
from formiga.storage.db import (
    ForeignSchema,
    connect,
    has_foreign_schema,
    schema_version,
    supports_fts5,
    tables_in,
)
from formiga.storage.idempotency import PROMPT_VERSION, SEGMENTER_VERSION

MIN_PYTHON = (3, 11)


@dataclass
class Check:
    """One named check with a machine-readable status."""

    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "skipped": self.skipped}


@dataclass
class DoctorReport:
    """The whole result of ``formiga doctor``."""

    checks: list[Check] = field(default_factory=list)
    profiles: tuple[str, ...] = ()
    rungs: tuple[str, ...] = ()
    model_alias: str | None = None

    @property
    def ok(self) -> bool:
        return all(check.ok or check.skipped for check in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if not check.ok and not check.skipped]

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [check.as_dict() for check in self.checks],
            "profiles": list(self.profiles),
            "rungs": list(self.rungs),
            "model": self.model_alias,
        }


def _check_python() -> Check:
    ok = sys.version_info[:2] >= MIN_PYTHON
    return Check(t("doctor.python", locale="en"), ok, platform.python_version())


def _check_platform() -> Check:
    ok = sys.platform.startswith("linux")
    detail = platform.platform() if ok else t(
        "doctor.platform_unsupported", locale="en", platform=platform.system()
    )
    return Check(t("doctor.platform", locale="en"), ok, detail)


def _check_home(home: Path) -> Check:
    return Check(t("doctor.home", locale="en"), home.exists(), str(home))


def _check_database(path: Path) -> list[Check]:
    checks: list[Check] = []
    try:
        connection = connect(path)
    except sqlite3.Error as exc:
        return [Check(t("doctor.database", locale="en"), False, str(exc))]

    try:
        if has_foreign_schema(connection):
            raise ForeignSchema(path, tables_in(connection))
        checks.append(Check(t("doctor.database", locale="en"), True, str(path)))
        checks.append(
            Check(t("doctor.fts5", locale="en"), supports_fts5(connection),
                  "bm25 available" if supports_fts5(connection) else "TF-IDF fallback")
        )
        version = schema_version(connection)
        checks.append(Check(t("doctor.schema", locale="en"), version > 0, f"v{version}"))
    except ForeignSchema as exc:
        checks.append(Check(t("doctor.database", locale="en"), False, str(exc)))
    finally:
        connection.close()
    return checks


def _check_endpoint(settings: Settings) -> list[Check]:
    from formiga.llm.client import HTTPLLM

    checks: list[Check] = []
    single = settings.layout.is_single()
    for tier, endpoint in settings.layout.tiers.items():
        name = t("doctor.endpoint", locale="en", tier=tier)
        backend = HTTPLLM(endpoint, profile_name=tier)
        try:
            healthy = backend.healthy()
        finally:
            backend.close()
        if healthy:
            checks.append(Check(name, True, t("doctor.endpoint_ok", locale="en",
                                             tier=tier, endpoint=endpoint.endpoint)))
            continue
        if tier == "strong" and not single:
            # PRD §8.2: in ``dual`` a dead strong tier degrades to the fast one, it does
            # not fail the run. Reporting it as fatal would make the recommended layout
            # un-startable whenever the second server is simply not up yet.
            checks.append(Check(
                name, True,
                t("doctor.endpoint_degraded", locale="en", tier=tier,
                  endpoint=endpoint.endpoint),
                skipped=True,
            ))
            continue
        checks.append(Check(name, False, t("doctor.endpoint_down", locale="en",
                                           tier=tier, endpoint=endpoint.endpoint)))
    return checks


def run_doctor(settings: Settings, *, probe_endpoints: bool = False) -> DoctorReport:
    """Run every check. Endpoint checks are skipped unless ``probe_endpoints``."""
    report = DoctorReport()
    report.checks.append(_check_python())
    report.checks.append(_check_platform())
    report.checks.append(_check_home(settings.paths.home))
    report.checks.extend(_check_database(settings.paths.db))

    if probe_endpoints:
        report.checks.extend(_check_endpoint(settings))
    else:
        for tier in settings.layout.tiers:
            report.checks.append(
                Check(t("doctor.endpoint", locale="en", tier=tier), True,
                      t("doctor.endpoint_skipped", locale="en"), skipped=True)
            )

    ram_gb = total_ram_gb()
    report.profiles = permitted_profiles(settings.layout.name, ram_gb=ram_gb)
    ceiling = settings.layout.rung_ceiling()
    report.rungs = tuple(RUNG_ORDER[: RUNG_ORDER.index(ceiling) + 1])
    report.model_alias = settings.layout.fast.model
    return report


def total_ram_gb() -> float | None:
    """Total physical memory in GB, or ``None`` when it cannot be read."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024 * 1024), 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def suggested_layout(ram_gb: float | None) -> str:
    """``single`` on small machines, ``dual`` when there is room for two models."""
    if ram_gb is None:
        return "single"
    return "dual" if ram_gb >= 14 else "single"


def diagnostics(settings: Settings) -> dict[str, object]:
    """Machine-readable block embedded in every report frontmatter."""
    return {
        "prompt_version": PROMPT_VERSION,
        "segmenter_version": SEGMENTER_VERSION,
        "layout": settings.layout.name,
        "layout_known": settings.layout.name in LAYOUT_NAMES,
        "profile": settings.report.profile,
        "language": settings.language,
    }


__all__ = [
    "Check",
    "DoctorReport",
    "MIN_PYTHON",
    "diagnostics",
    "run_doctor",
    "suggested_layout",
    "total_ram_gb",
]
