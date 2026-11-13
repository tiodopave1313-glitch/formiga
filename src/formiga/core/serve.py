"""``formiga serve``: launch the ``llama-server`` processes a layout needs.

The PRD is explicit that the agent does not download or manage weights (PRD §8.2,
``docs/uninstall.md``). What it *does* do is refuse to make the user assemble the command
line by hand: the layout already names an endpoint and a model alias, and every flag that
matters on CPU (§8.3) is a constant here.

A tier with no configured ``model_path`` is reported, not guessed: inventing a path would
start the wrong model under the right name, which is worse than saying so.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from formiga.config import Endpoint

#: Binary name looked up on ``PATH``; ``FORMIGA_LLAMA_SERVER`` overrides the lookup.
SERVER_BINARY = "llama-server"
ENV_SERVER_BINARY = "FORMIGA_LLAMA_SERVER"

#: CPU flags from PRD §8.3, documented rather than tuned per machine.
BASE_ARGS = ("--parallel", "1", "-ub", "512", "-b", "1024")


class ServeError(RuntimeError):
    """Raised when a server cannot be launched at all."""


@dataclass
class ServerPlan:
    """The command for one tier, plus why it may be missing."""

    tier: str
    command: list[str] = field(default_factory=list)
    endpoint: str = ""
    model_path: str = ""
    skipped_reason: str = ""

    @property
    def runnable(self) -> bool:
        return bool(self.command) and not self.skipped_reason


@dataclass
class ServeResult:
    """What ``serve`` started, so the CLI can print it and tests can assert on it."""

    plans: list[ServerPlan] = field(default_factory=list)
    processes: list[subprocess.Popen[bytes]] = field(default_factory=list)

    @property
    def started(self) -> list[ServerPlan]:
        return [plan for plan in self.plans if plan.runnable]

    @property
    def skipped(self) -> list[ServerPlan]:
        return [plan for plan in self.plans if not plan.runnable]


def port_of(endpoint: str) -> int | None:
    """Extract the port from ``http://host:port`` without importing a URL parser twice."""
    from urllib.parse import urlparse

    try:
        port = urlparse(endpoint).port
    except ValueError:
        return None
    return port


def plan_server(
    tier: str,
    endpoint: Endpoint,
    *,
    binary: str | None = None,
) -> ServerPlan:
    """Build the ``llama-server`` command for one tier, or explain why it is skipped.

    Skip reasons are machine-readable-ish strings: the caller turns them into catalog
    messages, so this module never prints.
    """
    plan = ServerPlan(tier=tier, endpoint=endpoint.endpoint)
    resolved = binary or _resolve_binary()
    if not resolved:
        plan.skipped_reason = "binary_missing"
        return plan
    if not endpoint.model_path:
        plan.skipped_reason = "model_path_unset"
        return plan
    model_path = Path(endpoint.model_path).expanduser()
    plan.model_path = str(model_path)
    if not model_path.is_file():
        plan.skipped_reason = "model_missing"
        return plan
    port = port_of(endpoint.endpoint)
    if port is None:
        plan.skipped_reason = "endpoint_unparsable"
        return plan

    command = [
        resolved,
        "--model", str(model_path),
        "--host", "127.0.0.1",
        "--port", str(port),
        "--ctx-size", str(endpoint.context),
        *BASE_ARGS,
    ]
    threads = endpoint.threads or _physical_cores()
    if threads:
        command.extend(["--threads", str(threads)])
    if endpoint.model:
        command.extend(["--alias", endpoint.model])
    plan.command = command
    return plan


def _resolve_binary() -> str | None:
    """Find ``llama-server``: an explicit env override first, then ``PATH``.

    The PRD ships no binary and does not install one, so a build living outside ``PATH``
    (a source checkout, a build directory) must still be usable without editing config.
    """
    override = os.environ.get(ENV_SERVER_BINARY)
    if override:
        resolved = shutil.which(override) or (override if Path(override).is_file() else None)
        if resolved:
            return resolved
    return shutil.which(SERVER_BINARY)


def _physical_cores() -> int:
    """Physical, not logical, cores: hyperthreads hurt CPU prefill (PRD §8.3)."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            cores = {
                (line.split(":")[1].strip())
                for line in handle
                if line.startswith("core id")
            }
    except OSError:
        return 0
    return len(cores) or (os.cpu_count() or 0)


def launch(plans: list[ServerPlan], *, dry_run: bool = False) -> ServeResult:
    """Start every runnable plan. ``dry_run`` reports the commands without executing."""
    result = ServeResult(plans=plans)
    if dry_run:
        return result
    for plan in plans:
        if not plan.runnable:
            continue
        # A new session detaches the server from the terminal's Ctrl-C group: closing the
        # agent should not silently kill a 5 GB model the user is still using.
        process = subprocess.Popen(  # noqa: S603 - argv is built here, never from the model
            plan.command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        result.processes.append(process)
    return result


__all__ = [
    "BASE_ARGS",
    "ENV_SERVER_BINARY",
    "SERVER_BINARY",
    "ServeError",
    "ServeResult",
    "ServerPlan",
    "launch",
    "plan_server",
    "port_of",
]
