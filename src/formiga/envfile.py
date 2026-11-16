"""Carregamento de arquivo `.env` (sem dependências externas).

Formato suportado: linhas `CHAVE=VALOR`, comentários com `#`, prefixo
opcional `export `, aspas simples/duplas e comentário inline não-quotado.

Precedência: variáveis já presentes no ambiente vencem — o arquivo apenas
preenche o que está faltando (semântica de `os.environ.setdefault`).

Descoberta, nesta ordem:
1. `FORMIGA_ENV_FILE` (variável de ambiente) — precisa existir;
2. `./.env` no diretório atual;
3. `~/.config/formiga/.env`.

Uso típico: `NVIDIA_API_KEY=nvapi-...` no `.env` (ignorado pelo git), com o
Formiga lendo a chave conforme `api_key_env` da configuração. Como o arquivo
costuma conter segredos, exige permissão 0600 — mesma regra do `api_key`
embutido no TOML.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from formiga.config import ConfigError

DEFAULT_NAME = ".env"
_XDG_PATH = Path("~/.config/formiga/.env")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_file(path: Path) -> dict[str, str]:
    """Lê o `.env` e devolve um dicionário validado."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Arquivo .env não encontrado: {path}") from exc
    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            raise ConfigError(
                f"{path}:{lineno}: linha inválida (esperado CHAVE=VALOR): {raw!r}"
            )
        key, _, value = line.partition("=")
        key = key.strip()
        if not _KEY_RE.match(key):
            raise ConfigError(f"{path}:{lineno}: nome de variável inválido: {key!r}")
        values[key] = _parse_value(value.strip())
    if values and os.name == "posix":
        _check_permissions(path)
    return values


def _parse_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    hash_pos = value.find(" #")  # comentário inline não-quotado
    if hash_pos != -1:
        value = value[:hash_pos].rstrip()
    # Valor como `"0.3"  # comentário`: aspas sobram após o corte do comentário.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _check_permissions(path: Path) -> None:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ConfigError(
            f"O arquivo {path} pode conter segredos (ex.: chave de API) e deve "
            f"ter permissão 0600 (atual: {oct(mode)}). Use 'chmod 600 {path}'."
        )


def find_env_file(
    env: dict[str, str] | None = None, config_path: Path | None = None
) -> Path | None:
    """Localiza o `.env`; `None` indica ausência (ok)."""
    env = dict(os.environ if env is None else env)
    explicit = env.get("FORMIGA_ENV_FILE")
    if explicit and explicit.strip():
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"Arquivo .env não encontrado: {path}")
        return path
    candidates = [Path.cwd() / DEFAULT_NAME]
    if config_path is not None:
        candidates.append(config_path.parent / DEFAULT_NAME)
    candidates.append(_XDG_PATH.expanduser())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_env_file(
    env: dict[str, str] | None = None,
    config_path: Path | None = None,
    apply: bool = True,
) -> dict[str, str]:
    """Carrega o `.env` e preenche as variáveis ausentes no ambiente.

    Variáveis já definidas no ambiente **não** são sobrescritas. Com
    `apply=False`, apenas lê e devolve o conteúdo. `{}` quando não há arquivo.
    """
    path = find_env_file(env=env, config_path=config_path)
    if path is None:
        return {}
    values = parse_env_file(path)
    if apply:
        target = os.environ if env is None else env
        for key, value in values.items():
            if key not in target:
                target[key] = value
    return values
