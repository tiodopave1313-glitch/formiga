"""Loop agêntico do Formiga Agent (seção 5 do PRD).

Um turno = uma chamada ao LLM (streaming) + até uma chamada de ferramenta.
O loop controla orçamento, guardrails, persistência por turno e cancelamento
cooperativo (`cancel()` sinaliza; ferramenta em curso termina no próprio
timeout; o loop só confirma a interrupção na fronteira seguinte).

O núcleo **não conhece nenhuma ferramenta concreta**: todas chegam pelo
`ExtensionRegistry`, que é o único caminho do loop até uma tool
(objetivo 3.1 do PRD v2).

Eventos para a TUI (via `on_event`):
- `llm_call`                — início de chamada ao modelo;
- `stream`                  — pedaço de texto gerado (deltas do stream);
- `tool_start`              — antes de executar a tool (args curtos);
- `tool_end`                — após executar (ok, seconds, texto capado);
- `tool_progress`           — progresso reexposto por uma ferramenta/extensão;
- `budget`                  — snapshot de turnos/chamadas vs máximos;
- `interrupted`             — interrupção confirmada pelo loop;

Hooks do registry (seção 6 e 7 do PRD v2):
- `input`        — transforma/intercepta a pergunta do usuário (chain);
- `before_agent_start` — contribui seções ao system prompt (chain);
- `context`      — filtra/windowa mensagens antes da chamada LLM (chain);
- `tool_call`    — gateia/muta argumentos antes de executar (chain);
- `tool_result`  — transforma o resultado após executar (chain);
- `turn_end`     — observa o fim do turno (observe).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from formiga.agent.chat import AgentCancelled, ChatResponse
from formiga.agent.extensions.budget import (
    ContextBudget,
    evict_pairs,
    reinject_anchor,
)
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.guardrails import (
    AgentBudget,
    AntiLoop,
    ToolBudgets,
    ToolResultCap,
)
from formiga.agent.parser import parse_tool_call, result_to_context
from formiga.agent.prompts import build_system_prompt
from formiga.agent.session import Session
from formiga.config import Config
from formiga.llm import LLMError


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
        registry: ExtensionRegistry,
        session: Session,
        config: Config,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.chat = chat_client
        self.registry = registry
        self.tools = registry.tools
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
        # Orçamentos por mensagem declarados pelas extensões no registry.
        self.tool_budgets = ToolBudgets(
            limits={
                name: registration.budget_per_message
                for name, registration in registry.registrations.items()
                if registration.budget_per_message is not None
            }
        )

        # Orçamento de janela de contexto (seção 9.1 do PRD).
        self.context_budget = ContextBudget(
            max_context_tokens=int(
                getattr(config, "max_context_tokens", 32768)
            ),
        )

        # Seções contribuídas por extensões via before_agent_start.
        self.secoes_extensao: dict[str, str] = {}

        # Contador acumulado de mensagens descartadas por eviction (seção 9.1).
        self.evicted: int = 0

        # system prompt montado a partir dos specs do registry — nenhuma
        # ferramenta concreta é citada pelo núcleo.
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    registry, secoes_extensao=self.secoes_extensao
                ),
            }
        ]

        # Índice do início do turno de tool ainda não confirmado pelo
        # modelo — usado para rollback se a chamada seguinte falhar.
        self._pending_len: int | None = None
        # Bloco "## Agent" aberto no transcript (fecha antes de tools).
        self._agent_section = False

    # ------------------------------------------------------------------ #
    # Cancelamento cooperativo

    def cancel(self) -> None:
        """Sinaliza interrupção; o loop confirma na fronteira seguinte."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def reset_session(self, base_dir: Path) -> Session:
        """Inicia uma nova sessão em disco (comando `/new`).

        Cria um diretório de sessão novo (a anterior permanece no disco),
        reseta mensagens (só o system prompt), orçamentos, anti-loop,
        contador de eviction e turno do registry. Devolve a nova `Session`
        para o caller persistir a referência se quiser.
        """
        self.session = Session(base_dir)
        self.budget = AgentBudget(
            max_turns=int(getattr(self.config, "agent_max_turns", 24)),
            max_llm_calls=int(
                getattr(self.config, "agent_max_llm_calls", 120)
            ),
            timeout_seconds=float(
                getattr(self.config, "agent_timeout_seconds", 1800)
            ),
        )
        self.tool_budgets = ToolBudgets(
            limits={
                name: registration.budget_per_message
                for name, registration in self.registry.registrations.items()
                if registration.budget_per_message is not None
            }
        )
        self.anti_loop = AntiLoop()
        self.evicted = 0
        self.registry.current_turn = 0
        self._pending_len = None
        self._agent_section = False
        self.secoes_extensao = {}
        self.messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.registry, secoes_extensao=self.secoes_extensao
                ),
            }
        ]
        self.session.save_messages(self.messages)
        self.session.append_transcript("\n## Nova sessão\n")
        self._emit("budget", self._budget_snapshot())
        return self.session

    def _on_delta(self, piece: str) -> None:
        """Callback de streaming: emite evento e sinaliza cancelamento."""
        if self._cancel.is_set():
            raise AgentCancelled()
        self._emit("stream", {"text": piece})

    def _emit(self, event: str, data: dict) -> None:
        """Emite o evento para a TUI e espelha no transcript.md.

        O transcript grava a mesma sequência que a TUI exibe (PRD §8):
        perguntas, texto do agent, linhas de ferramenta, progresso,
        interrupções e respostas parciais — a sessão completa fica em
        `sessoes/<sessão>/transcript.md`.
        """
        if event == "stream":
            if not self._agent_section:
                self.session.append_transcript("\n## Agent\n")
                self._agent_section = True
            self.session.append_transcript(data.get("text", ""))
            self.on_event(event, data)
            return
        if event == "tool_start":
            if self._agent_section:  # fecha o bloco do agent antes da tool
                self.session.append_transcript("\n")
                self._agent_section = False
            self.session.append_transcript(
                f"\n⚙ {data.get('tool')} — {data.get('args', '')}\n"
            )
        elif event == "tool_end":
            if data.get("budget_exhausted"):
                self.session.append_transcript(
                    f"  (⚙ {data.get('tool')} — orçamento esgotado)\n"
                )
            elif not data.get("ok", True):
                seconds = data.get("seconds")
                dur = f" ({seconds:.1f} s)" if isinstance(seconds, (int, float)) else ""
                self.session.append_transcript(f"  ✗ erro{dur}\n")
            else:
                seconds = data.get("seconds")
                if isinstance(seconds, (int, float)):
                    self.session.append_transcript(f"  ({seconds:.1f} s)\n")
        elif event == "tool_progress":
            self.session.append_transcript(f"· {data.get('message', '')}\n")
        elif event == "interrupted":
            self.session.append_transcript("\n— interrompido pelo usuário —\n")
        elif event == "run_final" and not data.get("streamed"):
            if self._agent_section:
                self.session.append_transcript("\n")
                self._agent_section = False
            self.session.append_transcript(f"\n## Agent\n{data.get('text', '')}\n")
        self.on_event(event, data)

    def _budget_snapshot(self) -> dict:
        context_tokens = self.context_budget.custo(self.messages)
        return {
            "turns": self.budget.turns_used,
            "max_turns": self.budget.max_turns,
            "llm_calls": self.budget.llm_calls_used,
            "max_llm_calls": self.budget.max_llm_calls,
            "context_tokens": context_tokens,
            "max_context_tokens": self.context_budget.max_context_tokens,
            "ext": len(self.registry.registrations),
            "evicted": self.evicted,
        }

    # ------------------------------------------------------------------ #

    def run(self, question: str) -> str:
        """Executa o loop até resposta final, orçamento esgotado ou interrupção.

        Cada chamada a `run` é uma nova mensagem do usuário: os orçamentos de
        ferramentas são reiniciados (seção 7 do PRD). Um cancelamento
        pendente (`cancel()`) é honrado imediatamente; a flag é limpa ao fim.
        """
        try:
            return self._run(question)
        finally:
            self._cancel.clear()

    def _run(self, question: str) -> str:
        # Reinicia orçamentos de ferramentas por mensagem do usuário.
        self.tool_budgets = ToolBudgets(
            limits={
                name: registration.budget_per_message
                for name, registration in self.registry.registrations.items()
                if registration.budget_per_message is not None
            }
        )
        self.anti_loop = AntiLoop()
        self._pending_len = None  # nenhum turno de tool pendente

        # Hook input: extensões podem transformar a pergunta do usuário.
        question = self.registry.chain("input", question)

        self.messages.append({"role": "user", "content": question})
        self.session.save_messages(self.messages)
        self._agent_section = False
        self.session.append_transcript(f"\n## Você\n{question}\n")
        self.session.append_event("turn_started", {"turns": 0})
        self._emit("budget", self._budget_snapshot())

        while True:
            if self._cancel.is_set():
                return self._final_interrupted()

            limit = self.budget.can_start_turn()
            if limit is not None:
                return self._final(limit)

            # before_agent_start: extensões contribuem seções ao system prompt.
            self.secoes_extensao = self.registry.chain(
                "before_agent_start", dict(self.secoes_extensao)
            )
            self.messages[0] = {
                "role": "system",
                "content": build_system_prompt(
                    self.registry, secoes_extensao=self.secoes_extensao
                ),
            }

            # context: extensões podem filtrar/windowar mensagens; eviction
            # padrão se ainda exceder a janela útil (seção 9.1).
            self.messages = self.registry.chain("context", list(self.messages))
            if not self.context_budget.coube(self.messages):
                antes = len(self.messages)
                self.messages = evict_pairs(
                    self.messages, self.context_budget.max_context_tokens
                )
                self.evicted += antes - len(self.messages)

            # Âncora de objetivo: se o hook `context` (ou a eviction) removeu a
            # última mensagem do usuário, re-inseri-la após a system para que o
            # modelo nunca perca o objetivo original da sessão (seção 9.1).
            self.messages, reinjetou = reinject_anchor(
                self.messages, question
            )
            if reinjetou:
                self.session.append_event(
                    "budget",
                    {"ancora_re_injetada": True, "turns": self.budget.turns_used},
                )

            # chama o modelo com histórico + schemas das ferramentas
            # Atualiza turno e expira ferramentas lazy cujo TTL acabou.
            self.registry.current_turn = self.budget.turns_used
            self.registry.expire_lazy_tools(self.registry.current_turn)

            self.budget.record_llm_call()
            self._emit("llm_call", {"turns": self.budget.turns_used})
            try:
                response: ChatResponse = self.chat.chat(
                    self.messages,
                    tools=self.registry.schemas,
                    max_tokens=self._max_tokens(),
                    on_delta=self._on_delta,
                )
            except (AgentCancelled, KeyboardInterrupt):
                return self._final_interrupted()
            except LLMError as exc:
                # Falha do modelo (HTTP 4xx/5xx, timeout, parse): desfaz o
                # turno incompleto para não envenenar o histórico — senão
                # toda chamada seguinte falharia de novo com o mesmo erro.
                self._rollback_pending()
                self.session.append_event(
                    "llm_error", {"message": str(exc)[:400]}
                )
                self.session.append_transcript(f"  ✗ erro: {str(exc)[:200]}\n")
                raise
            if self._cancel.is_set():
                # Cancelamento pedido durante a chamada: resposta descartada.
                return self._final_interrupted()

            if response.tool_calls:
                tool_call = response.tool_calls[0]  # uma por iteração (MVP)
                try:
                    context = self._handle_tool_call(response)
                except KeyboardInterrupt:
                    return self._final_interrupted()
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
                self._emit("budget", self._budget_snapshot())
                self.registry.observe("turn_end", {"turns": self.budget.turns_used})
                continue

            # resposta final sem tool call
            final = response.content or "(sem resposta)"
            self.messages.append({"role": "assistant", "content": final})
            self.session.save_messages(self.messages)
            self._pending_len = None  # turno confirmado: sem rollback
            self.session.append_event("turn_ended", {"turns": self.budget.turns_used})
            self._emit("budget", self._budget_snapshot())
            self.registry.observe("turn_end", {"turns": self.budget.turns_used})
            self._emit("run_final", {"text": final, "streamed": True})
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

        # Hook tool_call: extensões podem gatear (block) ou mutar args.
        args = self.registry.chain("tool_call", args, name=name, tool=tool)
        if isinstance(args, dict) and args.get("block"):
            return args.get(
                "reason", f"chamada bloqueada por extensão: {name}."
            )

        # Orçamento por mensagem declarado pela extensão no registry; nenhuma
        # lista de ferramentas especiais fica hardwired no loop.
        budget_err = self.registry.consume_message_budget(name, self.tool_budgets)
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
            self._emit("tool_end", {"tool": name, "ok": False, "budget_exhausted": True})
            return budget_err

        if self._cancel.is_set():
            return "ERRO: interrompido pelo usuário."

        # Evento de progresso opcional fornecido por uma ferramenta/extensão.
        if hasattr(tool, "on_event"):
            tool.on_event = self._emit

        self._emit("tool_start", {"tool": name, "args": short_args(args)})
        started = monotonic()
        result = tool.execute(**args)
        elapsed = monotonic() - started

        # cap de resultado: declaração da extensão no registry ou default.
        cap = self.registry.cap_for(name, self.tool_cap.default_chars)
        text = result.text
        if len(text) > cap:
            text = text[:cap] + f"\n…(truncado a {cap} chars)"
        result.text = text

        # Renova TTL de ferramenta lazy ativa ao usar (renovável).
        reg = self.registry._tools.get(name)
        if reg is not None and reg.lazy and reg.state == "ativa":
            self.registry.activate_lazy_tool(
                name, self.registry.current_turn
            )

        # Hook tool_result: extensões podem transformar o resultado.
        resultado = self.registry.chain(
            "tool_result",
            {"ok": result.ok, "text": result.text, "error": result.error},
        )
        result.ok = resultado.get("ok", result.ok)
        result.text = resultado.get("text", result.text)
        result.error = resultado.get("error", result.error)

        self.session.append_event(
            "tool_call",
            {
                "tool": name,
                "args": tool_call.arguments,
                "ok": result.ok,
                "seconds": round(elapsed, 3),
            },
        )
        self._emit(
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
        self._emit("run_final", {"text": partial, "streamed": False})
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
        self._emit("interrupted", {"turns": self.budget.turns_used})
        self._emit("run_final", {"text": partial, "streamed": False})
        return partial
