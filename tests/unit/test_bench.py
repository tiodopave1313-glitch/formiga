"""``formiga bench``: the deadline formula, measured rather than invented.

The numbers here are a *contract*: if the formula or the overhead factors change, a
deadline changes, and a deadline that changes silently lets a profile over-promise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.core.bench import (
    CALL_OVERHEAD_S,
    FETCH_SECONDS,
    OVERHEAD_FACTOR,
    BenchResult,
    Speed,
    estimate_seconds,
    estimate_table,
    measure_endpoint,
    peak_rss_mb,
    write_benchmarks,
)
from formiga.research.contract import DEFAULT_PROFILES, get_profile


def _speed(**overrides: float) -> Speed:
    values = {"generate_tps": 20.0, "prefill_tps": 200.0}
    values.update(overrides)
    return Speed(**values)


def test_estimate_grows_with_the_profile() -> None:
    speed = _speed()
    short = estimate_seconds("short", layout="dual", speed=speed)
    medium = estimate_seconds("medium", layout="dual", speed=speed)
    long = estimate_seconds("long", layout="dual", speed=speed)
    thesis = estimate_seconds("thesis", layout="dual", speed=speed)
    assert short < medium < long < thesis


def test_a_single_layout_costs_more_than_a_dual_one() -> None:
    speed = _speed()
    dual = estimate_seconds("medium", layout="dual", speed=speed)
    single = estimate_seconds("medium", layout="single", speed=speed)
    assert single > dual
    assert OVERHEAD_FACTOR["single"] > OVERHEAD_FACTOR["dual"]


def test_slower_generation_pushes_the_estimate_up() -> None:
    fast = estimate_seconds("medium", layout="dual", speed=_speed(generate_tps=40.0))
    slow = estimate_seconds("medium", layout="dual", speed=_speed(generate_tps=5.0))
    assert slow > fast


def test_the_formula_honours_the_row_it_is_given() -> None:
    speed = _speed()
    caps = estimate_seconds("medium", layout="dual", speed=speed, use_caps=True)
    typical = estimate_seconds("medium", layout="dual", speed=speed, use_caps=False)
    spec = get_profile("medium")
    assert spec.llm_calls[1] > spec.llm_calls[0]
    assert caps > typical


def test_zero_speeds_do_not_divide_by_zero() -> None:
    estimate = estimate_seconds(
        "short", layout="single", speed=Speed(generate_tps=0.0, prefill_tps=0.0)
    )
    assert estimate > 0
    assert estimate == estimate  # not NaN


def test_fetch_seconds_dominate_the_smallest_profile() -> None:
    speed = _speed(generate_tps=1000.0, prefill_tps=100_000.0)
    estimate = estimate_seconds("short", layout="dual", speed=speed)
    assert estimate >= FETCH_SECONDS["short"]


def test_call_overhead_is_charged_per_call() -> None:
    spec = DEFAULT_PROFILES["short"]
    calls = spec.llm_calls[0]
    speed = _speed(generate_tps=1e9, prefill_tps=1e9)
    model_part = calls * CALL_OVERHEAD_S
    estimate = estimate_seconds("short", layout="dual", speed=speed)
    assert estimate >= model_part * OVERHEAD_FACTOR["dual"]


def test_estimate_table_covers_every_profile() -> None:
    result = BenchResult(tiers={"fast": _speed()}, layout="single")
    table = estimate_table(result)
    assert set(table) == set(DEFAULT_PROFILES)
    assert all(value > 0 for value in table.values())


def test_estimate_table_is_empty_without_measurements() -> None:
    assert estimate_table(BenchResult()) == {}


def test_the_slowest_tier_sets_the_expectation() -> None:
    result = BenchResult(
        tiers={
            "fast": _speed(generate_tps=80.0),
            "strong": _speed(generate_tps=8.0),
        },
        layout="dual",
    )
    slow = estimate_table(result)["medium"]
    only_fast = estimate_table(BenchResult(tiers={"fast": _speed(generate_tps=80.0)},
                                          layout="dual"))["medium"]
    assert slow > only_fast


def test_bench_result_is_json_ready() -> None:
    payload = BenchResult(tiers={"fast": _speed()}, peak_rss_mb=123.456).as_dict()
    assert payload["tiers"]["fast"]["generate_tps"] == 20.0
    assert payload["peak_rss_mb"] == 123.5
    assert "measured_on" in payload


def test_benchmarks_are_appended_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "benchmarks.md"
    write_benchmarks(path, BenchResult(tiers={"fast": _speed()}, layout="single"))
    first = path.read_text()
    write_benchmarks(path, BenchResult(tiers={"fast": _speed(generate_tps=10.0)},
                                       layout="single"))
    second = path.read_text()
    assert second.startswith(first.rstrip())
    assert second.count("| tier |") == 2


def test_benchmarks_record_the_estimate_table(tmp_path: Path) -> None:
    path = tmp_path / "benchmarks.md"
    write_benchmarks(path, BenchResult(tiers={"fast": _speed()}, layout="single"))
    text = path.read_text()
    assert "estimated minutes" in text
    assert "thesis" in text


def test_measure_endpoint_uses_two_short_requests() -> None:
    from formiga.config import Endpoint
    from formiga.llm.fake import FakeLLM
    from formiga.llm.types import Completion

    backend = FakeLLM(
        [
            Completion(content="ok", input_tokens=500, output_tokens=1, finish_reason="stop"),
            Completion(content="a\nb\nc", input_tokens=10, output_tokens=3, finish_reason="stop"),
        ]
    )
    speed = measure_endpoint(Endpoint(), client=backend)
    assert speed.input_tokens == 500
    assert speed.output_tokens == 3
    assert speed.prefill_tps > 0
    assert speed.generate_tps > 0
    assert len(backend.requests) == 2
    assert backend.requests[0].max_tokens == 1
    assert not backend.closed, "an injected client is owned by the caller"


def test_peak_rss_is_read_from_proc() -> None:
    assert peak_rss_mb() > 0


def test_an_unreachable_endpoint_is_reported_not_raised() -> None:
    """A bench run with one tier down still measures the other (see ``run_bench``)."""
    from formiga.config import Endpoint
    from formiga.core.bench import BenchUnavailable

    with pytest.raises(BenchUnavailable) as caught:
        measure_endpoint(Endpoint(endpoint="http://127.0.0.1:9", request_timeout_s=1.0))
    assert caught.value.endpoint.endswith(":9")
    assert "not answering" in str(caught.value)


def test_failures_are_part_of_the_bench_result() -> None:
    payload = BenchResult(tiers={"fast": _speed()}, failures={"strong": "down"}).as_dict()
    assert payload["failures"] == {"strong": "down"}


def test_failures_are_recorded_in_the_document(tmp_path: Path) -> None:
    path = tmp_path / "benchmarks.md"
    write_benchmarks(path, BenchResult(tiers={"fast": _speed()}, failures={"strong": "down"}))
    text = path.read_text()
    assert "Unmeasured tiers" in text
    assert "`strong`: down" in text


def test_the_prefill_probe_is_never_repeated() -> None:
    """A repeated prompt measures the server's prefix cache, not prefill (PRD §8.3)."""
    from formiga.core.bench import prefill_probe

    first, second = prefill_probe(), prefill_probe()
    assert first != second
    assert first.endswith(prefill_probe().split("] ", 1)[1])
    assert first.startswith("[bench ")


def test_measure_endpoint_sends_the_nonce_with_the_prompt() -> None:
    from formiga.config import Endpoint
    from formiga.core.bench import PREFILL_PROMPT
    from formiga.llm.fake import FakeLLM
    from formiga.llm.types import Completion

    backend = FakeLLM(
        [
            Completion(content="ok", input_tokens=500, output_tokens=1, finish_reason="stop"),
            Completion(content="a\nb", input_tokens=10, output_tokens=2, finish_reason="stop"),
        ]
    )
    measure_endpoint(Endpoint(), client=backend)
    sent = backend.requests[0].messages[0].content
    assert PREFILL_PROMPT in sent
    assert sent.startswith("[bench ")
