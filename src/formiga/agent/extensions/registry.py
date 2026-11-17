"""Registry mínimo de ferramentas extensíveis para o agente.

A fase 1 mantém a API deliberadamente pequena: descoberta e comandos chegam na
fase seguinte; por enquanto a fábrica instancia extensões builtin via `setup`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from formiga.agent.tools.base import Tool

if TYPE_CHECKING:
    from formiga.agent.session import Session
    from formiga.config import Config


@dataclass(frozen=True)
class ToolRegistration:
    tool: Tool
    budget_per_message: int | None = None
    category: str = "general"


class ExtensionRegistry:
    """Registro ordenado das ferramentas anunciadas por extensões."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration] = {}

    def register_tool(
        self,
        tool: Tool,
        *,
        budget_per_message: int | None = None,
        category: str = "general",
    ) -> None:
        if not getattr(tool, "name", None):
            raise ValueError("ferramenta precisa declarar um nome não vazio")
        if budget_per_message is not None and budget_per_message <= 0:
            raise ValueError("budget_per_message precisa ser positivo")
        if tool.name in self._tools:
            raise ValueError(f"ferramenta duplicada: {tool.name}")
        self._tools[tool.name] = ToolRegistration(
            tool=tool,
            budget_per_message=budget_per_message,
            category=category,
        )

    @property
    def tools(self) -> dict[str, Tool]:
        """Ferramentas indexadas por nome, em ordem de registro."""
        return {name: registration.tool for name, registration in self._tools.items()}

    @property
    def registrations(self) -> dict[str, ToolRegistration]:
        return dict(self._tools)

    @property
    def schemas(self) -> list[dict]:
        return [registration.tool.schema() for registration in self._tools.values()]

    def budget_for(self, name: str) -> int | None:
        registration = self._tools.get(name)
        return registration.budget_per_message if registration else None

    def reset_budgets(self) -> None:
        """Inicia uma mensagem do usuário sem consumo de budget no registry.

        Contadores são mantidos no `ToolBudgets` legado nesta fase para
        compatibilidade de observabilidade; o registry passa a ser a fonte da
        política (quais ferramentas têm orçamento e seus limites).
        """
        return None

    def __len__(self) -> int:
        return len(self._tools)


class ExtensionContext:
    """Contexto fornecido a `setup(pi)` por uma extensão builtin."""

    def __init__(
        self,
        registry: ExtensionRegistry,
        config: Config,
        session: Session,
    ) -> None:
        self._registry = registry
        self.config = config
        self.session = session

    def register_tool(
        self,
        tool: Tool,
        *,
        budget_per_message: int | None = None,
        category: str = "general",
    ) -> None:
        self._registry.register_tool(
            tool,
            budget_per_message=budget_per_message,
            category=category,
        )
