"""``formiga serve``: build the right command, and never invent a model path.

The agent does not download weights, so ``serve`` has exactly two jobs: translate a layout
into ``llama-server`` invocations, and say clearly why it cannot when a piece is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.config import Endpoint
from formiga.core.serve import (
    BASE_ARGS,
    ENV_SERVER_BINARY,
    launch,
    plan_server,
    port_of,
)


@pytest.fixture
def fake_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "llama-server"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv(ENV_SERVER_BINARY, str(binary))
    return binary


@pytest.fixture
def fake_model(tmp_path: Path) -> Path:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"not a real model")
    return model


def test_port_is_read_from_the_endpoint() -> None:
    assert port_of("http://127.0.0.1:8080") == 8080
    assert port_of("http://127.0.0.1:8081") == 8081
    assert port_of("not a url") is None


def test_a_complete_endpoint_yields_a_full_command(fake_binary: Path, fake_model: Path) -> None:
    endpoint = Endpoint(endpoint="http://127.0.0.1:8080", model="small",
                        model_path=str(fake_model), context=4096, threads=4)
    plan = plan_server("fast", endpoint)
    assert plan.runnable
    assert plan.command[0] == str(fake_binary)
    assert plan.command[plan.command.index("--model") + 1] == str(fake_model)
    assert plan.command[plan.command.index("--port") + 1] == "8080"
    assert plan.command[plan.command.index("--ctx-size") + 1] == "4096"
    assert plan.command[plan.command.index("--threads") + 1] == "4"
    assert plan.command[plan.command.index("--alias") + 1] == "small"
    for argument in BASE_ARGS:
        assert argument in plan.command


def test_no_model_path_is_a_named_skip_not_a_guess(fake_binary: Path) -> None:
    plan = plan_server("fast", Endpoint())
    assert not plan.runnable
    assert plan.skipped_reason == "model_path_unset"


def test_a_missing_model_file_is_a_named_skip(fake_binary: Path, tmp_path: Path) -> None:
    plan = plan_server("fast", Endpoint(model_path=str(tmp_path / "absent.gguf")))
    assert not plan.runnable
    assert plan.skipped_reason == "model_missing"
    assert plan.model_path.endswith("absent.gguf")


def test_a_missing_binary_is_a_named_skip(fake_model: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_SERVER_BINARY, raising=False)
    monkeypatch.setenv("PATH", "")
    plan = plan_server("fast", Endpoint(model_path=str(fake_model)))
    assert not plan.runnable
    assert plan.skipped_reason == "binary_missing"


def test_an_endpoint_without_a_port_is_refused(fake_binary: Path, fake_model: Path) -> None:
    plan = plan_server("fast", Endpoint(endpoint="http://127.0.0.1",
                                       model_path=str(fake_model)))
    assert not plan.runnable
    assert plan.skipped_reason == "endpoint_unparsable"


def test_threads_are_derived_when_not_configured(fake_binary: Path, fake_model: Path) -> None:
    plan = plan_server("fast", Endpoint(model_path=str(fake_model), threads=0))
    assert "--threads" in plan.command
    assert int(plan.command[plan.command.index("--threads") + 1]) >= 1


def test_dry_run_launches_nothing(fake_binary: Path, fake_model: Path) -> None:
    plan = plan_server("fast", Endpoint(model_path=str(fake_model)))
    result = launch([plan], dry_run=True)
    assert result.processes == []
    assert [item.tier for item in result.started] == ["fast"]


def test_skipped_plans_are_not_started(fake_binary: Path) -> None:
    result = launch([plan_server("fast", Endpoint())])
    assert result.processes == []
    assert result.started == []
    assert result.skipped[0].skipped_reason == "model_path_unset"


def test_launch_executes_the_planned_command(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """A real subprocess, but a harmless one: ``/bin/true`` stands in for the server."""
    model = tmp_path / "m.gguf"
    model.write_bytes(b"x")
    plan = plan_server("fast", Endpoint(model_path=str(model)), binary="/bin/true")
    assert plan.runnable, plan.skipped_reason
    result = launch([plan])
    assert len(result.processes) == 1
    assert result.processes[0].wait(timeout=5) == 0
