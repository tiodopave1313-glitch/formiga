"""Loop agêntico do Formiga Agent (seção 5 do PRD).

Um turno = uma chamada ao LLM (streaming) + até uma chamada de ferramenta.
O loop controla orçamento, guardrails, persistência por turno e cancelamento
cooperativo (`cancel()` sinaliza; ferramenta em curso termina no próprio
timeout; o loop só confirma a interrupção na fronteira seguinte).

Eventos para a TUI (via `on_event`):
- `llm_call`                — início de chamada ao modelo;
- `stream`                  — pedaço de texto gerado (deltas do stream);
- `tool_start`              — antes de executar a tool (args curtos);
- `tool_end`                — após executar (ok, seconds, texto capado);
- `budget`                  — snapshot de turnos/chamadas vs máximos;
- `interrupted`             — interrupção confirmada pelo loop;
- `deep_search_progress`    — progresso do motor (reexposto pela tool).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from time import monotonic

from formiga.agent.chat import AgentCancelled, ChatResponse
from formiga.agent.guardrails import (
    AgentBudget,
    AntiLoop,
    ToolBudgets,
    ToolResultCap,
)
from formiga.agent.parser import parse_tool_call, result_to_context
from formiga.agent.prompts import SYSTEM_PROMPT
from formiga.agent.session import Session
from formiga.agent.tools.base import Tool
from formiga.config import Config
from formiga.llm import LLMError

# Tools com orçamento próprio por mensagem do usuário.
BUDGETED_TOOLS = ("deep_search", "web_search", "web_fetch")


def short_args(args: dict, limit: int = 60) -> str:
    """Representação curta dos argumentos para exibição em eventos."""
    if not args:
        return ""
    parts = []
    for key, value in args.items():
        text = str(value).replace("\n", " ⏎ ")
        parts.append(f"{key}={text}")
    joined = ", ".join(parts)
    return joined if len(joined) <= limit else joined[: limit - 1] + "…"


class AgentLoop:
    def __init__(
        self,
        chat_client,
        tools: list[Tool],
        session: Session,
        config: Config,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.chat = chat_client
        self.tools = {t.name: t for t in tools}
        self.session = session
        self.config = config
        self.on_event = on_event or (lambda *a, **k: None)

        self._cancel = threading.Event()

        agent_cfg = config
        self.budget = AgentBudget(
            max_turns=int(getattr(agent_cfg, "agent_max_turns", 24)),
            max_llm_calls=int(getattr(agent_cfg, "agent_max_llm_calls", 120)),
            timeout_seconds=float(getattr(agent_cfg, "agent_timeout_seconds", 1800)),
        )
        self.tool_cap = ToolResultCap(
            default_chars=int(getattr(agent_cfg, "agent_tool_result_chars", 4000)),
        )
        self.anti_loop = AntiLoop()
        self.tool_budgets = ToolBudgets(
            max_deep_searches=int(getattr(agent_cfg, "agent_max_deep_searches", 2)),
            max_web_searches=int(getattr(agent_cfg, "agent_max_web_searches", 6)),
            max_web_fetches=int(getattr(agent_cfg, "agent_max_web_fetches", 8)),
        )

        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Índice do início do turno de tool ainda não confirmado pelo
        # modelo — usado para rollback se a chamada seguinte falhar.
        self._pending_len: int | None = None

    # ------------------------------------------------------------------ #
    # Cancelamento cooperativo

    def cancel(self) -> None:
        """Sinaliza interrupção; o loop confirma na fronteira seguinte."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _on_delta(self, piece: str) -> None:
        """Callback de streaming: emite evento e sinaliza cancelamento."""
        if self._cancel.is_set():
            raise AgentCancelled()
        self.on_event("stream", {"text": piece})

    def _budget_snapshot(self) -> dict:
        return {
            "turns": self.budget.turns_used,
            "max_turns": self.budget.max_turns,
            "llm_calls": self.budget.llm_calls_used,
            "max_llm_calls": self.budget.max_llm_calls,
        }

    # ------------------------------------------------------------------ #

    def run(self, question: str) -> str:
        """Executa o loop até resposta final, orçamento esgotado ou interrupção.

        Cada chamada a `run` é uma nova mensagem do usuário: os orçamentos de
        ferramentas web são reiniciados (seção 7 do PRD). Um cancelamento
        pendente (`cancel()`) é honrado imediatamente; a flag é limpa ao fim.
        """
        try:
            return self._run(question)
        finally:
            self._cancel.clear()

    def _run(self, question: str) -> str:
        # Reinicia orçamentos de tools web por mensagem do usuário.
        self.tool_budgets = ToolBudgets(
            max_deep_searches=self.tool_budgets.max_deep_searches,
            max_web_searches=self.tool_budgets.max_web_searches,
            max_web_fetches=self.tool_budgets.max_web_fetches,
        )
        self.anti_loop = AntiLoop()
        self._pending_len = None  # nenhum turno de tool pendente

        self.messages.append({"role": "user", "content": question})
        self.session.save_messages(self.messages)
        self.session.append_event("turn_started", {"turns": 0})
        self.on_event("budget", self._budget_snapshot())

        while True:
            if self._cancel.is_set():
                return self._final_interrupted()

            limit = self.budget.can_start_turn()
            if limit is not None:
                return self._final(limit)

            # chama o modelo com histórico + schemas das ferramentas
            self.budget.record_llm_call()
            self.on_event("llm_call", {"turns": self.budget.turns_used})
            try:
                response: ChatResponse = self.chat.chat(
                    self.messages,
                    tools=[t.schema() for t in self.tools.values()],
                    max_tokens=self._max_tokens(),
                    on_delta=self._on_delta,
                )
            except AgentCancelled:
                return self._final_interrupted()
            except LLMError as exc:
                # Falha do modelo (HTTP 4xx/5xx, timeout, parse): desfaz o
                # turno incompleto para não envenenar o histórico — senão
                # toda chamada seguinte falharia de novo com o mesmo erro.
                self._rollback_pending()
                self.session.append_event(
                    "llm_error", {"message": str(exc)[:400]}
                )
                raise
            if self._cancel.is_set():
                # Cancelamento pedido durante a chamada: resposta descartada.
                return self._final_interrupted()

            if response.tool_calls:
                tool_call = response.tool_calls[0]  # uma por iteração (MVP)
                context = self._handle_tool_call(response)
                # registra assistant + resultado da ferramenta no histórico,
                # no formato wire OpenAI (aceito pelos 3 backends):
                # `type`/`function` em tool_calls e `role: "tool"` com
                # `tool_call_id` no resultado.
                self._pending_len = len(self.messages)
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": context,
                    }
                )
                self.session.save_messages(self.messages)
                self.budget.record_turn()
                self.on_event("budget", self._budget_snapshot())
                continue

            # resposta final sem tool call
            final = response.content or "(sem resposta)"
            self.messages.append({"role": "assistant", "content": final})
            self.session.save_messages(self.messages)
            self._pending_len = None  # turno confirmado: sem rollback
            self.session.append_event("turn_ended", {"turns": self.budget.turns_used})
            self.on_event("budget", self._budget_snapshot())
            self.on_event("run_final", {"text": final, "streamed": True})
            return final

    # ------------------------------------------------------------------ #

    def _rollback_pending(self) -> None:
        """Desfaz o turno de tool pendente (assistant tool_calls + resultado).

        A tool já executou e seus eventos ficam no disco; o rollback remove
        apenas as mensagens não confirmadas, para o próximo run recomeçar
        com histórico válido.
        """
        if self._pending_len is None:
            return
        del self.messages[self._pending_len:]
        self._pending_len = None
        self.session.save_messages(self.messages)

    def _handle_tool_call(self, response: ChatResponse) -> str:
        """Parser, guardrails, orçamento e execução da tool — devolve contexto."""
        tool_call = response.tool_calls[0]  # uma por iteração (MVP)
        name = tool_call.name
        tool = self.tools.get(name)
        if tool is None:
            return f"ERRO: ferramenta desconhecida: {name}."

        args, parse_err = parse_tool_call(
            None,
            [{"id": tool_call.id, "name": name, "arguments": tool_call.arguments}],
            self.tools,
        )
        if parse_err is not None:
            return f"ERRO: {parse_err}"

        # guardrail anti-loop
        action = self.anti_loop.register(name, tool_call.arguments)
        if action == "stop":
            return (
                "ERRO: anti-loop — mesma chamada repetida 4 vezes. "
                "Responda ao usuário com o que tiver."
            )
        if action == "nudge":
            return (
                self.anti_loop.nudge_message(name)
                + "\nResultado não útil; tente outro caminho ou responda."
            )

        # orçamento da tool (web/deep_search); outras tools não têm orçamento
        # próprio por mensagem.
        budget_err = None
        if name in BUDGETED_TOOLS:
            budget_err = self.tool_budgets.consume(name)
        if budget_err is not None:
            self.session.append_event(
                "tool_call",
                {
                    "tool": name,
                    "args": tool_call.arguments,
                    "ok": False,
                    "budget_exhausted": True,
                },
            )
            self.on_event("tool_end", {"tool": name, "ok": False, "budget_exhausted": True})
            return budget_err

        if self._cancel.is_set():
            return "ERRO: interrompido pelo usuário."

        # eventos do motor reexpostos pela tool (deep_search)
        if hasattr(tool, "on_event"):
            tool.on_event = self.on_event

        self.on_event("tool_start", {"tool": name, "args": short_args(args)})
        started = monotonic()
        result = tool.execute(**args)
        elapsed = monotonic() - started

        # cap de resultado
        cap = self.tool_cap.cap_for(name)
        text = result.text
        if len(text) > cap:
            text = text[:cap] + f"\n…(truncado a {cap} chars)"
        result.text = text

        self.session.append_event(
            "tool_call",
            {
                "tool": name,
                "args": tool_call.arguments,
                "ok": result.ok,
                "seconds": round(elapsed, 3),
            },
        )
        self.on_event(
            "tool_end",
            {
                "tool": name,
                "ok": result.ok,
                "seconds": round(elapsed, 3),
                "text": result.text,
            },
        )
        return result_to_context(result)

    def _max_tokens(self) -> int:
        # 4096 por turno; 8192 com thinking ligado (conforme llm.py)
        return 8192 if getattr(self.config, "llm_thinking", False) else 4096

    def _final(self, reason: str) -> str:
        partial = (
            f"{reason}\n\nResposta parcial: o orçamento da sessão foi esgotado. "
            "Retome com uma nova pergunta ou aumente os limites em [agent] do formiga.toml."
        )
        self.messages.append({"role": "assistant", "content": partial})
        self.session.save_messages(self.messages)
        self._pending_len = None
        self.session.append_event("budget_exhausted", {"reason": reason})
        self.on_event("run_final", {"text": partial, "streamed": False})
        return partial

    def _final_interrupted(self) -> str:
        partial = (
            "Interrompido pelo usuário.\n\nResposta parcial: a execução foi "
            "interrompida a pedido do usuário. A sessão permanece salva no disco."
        )
        self.messages.append({"role": "assistant", "content": partial})
        self.session.save_messages(self.messages)
        self._pending_len = None
        self.session.append_event("interrupted", {"turns": self.budget.turns_used})
        self.on_event("interrupted", {"turns": self.budget.turns_used})
        self.on_event("run_final", {"text": partial, "streamed": False})
        return partial
