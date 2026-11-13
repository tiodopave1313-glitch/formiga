"""Configuration precedence, layout validation and profile overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.config import ConfigError, Layout, load_settings, user_config_path

CONFIG = """
language = "pt-BR"
output_language = "pt-BR"
search_languages = ["pt-BR", "en"]

[layout]
name = "dual"

[layout.fast]
endpoint = "http://127.0.0.1:9001"
model = "small"
rung_ceiling = "bounded-edit"

[layout.strong]
endpoint = "http://127.0.0.1:9002"
model = "large"
rung_ceiling = "anchored-rewrite"

[report]
profile = "long"
citation_style = "abnt"

[report.profiles.thesis]
words = [4200, 8200]

[chat]
keep_turns = 6
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_defaults_are_the_single_layout(home: Path) -> None:
    settings = load_settings(home=home, environ={})
    assert settings.layout.name == "single"
    assert settings.layout.strong is None
    assert settings.layout.is_single()
    assert settings.report.profile == "medium"
    assert settings.report.citation_style == "apa"


def test_user_file_is_read(home: Path) -> None:
    _write(user_config_path(home), CONFIG)
    settings = load_settings(home=home, environ={})
    assert settings.language == "pt-BR"
    assert settings.layout.name == "dual"
    assert settings.layout.strong is not None
    assert settings.layout.strong.endpoint == "http://127.0.0.1:9002"
    assert settings.report.profile == "long"
    assert settings.chat.keep_turns == 6


def test_cli_overrides_env_overrides_project_overrides_user(home: Path, tmp_path: Path) -> None:
    _write(user_config_path(home), CONFIG)
    project = tmp_path / "project"
    project.mkdir()
    _write(project / ".formiga.toml", '[report]\nprofile = "short"\n')
    settings = load_settings(
        cwd=project,
        home=home,
        cli_overrides={"report": {"profile": "medium"}},
        environ={"FORMIGA_PROFILE": "thesis"},
    )
    assert settings.report.profile == "medium"


def test_env_overrides_file(home: Path) -> None:
    _write(user_config_path(home), CONFIG)
    settings = load_settings(home=home, environ={"FORMIGA_PROFILE": "short"})
    assert settings.report.profile == "short"


def test_env_can_set_the_layout_endpoint(home: Path) -> None:
    settings = load_settings(home=home, environ={"FORMIGA_ENDPOINT": "http://127.0.0.1:7777"})
    assert settings.layout.fast.endpoint == "http://127.0.0.1:7777"


def test_none_overrides_do_not_erase_file_values(home: Path) -> None:
    _write(user_config_path(home), CONFIG)
    settings = load_settings(
        home=home, cli_overrides={"language": None}, environ={}
    )
    assert settings.language == "pt-BR"


def test_unknown_key_is_a_hard_error(home: Path) -> None:
    _write(user_config_path(home), "[layout]\nname = 'single'\nbogus = 1\n")
    with pytest.raises(ConfigError) as caught:
        load_settings(home=home, environ={})
    assert "bogus" in str(caught.value)


def test_invalid_toml_reports_the_source(home: Path) -> None:
    _write(user_config_path(home), "[layout\nname = 'single'")
    with pytest.raises(ConfigError) as caught:
        load_settings(home=home, environ={})
    assert caught.value.source == user_config_path(home)


def test_unknown_layout_is_rejected(home: Path) -> None:
    _write(user_config_path(home), '[layout]\nname = "triple"\n')
    with pytest.raises(ConfigError):
        load_settings(home=home, environ={})


def test_unknown_ui_language_is_rejected(home: Path) -> None:
    _write(user_config_path(home), 'language = "xx-YY"\n')
    with pytest.raises(ConfigError):
        load_settings(home=home, environ={})


def test_unknown_citation_style_is_rejected(home: Path) -> None:
    _write(user_config_path(home), '[report]\ncitation_style = "chicago"\n')
    with pytest.raises(ConfigError):
        load_settings(home=home, environ={})


def test_temperatures_default_per_role_and_accept_overrides(home: Path) -> None:
    _write(
        user_config_path(home),
        '[layout.fast]\n[layout.fast.temperature]\nreader = 0.1\n',
    )
    settings = load_settings(home=home, environ={})
    assert settings.layout.fast.temperature_for("reader") == 0.1
    assert settings.layout.fast.temperature_for("router") == 0.2
    assert settings.layout.fast.temperature_for("synthesizer") == 0.3


def test_unknown_temperature_role_is_rejected(home: Path) -> None:
    _write(
        user_config_path(home),
        '[layout.fast.temperature]\nsummarizer = 0.3\n',
    )
    with pytest.raises(ConfigError):
        load_settings(home=home, environ={})


def test_layout_ceiling_is_the_lowest_tier(home: Path) -> None:
    layout = Layout()
    assert layout.rung_ceiling() == "bounded-edit"
    _write(user_config_path(home), CONFIG)
    dual = load_settings(home=home, environ={}).layout
    assert dual.rung_ceiling() == "bounded-edit"


def test_dual_with_same_endpoint_is_treated_as_single(home: Path) -> None:
    from formiga.config import Endpoint

    layout = Layout(name="dual", fast=Endpoint(), strong=Endpoint())
    assert layout.is_single()


def test_report_profile_overrides_reach_the_spec(home: Path) -> None:
    _write(user_config_path(home), CONFIG)
    spec = load_settings(home=home, environ={}).profile_spec()
    assert spec.name == "long"


def test_paths_live_under_the_home(home: Path) -> None:
    settings = load_settings(home=home, environ={})
    assert settings.paths.db == home / "formiga.db"
    assert settings.paths.runs == home / "runs"
    assert settings.paths.cache == home / "cache"


def test_project_file_is_optional(tmp_path: Path, home: Path) -> None:
    settings = load_settings(cwd=tmp_path, home=home, environ={})
    assert settings.layout.name == "single"


def test_budget_overrides_are_optional(home: Path) -> None:
    assert load_settings(home=home, environ={}).budget.max_llm_calls is None
    _write(user_config_path(home), "[budget]\nmax_llm_calls = 7\n")
    assert load_settings(home=home, environ={}).budget.max_llm_calls == 7
