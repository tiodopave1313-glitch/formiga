"""Carregamento de arquivo de configuração TOML.

Precedência: defaults < arquivo < variáveis de ambiente < CLI.

Descoberta do arquivo, nesta ordem:
1. `--config PATH` (CLI) ou `FORMIGA_CONFIG` (ambiente) — devem existir;
2. `./formiga.toml` no diretório atual;
3. `~/.config/formiga/config.toml`.

Formato suportado (ver `formiga.toml.example`):

    [llm]
    backend = "openai"
    model = "nvidia/nemotron-3.5-bolt-e4b"
    base_url = "https://integrate.api.nvidia.com/v1"
    api_key_env = "NVIDIA_API_KEY"   # nome da variável de ambiente
    temperature = 0.2
    timeout_seconds = 120.0
    max_retries = 2
    # thinking = true
    # fallback_backend = "ollama"    # backup opt-in
    # fallback_after_failures = 1

    [search]
    searxng_url = "http://localhost:8080"

    [budget]
    max_searches = 12
    max_pages = 18
    max_llm_calls = 40
    timeout_seconds = 900

A chave da API pode ser indicada por `api_key_env` (recomendado) ou embutida
via `api_key` — nesse caso o arquivo precisa de permissão 0600, pois é
ignorado pelo git e ficaria legível para outros usuários da máquina.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from formiga.config import ConfigError

ENV_CONFIG = "FORMIGA_CONFIG"

_LLM_KEYS = {
    "backend": "llm_backend",
    "model": "model",
    "base_url": "openai_url",
    "api_key_env": "openai_api_key_env",
    "api_key": "openai_api_key",
    "temperature": "llm_temperature",
    "timeout_seconds": "llm_timeout",
    "thinking": "llm_thinking",
    "max_retries": "llm_max_retries",
    "fallback_backend": "fallback_backend",
    "fallback_after_failures": "fallback_after_failures",
}
_SEARCH_KEYS = {
    "searxng_url": "searxng_url",
}
_BUDGET_KEYS = {
    "max_searches": "max_searches",
    "max_pages": "max_pages",
    "max_llm_calls": "max_llm_calls",
    "timeout_seconds": "timeout_seconds",
}
_AGENT_KEYS = {
    "max_turns": "agent_max_turns",
    "max_llm_calls": "agent_max_llm_calls",
    "timeout_seconds": "agent_timeout_seconds",
    "max_deep_searches": "agent_max_deep_searches",
    "max_web_searches": "agent_max_web_searches",
    "max_web_fetches": "agent_max_web_fetches",
    "tool_result_chars": "agent_tool_result_chars",
    "workdir": "agent_workdir",
}
_EXTENSIONS_KEYS = {"enabled": "extensions_enabled"}
_SECTIONS = {
    "llm": _LLM_KEYS,
    "search": _SEARCH_KEYS,
    "budget": _BUDGET_KEYS,
    "agent": _AGENT_KEYS,
    "extensions": _EXTENSIONS_KEYS,
}

_FLOAT_FIELDS = {"llm_temperature", "llm_timeout", "timeout_seconds", "agent_timeout_seconds"}
_INT_FIELDS = {
    "max_searches",
    "max_pages",
    "max_llm_calls",
    "llm_max_retries",
    "fallback_after_failures",
    "agent_max_turns",
    "agent_max_llm_calls",
    "agent_timeout_seconds",
    "agent_max_deep_searches",
    "agent_max_web_searches",
    "agent_max_web_fetches",
    "agent_tool_result_chars",
}
_BOOL_FIELDS = {"llm_thinking"}
_NULLABLE_STR_FIELDS = {"fallback_backend"}
_DEFAULT_NAME = "formiga.toml"
_XDG_PATH = Path("~/.config/formiga/config.toml")


def find_config_file(
    explicit: str | None = None, env: dict[str, str] | None = None
) -> Path | None:
    """Localiza o arquivo de configuração; `None` indica ausência (ok).

    Caminho explícito (`--config` ou `FORMIGA_CONFIG`) precisa existir.
    """
    env = dict(os.environ if env is None else env)
    for source in (explicit, env.get(ENV_CONFIG)):
        if source and source.strip():
            path = Path(source).expanduser()
            if not path.is_file():
                raise ConfigError(f"Arquivo de configuração não encontrado: {path}")
            return path
    local = Path.cwd() / _DEFAULT_NAME
    if local.is_file():
        return local
    xdg = _XDG_PATH.expanduser()
    if xdg.is_file():
        return xdg
    return None


def load_config_values(path: Path) -> dict[str, object]:
    """Lê o TOML e devolve um mapa `campo_do_Config -> valor` validado."""
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Arquivo de configuração não encontrado: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML inválido em {path}: {exc}") from exc

    values: dict[str, object] = {}
    for section, mapping in _SECTIONS.items():
        block = data.get(section)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise ConfigError(f"Seção [{section}] inválida em {path}.")
        for key, value in block.items():
            name = mapping.get(key)
            if name is None:
                raise ConfigError(f"Chave desconhecida [{section}].{key} em {path}.")
            _check_type(name, value, path)
            values[name] = value
    unknown = set(data) - set(_SECTIONS)
    if unknown:
        raise ConfigError(f"Seções desconhecidas em {path}: {sorted(unknown)}.")
    if "openai_api_key" in values and os.name == "posix":
        _check_api_key_permissions(path)
    return values


def load_file_values(
    explicit: str | None = None, env: dict[str, str] | None = None
) -> dict[str, object]:
    """Descobre e carrega o arquivo de config; `{}` quando não há arquivo."""
    path = find_config_file(explicit=explicit, env=env)
    if path is None:
        return {}
    return load_config_values(path)


def _check_type(name: str, value: object, path: Path) -> None:
    if name == "extensions_enabled":
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
    elif name in _FLOAT_FIELDS:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif name in _INT_FIELDS:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif name in _BOOL_FIELDS:
        ok = isinstance(value, bool)
    elif name in _NULLABLE_STR_FIELDS:
        ok = value is None or isinstance(value, str)
    else:
        ok = isinstance(value, str)
    if not ok:
        raise ConfigError(f"Tipo inválido para {name!r} em {path}: {value!r}.")


def _check_api_key_permissions(path: Path) -> None:
    """Arquivo com chave embutida precisa ser legível apenas pelo dono."""
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ConfigError(
            f"O arquivo {path} contém uma chave de API e deve ter permissão 0600 "
            f"(atual: {oct(mode)}). Use 'chmod 600 {path}' ou prefira api_key_env."
        )
