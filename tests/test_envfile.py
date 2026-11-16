"""Testes do carregamento de arquivo .env (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.config import Config, ConfigError
from formiga.envfile import find_env_file, load_env_file, parse_env_file


def write_env(tmp_path: Path, content: str, name: str = ".env") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


ENV_CONTENT = """
# comentário
export NVIDIA_API_KEY=nvapi-abc

FORMIGA_MODEL='qwen2.5:8b'
TEMPERATURE="0.3"  # comentário inline
EMPTY=
"""


class TestParseEnvFile:
    def test_basic_parsing(self, tmp_path):
        path = write_env(tmp_path, ENV_CONTENT)
        path.chmod(0o600)
        values = parse_env_file(path)
        assert values == {
            "NVIDIA_API_KEY": "nvapi-abc",
            "FORMIGA_MODEL": "qwen2.5:8b",
            "TEMPERATURE": "0.3",
            "EMPTY": "",
        }

    def test_quotes_preserve_hash(self, tmp_path):
        path = write_env(tmp_path, 'KEY="valor # não é comentário"\n')
        path.chmod(0o600)
        assert parse_env_file(path)["KEY"] == "valor # não é comentário"

    def test_malformed_line_rejected(self, tmp_path):
        path = write_env(tmp_path, "sem igual aqui\n")
        path.chmod(0o600)
        with pytest.raises(ConfigError, match="linha inválida"):
            parse_env_file(path)

    def test_invalid_variable_name_rejected(self, tmp_path):
        path = write_env(tmp_path, "1ERRADO=x\n")
        path.chmod(0o600)
        with pytest.raises(ConfigError, match="nome de variável"):
            parse_env_file(path)

    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(ConfigError, match="não encontrado"):
            parse_env_file(tmp_path / ".env")

    def test_loose_permissions_rejected(self, tmp_path):
        path = write_env(tmp_path, "NVIDIA_API_KEY=nvapi-abc\n")
        path.chmod(0o644)
        with pytest.raises(ConfigError, match="0600"):
            parse_env_file(path)


class TestDiscovery:
    def test_cwd_dotenv_discovered(self, tmp_path, monkeypatch):
        path = write_env(tmp_path, "A=1\n")
        path.chmod(0o600)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORMIGA_ENV_FILE", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert find_env_file() == path

    def test_explicit_formiga_env_file(self, tmp_path, monkeypatch):
        path = write_env(tmp_path, "A=1\n", name="secrets.env")
        path.chmod(0o600)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORMIGA_ENV_FILE", "secrets.env")
        assert find_env_file() == Path("secrets.env")

    def test_explicit_missing_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORMIGA_ENV_FILE", "inexistente.env")
        with pytest.raises(ConfigError, match="não encontrado"):
            find_env_file()

    def test_no_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORMIGA_ENV_FILE", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert find_env_file() is None
        assert load_env_file() == {}


class TestApply:
    def test_fills_missing_env_only(self, tmp_path, monkeypatch):
        import os

        path = write_env(tmp_path, "NVIDIA_API_KEY=nvapi-do-arquivo\nOUTRA=1\n")
        path.chmod(0o600)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORMIGA_ENV_FILE", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-do-ambiente")
        env = dict(os.environ)  # retrata o ambiente real (com a var já definida)
        load_env_file(env=env)
        # Ambiente real vence; arquivo só preenche o que falta.
        assert env["NVIDIA_API_KEY"] == "nvapi-do-ambiente"
        assert env["OUTRA"] == "1"

    def test_applies_to_real_environment(self, tmp_path, monkeypatch):
        path = write_env(tmp_path, "NVIDIA_API_KEY=nvapi-do-arquivo\n")
        path.chmod(0o600)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORMIGA_ENV_FILE", raising=False)
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        load_env_file()
        import os

        assert os.environ["NVIDIA_API_KEY"] == "nvapi-do-arquivo"

    def test_read_only_mode(self, tmp_path, monkeypatch):
        path = write_env(tmp_path, "A=1\n")
        path.chmod(0o600)
        monkeypatch.chdir(tmp_path)
        values = load_env_file(env={}, apply=False, config_path=path.parent)
        assert values == {"A": "1"}

    def test_key_resolves_via_config(self, tmp_path, monkeypatch):
        path = write_env(tmp_path, "NVIDIA_API_KEY=nvapi-do-arquivo\n")
        path.chmod(0o600)
        monkeypatch.chdir(tmp_path)
        values = load_env_file(env={}, apply=False, config_path=path.parent)
        config = Config(llm_backend="openai", openai_url="https://x/v1", model="m")
        assert config.resolve_api_key(env=values) == "nvapi-do-arquivo"
