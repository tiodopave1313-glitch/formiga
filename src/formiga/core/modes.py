"""Modes and permissions (PRD §4.2, FR13).

``research`` may use the web, memory and the output directory. ``plan`` is read-only with
no network. ``build`` is F4 and is refused here rather than half-implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Permission(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Mode(StrEnum):
    RESEARCH = "research"
    PLAN = "plan"
    BUILD = "build"


#: Tools that touch the network or write to disk, by mode.
MODE_PERMISSIONS: dict[Mode, dict[str, Permission]] = {
    Mode.RESEARCH: {
        "web_search": Permission.ALLOW,
        "web_fetch": Permission.ALLOW,
        "deep_research": Permission.ALLOW,
        "history_search": Permission.ALLOW,
        "memory_save": Permission.ALLOW,
        "memory_search": Permission.ALLOW,
        "skill_load": Permission.ALLOW,
        "write_file": Permission.ALLOW,
    },
    Mode.PLAN: {
        "web_search": Permission.DENY,
        "web_fetch": Permission.DENY,
        "deep_research": Permission.DENY,
        "history_search": Permission.ALLOW,
        "memory_save": Permission.DENY,
        "memory_search": Permission.ALLOW,
        "skill_load": Permission.ALLOW,
        "write_file": Permission.DENY,
    },
}


class PermissionDenied(PermissionError):
    """Raised when a mode does not allow an action."""

    def __init__(self, action: str, mode: Mode) -> None:
        self.action = action
        self.mode = mode
        super().__init__(f"{action} is not allowed in {mode.value} mode")


@dataclass(frozen=True)
class Guard:
    """Checks a mode's table and, for writes, the allowed directory."""

    mode: Mode
    output_dir: Path

    def check(self, action: str) -> Permission:
        table = MODE_PERMISSIONS.get(self.mode, {})
        return table.get(action, Permission.DENY)

    def require(self, action: str) -> None:
        if self.check(action) is not Permission.ALLOW:
            raise PermissionDenied(action, self.mode)

    def check_write(self, path: Path) -> None:
        """Writes are confined to the run/output directory, never anywhere else."""
        self.require("write_file")
        resolved = Path(path).expanduser().resolve()
        root = self.output_dir.expanduser().resolve()
        if resolved != root and root not in resolved.parents:
            raise PermissionDenied(f"write outside {root}", self.mode)


__all__ = [
    "MODE_PERMISSIONS",
    "Guard",
    "Mode",
    "Permission",
    "PermissionDenied",
]
