"""Ponte loop ↔ TUI (PRD §4): executa o loop em thread e converte eventos.

A TUI não decide fluxo do agente nem chama LLM/ferramentas diretamente — o
controller expõe apenas `ask` (inicia execução), `interrupt` (sinaliza `Esc`)
e o estado/orçamento observado. Eventos do loop chegam ao callback da TUI na
thread do controller; a TUI os encaminha à thread da UI via
`app.call_from_thread`.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable

from formiga.agent.factory import build_agent
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.config import Config

# Estados observáveis da TUI (PRD §8): ocioso · executando · interrompendo · erro.
IDLE = "ocioso"
RUNNING = "executando"
INTERRUPTING = "interrompendo"
ERROR = "erro"

EventCallback = Callable[[str, dict], None]


class AgentController:
    """Executa o `AgentLoop` em worker thread e repassa eventos à TUI."""

    def __init__(
        self,
        config: Config,
        session: Session,
        on_event: EventCallback | None = None,
        loop: AgentLoop | None = None,
    ) -> None:
        self.config = config
        self.session = session
        self._on_event = on_event or (lambda *a, **k: None)
        self.state = IDLE
        self.budget: dict = {}
        self.last_tool_result: str | None = None
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        if loop is not None:
            # Injeção para testes (fakes offline); ainda repassa os eventos.
            loop.on_event = self._handle_loop_event
            self.loop = loop
        else:
            self.loop = build_agent(config, session, on_event=self._handle_loop_event)

    # ------------------------------------------------------------------ #
    # Interface para a TUI (thread da UI)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ask(self, question: str) -> bool:
        """Inicia a execução numa thread; retorna False se já houver uma."""
        if self.running or not question.strip():
            return False
        self.state = RUNNING
        self.error = None
        self.last_tool_result = None
        self._thread = threading.Thread(target=self._execute, args=(question,), daemon=True)
        self._thread.start()
        return True

    def interrupt(self) -> None:
        """Esc: sinaliza o loop. A TUI só mostra 'interrompida' após confirmar."""
        self.state = INTERRUPTING
        self.loop.cancel()

    # ------------------------------------------------------------------ #
    # Thread do controller

    def _execute(self, question: str) -> None:
        try:
            self.loop.run(question)
            self.state = IDLE
            self._on_event("run_done", {})
        except Exception as exc:  # noqa: BLE001 — a TUI mostra o erro ao usuário
            self.state = ERROR
            self.error = str(exc)
            self._on_event("controller_error", {"message": str(exc)})

    def _handle_loop_event(self, event: str, data: dict) -> None:
        """Observa eventos do loop antes de repassá-los (thread do loop)."""
        if event == "tool_end":
            self.last_tool_result = data.get("text")
        elif event == "budget":
            self.budget = data
        elif event == "interrupted":
            self.state = IDLE
        # Eventos nunca derrubam o loop.
        with contextlib.suppress(Exception):
            self._on_event(event, data)
