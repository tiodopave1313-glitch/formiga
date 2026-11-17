"""TUI do Formiga Agent (PRD §8): stream, eventos em linha, barra de status.

Textual, uma tela, pouco ruído, estado explícito, sem falsa precisão:

- stream do texto do agente no centro, token a token;
- eventos de ferramenta em linha (símbolo, nome, argumento curto, duração);
- barra de status com orçamento consumido (única barra percentual permitida);
- entrada única `❯` com histórico ↑/↓, desabilitada durante execução;
- `Esc` armazena interrupção (padrão continuar; 2ª `Esc` confirma) — a TUI só
  mostra "interrompida" quando o loop confirma;
- `Ctrl+L` alterna rolagem livre; `Ctrl+O` mostra o último resultado de tool;
  `Ctrl+Q` sai (a sessão permanece no disco);
- sem cores obrigatórias (NO_COLOR), alvo 80×24, spinner é a única animação.

A TUI não decide fluxo do agente nem chama LLM/ferramentas — o controller
(thead de execução) é a única ponte para o loop.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from formiga.agent.session import Session
from formiga.agent.tui.controller import (
    INTERRUPTING,
    RUNNING,
    AgentController,
)
from formiga.config import Config

CONFIRM_TIMEOUT = 3.0  # s: "interrompendo?" volta a "executando" sozinho

BAR_WIDTH = 12


def _bar(ratio: float, width: int = BAR_WIDTH) -> str:
    filled = max(0, min(width, round(ratio * width)))
    return "█" * filled + "░" * (width - filled)


class ToolDetailsScreen(ModalScreen):
    """`Ctrl+O`: resultado completo da última ferramenta (overlay)."""

    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("ctrl+o", "dismiss", show=False),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="tool_details"):
            yield Static(self._title, id="tool_details_title")
            yield Static(self._body, id="tool_details_body")


class AgentApp(App):
    TITLE = "formiga agent"
    CSS = """
    #header { height: 1; padding: 0 1; }
    #transcript { height: 1fr; padding: 0 1; }
    #status { height: 1; padding: 0 1; }
    #input { height: 3; }
    .role { text-style: bold; }
    .toolline { color: $text-muted; }
    #tool_details {
        background: $surface;
        border: round $primary;
        padding: 1 2;
        margin: 1 2;
        height: auto;
        max-height: 80%;
    }
    #tool_details_title { text-style: bold; }
    """

    BINDINGS = [
        Binding("escape", "request_interrupt", "Interromper", priority=True, show=False),
        Binding("ctrl+o", "tool_details", "Detalhes da tool", show=False),
        Binding("ctrl+l", "toggle_scroll", "Rolagem livre", show=False),
        Binding("ctrl+q", "quit", "Sair", show=False),
        Binding("up", "history_prev", show=False, priority=True),
        Binding("down", "history_next", show=False, priority=True),
    ]

    def __init__(
        self,
        config: Config,
        session: Session,
        initial_question: str | None = None,
        controller: AgentController | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.session = session
        self.controller = controller or AgentController(
            config, session, on_event=self._relay_event
        )
        if controller is not None:
            controller._on_event = self._relay_event
        self.initial_question = (initial_question or "").strip()

        self._follow = True
        self._history: list[str] = []
        self._history_index: int | None = None
        self._interrupt_pending = False
        self._agent_open = False
        self._agent_text = ""
        self._agent_widget: Static | None = None
        self._streaming = False

    # ------------------------------------------------------------------ #
    # Composição

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), id="header")
        yield VerticalScroll(id="transcript")
        yield Static("", id="status")
        yield Input(placeholder="Faça uma pergunta… (❯)", id="input")

    def on_mount(self) -> None:
        self._write_user_block(
            "formiga agent",
            "A sessão é salva em " + str(self.session.dir) + " (messages.json, "
            "events.jsonl e transcript.md — o transcript tem toda a conversa, "
            "dá para abrir e copiar de fora da TUI).",
        )
        endpoint = self._endpoint_hint()
        self._write_user_block(
            "Aviso",
            "As mensagens e resultados de ferramentas são enviados ao modelo "
            f"configurado ({endpoint}). A chave de API nunca aparece aqui.",
        )
        if self.initial_question:
            self.query_one("#input", Input).value = self.initial_question
        self.query_one("#input", Input).focus()
        self._update_status()

    def _endpoint_hint(self) -> str:
        backend = self.config.llm_backend
        if backend == "openai":
            url = self.config.openai_url
            remoto = "http" not in url.lower() or "localhost" not in url.lower()
            detalhe = "endpoint remoto" if remoto else "endpoint local"
            return f"openai, {detalhe}: {url}"
        if backend == "ollama":
            return f"ollama local: {self.config.ollama_url}"
        return f"llama-server local: {self.config.llamacpp_url}"

    def _header_text(self) -> str:
        return f" formiga agent{'':<25} {self.config.model}"

    # ------------------------------------------------------------------ #
    # Eventos do loop → UI (via call_from_thread)

    def _relay_event(self, event: str, data: dict) -> None:
        """Recebido na thread do controller; encaminha à thread da UI."""
        self.call_from_thread(self._handle_event, event, data)

    def _handle_event(self, event: str, data: dict) -> None:
        if event == "stream":
            self._stream_append(data.get("text", ""))
        elif event == "tool_start":
            self._close_agent_block()
            self._write_tool_line(f"⚙ {data.get('tool')} — {data.get('args', '')}")
        elif event == "tool_end":
            seconds = data.get("seconds")
            duration = f"{seconds:.1f} s" if isinstance(seconds, (int, float)) else ""
            if data.get("budget_exhausted"):
                self._write_tool_line(f"⚙ {data.get('tool')} — orçamento esgotado")
            elif not data.get("ok", True):
                self._write_tool_line(f"  ✗ erro {duration}".rstrip())
            elif duration:
                self._write_tool_line(f"  ({duration})")
        elif event == "tool_progress":
            self._write_tool_line(f"· {data.get('message', '')}")
        elif event == "run_final":
            if not data.get("streamed"):
                self._close_agent_block()
                self._write_user_block("Agent", data.get("text", ""))
        elif event == "interrupted":
            self._write_tool_line("— interrompido pelo usuário —")
            self._on_run_done()
        elif event == "run_done":
            self._on_run_done()
        elif event == "controller_error":
            self._write_tool_line(f"✗ erro: {data.get('message', '')}")
            self._on_run_done()
        self._update_status()

    def _on_run_done(self) -> None:
        self._close_agent_block()
        self._streaming = False
        self._interrupt_pending = False
        self.query_one("#input", Input).disabled = False
        self.query_one("#input", Input).focus()

    # ------------------------------------------------------------------ #
    # Blocos do transcript

    def _write_user_block(self, role: str, text: str) -> None:
        container = self.query_one("#transcript", VerticalScroll)
        container.mount(Static(f"{role}\n{text}", classes="block"))
        self._scroll_follow()

    def _stream_append(self, piece: str) -> None:
        if not self._agent_open:
            container = self.query_one("#transcript", VerticalScroll)
            self._agent_text = ""
            self._agent_widget = Static("", classes="block agent")
            container.mount(Static("Agent", classes="role"))
            container.mount(self._agent_widget)
            self._agent_open = True
            self._streaming = True
        self._agent_text += piece
        assert self._agent_widget is not None
        self._agent_widget.update(self._agent_text)
        self._scroll_follow()

    def _close_agent_block(self) -> None:
        self._agent_open = False
        self._streaming = False
        self._agent_widget = None

    def _write_tool_line(self, text: str) -> None:
        container = self.query_one("#transcript", VerticalScroll)
        container.mount(Static(text, classes="toolline"))
        self._scroll_follow()

    def _scroll_follow(self) -> None:
        if self._follow:
            self.query_one("#transcript", VerticalScroll).scroll_end(animate=False)

    # ------------------------------------------------------------------ #
    # Entrada e histórico

    def _input(self) -> Input:
        return self.query_one("#input", Input)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        question = event.value.strip()
        if not question or self.controller.running:
            return
        if question.startswith("/"):
            resultado = self.controller.run_command(question)
            if resultado is not None:
                self._write_user_block("formiga", resultado)
            event.input.value = ""
            self._update_status()
            return
        self._history.append(question)
        self._history_index = None
        event.input.value = ""
        self._close_agent_block()
        self._write_user_block("Você", question)
        event.input.disabled = True
        started = self.controller.ask(question)
        if not started:  # pragma: no cover — defesa
            event.input.disabled = False
        self._update_status()

    def action_history_prev(self) -> None:
        if not self._history or self.controller.running:
            return
        if self._history_index is None:
            self._history_index = len(self._history) - 1
        else:
            self._history_index = max(0, self._history_index - 1)
        self._input().value = self._history[self._history_index]

    def action_history_next(self) -> None:
        if self._history_index is None or self.controller.running:
            return
        self._history_index += 1
        if self._history_index >= len(self._history):
            self._history_index = None
            self._input().value = ""
        else:
            self._input().value = self._history[self._history_index]

    # ------------------------------------------------------------------ #
    # Atalhos

    def action_request_interrupt(self) -> None:
        """Esc: fecha o overlay de detalhes; fora dele, armazena interrupção."""
        if isinstance(self.screen, ToolDetailsScreen):
            self.screen.dismiss()
            return
        if self.controller.state == INTERRUPTING and self._interrupt_pending:
            self.controller.interrupt()
            self._update_status()
            return
        if self.controller.running:
            self._interrupt_pending = True
            self.controller.state = INTERRUPTING
            self.set_timer(CONFIRM_TIMEOUT, self._clear_interrupt_pending)
            self._update_status()

    def _clear_interrupt_pending(self) -> None:
        if self._interrupt_pending and self.controller.state == INTERRUPTING:
            self._interrupt_pending = False
            self.controller.state = RUNNING
            self._update_status()

    def action_tool_details(self) -> None:
        if self.controller.last_tool_result is None:
            return
        self.push_screen(
            ToolDetailsScreen("Último resultado de ferramenta", self.controller.last_tool_result)
        )

    def action_toggle_scroll(self) -> None:
        self._follow = not self._follow
        if self._follow:
            self._scroll_follow()

    # ------------------------------------------------------------------ #
    # Barra de status

    def _update_status(self) -> None:
        budget = self.controller.budget or {}
        turns = budget.get("turns", 0)
        max_turns = budget.get("max_turns", 0)
        calls = budget.get("llm_calls", 0)
        max_calls = budget.get("max_llm_calls", 0)
        ratio = 0.0
        if max_turns:
            ratio = max(ratio, turns / max_turns)
        if max_calls:
            ratio = max(ratio, calls / max_calls)
        estado = self.controller.state
        if self._interrupt_pending:
            estado = "interrompendo? Esc de novo confirma · outra tecla continua"
        spinner = "⠿" if self.controller.running else "·"
        status = (
            f" turnos {turns}/{max_turns} · chamadas {calls}/{max_calls} · "
            f"{_bar(ratio)} {ratio * 100:.0f}% · {spinner} {estado}"
        )
        self.query_one("#status", Static).update(status)
