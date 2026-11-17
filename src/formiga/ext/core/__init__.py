"""Extensão builtin com primitivas de arquivos e shell."""

from __future__ import annotations

from pathlib import Path

from formiga.agent.extensions.api import ExtensionAPI
from formiga.ext.core.files import EditTool, LsTool, ReadTool, WriteTool
from formiga.ext.core.shell import BashTool


def setup(pi: ExtensionAPI) -> None:
    """Registra ferramentas core no registry usando a API pública de extensão."""
    workdir = Path(getattr(pi.runtime_config, "agent_workdir", "."))
    for tool in (
        LsTool(workdir),
        ReadTool(workdir),
        WriteTool(workdir),
        EditTool(workdir),
        BashTool(workdir),
    ):
        pi.register_tool(tool)


__all__ = ["BashTool", "EditTool", "LsTool", "ReadTool", "WriteTool", "setup"]
