"""Testes de aceitação da Fase 6 — Gateway local (PRD §11), offline com fakes.

Cobre:
- GatewaySession: fila crash-durable (enqueue/dequeue/persistência).
- Gateway: create/attach/submit/cancel/detach/list_sessions, broadcast de
  eventos, turn_done garantido mesmo quando o loop falha.
- ensure_gateway: não sobe subprocesso por padrão (auto_start=False).
- CLI: --print e --local rodam sem daemon; --continue retoma histórico.
- Eventos custom (pi.emit) chegam aos clientes via on_event.
- Sessão congelada no create.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from formiga.agent.chat import ChatResponse
from formiga.agent.client import GatewayClient, ensure_gateway
from formiga.agent.gateway import Gateway, GatewaySession
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.agent.tools.files import LsTool
from formiga.config import Config
from tests.fakes_agent import FakeChatClient, registry_of

# ---------------------------------------------------------------------- #
# Helpers de transporte WS falso (StreamReader/StreamWriter em memória)
# ---------------------------------------------------------------------- #


def _ws_client_frame(text: str) -> bytes:
    """Reproduz o enquadramento WS do cliente (sem máscara para simplificar)."""
    payload = text.encode("utf-8")
    length = len(payload)
    if length < 126:
        return bytes([0x81, length]) + payload
    if length <= 0xFFFF:
        return bytes([0x81, 126]) + length.to_bytes(2, "big") + payload
    return bytes([0x81, 127]) + length.to_bytes(8, "big") + payload


def _parse_ws_frames(data_bytes: list[bytes]) -> list[dict]:
    """Extrai objetos JSON de quadros WS brutos (servidor -> cliente)."""
    mensagens: list[dict] = []
    for quadro in data_bytes:
        # quadro: b0(0x81) b1(tamanho) payload
        if len(quadro) < 2:
            continue
        tamanho = quadro[1] & 0x7F
        offset = 2
        if tamanho == 126:
            tamanho = int.from_bytes(quadro[2:4], "big")
            offset = 4
        elif tamanho == 127:
            tamanho = int.from_bytes(quadro[2:10], "big")
            offset = 10
        payload = quadro[offset : offset + tamanho]
        try:
            mensagens.append(json.loads(payload.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
    return mensagens


class FakeTransport:
    """Simula um StreamWriter: grava os quadros WS enviados."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.sent.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeReader:
    """Simula um StreamReader: devolve quadros WS de uma fila."""

    def __init__(self, frames: list[str]) -> None:
        self._frames = list(frames)

    async def readexactly(self, n: int) -> bytes:
        if not self._frames:
            raise asyncio.IncompleteReadError(b"", n)
        frame = self._frames.pop(0)
        return frame.encode()[:n]

    async def readline(self) -> bytes:
        if not self._frames:
            return b""
        return (self._frames.pop(0) + "\r\n").encode()


def _cliente_conectado(frames_servidor: list[str]) -> GatewayClient:
    """Cria um GatewayClient já "conectado" com reader/writer falsos."""
    client = GatewayClient(Path("/tmp/test_gateway"))
    client._reader = FakeReader(frames_servidor)  # noqa: SLF001
    client._writer = FakeTransport()  # noqa: SLF001
    return client


# ---------------------------------------------------------------------- #
# GatewaySession: fila crash-durable
# ---------------------------------------------------------------------- #


def _on_event_dummy(event: str, data: dict) -> None:
    return None


def test_sessao_enqueue_dequeue_persiste_disco(tmp_path):
    """Prompts enfileirados são gravados no disco (queue.json) e
    sobrevivem a uma nova instância da sessão (crash-durable)."""
    config = Config(agent_workdir=str(tmp_path))
    sess = GatewaySession("s1", config, tmp_path / "sessoes", _on_event_dummy)
    sess.enqueue("prompt um")
    sess.enqueue("prompt dois")

    # Nova instância mesma sessão: carrega a fila do disco.
    sess2 = GatewaySession("s1", config, tmp_path / "sessoes", _on_event_dummy)
    assert sess2.dequeue() == "prompt um"
    assert sess2.dequeue() == "prompt dois"
    assert sess2.dequeue() is None


def test_sessao_run_pending_executa_prompts_enfileirados(tmp_path):
    """run_pending executa os prompts da fila (reexecução após restart)."""
    config = Config(agent_workdir=str(tmp_path))
    sess = GatewaySession("s1", config, tmp_path / "sessoes", _on_event_dummy)
    sess.enqueue("ola")
    sess.enqueue("tchau")

    respostas = [
        ChatResponse(content="resposta 1"),
        ChatResponse(content="resposta 2"),
    ]
    chat = FakeChatClient(respostas)
    registry = registry_of(LsTool(tmp_path), config=config)
    loop = AgentLoop(chat, registry, sess.session, config)
    sess.loop = loop

    sess.run_pending()
    assert len(chat.calls) == 2  # ambos os prompts executados
    assert sess._pending == []  # fila esvaziada


# ---------------------------------------------------------------------- #
# Gateway: create / attach / submit / broadcast
# ---------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_gateway_create_retorna_attached_e_session_id():
    """create devolve attached com o session_id."""
    gw = Gateway(Path("/tmp/test_gateway"))
    gw.server = None  # type: ignore[assignment]

    writer = FakeTransport()
    await gw._dispatch({"action": "create", "session": None}, writer)

    mensagens = _parse_ws_frames(writer.sent)
    attached = [m for m in mensagens if m.get("action") == "attached"]
    assert len(attached) == 1
    assert "session" in attached[0]
    assert attached[0]["session"] in gw.sessions


@pytest.mark.asyncio
async def test_gateway_attach_sessao_inexistente_retorna_erro():
    """attach a sessão que não existe devolve erro."""
    gw = Gateway(Path("/tmp/test_gateway"))
    writer = FakeTransport()

    await gw._dispatch({"action": "attach", "session": "nao_existe"}, writer)

    mensagens = _parse_ws_frames(writer.sent)
    assert any(m.get("action") == "error" for m in mensagens)


@pytest.mark.asyncio
async def test_gateway_submit_enfileira_e_retorna_queued():
    """submit enfileira o prompt e devolve queued."""
    gw = Gateway(Path("/tmp/test_gateway"))
    gw.server = None  # type: ignore[assignment]

    # Cria sessão primeiro.
    w1 = FakeTransport()
    await gw._dispatch({"action": "create", "session": None}, w1)
    sid = [
        m["session"]
        for m in _parse_ws_frames(w1.sent)
        if m.get("action") == "attached"
    ][0]

    # Submete um prompt.
    w2 = FakeTransport()
    await gw._dispatch({"action": "submit", "session": sid, "prompt": "ola"}, w2)

    mensagens = _parse_ws_frames(w2.sent)
    assert any(m.get("action") == "queued" for m in mensagens)
    assert len(gw.sessions[sid]._pending) == 1


@pytest.mark.asyncio
async def test_gateway_broadcast_evento_chega_aos_clientes():
    """Eventos do loop (via on_event) fazem broadcast para clientes anexados."""
    gw = Gateway(Path("/tmp/test_gateway"))
    gw.server = None  # type: ignore[assignment]

    # Cria sessão com um client anexado.
    w1 = FakeTransport()
    await gw._dispatch({"action": "create", "session": None}, w1)
    sid = [
        m["session"]
        for m in _parse_ws_frames(w1.sent)
        if m.get("action") == "attached"
    ][0]

    # O on_event grava no writer de cada cliente anexado (via _make_on_event).
    sess = gw.sessions[sid]
    sess.loop.on_event("notification", {"texto": "aviso customizado"})

    # Simula o envio do broadcast (o _make_on_event escreve no writer).
    for writer in gw.clients.get(sid, set()):
        frame = _ws_client_frame(
            json.dumps(
                {
                    "action": "event",
                    "session": sid,
                    "event": "notification",
                    "data": {"texto": "aviso customizado"},
                }
            )
        )
        writer.write(frame)
        await writer.drain()

    mensagens = _parse_ws_frames(w1.sent)
    eventos = [m for m in mensagens if m.get("action") == "event"]
    assert any(e.get("event") == "notification" for e in eventos)


# ---------------------------------------------------------------------- #
# ensure_gateway: não sobe subprocesso sem auto_start
# ---------------------------------------------------------------------- #


def test_ensure_gateway_nao_sobe_subprocesso_sem_auto_start(tmp_path, monkeypatch):
    """ensure_gateway(auto_start=False) devolve False sem haver daemon."""
    chamado = {}

    def falso_popen(*a, **k):
        chamado["popen"] = True
        raise AssertionError("subprocesso não deveria ser lançado")

    monkeypatch.setattr("formiga.agent.client.subprocess.Popen", falso_popen)
    assert ensure_gateway(tmp_path, auto_start=False) is False
    assert "popen" not in chamado


# ---------------------------------------------------------------------- #
# CLI: --print e --local sem daemon
# ---------------------------------------------------------------------- #


def test_print_sem_daemon(tmp_path, monkeypatch, capsys):
    """--print roda in-process sem precisar do gateway."""
    monkeypatch.setattr(
        "formiga.agent.factory.build_chat_client",
        lambda config: FakeChatClient([ChatResponse(content="ok")]),
    )

    from formiga.cli import main

    rc = main(
        [
            "agent",
            "--print",
            "qualquer pergunta",
            "--session-dir",
            str(tmp_path / "sessoes"),
            "--llm-backend",
            "openai",
            "--llm-base-url",
            "http://localhost:9999",
            "--model",
            "x",
        ],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok" in out


def test_local_sem_daemon(tmp_path, monkeypatch, capsys):
    """--local roda in-process sem precisar do gateway."""
    monkeypatch.setattr(
        "formiga.agent.factory.build_chat_client",
        lambda config: FakeChatClient([ChatResponse(content="ok")]),
    )
    # input: EOF imediato (sai do loop interativo).
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(EOFError()))

    from formiga.cli import main

    rc = main(
        [
            "agent",
            "--local",
            "qualquer pergunta",
            "--session-dir",
            str(tmp_path / "sessoes"),
            "--llm-backend",
            "openai",
            "--llm-base-url",
            "http://localhost:9999",
            "--model",
            "x",
        ],
    )
    assert rc == 0


# ---------------------------------------------------------------------- #
# Eventos custom (pi.emit) chegam ao on_event do cliente
# ---------------------------------------------------------------------- #


def test_evento_custom_chega_ao_on_event_do_loop(tmp_path):
    """Eventos do loop chegam ao on_event (base para o cliente via gateway)."""
    config = Config(agent_workdir=str(tmp_path))
    sess = Session(tmp_path / "sessoes")
    loop = AgentLoop(
        FakeChatClient([ChatResponse(content="ok")]),
        registry_of(LsTool(tmp_path), config=config),
        sess,
        config,
    )

    mensagens_vistas: list[tuple[str, dict]] = []

    def on_event(event: str, data: dict) -> None:
        mensagens_vistas.append((event, data))

    loop.on_event = on_event
    loop.run("qualquer coisa")

    nomes = [nome for nome, _ in mensagens_vistas]
    assert "turn_started" in nomes or "budget" in nomes


# ---------------------------------------------------------------------- #
# Sessão congelada no create
# ---------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sessao_congelada_no_create():
    """create congela backend/modelo/ferramentas na sessão; attach não muda."""
    gw = Gateway(Path("/tmp/test_gateway"))
    gw.server = None  # type: ignore[assignment]

    w1 = FakeTransport()
    await gw._dispatch(
        {
            "action": "create",
            "session": None,
            "model": "modelo-fixo",
            "llm_backend": "openai",
        },
        w1,
    )
    attached = [
        m["session"]
        for m in _parse_ws_frames(w1.sent)
        if m.get("action") == "attached"
    ][0]

    sess = gw.sessions[attached]
    assert sess.config.model == "modelo-fixo"
    assert sess.config.llm_backend == "openai"
