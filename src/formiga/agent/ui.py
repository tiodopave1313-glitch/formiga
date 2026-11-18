"""Apresentação da CLI interativa: cores, limpeza de tela e painel.

As regras do PRD §8 continuam valendo: nada de ANSI obrigatório. Toda
sequência de escape só é emitida em TTY (ou com ``CLICOLOR_FORCE``) e nunca
com ``NO_COLOR`` definido. Fora dessas condições o texto sai exatamente como
antes, o que mantém pipes, logs e testes limpos.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from formiga.agent.extensions.registry import ExtensionRegistry
    from formiga.agent.session import Session

_RESET = "\x1b[0m"
_NEGRITO = "\x1b[1m"
_DIM = "\x1b[2m"

_CORES = {
    "cyan": "\x1b[36m",
    "magenta": "\x1b[35m",
    "yellow": "\x1b[33m",
    "green": "\x1b[32m",
    "red": "\x1b[31m",
    "blue": "\x1b[34m",
}

# Desligamento explícito via `--no-color` (por invocação da CLI).
_SEM_COR = False


def sem_cor(ativo: bool = True) -> None:
    """Liga/desliga cores para o processo (``--no-color``)."""
    global _SEM_COR
    _SEM_COR = ativo


def _controle_ativo(stream: TextIO | None = None) -> bool:
    """True quando é seguro emitir ANSI (cor ou limpeza de tela)."""
    if _SEM_COR or os.environ.get("NO_COLOR", "") != "":
        return False
    if os.environ.get("CLICOLOR_FORCE", "").strip() not in {"", "0"}:
        return True
    stream = stream or sys.stdout
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty and isatty())
    except (OSError, ValueError):
        return False


def cores_ativas(stream: TextIO | None = None) -> bool:
    """Expõe a decisão para a CLI e para os testes."""
    return _controle_ativo(stream)


def pintar(
    texto: object,
    cor: str = "",
    *,
    negrito: bool = False,
    dim: bool = False,
    stream: TextIO | None = None,
) -> str:
    """Aplica cor/estilo quando o terminal aceita; senão devolve o texto cru."""
    valor = str(texto)
    if not _controle_ativo(stream):
        return valor
    prefixo = _CORES.get(cor, "")
    if negrito:
        prefixo += _NEGRITO
    if dim:
        prefixo += _DIM
    return f"{prefixo}{valor}{_RESET}" if prefixo else valor


def limpar_tela(stream: TextIO | None = None) -> None:
    """Limpa a tela e leva o cursor ao topo, só quando o terminal aceita."""
    stream = stream or sys.stdout
    if not _controle_ativo(stream):
        return
    stream.write("\x1b[2J\x1b[H")
    stream.flush()


def estado_sessao(registry: ExtensionRegistry, session: Session) -> dict:
    """Resumo estruturado da sessão (dados, não texto pronto).

    Usado pela CLI in-process e enviado pelo gateway no frame ``attached``,
    para que o cliente formate e colore localmente.
    """
    return {
        "session": getattr(session, "session_id", ""),
        "session_dir": str(getattr(session, "dir", "")),
        "transcript": str(getattr(session, "transcript_path", "")),
        "tools": [reg.tool.name for reg in registry.registrations.values()],
        "extensions": [
            {
                "name": rec.name,
                "source": rec.source,
                "status": rec.status,
                "error": rec.error,
            }
            for rec in registry.extensions
        ],
        "commands": sorted(registry.commands),
        "summaries": registry.summaries,
    }


def _largura() -> int:
    try:
        return max(40, shutil.get_terminal_size((100, 24)).columns)
    except OSError:  # pragma: no cover - terminal exótico
        return 100


def _secao(
    linhas: list[str],
    rotulo: str,
    itens: list[str],
    cor: str,
    *,
    mostrar_vazio: bool = False,
) -> None:
    itens = [str(item) for item in itens if str(item).strip()]
    if not itens and not mostrar_vazio:
        return
    coluna = 17
    etiqueta = f"{rotulo.upper()} ({len(itens)})"
    prefixo = pintar(f"{etiqueta:<{coluna}}", cor, negrito=True)
    largura = max(30, _largura() - coluna)
    pedacos = textwrap.wrap(
        " · ".join(itens), width=largura, break_long_words=False
    ) or ["(nenhuma)"]
    linhas.append(prefixo + pedacos[0])
    for pedaco in pedacos[1:]:
        linhas.append(" " * coluna + pedaco)


def linhas_painel(estado: dict) -> list[str]:
    """Painel de abertura: sessão, ferramentas, extensões, comandos e seções."""
    linhas = [
        f"{pintar('formiga agent', 'cyan', negrito=True)}"
        f" · sessão: {estado.get('session_dir', '')}"
    ]
    transcript = estado.get("transcript")
    if transcript:
        linhas.append(pintar(f"transcript: {transcript}", dim=True))
    linhas.append("")

    _secao(linhas, "ferramentas", list(estado.get("tools") or []), "cyan")

    extensoes = []
    for rec in estado.get("extensions") or []:
        nome = str(rec.get("name", ""))
        status = rec.get("status")
        marca = "" if status in {None, "loaded"} else f" [{status}]"
        extensoes.append(f"{nome}{marca}")
    _secao(linhas, "extensões", extensoes, "magenta")

    _secao(
        linhas,
        "comandos",
        [f"/{nome}" for nome in estado.get("commands") or []],
        "yellow",
    )

    for nome, itens in (estado.get("summaries") or {}).items():
        _secao(linhas, str(nome), list(itens), "green", mostrar_vazio=True)

    linhas.append("")
    linhas.append(
        pintar("Ctrl+C interrompe · Ctrl+D sai · /help lista comandos", dim=True)
    )
    return linhas


def linhas_ajuda(registry: ExtensionRegistry) -> list[str]:
    """Lista textual usada pelo comando ``/help``."""
    linhas = ["Comandos disponíveis:"]
    for nome in sorted(registry.commands):
        origem = registry.commands[nome].source
        sufixo = "" if origem in {"builtin", "runtime"} else f" [{origem}]"
        linhas.append(f"  /{nome}{sufixo}")

    for nome, itens in registry.summaries.items():
        if not itens:
            continue
        linhas.append("")
        linhas.append(f"{str(nome).capitalize()}:")
        linhas.extend(f"  {item}" for item in itens)

    linhas.append("")
    linhas.append("Formato: /comando [argumentos].")
    linhas.append("Ctrl+C interrompe a resposta · Ctrl+D sai da CLI.")
    return linhas
