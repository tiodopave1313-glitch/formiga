"""Registry e runtime de extensões do agente.

O registry mantém ferramentas, comandos, handlers e metadados em ordem de carga.
Nenhum módulo de extensão concreta é importado daqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from formiga.agent.extensions.events import CHAIN_EVENTS, OBSERVATION_EVENTS
from formiga.agent.guardrails import ToolBudgets
from formiga.agent.tools.base import Tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from formiga.agent.session import Session
    from formiga.config import Config


@dataclass(frozen=True)
class ToolRegistration:
    tool: Tool
    budget_per_message: int | None = None
    category: str = "general"
    extension: str = "legacy"
    source: str = "runtime"
    lazy: bool = False
    cap_chars: int | None = None
    prompt_hint: str | None = None


@dataclass(frozen=True)
class CommandRegistration:
    name: str
    handler: Callable[[str], object]
    extension: str = "unknown"
    source: str = "unknown"


@dataclass
class ExtensionRecord:
    name: str
    source: str
    order: int
    status: str = "loaded"
    error: str | None = None
    tools: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)


class ExtensionRegistry:
    """Registro ordenado de ferramentas, comandos e hooks de extensão.

    `CHAIN_EVENTS` e `OBSERVATION_EVENTS` são definidos em
    `formiga.agent.extensions.events` (fonte única) e reexpôs aqui como
    atributos de classe para compatibilidade.
    """

    CHAIN_EVENTS = CHAIN_EVENTS
    OBSERVATION_EVENTS = OBSERVATION_EVENTS

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration] = {}
        self._commands: dict[str, CommandRegistration] = {}
        self._extensions: list[ExtensionRecord] = []
        self._handlers: dict[str, list[tuple[str, Callable[..., object]]]] = {}
        self._event_sink: Callable[[str, dict], None] = lambda *_: None
        self._session: Session | None = None
        self.warnings: list[str] = []

    def bind_runtime(
        self,
        session: Session,
        event_sink: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._session = session
        if event_sink is not None:
            self._event_sink = event_sink

    def set_event_sink(self, event_sink: Callable[[str, dict], None]) -> None:
        self._event_sink = event_sink

    def register_tool(
        self,
        tool: Tool,
        *,
        budget_per_message: int | None = None,
        category: str = "general",
        lazy: bool = False,
        extension: str = "legacy",
        source: str = "runtime",
        cap_chars: int | None = None,
        prompt_hint: str | None = None,
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
            extension=extension,
            source=source,
            lazy=lazy,
            cap_chars=cap_chars,
            prompt_hint=prompt_hint,
        )

    def register_command(
        self,
        name: str,
        handler: Callable[[str], object],
        *,
        extension: str = "unknown",
        source: str = "unknown",
    ) -> None:
        normalized = name.strip().lstrip("/")
        if not normalized or any(char.isspace() for char in normalized):
            raise ValueError("nome de comando inválido")
        if normalized in self._commands:
            raise ValueError(f"comando duplicado: /{normalized}")
        self._commands[normalized] = CommandRegistration(
            normalized, handler, extension=extension, source=source
        )

    def register_extension(self, record: ExtensionRecord) -> None:
        self._extensions.append(record)

    def add_handler(
        self,
        event: str,
        handler: Callable[..., object],
        *,
        extension: str = "unknown",
    ) -> None:
        if event not in self.CHAIN_EVENTS | self.OBSERVATION_EVENTS:
            raise ValueError(f"evento não suportado: {event}")
        self._handlers.setdefault(event, []).append((extension, handler))

    def observe(self, event: str, data: dict) -> None:
        """Executa handlers de observação isolando falhas por extensão."""
        for extension, handler in self._handlers.get(event, ()):
            try:
                handler(data)
            except Exception as exc:  # extensões não derrubam o loop
                self._extension_error(extension, event, exc)

    def chain(self, event: str, value: Any, **context: Any) -> Any:
        """Aplica transformações encadeadas e isola erros de handlers."""
        for extension, handler in self._handlers.get(event, ()):
            try:
                result = (
                    handler(value, **context)
                    if event == "tool_call"
                    else handler(value)
                )
                if result is not None:
                    value = result
                if event == "tool_call" and isinstance(value, dict) and value.get("block"):
                    break
            except Exception as exc:
                self._extension_error(extension, event, exc)
        return value

    def emit(self, event: str, data: dict | None = None) -> None:
        """Emite evento customizado para JSONL, handlers e interface."""
        payload = dict(data or {})
        if self._session is not None:
            self._session.append_event(event, payload)
        self._event_sink(event, payload)

    def dispatch_command(self, name: str, arguments: str = "") -> object:
        registration = self._commands.get(name.lstrip("/"))
        if registration is None:
            raise KeyError(name)
        return registration.handler(arguments)

    def _extension_error(self, extension: str, event: str, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"[:400]
        self.warnings.append(f"{extension}: {message}")
        if self._session is not None:
            self._session.append_event(
                "extension_error", {"extension": extension, "event": event, "message": message}
            )

    @property
    def tools(self) -> dict[str, Tool]:
        """Ferramentas indexadas por nome, em ordem de registro."""
        return {name: item.tool for name, item in self._tools.items()}

    @property
    def registrations(self) -> dict[str, ToolRegistration]:
        return dict(self._tools)

    @property
    def commands(self) -> dict[str, CommandRegistration]:
        return dict(self._commands)

    @property
    def extensions(self) -> tuple[ExtensionRecord, ...]:
        return tuple(self._extensions)

    @property
    def schemas(self) -> list[dict]:
        return [item.tool.schema() for item in self._tools.values() if not item.lazy]

    def budget_for(self, name: str) -> int | None:
        registration = self._tools.get(name)
        return registration.budget_per_message if registration else None

    def cap_for(self, name: str, default_chars: int = 4000) -> int:
        registration = self._tools.get(name)
        if registration is None or registration.cap_chars is None:
            return default_chars
        return registration.cap_chars

    def consume_message_budget(
        self, name: str, tool_budgets: ToolBudgets
    ) -> str | None:
        """Consome uma unidade do orçamento declarado da ferramenta.

        Retorna `None` se não houver orçamento declarado ou se ainda houver
        unidade disponível; caso contrário devolve a mensagem `ERRO:`.
        """
        limit = self.budget_for(name)
        if limit is None:
            return None
        return tool_budgets.consume(name, limit)

    def reset_message_budgets(self) -> None:
        """Zera os contadores de uso (chamado a cada nova mensagem do usuário).

        A zeragem real é feita no loop recriando `ToolBudgets`; este método
        existe para simetria e futuro uso por hooks de contexto.
        """
        pass

    def __len__(self) -> int:
        return len(self._tools)


class ExtensionUI:
    """Feedback visual não acoplado à CLI ou à TUI."""

    def __init__(self, registry: ExtensionRegistry) -> None:
        self._registry = registry

    def notify(self, text: str, level: str = "info") -> None:
        self._registry.emit("notification", {"text": str(text), "level": level})

    def setStatus(self, key: str, text: str) -> None:  # noqa: N802 - API do PRD
        self._registry.emit("extension_status", {"key": str(key), "text": str(text)})


class ExtensionContext:
    """Objeto `pi` entregue durante setup, com capacidades da extensão."""

    def __init__(
        self,
        registry: ExtensionRegistry,
        config: Config,
        session: Session,
        *,
        name: str = "builtin",
        source: str = "builtin",
        settings: dict[str, object] | None = None,
    ) -> None:
        self._registry = registry
        self.runtime_config = config
        self.config = dict(settings or {})
        self.session = session
        self.name = name
        self.source = source
        self.ui = ExtensionUI(registry)

    def register_tool(
        self,
        tool: Tool,
        *,
        budget_per_message: int | None = None,
        category: str = "general",
        lazy: bool = False,
    ) -> None:
        self._registry.register_tool(
            tool,
            budget_per_message=budget_per_message,
            category=category,
            lazy=lazy,
            extension=self.name,
            source=self.source,
        )

    def register_command(self, name: str, handler: Callable[[str], object]) -> None:
        self._registry.register_command(
            name, handler, extension=self.name, source=self.source
        )

    def on(self, event: str, handler: Callable[..., object]) -> None:
        self._registry.add_handler(event, handler, extension=self.name)

    def emit(self, event: str, data: dict | None = None) -> None:
        self._registry.emit(event, data)
