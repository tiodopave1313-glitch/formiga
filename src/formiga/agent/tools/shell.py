"""Ferramenta `bash` delimitada (seção 6 e guardrail da seção 7 do PRD).

Executa um comando no diretório de trabalho fixo, com timeout e cap de saída.
Recusa comandos perigosos de uma lista de negação (padrão conhecido, não
sandbox); `AGENT_UNSAFE=1` desativa a lista (não recomendado em produção).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from formiga.agent.tools.base import ToolResult

# Comandos que nunca são executados, independentemente do contexto.
# Trata-se de negação por padrão conhecido — não substitui contenção real.
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init ",
    "telinit",
    ":(){ :|:& };:",  # fork bomb
]

# Comandos de remoção/desinstalação de pacotes (bloqueados por padrão).
PACKAGE_MUTATION = [
    "apt-get remove",
    "apt-get purge",
    "apt remove",
    "apt purge",
    "yum remove",
    "dnf remove",
    "pacman -R",
    "pip uninstall",
    "pip3 uninstall",
]


def _is_dangerous(command: str) -> bool:
    lowered = command.lower()
    return any(
        pattern.lower() in lowered
        for pattern in (*DANGEROUS_PATTERNS, *PACKAGE_MUTATION)
    )


class BashTool:
    name = "bash"
    description = (
        "Executa um comando no diretório de trabalho fixo (timeout default 60 s, "
        "saída limitada a 8 000 chars, truncado na cauda). Comandos perigosos "
        "são recusados por padrão."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Comando a executar no workdir.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout em segundos (default 60).",
                "default": 60,
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, command: str, timeout: int = 60) -> ToolResult:
        if not command or not command.strip():
            return ToolResult(ok=False, text="ERRO: comando vazio.", error="empty_command")

        if (
            os.environ.get("AGENT_UNSAFE", "0") not in ("1", "true", "yes")
            and _is_dangerous(command)
        ):
            return ToolResult(
                ok=False,
                text=(
                    "ERRO: comando recusado pela lista de negação do `bash`. "
                    "Defina AGENT_UNSAFE=1 para desativar (não recomendado)."
                ),
                error="refused_command",
            )

        timeout = max(1, min(timeout or 60, 300))
        try:
            result = subprocess.run(
                shlex.split(command),
                cwd=str(self.workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "AGENT_UNSAFE": os.environ.get("AGENT_UNSAFE", "")},
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            output = (stdout + stderr).strip()
            if len(output) > 8000:
                output = output[:8000] + "\n…(truncado por timeout)"
            return ToolResult(
                ok=False,
                text=f"ERRO: comando excedeu o timeout de {timeout} s.\n{output}",
                error="timeout",
            )
        except (OSError, ValueError) as exc:
            return ToolResult(
                ok=False, text=f"ERRO: não foi possível executar: {exc}", error=str(exc)
            )

        output = result.stdout + ("\n" + result.stderr if result.stderr else "")
        output = output.strip()
        if len(output) > 8000:
            output = output[:8000] + "\n…(truncado na cauda)"

        if result.returncode == 0:
            return ToolResult(ok=True, text=output if output else "(sem saída)")
        return ToolResult(
            ok=False,
            text=f"ERRO: comando saiu com código {result.returncode}.\n{output}",
            error=f"exit_code_{result.returncode}",
        )
