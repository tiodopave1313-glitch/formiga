"""Testes do carregamento de arquivo de configuração TOML (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.config import Config, ConfigError
from formiga.configfile import (
    find_config_file,
    load_config_values,
    load_file_values,
)


def write_config(tmp_path: Path, content: str, name: str = "formiga.toml") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


FULL_CONFIG = """
[llm]
backend = "openai"
model = "nvidia/nemotron-3.5-bolt-e4b"
base_url = "https://integrate.api.nvidia.com/v1"
api_key_env = "NVIDIA_API_KEY"
temperature = 0.2
timeout_seconds = 120.0
max_retries = 3
thinking = false

[search]
searxng_url = "http://10.0.0.5:8080"

[budget]
max_searches = 5
max_pages = 6
max_llm_calls = 20
timeout_seconds = 600
"""


class TestLoadConfigValues:
    def test_maps_sections_to_config_fields(self, tmp_path):
        path = write_config(tmp_path, FULL_CONFIG)
        values = load_config_values(path)
        config = Config.from_sources(file_values=values)
        assert config.llm_backend == "openai"
        assert config.model == "nvidia/nemotron-3.5-bolt-e4b"
        assert config.openai_url == "https://integrate.api.nvidia.com/v1"
        assert config.openai_api_key_env == "NVIDIA_API_KEY"
        assert config.llm_temperature == 0.2
        assert config.llm_timeout == 120.0
        assert config.llm_max_retries == 3
        assert config.llm_thinking is False
        assert config.searxng_url == "http://10.0.0.5:8080"
        assert config.max_searches == 5
        assert config.max_pages == 6
        assert config.max_llm_calls == 20
        assert config.timeout_seconds == 600

    def test_fallback_in_file(self, tmp_path):
        path = write_config(
            tmp_path,
            '[llm]\nbackend = "openai"\nbase_url = "https://x/v1"\n'
            'fallback_backend = "ollama"\nfallback_after_failures = 2\n',
        )
        config = Config.from_sources(file_values=load_config_values(path))
        assert config.fallback_backend == "ollama"
        assert config.fallback_after_failures == 2

    def test_unknown_key_rejected(self, tmp_path):
        path = write_config(tmp_path, '[llm]\nfoo = "bar"\n')
        with pytest.raises(ConfigError, match="foo"):
            load_config_values(path)

    def test_unknown_section_rejected(self, tmp_path):
        path = write_config(tmp_path, '[outros]\nchave = 1\n')
        with pytest.raises(ConfigError, match="outros"):
            load_config_values(path)

    def test_malformed_toml_rejected(self, tmp_path):
        path = write_config(tmp_path, "[llm\nbackend = ")
        with pytest.raises(ConfigError, match="TOML inválido"):
            load_config_values(path)

    def test_wrong_types_rejected(self, tmp_path):
        path = write_config(tmp_path, '[budget]\nmax_searches = "abc"\n')
        with pytest.raises(ConfigError, match="max_searches"):
            load_config_values(path)
        path = write_config(tmp_path, '[llm]\nthinking = "yes"\n')
        with pytest.raises(ConfigError, match="thinking"):
            load_config_values(path)
        path = write_config(tmp_path, "[llm]\ntemperature = true\n")
        with pytest.raises(ConfigError, match="temperature"):
            load_config_values(path)

    def test_invalid_values_reach_config_validation(self, tmp_path):
        path = write_config(tmp_path, '[llm]\nbackend = "vllm"\n')
        with pytest.raises(ConfigError, match="llm_backend"):
            Config.from_sources(file_values=load_config_values(path))


class TestApiKeyInFile:
    def test_api_key_with_loose_permissions_rejected(self, tmp_path):
        path = write_config(tmp_path, '[llm]\napi_key = "nvapi-secret"\n')
        path.chmod(0o644)
        with pytest.raises(ConfigError, match="0600"):
            load_config_values(path)

    def test_api_key_with_0600_loaded_and_hidden_from_repr(self, tmp_path):
        path = write_config(tmp_path, '[llm]\napi_key = "nvapi-secret"\n')
        path.chmod(0o600)
        config = Config.from_sources(file_values=load_config_values(path))
        assert config.openai_api_key == "nvapi-secret"
        assert "nvapi-secret" not in repr(config)

    def test_api_key_env_preferred_semantics(self, tmp_path):
        # `api_key_env` (nome de variável) é o modo recomendado.
        path = write_config(tmp_path, '[llm]\napi_key_env = "NVIDIA_API_KEY"\n')
        config = Config.from_sources(file_values=load_config_values(path))
        assert config.openai_api_key_env == "NVIDIA_API_KEY"
        assert config.openai_api_key == ""


class TestPrecedence:
    def test_file_beats_defaults(self, tmp_path):
        path = write_config(tmp_path, '[llm]\nmodel = "from-file"\n')
        config = Config.from_sources(file_values=load_config_values(path))
        assert config.model == "from-file"

    def test_env_beats_file(self, tmp_path, monkeypatch):
        path = write_config(tmp_path, '[llm]\nmodel = "from-file"\n')
        monkeypatch.setenv("FORMIGA_MODEL", "from-env")
        config = Config.from_sources(file_values=load_config_values(path))
        assert config.model == "from-env"

    def test_cli_beats_env_and_file(self, tmp_path, monkeypatch):
        path = write_config(tmp_path, '[llm]\nmodel = "from-file"\n')
        monkeypatch.setenv("FORMIGA_MODEL", "from-env")
        config = Config.from_sources(file_values=load_config_values(path)).apply_args(
            type("Args", (), {"model": "from-cli"})
        )
        assert config.model == "from-cli"

    def test_absent_env_key_keeps_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORMIGA_MODEL", raising=False)
        path = write_config(tmp_path, '[llm]\nmodel = "from-file"\n')
        config = Config.from_sources(file_values=load_config_values(path))
        assert config.model == "from-file"


class TestDiscovery:
    def test_explicit_missing_file_raises(self):
        with pytest.raises(ConfigError, match="não encontrado"):
            find_config_file(explicit="/inexistente/formiga.toml")

    def test_explicit_wins_over_env_and_cwd(self, tmp_path, monkeypatch):
        explicit = write_config(tmp_path, "", name="explicit.toml")
        monkeypatch.chdir(tmp_path)
        write_config(tmp_path, "", name="formiga.toml")
        monkeypatch.setenv("FORMIGA_CONFIG", "formiga.toml")
        assert find_config_file(explicit=str(explicit)) == explicit

    def test_env_formiga_config(self, tmp_path, monkeypatch):
        write_config(tmp_path, "", name="env.toml")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORMIGA_CONFIG", "env.toml")
        assert find_config_file() == Path("env.toml")

    def test_cwd_formiga_toml_discovered(self, tmp_path, monkeypatch):
        path = write_config(tmp_path, "")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORMIGA_CONFIG", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert find_config_file() == path

    def test_no_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORMIGA_CONFIG", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert find_config_file() is None
        assert load_file_values() == {}

    def test_load_file_values_reads_discovered_file(self, tmp_path, monkeypatch):
        write_config(tmp_path, '[llm]\nmodel = "from-file"\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORMIGA_CONFIG", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        config = Config.from_sources(file_values=load_file_values())
        assert config.model == "from-file"
