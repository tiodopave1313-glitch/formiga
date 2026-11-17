"""Exemplo de extensão externa do Formiga (PRD §20.1 Fase 2).

Instale em `~/.formiga/extensions/todo.py` (escopo global) ou em
`.formiga/extensions/todo.py` dentro de um projeto confiado
(`formiga trust <projeto>`) para expor:

- tool `todo_add`: anota um item em `todos.txt` dentro da sessão atual;
- comando `/todo`: exemplo de comando registrado por uma extensão.

Usa apenas a API pública de extensão
(`formiga.agent.extensions.api.ExtensionAPI`) — não importa nada do núcleo
do agente.
"""

from __future__ import annotations

from formiga.agent.tools.base import ToolResult


class TodoAddTool:
    name = "todo_add"
    description = "Anota um item na lista de tarefas da sessão atual."
    parameters = {
        "type": "object",
        "properties": {
            "item": {"type": "string", "description": "Tarefa a anotar."}
        },
        "required": ["item"],
    }

    def __init__(self, store_path) -> None:
        self._store_path = store_path

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, item: str) -> ToolResult:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        with self._store_path.open("a", encoding="utf-8") as f:
            f.write(f"- {item}\n")
        return ToolResult(ok=True, text=f"anotado: {item}")


def setup(pi) -> None:
    pi.register_tool(TodoAddTool(pi.session.dir / "todos.txt"))
    pi.register_command("todo", lambda _args: "comando /todo de exemplo registrado")
