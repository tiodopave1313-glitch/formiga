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


def test_profiles_via_toml_chegam_em_config_profiles(tmp_path):
    """`[profiles.*]` é perfil de modelo, não config de extensão."""
    from formiga.agent.profiles import Profile

    path = write_config(
        tmp_path,
        """
[profiles.gemma4-e2b]
context_tokens = 32768
thinking = false
temperature = 1.0
top_p = 0.95
max_tokens_per_turn = 4096
tool_schema_tokens = 1600
""",
    )
    values = load_config_values(path)
    assert values["profiles"]["gemma4-e2b"]["thinking"] is False
    assert "gemma4-e2b" not in values.get("extension_settings", {})

    config = Config.from_sources(file_values=values)
    perfil = Profile(name="gemma4-e2b", **config.profiles["gemma4-e2b"])
    assert perfil.context_tokens == 32768
    assert perfil.thinking is False


def test_profile_active_do_toml_vira_active_profile(tmp_path):
    """`[profile] active` força o perfil (chave aceita e tipada)."""
    path = write_config(
        tmp_path,
        """
[profile]
active = "nemotron-3.5-bolt-e4b"
""",
    )
    values = load_config_values(path)
    assert values["active_profile"] == "nemotron-3.5-bolt-e4b"
    config = Config.from_sources(file_values=values)
    assert config.active_profile == "nemotron-3.5-bolt-e4b"


def test_formiga_toml_example_carrega_sem_erro():
    """O exemplo enviado com o projeto precisa carregar de verdade.

    Regressão: `[memory] recall/nudge` (bool) e `max_tokens` (int) falhavam
    no type-check e `[profile] active` era chave desconhecida.
    """
    exemplo = Path(__file__).resolve().parent.parent / "formiga.toml.example"
    values = load_config_values(exemplo)
    config = Config.from_sources(file_values=values)
    assert config.memory_recall is True
    assert config.memory_max_tokens == 1600
    assert config.model == "gemma4:e4b"
    # O nome do perfil do Bolt tem pontos: a chave precisa ir entre aspas
    # senão o TOML cria uma seção aninhada e o build_agent quebra.
    assert set(config.profiles) == {
        "gemma4-e2b",
        "gemma4-e4b",
        "nemotron-3.5-bolt-e4b",
    }
