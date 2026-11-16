"""Interface de linha de comando do Formiga (seção 11 do PRD)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from formiga import __version__
from formiga.config import Config, ConfigError
from formiga.configfile import load_file_values
from formiga.orchestrator import run_research
from formiga.storage import OutputDirExists, StorageError

EXIT_OK = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_INVALID_INPUT = 2
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formiga",
        description="Harness minimalista de pesquisa profunda.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    research = sub.add_parser("research", help="Executa uma pesquisa e gera um relatório.")
    research.add_argument("question", help="Pergunta a investigar.")
    research.add_argument("--output", type=Path, help="Diretório de saída.")
    research.add_argument(
        "--config",
        default=None,
        help="Arquivo de configuração TOML (default: ./formiga.toml se existir).",
    )
    research.add_argument(
        "--model", help="Nome do modelo no Ollama ou ID do modelo no backend remoto."
    )
    research.add_argument("--ollama-url", dest="ollama_url", help="Endpoint do Ollama.")
    research.add_argument(
        "--searxng-url", dest="searxng_url", help="Endpoint da instância SearXNG."
    )
    research.add_argument(
        "--llm-backend",
        dest="llm_backend",
        choices=["ollama", "llamacpp", "openai"],
        help="Backend do modelo: Ollama, llama-server ou endpoint remoto OpenAI-compatível.",
    )
    research.add_argument(
        "--llm-base-url",
        dest="openai_url",
        help=(
            "URL base do endpoint remoto OpenAI-compatível "
            "(ex.: https://integrate.api.nvidia.com/v1)."
        ),
    )
    research.add_argument(
        "--api-key-env",
        dest="openai_api_key_env",
        help=(
            "Nome da variável de ambiente com a chave do endpoint remoto "
            "(default: NVIDIA_API_KEY)."
        ),
    )
    research.add_argument(
        "--llm-thinking",
        dest="llm_thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Deixar o modelo raciocinar antes do JSON (os limites por tarefa "
            "recebem folga extra de tokens). Default: ligado."
        ),
    )
    research.add_argument(
        "--fallback-backend",
        dest="fallback_backend",
        choices=["ollama", "llamacpp", "openai"],
        default=None,
        help=(
            "Backup opt-in: ativa somente após falhas do backend principal "
            "e permanece pelo resto da execução. Default: sem backup."
        ),
    )
    research.add_argument(
        "--fallback-after-failures",
        dest="fallback_after_failures",
        type=int,
        default=None,
        help="Falhas consecutivas do principal antes do backup assumir (default 1).",
    )
    research.add_argument(
        "--llm-max-retries",
        dest="llm_max_retries",
        type=int,
        default=None,
        help="Retries HTTP (429/5xx) no backend remoto, com backoff (default 2).",
    )
    research.add_argument(
        "--llamacpp-url", dest="llamacpp_url", help="Endpoint do llama-server (OpenAI-compatível)."
    )
    research.add_argument(
        "--llamacpp-thinking",
        dest="llamacpp_thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Deixar o modelo raciocinar antes do JSON (consome tokens de geração; "
            "os limites por tarefa recebem folga extra). Default: ligado."
        ),
    )
    research.add_argument("--max-searches", dest="max_searches", type=int, help="Limite de buscas.")
    research.add_argument("--max-pages", dest="max_pages", type=int, help="Limite de páginas.")
    research.add_argument(
        "--max-llm-calls", dest="max_llm_calls", type=int, help="Limite total de chamadas ao LLM."
    )
    research.add_argument(
        "--timeout-seconds", dest="timeout_seconds", type=int, help="Tempo máximo da execução."
    )
    research.add_argument(
        "--llm-timeout-seconds",
        dest="llm_timeout",
        type=float,
        help="Timeout por chamada ao modelo (default 300; CPU lenta pode exigir mais).",
    )
    research.add_argument(
        "--llm-temperature",
        dest="llm_temperature",
        type=float,
        help=(
            "Temperatura de amostragem (default 1.0, recomendado pela ficha "
            "do Nemotron 3.5 Bolt; 0.2 pode ajudar em JSON estruturado)."
        ),
    )
    research.add_argument(
        "--overwrite",
        action="store_true",
        help="Autoriza sobrescrever um diretório de saída existente.",
    )
    research.add_argument("--verbose", action="store_true", help="Eventos operacionais adicionais.")

    sub.add_parser("version", help="Mostra a versão.")
    return parser


def _progress(message: str, verbose: bool) -> None:
    if verbose:
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"formiga {__version__}")
        return EXIT_OK

    if args.command == "research":
        if not args.question.strip():
            print("Erro: a pergunta não pode ser vazia.", file=sys.stderr)
            return EXIT_INVALID_INPUT
        try:
            from formiga.envfile import load_env_file

            # .env preenche variáveis ausentes (ex.: NVIDIA_API_KEY); o
            # ambiente real sempre vence. Precisa vir antes da config.
            load_env_file()
            file_values = load_file_values(explicit=getattr(args, "config", None))
            config = Config.from_sources(file_values=file_values).apply_args(args)
        except ConfigError as exc:
            print(f"Erro de configuração: {exc}", file=sys.stderr)
            return EXIT_INVALID_INPUT

        try:
            result = run_research(config, progress=lambda m: _progress(m, config.verbose))
            print(result.report_path)
            print(f"status: {result.status}")
            return EXIT_OK
        except OutputDirExists as exc:
            print(f"Erro de entrada: {exc}", file=sys.stderr)
            return EXIT_INVALID_INPUT
        except KeyboardInterrupt:
            print("Interrompido pelo usuário. Checkpoint salvo permanece legível.", file=sys.stderr)
            return EXIT_INTERRUPTED
        except StorageError as exc:
            print(f"Erro de persistência: {exc}", file=sys.stderr)
            return EXIT_OPERATIONAL_FAILURE
        except Exception as exc:  # noqa: BLE001 — última defesa da CLI.
            print(f"Falha operacional: {exc}", file=sys.stderr)
            return EXIT_OPERATIONAL_FAILURE

    parser.error(f"Comando desconhecido: {args.command}")
    return EXIT_INVALID_INPUT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
