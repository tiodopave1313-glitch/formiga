"""Interface de linha de comando do Formiga (seção 11 do PRD)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from formiga import __version__
from formiga.agent.chat import build_chat_client
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools import FILE_TOOLS
from formiga.agent.tools.deepsearch import DeepSearchTool
from formiga.agent.tools.shell import BashTool
from formiga.agent.tools.web import WebFetchTool, WebSearchTool
from formiga.config import Config, ConfigError
from formiga.configfile import load_file_values
from formiga.envfile import load_env_file
from formiga.orchestrator import run_research
from formiga.storage import OutputDirExists, StorageError

EXIT_OK = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_INVALID_INPUT = 2
EXIT_INTERRUPTED = 130


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    """Argumentos comuns de backend/modelo (compartilhados por research e agent)."""
    parser.add_argument(
        "--model", help="Nome do modelo no Ollama ou ID do modelo no backend remoto."
    )
    parser.add_argument("--ollama-url", dest="ollama_url", help="Endpoint do Ollama.")
    parser.add_argument(
        "--llm-backend",
        dest="llm_backend",
        choices=["ollama", "llamacpp", "openai"],
        help="Backend do modelo: Ollama, llama-server ou endpoint remoto OpenAI-compatível.",
    )
    parser.add_argument(
        "--llm-base-url",
        dest="openai_url",
        help=(
            "URL base do endpoint remoto OpenAI-compatível "
            "(ex.: https://integrate.api.nvidia.com/v1)."
        ),
    )
    parser.add_argument(
        "--api-key-env",
        dest="openai_api_key_env",
        help=(
            "Nome da variável de ambiente com a chave do endpoint remoto "
            "(default: NVIDIA_API_KEY)."
        ),
    )
    parser.add_argument(
        "--llm-thinking",
        dest="llm_thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Deixar o modelo raciocinar antes da resposta. Default: ligado."
        ),
    )
    parser.add_argument(
        "--fallback-backend",
        dest="fallback_backend",
        choices=["ollama", "llamacpp", "openai"],
        default=None,
        help=(
            "Backup opt-in: ativa somente após falhas do backend principal "
            "e permanece pelo resto da execução. Default: sem backup."
        ),
    )
    parser.add_argument(
        "--fallback-after-failures",
        dest="fallback_after_failures",
        type=int,
        default=None,
        help="Falhas consecutivas do principal antes do backup assumir (default 1).",
    )
    parser.add_argument(
        "--llm-max-retries",
        dest="llm_max_retries",
        type=int,
        default=None,
        help="Retries HTTP (429/5xx) no backend remoto, com backoff (default 2).",
    )
    parser.add_argument(
        "--llamacpp-url", dest="llamacpp_url", help="Endpoint do llama-server (OpenAI-compatível)."
    )
    parser.add_argument(
        "--llamacpp-thinking",
        dest="llamacpp_thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Deixar o modelo raciocinar antes da resposta (consome tokens). Default: ligado."
        ),
    )
    parser.add_argument(
        "--llm-timeout-seconds",
        dest="llm_timeout",
        type=float,
        help="Timeout por chamada ao modelo (default 300; CPU lenta pode exigir mais).",
    )
    parser.add_argument(
        "--llm-temperature",
        dest="llm_temperature",
        type=float,
        help=(
            "Temperatura de amostragem (default 1.0, recomendado pela ficha "
            "do Nemotron 3.5 Bolt; 0.2 pode ajudar em JSON estruturado)."
        ),
    )


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
    _add_llm_args(research)
    research.add_argument(
        "--searxng-url", dest="searxng_url", help="Endpoint da instância SearXNG."
    )
    research.add_argument(
        "--max-searches", dest="max_searches", type=int, help="Limite de buscas."
    )
    research.add_argument(
        "--max-pages", dest="max_pages", type=int, help="Limite de páginas."
    )
    research.add_argument(
        "--max-llm-calls", dest="max_llm_calls", type=int, help="Limite total de chamadas ao LLM."
    )
    research.add_argument(
        "--timeout-seconds", dest="timeout_seconds", type=int, help="Tempo máximo da execução."
    )
    research.add_argument(
        "--overwrite",
        action="store_true",
        help="Autoriza sobrescrever um diretório de saída existente.",
    )
    research.add_argument("--verbose", action="store_true", help="Eventos operacionais adicionais.")

    agent = sub.add_parser(
        "agent", help="Executa o harness agêntico (TUI ou modo headless --print)."
    )
    agent.add_argument("question", nargs="?", default=None, help="Pergunta a executar.")
    agent.add_argument(
        "--print",
        dest="print_mode",
        action="store_true",
        help="Modo headless: imprime a resposta final no stdout.",
    )
    agent.add_argument(
        "--session-dir",
        type=Path,
        default=None,
        help="Diretório de sessão (default: sessoes/<timestamp_id> sob ./sessoes).",
    )
    agent.add_argument("--config", default=None, help="Arquivo de configuração TOML.")
    _add_llm_args(agent)
    agent.add_argument(
        "--searxng-url", dest="searxng_url", help="Endpoint da instância SearXNG."
    )
    agent.add_argument(
        "--max-llm-calls", dest="max_llm_calls", type=int,
        help="Limite de chamadas ao LLM."
    )
    agent.add_argument(
        "--timeout-seconds", dest="timeout_seconds", type=int,
        help="Tempo máximo da sessão."
    )
    agent.add_argument("--verbose", action="store_true", help="Eventos operacionais adicionais.")

    sub.add_parser("version", help="Mostra a versão.")
    return parser


def _progress(message: str, verbose: bool) -> None:
    if verbose:
        print(message, file=sys.stderr)


def _load_config(args) -> Config:
    load_env_file()
    file_values = load_file_values(explicit=getattr(args, "config", None))
    config = Config.from_sources(file_values=file_values).apply_args(args)
    return config


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
            config = _load_config(args)
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

    if args.command == "agent":
        try:
            config = _load_config(args)
        except ConfigError as exc:
            print(f"Erro de configuração: {exc}", file=sys.stderr)
            return EXIT_INVALID_INPUT

        try:
            session = Session(
                base_dir=args.session_dir or Path("sessoes"),
            )
            chat_client = build_chat_client(config)
            workdir = Path(config.agent_workdir)
            tools = [
                BashTool(workdir),
                WebSearchTool(config),
                WebFetchTool(config),
                DeepSearchTool(config, session.research_dir),
                *FILE_TOOLS,
            ]
            loop = AgentLoop(chat_client, tools, session, config)
            if args.print_mode:
                if not args.question or not args.question.strip():
                    print("Erro: a pergunta é obrigatória em modo --print.", file=sys.stderr)
                    return EXIT_INVALID_INPUT
                answer = loop.run(args.question)
                print(answer)
                return EXIT_OK
            # TUI interativa (fase 3): ainda não implementada.
            print(
                "Erro: a TUI interativa ainda não foi implementada. Use --print.",
                file=sys.stderr,
            )
            return EXIT_INVALID_INPUT
        except KeyboardInterrupt:
            print("Interrompido pelo usuário.", file=sys.stderr)
            return EXIT_INTERRUPTED
        except Exception as exc:  # noqa: BLE001
            print(f"Falha operacional: {exc}", file=sys.stderr)
            return EXIT_OPERATIONAL_FAILURE

    parser.error(f"Comando desconhecido: {args.command}")
    return EXIT_INVALID_INPUT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
