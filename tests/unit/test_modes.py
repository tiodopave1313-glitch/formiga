"""Modes and permissions: ``plan`` is read-only, writes stay inside the output directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.core.modes import (
    MODE_PERMISSIONS,
    Guard,
    Mode,
    Permission,
    PermissionDenied,
)


def test_research_allows_network_and_memory_writes(tmp_path: Path) -> None:
    guard = Guard(mode=Mode.RESEARCH, output_dir=tmp_path)
    assert guard.check("web_search") is Permission.ALLOW
    assert guard.check("memory_save") is Permission.ALLOW
    guard.require("web_fetch")


def test_plan_denies_every_network_action(tmp_path: Path) -> None:
    guard = Guard(mode=Mode.PLAN, output_dir=tmp_path)
    for action in ("web_search", "web_fetch", "deep_research"):
        assert guard.check(action) is Permission.DENY
        with pytest.raises(PermissionDenied) as caught:
            guard.require(action)
        assert caught.value.mode is Mode.PLAN


def test_plan_keeps_local_reads_available(tmp_path: Path) -> None:
    guard = Guard(mode=Mode.PLAN, output_dir=tmp_path)
    for action in ("history_search", "memory_search", "skill_load"):
        assert guard.check(action) is Permission.ALLOW


def test_unknown_actions_default_to_deny(tmp_path: Path) -> None:
    guard = Guard(mode=Mode.RESEARCH, output_dir=tmp_path)
    assert guard.check("shell_exec") is Permission.DENY


def test_build_is_not_configured_in_f2(tmp_path: Path) -> None:
    """``build`` belongs to F4; an empty table denies everything rather than half-allowing."""
    assert MODE_PERMISSIONS.get(Mode.BUILD) is None
    guard = Guard(mode=Mode.BUILD, output_dir=tmp_path)
    assert guard.check("web_search") is Permission.DENY


def test_writes_are_confined_to_the_output_directory(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    guard = Guard(mode=Mode.RESEARCH, output_dir=output)
    guard.check_write(output / "report.md")
    guard.check_write(output / "nested" / "deep" / "file.txt")

    with pytest.raises(PermissionDenied):
        guard.check_write(tmp_path / "elsewhere.md")
    with pytest.raises(PermissionDenied):
        guard.check_write(Path("~/.bashrc").expanduser())


def test_a_sibling_with_the_same_prefix_is_not_inside(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (tmp_path / "out-evil").mkdir()
    guard = Guard(mode=Mode.RESEARCH, output_dir=output)
    with pytest.raises(PermissionDenied):
        guard.check_write(tmp_path / "out-evil" / "x.md")


def test_plan_cannot_write_even_inside_the_output_directory(tmp_path: Path) -> None:
    guard = Guard(mode=Mode.PLAN, output_dir=tmp_path)
    with pytest.raises(PermissionDenied):
        guard.check_write(tmp_path / "report.md")


def test_permission_denied_names_the_action() -> None:
    error = PermissionDenied("web_fetch", Mode.PLAN)
    assert "web_fetch" in str(error)
    assert "plan" in str(error)
    assert error.action == "web_fetch"


def test_modes_are_strings_so_they_reach_the_database_cleanly() -> None:
    assert Mode.RESEARCH == "research"
    assert Permission.ALLOW == "allow"
