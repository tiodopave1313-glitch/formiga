"""Interface de linha de comando do Formiga (seção 11 do PRD)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from formiga import __version__
from formiga.agent.cron import (
    JobStore,
    _iso,
    _parse_iso,
    criar_job,
    utc_now,
)
from formiga.agent.factory import build_agent
from formiga.agent.session import Session
from formiga.config import Config, ConfigError
from formiga.configfile import (
    global_config_path,
    load_file_values,
    read_global_config,
    write_global_config,
)
from formiga.envfile import load_env_file
from formiga.llm import LLMError
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
        "agent", help="Executa o harness agêntico (CLI interativa, --tui ou --print)."
    )
    agent.add_argument("question", nargs="?", default=None, help="Pergunta a executar.")
    agent.add_argument(
        "--print",
        dest="print_mode",
        action="store_true",
        help="Modo headless: imprime a resposta final no stdout.",
    )
    agent.add_argument(
        "--tui",
        dest="tui_mode",
        action="store_true",
        help="Abre a TUI Textual (requer extra: uv add --extra gui formiga).",
    )
    agent.add_argument(
        "--local",
        dest="local_mode",
        action="store_true",
        help="Execução in-process (modo v1), sem usar o daemon do gateway.",
    )
    agent.add_argument(
        "--session-dir",
        type=Path,
        default=None,
        help="Diretório de sessão (default: sessoes/<timestamp_id> sob ./sessoes).",
    )
    agente_retoma = agent.add_mutually_exclusive_group()
    agente_retoma.add_argument(
        "--continue",
        dest="continue_mode",
        action="store_true",
        help="Retoma a última sessão do workdir (in-process).",
    )
    agente_retoma.add_argument(
        "--resume",
        dest="resume_id",
        metavar="ID",
        help="Retoma a sessão com o ID informado (in-process).",
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

    trust = sub.add_parser(
        "trust", help="Adiciona um projeto à allowlist global de extensões (.formiga/extensions)."
    )
    trust.add_argument("caminho", help="Caminho do diretório do projeto.")

    untrust = sub.add_parser(
        "untrust", help="Remove um projeto da allowlist global de extensões."
    )
    untrust.add_argument("caminho", help="Caminho do diretório do projeto.")

    gateway = sub.add_parser(
        "gateway", help="Gerencia o daemon local do Formiga (Fase 6)."
    )
    gateway.add_argument(
        "acao",
        choices=["start", "stop", "status"],
        help="start: inicia o daemon | stop: para | status: mostra o estado.",
    )

    cron = sub.add_parser(
        "cron", help="Gerencia tarefas agendadas (Fase 7)."
    )
    cron_sub = cron.add_subparsers(dest="cron_acao", required=True)

    cron_add = cron_sub.add_parser(
        "add", help="Adiciona uma tarefa agendada."
    )
    cron_add.add_argument("prompt", help="Prompt do job (entre aspas).")
    cron_add.add_argument(
        "--schedule", required=True, help="Expressão cron (5 campos), 'every N[mhd]' ou 'at <ISO>'."
    )
    cron_add.add_argument(
        "--at", dest="at_override", help="Sobrescreve o primeiro disparo (ISO-8601)."
    )
    cron_add.add_argument("--max-turns", type=int, help="Limite de turnos do job.")
    cron_add.add_argument("--max-llm-calls", type=int, help="Limite de chamadas LLM do job.")
    cron_add.add_argument("--timeout-seconds", type=float, help="Tempo máximo do job.")
    cron_add.add_argument(
        "--catchup", choices=["skip", "once"], default="skip",
        help="O que fazer se o gateway estiver parado na hora marcada.",
    )
    cron_add.add_argument("--model", help="Modelo do job.")
    cron_add.add_argument("--profile", help="Perfil do job.")

    cron_sub.add_parser("list", help="Lista tarefas agendadas.")

    cron_rm = cron_sub.add_parser("rm", help="Remove uma tarefa agendada.")
    cron_rm.add_argument("id", help="ID do job.")

    cron_enable = cron_sub.add_parser("enable", help="Habilita uma tarefa.")
    cron_enable.add_argument("id", help="ID do job.")

    cron_disable = cron_sub.add_parser("disable", help="Desabilita uma tarefa.")
    cron_disable.add_argument("id", help="ID do job.")

    cron_run = cron_sub.add_parser("run", help="Executa uma tarefa agora (in-process).")
    cron_run.add_argument("id", help="ID do job.")

    return parser


def _progress(message: str, verbose: bool) -> None:
    if verbose:
        print(message, file=sys.stderr)


def _load_config(args) -> Config:
    load_env_file()
    file_values = load_file_values(explicit=getattr(args, "config", None))
    config = Config.from_sources(file_values=file_values).apply_args(args)
    return config


def _toggle_trust(caminho: str, *, add: bool) -> int:
    """Adiciona ou remove um projeto da allowlist global de extensões.

    Escreve/atualiza [extensions].trusted_projects em
    ~/.formiga/config.toml, usado por discover_extensions para decidir se
    .formiga/extensions/<projeto> carrega.
    """
    target = Path(caminho).expanduser().resolve()
    texto = str(target)
    data = read_global_config()
    extensions = data.get("extensions")
    if not isinstance(extensions, dict):
        extensions = {}
        data["extensions"] = extensions
    trusted = list(extensions.get("trusted_projects") or [])

    if add:
        if texto in trusted:
            print(f"já confiado: {target}")
            return EXIT_OK
        trusted.append(texto)
        verbo = "Adicionado"
    else:
        antes = len(trusted)
        trusted = [item for item in trusted if item != texto]
        if len(trusted) == antes:
            print(f"não estava confiado: {target}")
            return EXIT_OK
        verbo = "Removido"

    extensions["trusted_projects"] = trusted
    try:
        write_global_config(data)
    except (OSError, ValueError) as exc:
        print(
            f"Erro ao gravar {global_config_path()}: {exc}", file=sys.stderr
        )
        return EXIT_OPERATIONAL_FAILURE
    print(f"{verbo} à confiança de extensões: {target}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"formiga {__version__}")
        return EXIT_OK

    if args.command == "trust":
        return _toggle_trust(args.caminho, add=True)
    if args.command == "untrust":
        return _toggle_trust(args.caminho, add=False)

    if args.command == "gateway":
        from formiga.agent.gateway import gateway_start, gateway_status, gateway_stop

        if args.acao == "start":
            return gateway_start(Path.cwd())
        if args.acao == "stop":
            return gateway_stop(Path.cwd())
        if args.acao == "status":
            return gateway_status(Path.cwd())

    if args.command == "cron":

        return _cron_dispatch(args)

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

        session = Session(base_dir=args.session_dir or Path("sessoes"))

        if args.print_mode:
            return _run_print(config, session, args)
        if args.tui_mode:
            return _run_tui(config, session, args)

        if args.continue_mode or args.resume_id:
            return _run_resume(config, session, args)

        return _run_interactive(config, session, args)


def _run_print(config: Config, session: Session, args) -> int:
    """Modo headless --print: uma pergunta, uma resposta."""
    if not args.question or not args.question.strip():
        print("Erro: a pergunta é obrigatória em modo --print.", file=sys.stderr)
        return EXIT_INVALID_INPUT

    loop = build_agent(config, session)
    interrupted = {"flag": False}

    def on_event(event: str, data: dict) -> None:
        if event == "interrupted":
            interrupted["flag"] = True

    loop.on_event = on_event
    answer = loop.run(args.question)
    print(answer)
    loop.end_session()
    return EXIT_INTERRUPTED if interrupted["flag"] else EXIT_OK


def _run_tui(config: Config, session: Session, args) -> int:
    """TUI Textual via --tui (requer extra gui)."""
    try:
        from formiga.agent.tui import AgentApp
    except ImportError as exc:
        print(
            f"Erro: a TUI requer o extra 'gui' (uv add --extra gui formiga). "
            f"Detalhes: {exc}",
            file=sys.stderr,
        )
        return EXIT_OPERATIONAL_FAILURE

    app = AgentApp(config, session, initial_question=args.question)
    try:
        app.run()
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    finally:
        loop = app.loop if hasattr(app, "loop") else None
        if loop is not None:
            loop.end_session()
    return EXIT_OK


def _run_interactive(config: Config, session: Session, args) -> int:
    """CLI interativa padrão.

    Por padrão anexa ao gateway local (sobe on-demand). Com `--local` executa
    in-process (modo v1), sem usar o daemon.
    """
    transcript_path = session.transcript_path
    print(f"formiga agent · sessão: {session.dir}")
    print(f"transcript: {transcript_path} · Ctrl+C interrompe a resposta · Ctrl+D sai")

    budget_snapshot: dict = {}

    def _exibe_evento(event: str, data: dict) -> None:
        nonlocal budget_snapshot
        if event == "stream":
            sys.stdout.write(data.get("text", ""))
            sys.stdout.flush()
        elif event == "tool_start":
            # garante quebra de linha antes da linha de tool
            sys.stdout.write(f"\n⚙ {data.get('tool')} — {data.get('args', '')}")
            sys.stdout.flush()
        elif event == "tool_end":
            if data.get("budget_exhausted"):
                sys.stdout.write(f"  (⚙ {data.get('tool')} — orçamento esgotado)")
            elif not data.get("ok", True):
                seconds = data.get("seconds")
                dur = f" ({seconds:.1f} s)" if isinstance(seconds, (int, float)) else ""
                sys.stdout.write(f"  ✗ erro{dur}")
            else:
                seconds = data.get("seconds")
                if isinstance(seconds, (int, float)):
                    sys.stdout.write(f"  ({seconds:.1f} s)")
            sys.stdout.write("\n")
            sys.stdout.flush()
        elif event == "tool_progress":
            sys.stdout.write(f"· {data.get('message', '')}\n")
            sys.stdout.flush()
        elif event == "notification":
            sys.stdout.write(f"ℹ {data.get('text', '')}\n")
            sys.stdout.flush()
        elif event == "extension_status":
            sys.stdout.write(f"· {data.get('key')}: {data.get('text', '')}\n")
            sys.stdout.flush()
        elif event == "budget":
            budget_snapshot = data
        elif event == "run_final" and not data.get("streamed"):
            # resposta parcial (orçamento/interrupção) já impressa via stream
            # imprime linha de orçamento
            if budget_snapshot:
                t = budget_snapshot.get("turns", 0)
                mt = budget_snapshot.get("max_turns", 0)
                lc = budget_snapshot.get("llm_calls", 0)
                mlc = budget_snapshot.get("max_llm_calls", 0)
                ctx = budget_snapshot.get("context_tokens", 0)
                mctx = budget_snapshot.get("max_context_tokens", 0)
                ext = budget_snapshot.get("ext", 0)
                sys.stdout.write(
                    f"\nturnos {t}/{mt} · llm {lc}/{mlc} · "
                    f"ctx {ctx}/{mctx} · ext {ext} ferramentas\n"
                )
                sys.stdout.flush()
        elif event == "interrupted":
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _imprime_orcamento() -> None:
        if budget_snapshot:
            t = budget_snapshot.get("turns", 0)
            mt = budget_snapshot.get("max_turns", 0)
            lc = budget_snapshot.get("llm_calls", 0)
            mlc = budget_snapshot.get("max_llm_calls", 0)
            ctx = budget_snapshot.get("context_tokens", 0)
            mctx = budget_snapshot.get("max_context_tokens", 0)
            ext = budget_snapshot.get("ext", 0)
            sys.stdout.write(
                f"\nturnos {t}/{mt} · llm {lc}/{mlc} · "
                f"ctx {ctx}/{mctx} · ext {ext} ferramentas\n"
            )
            sys.stdout.flush()

    use_gateway = not args.local_mode
    client = None
    loop = None

    if use_gateway:
        from formiga.agent.client import ensure_gateway

        if not ensure_gateway(Path.cwd()):
            print(
                "Aviso: não foi possível subir o gateway. "
                "Caindo para execução in-process (--local).",
                file=sys.stderr,
            )
            use_gateway = False

    if not use_gateway:
        loop = build_agent(config, session)
        loop.on_event = _exibe_evento

        # Se args.question veio, roda uma vez antes de entrar no prompt
        if args.question and args.question.strip():
            try:
                loop.run(args.question)
            except LLMError as exc:
                print(f"\n✗ erro: {exc}")
            except KeyboardInterrupt:
                pass  # parcial já gravada pelo loop

        while True:
            try:
                q = input("\npergunta> ")
            except EOFError:
                if loop is not None:
                    loop.end_session()
                print(f"\nSaindo. Sessão salva em {transcript_path}")
                return EXIT_OK
            except KeyboardInterrupt:
                if loop is not None:
                    loop.end_session()
                print()
                return EXIT_OK

            if not q.strip():
                continue

            if q.startswith("/"):
                corpo = q[1:].strip()
                if not corpo:
                    continue
                partes = corpo.split(None, 1)
                nome = partes[0]
                argumentos = partes[1] if len(partes) > 1 else ""
                try:
                    resultado = loop.registry.dispatch_command(nome, argumentos)
                except KeyError:
                    print(f"Comando desconhecido: /{nome}")
                    continue
                print(resultado)
                continue

            try:
                loop.run(q)
                _imprime_orcamento()
            except LLMError as exc:
                print(f"\n✗ erro: {exc}")
                continue
            except KeyboardInterrupt:
                continue  # loop trata internamente; volta ao prompt

        if loop is not None:
            loop.end_session()
        return EXIT_OK

    # ---------- modo gateway (assíncrono, tudo em um único loop) ----------
    async def _main_gateway() -> None:
        from formiga.agent.client import GatewayClient

        nonlocal client
        client = GatewayClient(Path.cwd())
        try:
            await client.connect()
            await client.create(
                session_id=session.session_id,
                model=args.model,
                ollama_url=args.ollama_url,
                searxng_url=args.searxng_url,
                llm_backend=args.llm_backend,
                openai_url=args.openai_url,
                openai_api_key_env=args.openai_api_key_env,
                llm_thinking=args.llm_thinking,
                llamacpp_thinking=args.llamacpp_thinking,
                fallback_backend=args.fallback_backend,
                fallback_after_failures=args.fallback_after_failures,
                llm_max_retries=args.llm_max_retries,
                llm_temperature=args.llm_temperature,
                max_llm_calls=args.max_llm_calls,
                timeout_seconds=args.timeout_seconds,
            )
        except (ConnectionError, TimeoutError, OSError) as exc:
            print(
                f"Aviso: não foi possível anexar ao gateway ({exc}). "
                "Caindo para execução in-process (--local).",
                file=sys.stderr,
            )
            return

        # Se args.question veio, roda uma vez antes de entrar no prompt
        if args.question and args.question.strip():
            client.on_event = _exibe_evento
            try:
                await client.submit(args.question)
            except LLMError as exc:
                print(f"\n✗ erro: {exc}")
            except KeyboardInterrupt:
                pass
            _imprime_orcamento()

        loop_async = asyncio.get_event_loop()

        while True:
            try:
                q = await loop_async.run_in_executor(
                    None, input, "\npergunta> "
                )
            except EOFError:
                await client.close()
                print(f"\nSaindo. Sessão salva em {transcript_path}")
                return
            except KeyboardInterrupt:
                print()
                await client.close()
                return

            if not q.strip():
                continue

            if q.startswith("/"):
                corpo = q[1:].strip()
                if not corpo:
                    continue
                partes = corpo.split(None, 1)
                nome = partes[0]
                argumentos = partes[1] if len(partes) > 1 else ""
                try:
                    resultado = await client.command(nome, argumentos)
                except (ConnectionError, RuntimeError, TimeoutError) as exc:
                    print(f"Erro ao executar /{nome} via gateway: {exc}")
                    continue
                print(resultado)
                continue

            client.on_event = _exibe_evento
            try:
                await client.submit(q)
            except LLMError as exc:
                print(f"\n✗ erro: {exc}")
                continue
            except KeyboardInterrupt:
                continue
            _imprime_orcamento()

    asyncio.run(_main_gateway())
    return EXIT_OK

    asyncio.run(_main_gateway())
    return EXIT_OK


def _run_resume(config: Config, session: Session, args) -> int:
    """Retoma uma sessão existente (in-process).

    Carrega `messages.json` da sessão e continua o loop interativo
    a partir do histórico salvo.
    """
    base_dir = args.session_dir or Path("sessoes")

    # Determina o session_id: --resume <id> ou a última sessão do workdir.
    if args.resume_id:
        session_id = args.resume_id
    else:
        sessoes = Session.list_sessions(base_dir)
        if not sessoes:
            print(f"Nenhuma sessão encontrada em {base_dir}.", file=sys.stderr)
            return EXIT_INVALID_INPUT
        session_id = sessoes[-1].session_id  # a mais recente (listadas ordenadas)

    session = Session(base_dir, session_id=session_id)
    transcript_path = session.transcript_path
    print(f"formiga agent · retomando sessão: {session.dir}")
    print(f"transcript: {transcript_path} · Ctrl+C interrompe a resposta · Ctrl+D sai")

    loop = build_agent(config, session)

    # Substitui as mensagens só-system pelas mensagens salvas da sessão.
    mensagens_salvas = session.load_messages()
    if mensagens_salvas:
        loop.messages = mensagens_salvas
    else:
        print("Sessão vazia; iniciando do zero.", file=sys.stderr)

    budget_snapshot: dict = {}

    def _exibe_evento(event: str, data: dict) -> None:
        nonlocal budget_snapshot
        if event == "stream":
            sys.stdout.write(data.get("text", ""))
            sys.stdout.flush()
        elif event == "tool_start":
            sys.stdout.write(f"\n⚙ {data.get('tool')} — {data.get('args', '')}")
            sys.stdout.flush()
        elif event == "tool_end":
            if data.get("budget_exhausted"):
                sys.stdout.write(f"  (⚙ {data.get('tool')} — orçamento esgotado)")
            elif not data.get("ok", True):
                seconds = data.get("seconds")
                dur = f" ({seconds:.1f} s)" if isinstance(seconds, (int, float)) else ""
                sys.stdout.write(f"  ✗ erro{dur}")
            else:
                seconds = data.get("seconds")
                if isinstance(seconds, (int, float)):
                    sys.stdout.write(f"  ({seconds:.1f} s)")
            sys.stdout.write("\n")
            sys.stdout.flush()
        elif event == "tool_progress":
            sys.stdout.write(f"· {data.get('message', '')}\n")
            sys.stdout.flush()
        elif event == "notification":
            sys.stdout.write(f"ℹ {data.get('text', '')}\n")
            sys.stdout.flush()
        elif event == "extension_status":
            sys.stdout.write(f"· {data.get('key')}: {data.get('text', '')}\n")
            sys.stdout.flush()
        elif event == "budget":
            budget_snapshot = data
        elif event == "run_final" and not data.get("streamed"):
            if budget_snapshot:
                t = budget_snapshot.get("turns", 0)
                mt = budget_snapshot.get("max_turns", 0)
                lc = budget_snapshot.get("llm_calls", 0)
                mlc = budget_snapshot.get("max_llm_calls", 0)
                ctx = budget_snapshot.get("context_tokens", 0)
                mctx = budget_snapshot.get("max_context_tokens", 0)
                ext = budget_snapshot.get("ext", 0)
                sys.stdout.write(
                    f"\nturnos {t}/{mt} · llm {lc}/{mlc} · "
                    f"ctx {ctx}/{mctx} · ext {ext} ferramentas\n"
                )
                sys.stdout.flush()
        elif event == "interrupted":
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _imprime_orcamento() -> None:
        if budget_snapshot:
            t = budget_snapshot.get("turns", 0)
            mt = budget_snapshot.get("max_turns", 0)
            lc = budget_snapshot.get("llm_calls", 0)
            mlc = budget_snapshot.get("max_llm_calls", 0)
            ctx = budget_snapshot.get("context_tokens", 0)
            mctx = budget_snapshot.get("max_context_tokens", 0)
            ext = budget_snapshot.get("ext", 0)
            sys.stdout.write(
                f"\nturnos {t}/{mt} · llm {lc}/{mlc} · "
                f"ctx {ctx}/{mctx} · ext {ext} ferramentas\n"
            )
            sys.stdout.flush()

    loop.on_event = _exibe_evento

    while True:
        try:
            q = input("\npergunta> ")
        except EOFError:
            print(f"\nSaindo. Sessão salva em {transcript_path}")
            return EXIT_OK
        except KeyboardInterrupt:
            print()
            return EXIT_OK

        if not q.strip():
            continue

        if q.startswith("/"):
            corpo = q[1:].strip()
            if not corpo:
                continue
            partes = corpo.split(None, 1)
            nome = partes[0]
            argumentos = partes[1] if len(partes) > 1 else ""
            try:
                resultado = loop.registry.dispatch_command(nome, argumentos)
            except KeyError:
                print(f"Comando desconhecido: /{nome}")
                continue
            print(resultado)
            continue

        try:
            loop.run(q)
            _imprime_orcamento()
        except LLMError as exc:
            print(f"\n✗ erro: {exc}")
            continue
        except KeyboardInterrupt:
            continue  # loop trata internamente; volta ao prompt


# ---------------------------------------------------------------------- #
# CLI: formiga cron (Fase 7)
# ---------------------------------------------------------------------- #


def _cron_dispatch(args) -> int:
    store = JobStore()
    jobs = store.load()

    if args.cron_acao == "add":
        return _cron_add(store, jobs, args)
    if args.cron_acao == "list":
        return _cron_list(jobs)
    if args.cron_acao == "rm":
        return _cron_rm(store, jobs, args.id)
    if args.cron_acao == "enable":
        return _cron_toggle(store, jobs, args.id, True)
    if args.cron_acao == "disable":
        return _cron_toggle(store, jobs, args.id, False)
    if args.cron_acao == "run":
        return _cron_run(jobs, args.id)
    return EXIT_INVALID_INPUT


def _cron_add(store, jobs, args) -> int:
    """Adiciona um job a jobs.json e calcula o primeiro next_run."""
    agora = utc_now()
    primeiro = None
    if args.at_override:
        try:
            primeiro = _parse_iso(args.at_override)
        except ValueError as exc:
            print(f"Erro: --at inválido: {exc}", file=sys.stderr)
            return EXIT_INVALID_INPUT

    try:
        job = criar_job(
            prompt=args.prompt,
            schedule=args.schedule,
            id=None,
            enabled=True,
            model=args.model,
            profile=args.profile,
            max_turns=args.max_turns,
            max_llm_calls=args.max_llm_calls,
            timeout_seconds=args.timeout_seconds,
            catchup=args.catchup,
            tz=None,
            output_dir=None,
            now_fn=lambda: agora,
        )
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    if primeiro is not None:
        job.next_run = _iso(primeiro)

    jobs[job.id] = job
    store.save(jobs)
    print(f"Job criado: {job.id}")
    print(f"  schedule: {job.schedule}")
    print(f"  próximo:  {job.next_run}")
    print(f"  catchup:  {job.catchup}")
    return EXIT_OK


def _cron_list(jobs) -> int:
    """Lista os jobs agendados."""
    if not jobs:
        print("Nenhuma tarefa agendada.")
        return EXIT_OK
    print("Tarefas agendadas (cron):")
    for jid in sorted(jobs):
        job = jobs[jid]
        status = f"{job.last_status or '—'}"
        if job.last_error:
            status += f" ({job.last_error})"
        print(
            f"  {jid:8} | {'ativado' if job.enabled else 'desabilitado':9} | "
            f"{job.schedule:24} | próximo: {job.next_run or '—'} | {status}"
        )
    return EXIT_OK


def _cron_rm(store, jobs, job_id: str) -> int:
    if job_id not in jobs:
        print(f"Job não encontrado: {job_id}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    del jobs[job_id]
    store.save(jobs)
    print(f"Job removido: {job_id}")
    return EXIT_OK


def _cron_toggle(store, jobs, job_id: str, habilitar: bool) -> int:
    if job_id not in jobs:
        print(f"Job não encontrado: {job_id}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    jobs[job_id].enabled = habilitar
    store.save(jobs)
    verbo = "Habilitado" if habilitar else "Desabilitado"
    print(f"{verbo}: {job_id}")
    return EXIT_OK


def _cron_run(jobs, job_id: str) -> int:
    """Executa um job agora, in-process (offline, sem depender do daemon)."""
    if job_id not in jobs:
        print(f"Job não encontrado: {job_id}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    job = jobs[job_id]

    agora = utc_now()
    agora_iso = _iso(agora)
    timestamp = agora.strftime("%Y-%m-%d_%H%M%S")
    cron_base = Path("sessoes") / "cron" / job.id
    session_id = f"cron_{timestamp}"

    print(f"Executando job {job.id} (in-process)...")
    print(f"  schedule: {job.schedule}")
    print(f"  sessão:   {cron_base / session_id}")

    kwargs: dict[str, object] = {"agent_workdir": str(Path.cwd())}
    if job.model:
        kwargs["model"] = job.model
    if job.profile:
        kwargs["active_profile"] = job.profile
    if job.max_turns is not None:
        kwargs["agent_max_turns"] = job.max_turns
    if job.max_llm_calls is not None:
        kwargs["agent_max_llm_calls"] = job.max_llm_calls
    if job.timeout_seconds is not None:
        kwargs["agent_timeout_seconds"] = job.timeout_seconds
    config = Config(**kwargs)

    contexto = (
        f"[Contexto do job agendado]\n"
        f"Job: {job.id}\n"
        f"Disparado em: {agora_iso}\n"
        f"Diretório: {Path.cwd()}\n"
        f"\n{job.prompt}\n"
    )

    sess = Session(cron_base, session_id=session_id)
    loop = build_agent(config, sess)
    try:
        loop.run(contexto)
        print(f"\nJob {job.id} concluído com sucesso.")
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001 — isola o job.
        import traceback

        traceback.print_exc()
        print(f"\nJob {job.id} falhou: {exc}", file=sys.stderr)
        return EXIT_OPERATIONAL_FAILURE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
