"""Configuração da execução: precedência CLI > variável de ambiente > default."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_SEARXNG_URL = "http://localhost:8080"

DEFAULT_MAX_INITIAL_QUESTIONS = 4
DEFAULT_MAX_TOTAL_QUESTIONS = 6
DEFAULT_MAX_ROUNDS = 8
DEFAULT_MAX_SEARCHES = 12
DEFAULT_MAX_PAGES = 18
DEFAULT_PAGES_PER_ROUND = 3
DEFAULT_CHUNKS_PER_CALL = 2
DEFAULT_MAX_LLM_CALLS = 40
DEFAULT_RESERVED_LLM_CALLS = 8
DEFAULT_TIMEOUT_SECONDS = 15 * 60
DEFAULT_NO_PROGRESS_ROUNDS = 2
DEFAULT_FORMAT_RETRIES = 1
DEFAULT_MAX_HTTP_BYTES = 2 * 1024 * 1024
DEFAULT_NETWORK_TIMEOUT = 20.0
DEFAULT_LLM_TIMEOUT = 300.0  # geração do modelo em CPU leva dezenas de segundos
# Gemma 4 recomenda temperature=1.0; para JSON estruturado baixamos por default
# e deixamos configurável (FORMIGA_LLM_TEMPERATURE / --llm-temperature).
DEFAULT_LLM_TEMPERATURE = 0.2

ENV_LLM_TIMEOUT = "FORMIGA_LLM_TIMEOUT"
ENV_LLM_TEMPERATURE = "FORMIGA_LLM_TEMPERATURE"

ENV_MODEL = "FORMIGA_MODEL"
ENV_OLLAMA_URL = "FORMIGA_OLLAMA_URL"
ENV_SEARXNG_URL = "FORMIGA_SEARXNG_URL"
ENV_LLM_BACKEND = "FORMIGA_LLM_BACKEND"
ENV_LLAMACPP_URL = "FORMIGA_LLAMACPP_URL"
ENV_LLAMACPP_THINKING = "FORMIGA_LLAMACPP_THINKING"

LLM_BACKENDS = ("ollama", "llamacpp")
DEFAULT_LLM_BACKEND = "ollama"
DEFAULT_LLAMACPP_URL = "http://localhost:8080"  # porta default do llama-server
# Modelos de raciocínio (ex.: Gemma Forge) pensam antes do JSON e podem
# consumir o teto de geração com `reasoning_content`. Default: desligado,
# pois os caps por tarefa são pequenos. Modelos sem o kwarg no template
# podem rejeitar; aí ative o thinking explicitamente.
DEFAULT_LLAMACPP_THINKING = False


class ConfigError(ValueError):
    """Configuração inválida; corresponde ao código de saída 2."""


def _env(env: dict[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _positive_int(name: str, value: int) -> int:
    if value <= 0:
        raise ConfigError(f"{name} deve ser um inteiro positivo (recebido: {value}).")
    return value


@dataclass
class Config:
    """Configuração efetiva de uma execução."""

    question: str | None = None
    output: Path | None = None
    model: str = DEFAULT_MODEL
    ollama_url: str = DEFAULT_OLLAMA_URL
    searxng_url: str = DEFAULT_SEARXNG_URL
    llm_backend: str = DEFAULT_LLM_BACKEND
    llamacpp_url: str = DEFAULT_LLAMACPP_URL
    llamacpp_thinking: bool = DEFAULT_LLAMACPP_THINKING
    verbose: bool = False
    overwrite: bool = False

    # Orçamentos (defaults da seção 9 do PRD, configuráveis).
    max_initial_questions: int = DEFAULT_MAX_INITIAL_QUESTIONS
    max_total_questions: int = DEFAULT_MAX_TOTAL_QUESTIONS
    max_rounds: int = DEFAULT_MAX_ROUNDS
    max_searches: int = DEFAULT_MAX_SEARCHES
    max_pages: int = DEFAULT_MAX_PAGES
    pages_per_round: int = DEFAULT_PAGES_PER_ROUND
    chunks_per_call: int = DEFAULT_CHUNKS_PER_CALL
    max_llm_calls: int = DEFAULT_MAX_LLM_CALLS
    reserved_llm_calls: int = DEFAULT_RESERVED_LLM_CALLS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    no_progress_rounds: int = DEFAULT_NO_PROGRESS_ROUNDS
    format_retries: int = DEFAULT_FORMAT_RETRIES
    max_http_bytes: int = DEFAULT_MAX_HTTP_BYTES
    network_timeout: float = DEFAULT_NETWORK_TIMEOUT
    llm_timeout: float = DEFAULT_LLM_TIMEOUT
    llm_temperature: float = DEFAULT_LLM_TEMPERATURE

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        env = dict(os.environ if env is None else env)
        config = cls()
        if (model := _env(env, ENV_MODEL)) is not None:
            config = replace(config, model=model)
        if (ollama := _env(env, ENV_OLLAMA_URL)) is not None:
            config = replace(config, ollama_url=ollama)
        if (searxng := _env(env, ENV_SEARXNG_URL)) is not None:
            config = replace(config, searxng_url=searxng)
        if (backend := _env(env, ENV_LLM_BACKEND)) is not None:
            config = replace(config, llm_backend=backend)
        if (llamacpp := _env(env, ENV_LLAMACPP_URL)) is not None:
            config = replace(config, llamacpp_url=llamacpp)
        if (thinking := _env(env, ENV_LLAMACPP_THINKING)) is not None:
            flag = thinking.lower() in ("1", "true", "yes", "on")
            if not flag and thinking.lower() not in ("0", "false", "no", "off"):
                raise ConfigError(
                    f"FORMIGA_LLAMACPP_THINKING não é booleano: {thinking!r}."
                )
            config = replace(config, llamacpp_thinking=flag)
        if (llm_timeout := _env(env, ENV_LLM_TIMEOUT)) is not None:
            try:
                config = replace(config, llm_timeout=float(llm_timeout))
            except ValueError as exc:
                raise ConfigError(f"FORMIGA_LLM_TIMEOUT não é um número: {llm_timeout!r}.") from exc
        if (temperature := _env(env, ENV_LLM_TEMPERATURE)) is not None:
            try:
                config = replace(config, llm_temperature=float(temperature))
            except ValueError as exc:
                raise ConfigError(
                    f"FORMIGA_LLM_TEMPERATURE não é um número: {temperature!r}."
                ) from exc
        config.validate()
        return config

    def apply_args(self, args: object) -> Config:
        """Aplica argumentos da CLI sobre esta configuração.

        Apenas argumentos explicitamente fornecidos sobrescrevem os valores
        herdados de variáveis de ambiente ou dos defaults.
        """
        updates: dict[str, object] = {}
        for key in (
            "question",
            "model",
            "ollama_url",
            "searxng_url",
            "llm_backend",
            "llamacpp_url",
            "llamacpp_thinking",
            "verbose",
            "overwrite",
            "max_initial_questions",
            "max_total_questions",
            "max_rounds",
            "max_searches",
            "max_pages",
            "pages_per_round",
            "chunks_per_call",
            "max_llm_calls",
            "reserved_llm_calls",
            "timeout_seconds",
            "no_progress_rounds",
            "format_retries",
            "max_http_bytes",
            "network_timeout",
            "llm_timeout",
            "llm_temperature",
        ):
            value = getattr(args, key, None)
            if value is not None and value != getattr(self, key):
                updates[key] = value
        output = getattr(args, "output", None)
        if output is not None:
            updates["output"] = Path(output)
        updated = replace(self, **updates)
        updated.validate()
        return updated

    def validate(self) -> None:
        int_fields = (
            ("max_initial_questions", self.max_initial_questions),
            ("max_total_questions", self.max_total_questions),
            ("max_rounds", self.max_rounds),
            ("max_searches", self.max_searches),
            ("max_pages", self.max_pages),
            ("pages_per_round", self.pages_per_round),
            ("chunks_per_call", self.chunks_per_call),
            ("max_llm_calls", self.max_llm_calls),
            ("reserved_llm_calls", self.reserved_llm_calls),
            ("no_progress_rounds", self.no_progress_rounds),
            ("format_retries", self.format_retries),
            ("max_http_bytes", self.max_http_bytes),
        )
        for name, value in int_fields:
            _positive_int(name, value)
        for name in ("network_timeout", "timeout_seconds", "llm_timeout"):
            value = getattr(self, name)
            if value <= 0:
                raise ConfigError(f"{name} deve ser positivo (recebido: {value}).")
        if not 0 <= self.llm_temperature <= 2:
            raise ConfigError(
                f"llm_temperature deve estar em [0, 2] (recebido: {self.llm_temperature})."
            )
        if self.reserved_llm_calls > self.max_llm_calls:
            raise ConfigError(
                "reserved_llm_calls não pode exceder max_llm_calls "
                f"({self.reserved_llm_calls} > {self.max_llm_calls})."
            )
        if self.max_initial_questions > self.max_total_questions:
            raise ConfigError(
                "max_initial_questions não pode exceder max_total_questions."
            )
        for name, url in (
            ("ollama_url", self.ollama_url),
            ("searxng_url", self.searxng_url),
            ("llamacpp_url", self.llamacpp_url),
        ):
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ConfigError(f"{name} deve ser uma URL http(s): {url!r}.")
        if self.llm_backend not in LLM_BACKENDS:
            raise ConfigError(
                f"llm_backend inválido: {self.llm_backend!r} (use um de {LLM_BACKENDS})."
            )

    @property
    def investigation_llm_calls(self) -> int:
        """Chamadas de LLM disponíveis para investigação (as reservadas não podem ser usadas)."""
        return self.max_llm_calls - self.reserved_llm_calls
