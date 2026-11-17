"""Extensão builtin com primitivas de arquivos e shell."""

from __future__ import annotations

from pathlib import Path

from formiga.agent.extensions.api import ExtensionAPI
from formiga.agent.tools.base import ToolResult
from formiga.ext.core.files import EditTool, LsTool, ReadTool, WriteTool
from formiga.ext.core.shell import BashTool


class ActivateTool:
    """Meta-ferramenta: ativa uma ferramenta lazy pelos próximos 6 turnos.

    Só faz sentido quando há ferramentas lazy registradas (seção 9.7 do PRD).
    """

    name = "activate_tool"
    description = "Ativa uma ferramenta latente (lazy) pelos próximos 6 turnos."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Nome da ferramenta lazy a ativar.",
            }
        },
        "required": ["name"],
    }

    def __init__(self, registry) -> None:
        self._registry = registry

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, name: str) -> ToolResult:
        ok = self._registry.activate_lazy_tool(
            name, self._registry.current_turn
        )
        if not ok:
            return ToolResult(
                ok=False,
                text=f"ERRO: não foi possível ativar `{name}` (não existe ou não é lazy).",
            )
        return ToolResult(
            ok=True,
            text=f"Ferramenta `{name}` ativada por 6 turnos (renovável ao usar).",
        )


def setup(pi: ExtensionAPI) -> None:
    """Registra ferramentas core no registry usando a API pública de extensão."""
    workdir = Path(getattr(pi.runtime_config, "agent_workdir", "."))
    for tool in (
        LsTool(workdir),
        ReadTool(workdir),
        WriteTool(workdir),
        EditTool(workdir),
        BashTool(workdir),
        ActivateTool(pi.registry),
    ):
        pi.register_tool(tool)


__all__ = [
    "ActivateTool",
    "BashTool",
    "EditTool",
    "LsTool",
    "ReadTool",
    "WriteTool",
    "setup",
]
