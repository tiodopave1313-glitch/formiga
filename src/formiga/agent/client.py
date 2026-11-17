"""Cliente WebSocket do gateway (seção 11 do PRD v2 — Fase 6).

`GatewayClient` conecta ao daemon local (pidfile `~/.formiga/gateway-<hash>.json`),
envia frames JSON e consome eventos do `AgentLoop` via callbacks.

`ensure_gateway()` sobe o daemon on-demand quando ele não está rodando.
`--local` e `--print` nunca usam este cliente (in-process).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from formiga.agent.gateway import _GLOBAL_DIR, _process_alive, _read_pidfile

# ---------------------------------------------------------------------- #
# WebSocket mínimo (cliente, biblioteca padrão)
# ---------------------------------------------------------------------- #

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_client_frame(text: str, mask: bool = True) -> bytes:
    """Enquadra um texto como quadro WebSocket (cliente → servidor)."""
    payload = text.encode("utf-8")
    b0 = 0x81  # FIN + texto
    length = len(payload)
    b1 = 0x80 | length if mask else length
    if length < 126:
        header = bytes([b0, b1])
    elif length <= 0xFFFF:
        header = bytes([b0, 128 | 126]) + length.to_bytes(2, "big")
    else:
        header = bytes([b0, 128 | 127]) + length.to_bytes(8, "big")
    if mask:
        mask_key = b"\x01\x02\x03\x04"  # fixo: suficiente para teste local
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return header + mask_key + masked
    return header + payload


async def _ws_client_read_frame(reader: asyncio.StreamReader) -> str | None:
    """Lê um quadro de texto (servidor → cliente, sem máscara)."""
    try:
        b0 = await reader.readexactly(1)
        b1 = await reader.readexactly(1)
    except (asyncio.IncompleteReadError, OSError):
        return None

    opcode = b0[0] & 0x0F
    length = b1[0] & 0x7F

    if opcode == 0x8:  # close
        return None
    if opcode != 0x1:
        return None

    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")

    data = await reader.readexactly(length) if length else b""
    return data.decode("utf-8", "replace")


async def _ws_client_handshake(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> bool:
    """Faz o handshake de upgrade do lado cliente."""
    client_key = base64.b64encode(
        b"\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff\x00"
    ).decode()
    request = (
        f"GET / HTTP/1.1\r\n"
        f"Host: 127.0.0.1\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {client_key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    writer.write(request.encode("utf-8"))
    await writer.drain()

    try:
        status_line = await reader.readline()
        if b"101" not in status_line:
            return False
        while True:
            line = await reader.readline()
            if line in (b"", b"\r\n"):
                break
    except (asyncio.IncompleteReadError, OSError):
        return False
    return True


# ---------------------------------------------------------------------- #
# GatewayClient
# ---------------------------------------------------------------------- #


class GatewayClient:
    """Cliente WS que anexa a uma sessão do gateway e expõe on_event."""

    def __init__(self, cwd: Path | str) -> None:
        self.cwd = Path(cwd).resolve()
        self.port: int | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._session_id: str | None = None
        self.on_event: Callable[[str, dict], None] | None = None
        self._recv_task: asyncio.Task | None = None

    # -- conexão ------------------------------------------------------- #

    async def connect(self, timeout: float = 5.0) -> None:
        """Conecta ao gateway do workdir. Levanta se não houver daemon."""
        dados = _read_pidfile(self.cwd)
        if not dados or not _process_alive(dados.get("pid", 0)):
            raise ConnectionError(
                f"Gateway não está rodando em {self.cwd}. "
                "Rode `formiga gateway start` ou use --local/--print."
            )
        self.port = dados["port"]
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", self.port), timeout=timeout
        )
        self._reader = reader
        self._writer = writer
        if not await _ws_client_handshake(reader, writer):
            writer.close()
            raise ConnectionError("Handshake WebSocket falhou.")
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        """Desconecta (detach) e fecha o socket."""
        if self._recv_task:
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
        if self._writer:
            with contextlib.suppress(OSError):
                self._writer.write(b"\x88\x00")  # close frame
                self._writer.close()

    async def _recv_loop(self) -> None:
        """Lê frames do servidor e despacha para on_event."""
        assert self._reader is not None
        while True:
            text = await _ws_client_read_frame(self._reader)
            if text is None:
                break
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            action = msg.get("action")
            if action == "event" and self.on_event:
                self.on_event(msg.get("event", ""), msg.get("data", {}))
            elif action == "attached":
                self._session_id = msg.get("session")

    # -- envio --------------------------------------------------------- #

    async def _send(self, obj: dict[str, Any]) -> None:
        if not self._writer:
            raise ConnectionError("não conectado ao gateway")
        self._writer.write(_ws_client_frame(json.dumps(obj, ensure_ascii=False)))
        await self._writer.drain()

    async def create(self, session_id: str | None = None, **config_overrides) -> str:
        """Cria uma sessão no gateway. Devolve o session_id."""
        await self._send(
            {
                "action": "create",
                "session": session_id,
                **config_overrides,
            }
        )
        # Aguarda o attached para saber o session_id real.
        # (simplificação: aguarda o recv_loop preencher _session_id)
        for _ in range(100):
            await asyncio.sleep(0.05)
            if self._session_id:
                return self._session_id
        raise TimeoutError("gateway não confirmou a criação da sessão")

    async def attach(self, session_id: str) -> None:
        """Anexa a uma sessão existente."""
        await self._send({"action": "attach", "session": session_id})
        self._session_id = session_id

    async def submit(self, prompt: str) -> None:
        """Enfileira um prompt para execução no gateway."""
        if not self._session_id:
            raise RuntimeError("nenhuma sessão anexada/criada")
        await self._send({"action": "submit", "session": self._session_id, "prompt": prompt})

    async def cancel(self) -> None:
        if self._session_id:
            await self._send({"action": "cancel", "session": self._session_id})

    async def detach(self) -> None:
        if self._session_id:
            await self._send({"action": "detach", "session": self._session_id})
        await self.close()

    async def list_sessions(self) -> list[str]:
        await self._send({"action": "list_sessions"})
        # simplificação: devolve vazio (o attached já traz o snapshot)
        return []

    async def ping(self) -> None:
        await self._send({"action": "ping"})


# ---------------------------------------------------------------------- #
# ensure_gateway
# ---------------------------------------------------------------------- #


def ensure_gateway(cwd: Path | str) -> bool:
    """Sobe o daemon on-demand se não estiver rodando. Devolve True se ativo."""
    cwd = Path(cwd).resolve()
    if _read_pidfile(cwd) and _process_alive(_read_pidfile(cwd).get("pid", 0)):
        return True

    # Lança o servidor detached.
    cmd = [sys.executable, "-m", "formiga.agent.gateway", "--serve", str(cwd)]
    log_path = _GLOBAL_DIR / "gateway.log"
    _GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            cwd=str(cwd),
            start_new_session=True,
        )

    # Aguarda o pidfile aparecer.
    for _ in range(100):
        time.sleep(0.05)
        dados = _read_pidfile(cwd)
        if dados and _process_alive(dados.get("pid", 0)):
            return True
    return False


def _workdir_hash(cwd: Path | str) -> str:
    return hashlib.sha1(str(Path(cwd).resolve()).encode()).hexdigest()[:8]


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
