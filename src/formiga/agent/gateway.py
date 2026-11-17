"""Gateway local do Formiga Agent (seção 11 do PRD v2 — Fase 6).

Daemon WebSocket apenas em loopback que **possui o `AgentLoop` e as sessões**,
sobrevivendo ao terminal. As interfaces (CLI e TUI) viram clientes que se
anexam via WS.

Modelo de processo:

    ┌────────────────┐  anexa / cria   ┌────────────────────────────────┐
    │ formiga agent  │ ───────────────▶│ formiga gateway (daemon)       │
    │ (CLI = client) │ ◀───────────────│  · possui sessoes/             │
    │ formiga --tui  │  eventos (WS)   │  · executa o AgentLoop         │
    │ (mesmo proto)  │                 │  · fila de prompts persistida  │
    └────────────────┘                 └────────────────────────────────┘

Não há autenticação nem TLS no MVP (single-user, loopback). Scripts e `--print`
nunca dependem do daemon (in-process).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from formiga.agent.factory import build_agent
from formiga.agent.session import Session
from formiga.config import Config, ConfigError
from formiga.configfile import global_config_path

# Diretório de configuração global (~/.formiga).
_GLOBAL_DIR = global_config_path().parent

# PID + porta + versão gravados em <GLOBAL_DIR>/gateway-<hash(cwd)>.json
_PIDFILE_NAME = "gateway-{}.json"
# Idle-shutdown (s) para daemon subido on-demand: 10 min sem sessão ativa.
IDLE_SHUTDOWN_SECONDS = 600


def _workdir_hash(cwd: Path | str) -> str:
    """Hash curto do diretório de trabalho (um gateway por workdir)."""
    return hashlib.sha1(str(cwd).encode()).hexdigest()[:8]


def _pidfile_path(cwd: Path | str) -> Path:
    return _GLOBAL_DIR / _PIDFILE_NAME.format(_workdir_hash(cwd))


def _read_pidfile(cwd: Path | str) -> dict | None:
    path = _pidfile_path(cwd)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_pidfile(cwd: Path | str, port: int, pid: int) -> None:
    _GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    path = _pidfile_path(cwd)
    payload = {
        "pid": pid,
        "port": port,
        "cwd": str(Path(cwd).resolve()),
        "version": "0.2.0a1",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _remove_pidfile(cwd: Path | str) -> None:
    with contextlib.suppress(OSError):
        _pidfile_path(cwd).unlink(missing_ok=True)  # type: ignore[attr-defined]


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------- #
# WebSocket mínimo (biblioteca padrão)
# ---------------------------------------------------------------------- #

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_accept_key(key: str) -> str:
    sha = hashlib.sha1((key + _WS_GUID).encode()).digest()
    return base64.b64encode(sha).decode()


async def _ws_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    """Handshake HTTP de upgrade para WebSocket. Devolve True se aceito."""
    try:
        request_line = await reader.readline()
        if not request_line:
            return False
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if line in (b"", b"\r\n"):
                break
            decoded = line.decode("utf-8", "replace").rstrip("\r\n")
            if ": " in decoded:
                k, v = decoded.split(": ", 1)
                headers[k.lower()] = v

        key = headers.get("sec-websocket-key", "")
        if not key:
            return False

        accept = _ws_accept_key(key)
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        writer.write(response.encode("utf-8"))
        await writer.drain()
        return True
    except (OSError, asyncio.IncompleteReadError):
        return False


def _ws_frame(text: str) -> bytes:
    """Enquadra um texto como quadro WebSocket (servidor → cliente, sem máscara)."""
    payload = text.encode("utf-8")
    b0 = 0x81  # FIN + texto
    length = len(payload)
    if length < 126:
        header = bytes([b0, length])
    elif length <= 0xFFFF:
        header = bytes([b0, 126]) + length.to_bytes(2, "big")
    else:
        header = bytes([b0, 127]) + length.to_bytes(8, "big")
    return header + payload


def _ws_close(code: int = 1000, reason: str = "") -> bytes:
    payload = code.to_bytes(2, "big") + reason.encode("utf-8")
    b0 = 0x88  # FIN + close
    header = bytes([b0, len(payload)])
    return header + payload


async def _ws_read_frame(reader: asyncio.StreamReader) -> str | None:
    """Lê um quadro de texto (cliente → servidor, com máscara). Devolve None se fechar."""
    try:
        b0 = await reader.readexactly(1)
        b1 = await reader.readexactly(1)
    except (asyncio.IncompleteReadError, OSError):
        return None

    fin = bool(b0[0] & 0x80)
    opcode = b0[0] & 0x0F
    masked = bool(b1[0] & 0x80)
    length = b1[0] & 0x7F

    if opcode == 0x8:  # close
        return None
    if opcode != 0x1:  # só texto
        return None
    if not masked:
        return None

    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")

    mask = await reader.readexactly(4)
    data = await reader.readexactly(length) if length else b""

    unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return unmasked.decode("utf-8", "replace") if fin else ""


# ---------------------------------------------------------------------- #
# Sessão gerenciada pelo gateway
# ---------------------------------------------------------------------- #


class GatewaySession:
    """Uma sessão do agente sob controle do gateway.

    Possui o `AgentLoop`, a `Session` em disco e a fila de prompts pendentes.
    """

    def __init__(
        self,
        session_id: str,
        config: Config,
        base_dir: Path,
        on_event: Callable[[str, dict], None],
    ) -> None:
        self.session_id = session_id
        self.config = config
        self.base_dir = base_dir
        self.session = Session(base_dir, session_id=session_id)
        self.loop = build_agent(config, self.session, on_event=on_event)
        self.queue_file = self.session.dir / "queue.json"
        self._pending: list[str] = []
        self._load_queue()

    def _load_queue(self) -> None:
        """Carrega prompts pendentes do disco (crash-durable)."""
        if not self.queue_file.exists():
            return
        try:
            payload = json.loads(self.queue_file.read_text(encoding="utf-8"))
            self._pending = list(payload.get("pending", []))
        except (OSError, ValueError):
            self._pending = []

    def _save_queue(self) -> None:
        payload = {"pending": self._pending}
        self.queue_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def enqueue(self, prompt: str) -> None:
        """Adiciona um prompt à fila e grava no disco antes de executar."""
        self._pending.append(prompt)
        self._save_queue()

    def dequeue(self) -> str | None:
        """Remove e devolve o próximo prompt da fila; grava no disco."""
        if not self._pending:
            return None
        prompt = self._pending.pop(0)
        self._save_queue()
        return prompt

    def run_pending(self) -> None:
        """Executa todos os prompts enfileirados (reexecução após restart)."""
        while self._pending:
            prompt = self.dequeue()
            if prompt:
                self.loop.run(prompt)


# ---------------------------------------------------------------------- #
# Gateway
# ---------------------------------------------------------------------- #


class Gateway:
    """Servidor WebSocket local: gerencia sessões e faz broadcast de eventos."""

    def __init__(self, cwd: Path | str) -> None:
        self.cwd = Path(cwd).resolve()
        self.server: asyncio.AbstractServer | None = None
        self.sessions: dict[str, GatewaySession] = {}
        self.clients: dict[str, set[asyncio.StreamWriter]] = {}  # session_id -> writers
        self._idle_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # -- ciclo de vida ------------------------------------------------- #

    async def start(self, port: int = 0) -> int:
        """Inicia o servidor na porta informada (0 = aleatória). Devolve a porta."""
        self.server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", port
        )
        actual_port = self.server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        _write_pidfile(self.cwd, actual_port, os.getpid())
        self._schedule_idle()
        return actual_port

    async def stop(self) -> None:
        """Para o servidor e remove o pidfile."""
        self._stop.set()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        _remove_pidfile(self.cwd)

    def _schedule_idle(self) -> None:
        """Agenda o idle-shutdown do daemon on-demand."""
        if self._idle_task:
            self._idle_task.cancel()

        async def _idle() -> None:
            try:
                await asyncio.sleep(IDLE_SHUTDOWN_SECONDS)
                if not self.sessions:
                    await self.stop()
            except asyncio.CancelledError:
                pass

        self._idle_task = asyncio.create_task(_idle())

    def _reset_idle(self) -> None:
        """Reinicia o contador de idle quando há sessão ativa."""
        self._schedule_idle()

    # -- clientes ------------------------------------------------------ #

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Atende uma conexão WS: handshake + loop de frames."""
        if not await _ws_handshake(reader, writer):
            writer.close()
            return

        session_id: str | None = None
        try:
            while not self._stop.is_set():
                text = await _ws_read_frame(reader)
                if text is None:
                    break
                try:
                    msg = json.loads(text)
                except ValueError:
                    continue
                await self._dispatch(msg, writer)
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            if session_id:
                self.clients.get(session_id, set()).discard(writer)
            writer.close()

    async def _dispatch(
        self, msg: dict, writer: asyncio.StreamWriter
    ) -> None:
        action = msg.get("action")
        session_id = msg.get("session")

        if action == "create":
            sid = msg.get("session") or self._new_session_id()
            try:
                config = self._build_config(msg)
                sess = GatewaySession(sid, config, self.cwd / "sessoes", self._make_on_event(sid))
                self.sessions[sid] = sess
                self.clients.setdefault(sid, set()).add(writer)
                await self._send(
                    writer,
                    {
                        "action": "attached",
                        "session": sid,
                        "snapshot": self._snapshot(sid),
                    },
                )
                self._reset_idle()
            except (ConfigError, ValueError, OSError) as exc:
                await self._send(
                    writer,
                    {
                        "action": "error",
                        "message": f"falha ao criar sessão: {exc}",
                    },
                )
            return

        if action == "attach":
            sid = session_id
            if sid not in self.sessions:
                await self._send(writer, {"action": "error", "message": "sessão não encontrada"})
                return
            self.clients.setdefault(sid, set()).add(writer)
            await self._send(
                writer,
                {
                    "action": "attached",
                    "session": sid,
                    "snapshot": self._snapshot(sid),
                },
            )
            self._reset_idle()
            return

        if action == "submit":
            sid = session_id
            if sid not in self.sessions:
                await self._send(writer, {"action": "error", "message": "sessão não encontrada"})
                return
            prompt = msg.get("prompt", "")
            self.sessions[sid].enqueue(prompt)
            await self._send(writer, {"action": "queued", "session": sid})
            # Executa imediatamente se não houver turno em curso (o loop é síncrono;
            # usamos create_task para não bloquear a leitura WS).
            asyncio.create_task(self._run_session(sid))
            return

        if action == "cancel":
            sid = session_id
            if sid in self.sessions:
                self.sessions[sid].loop.cancel()
            return

        if action == "detach":
            sid = session_id
            if sid:
                self.clients.get(sid, set()).discard(writer)
            return

        if action == "list_sessions":
            await self._send(
                writer,
                {
                    "action": "sessions_list",
                    "sessions": sorted(self.sessions),
                },
            )
            return

        if action == "ping":
            await self._send(writer, {"action": "pong"})
            return

        if action == "command":
            sid = session_id
            if sid not in self.sessions:
                await self._send(
                    writer,
                    {"action": "error", "message": "sessão não encontrada"},
                )
                return
            nome = msg.get("nome", "")
            argumentos = msg.get("argumentos", "")
            try:
                resultado = self.sessions[sid].loop.registry.dispatch_command(
                    nome, argumentos
                )
            except KeyError:
                resultado = f"Comando desconhecido: /{nome}"
            await self._send(
                writer,
                {
                    "action": "command_result",
                    "session": sid,
                    "comando": nome,
                    "resultado": resultado,
                },
            )
            return

    # -- execução da sessão ------------------------------------------- #

    async def _run_session(self, session_id: str) -> None:
        """Executa os prompts enfileirados de uma sessão."""
        sess = self.sessions.get(session_id)
        if not sess:
            return
        sess.run_pending()
        # Notifica clientes que a sessão ficou ociosa (snapshot atualizado).
        snapshot = self._snapshot(session_id)
        for writer in list(self.clients.get(session_id, set())):
            await self._send(
                writer,
                {
                    "action": "turn_done",
                    "session": session_id,
                    "snapshot": snapshot,
                },
            )

    # -- eventos do loop ---------------------------------------------- #

    def _make_on_event(self, session_id: str) -> Callable[[str, dict], None]:
        """Devolve um on_event que empacota em frames e faz broadcast."""

        def on_event(event: str, data: dict) -> None:
            frame = {
                "action": "event",
                "session": session_id,
                "event": event,
                "data": data,
            }
            # Broadcast síncrono: agende o envio no loop de eventos.
            for writer in list(self.clients.get(session_id, set())):
                with contextlib.suppress(OSError):
                    writer.write(_ws_frame(json.dumps(frame, ensure_ascii=False)))

        return on_event

    async def _send(self, writer: asyncio.StreamWriter, obj: dict) -> None:
        """Envia um objeto JSON como quadro WS."""
        writer.write(_ws_frame(json.dumps(obj, ensure_ascii=False)))
        await writer.drain()

    def _snapshot(self, session_id: str) -> dict:
        """Snapshot resumido da sessão para anexação."""
        sess = self.sessions.get(session_id)
        if not sess:
            return {}
        b = sess.loop._budget_snapshot()
        return {
            "session": session_id,
            "turns": b.get("turns", 0),
            "llm_calls": b.get("llm_calls", 0),
            "context_tokens": b.get("context_tokens", 0),
            "ext": b.get("ext", 0),
            "evicted": b.get("evicted", 0),
            "pending": len(sess._pending),
        }

    def _new_session_id(self) -> str:
        import uuid
        from datetime import UTC, datetime

        ts = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
        return f"{ts}_{uuid.uuid4().hex[:4]}"

    def _build_config(self, msg: dict) -> Config:
        """Constrói um Config a partir dos campos de `create`.

        Campos de backend/modelo (llm_backend, model, urls, thinking, etc.)
        são campos diretos do dataclass Config e são aplicados aqui.
        """
        kwargs: dict[str, object] = {"agent_workdir": str(self.cwd)}
        # Orçamento de agente (campos diretos do dataclass).
        for chave in (
            "agent_max_turns",
            "agent_max_llm_calls",
            "agent_timeout_seconds",
            "max_context_tokens",
            "tool_schema_tokens",
        ):
            if msg.get(chave) is not None:
                kwargs[chave] = msg[chave]
        # Backend / modelo / rede (campos diretos do dataclass).
        for chave in (
            "model",
            "ollama_url",
            "searxng_url",
            "llm_backend",
            "openai_url",
            "openai_api_key_env",
            "llm_thinking",
            "llamacpp_thinking",
            "fallback_backend",
            "fallback_after_failures",
            "llm_max_retries",
            "llm_temperature",
        ):
            if msg.get(chave) is not None:
                kwargs[chave] = msg[chave]
        # Perfil e extensões.
        if msg.get("profile"):
            kwargs["active_profile"] = msg["profile"]
        if msg.get("extensions") is not None:
            kwargs["extensions_enabled"] = tuple(msg["extensions"])
        return Config(**kwargs)


# ---------------------------------------------------------------------- #
# CLI do gateway
# ---------------------------------------------------------------------- #


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def gateway_start(cwd: Path | str) -> int:
    """Inicia o gateway como processo separado (detached)."""
    import subprocess

    cwd = Path(cwd).resolve()
    existente = _read_pidfile(cwd)
    if existente and _process_alive(existente.get("pid", 0)):
        print(f"Gateway já rodando (pid {existente['pid']}, porta {existente['port']}).")
        return 0

    # Lança o servidor como subprocesso desanexado.
    cmd = [sys.executable, "-m", "formiga.agent.gateway", "--serve", str(cwd)]
    log_path = _GLOBAL_DIR / "gateway.log"
    _GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            cwd=str(cwd),
            start_new_session=True,
        )

    # Aguarda o pidfile aparecer (o gateway o grava ao ligar).
    import time

    for _ in range(50):
        time.sleep(0.1)
        dados = _read_pidfile(cwd)
        if dados and dados.get("pid") == proc.pid:
            print(
                f"Gateway iniciado (pid {proc.pid}, porta {dados.get('port')})."
            )
            return 0
    print("Gateway não respondeu a tempo. Veja ~/.formiga/gateway.log", file=sys.stderr)
    return 1


def gateway_stop(cwd: Path | str) -> int:
    """Para o gateway do workdir."""
    cwd = Path(cwd).resolve()
    dados = _read_pidfile(cwd)
    if not dados:
        print("Nenhum gateway para este diretório.")
        return 0
    pid = dados.get("pid", 0)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"Não foi possível parar o gateway (pid {pid}): {exc}", file=sys.stderr)
        return 1
    _remove_pidfile(cwd)
    print(f"Gateway parado (pid {pid}).")
    return 0


def gateway_status(cwd: Path | str) -> int:
    """Mostra o status do gateway do workdir."""
    cwd = Path(cwd).resolve()
    dados = _read_pidfile(cwd)
    if not dados:
        print("Nenhum gateway configurado para este diretório.")
        return 0
    pid = dados.get("pid", 0)
    if not _process_alive(pid):
        _remove_pidfile(cwd)
        print("Gateway não está rodando (pidfile órfão removido).")
        return 0
    print(
        f"Gateway ativo (pid {pid}, porta {dados.get('port')}, "
        f"workdir {dados.get('cwd')}, versão {dados.get('version')})."
    )
    return 0


# ---------------------------------------------------------------------- #
# Ponto de entrada: python -m formiga.agent.gateway --serve <cwd>
# ---------------------------------------------------------------------- #


async def _serve(cwd: Path | str) -> None:
    gateway = Gateway(cwd)
    port = await gateway.start()
    print(f"formiga gateway ouvindo em 127.0.0.1:{port} (workdir {cwd})", flush=True)
    await gateway._stop.wait()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="formiga gateway")
    parser.add_argument("--serve", metavar="CWD", help="Inicia o daemon neste diretório.")
    args = parser.parse_args()

    if args.serve:
        asyncio.run(_serve(args.serve))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
