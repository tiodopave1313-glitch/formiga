"""Contratos e compatibilidade dos imports antigos de ferramentas.

Ferramentas concretas vivem em `formiga.ext.*`; manter este pacote sem imports
concretos garante que o núcleo possa importar o protocolo sem carregar builtins.
"""

from formiga.agent.tools.base import Tool, ToolResult

__all__ = ["Tool", "ToolResult"]
