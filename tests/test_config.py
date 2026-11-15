"""Testes de configuração: precedência CLI > env > default e validação."""

from __future__ import annotations

import pytest

from formiga.config import (
    DEFAULT_MAX_LLM_CALLS,
    DEFAULT_MODEL,
    DEFAULT_RESERVED_LLM_CALLS,
    Config,
    ConfigError,
)


class TestDefaults:
    def test_defaults_match_prd(self):
        config = Config()
        assert config.model == DEFAULT_MODEL == "llama3.1:8b"
        assert config.ollama_url == "http://localhost:11434"
        assert config.searxng_url == "http://localhost:8080"
        assert config.max_initial_questions == 4
        assert config.max_total_questions == 6
        assert config.max_rounds == 8
        assert config.max_searches == 12
        assert config.max_pages == 18
        assert config.pages_per_round == 3
        assert config.chunks_per_call == 2
        assert config.max_llm_calls == 40
        assert config.reserved_llm_calls == 8
        assert config.timeout_seconds == 900
        assert config.max_http_bytes == 2 * 1024 * 1024
        assert config.network_timeout == 20.0

    def test_investigation_calls_exclude_reserved(self):
        assert Config().investigation_llm_calls == (
            DEFAULT_MAX_LLM_CALLS - DEFAULT_RESERVED_LLM_CALLS
        )


class TestPrecedence:
    def test_env_overrides_defaults(self):
        config = Config.from_env(
            {
                "FORMIGA_MODEL": "qwen2.5:8b",
                "FORMIGA_OLLAMA_URL": "http://127.0.0.1:11434",
                "FORMIGA_SEARXNG_URL": "http://10.0.0.5:8080",
            }
        )
        assert config.model == "qwen2.5:8b"
        assert config.ollama_url == "http://127.0.0.1:11434"
        assert config.searxng_url == "http://10.0.0.5:8080"

    def test_empty_env_value_ignored(self):
        config = Config.from_env({"FORMIGA_MODEL": "   "})
        assert config.model == DEFAULT_MODEL

    def test_cli_args_override_env(self):
        config = Config.from_env({"FORMIGA_MODEL": "from-env"}).apply_args(
            type("Args", (), {"model": "from-cli"})
        )
        assert config.model == "from-cli"

    def test_absent_cli_arg_keeps_env(self):
        config = Config.from_env({"FORMIGA_MODEL": "from-env"}).apply_args(
            type("Args", (), {"model": None})
        )
        assert config.model == "from-env"


class TestValidation:
    @pytest.mark.parametrize(
        "updates",
        [
            {"max_searches": 0},
            {"max_pages": -3},
            {"reserved_llm_calls": 0},
            {"timeout_seconds": 0},
            {"network_timeout": -1},
        ],
    )
    def test_invalid_values_rejected(self, updates):
        with pytest.raises(ConfigError):
            Config(**updates).validate()

    def test_reserved_cannot_exceed_total(self):
        with pytest.raises(ConfigError):
            Config(max_llm_calls=5, reserved_llm_calls=8).validate()

    def test_initial_questions_cannot_exceed_total(self):
        with pytest.raises(ConfigError):
            Config(max_initial_questions=6, max_total_questions=4).validate()

    def test_urls_must_be_http(self):
        with pytest.raises(ConfigError):
            Config(ollama_url="ftp://localhost:11434").validate()
