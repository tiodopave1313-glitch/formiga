"""Extensão builtin de memória estilo Hermes (Fase 8).

Fornece `recall` (busca FTS5 em sessões passadas) e memória curada
(`MEMORY.md`/`USER.md` com nudge e aprovação humana).
"""

from formiga.ext.memory.memory import setup

__all__ = ["setup"]
