"""Loop agêntico do Formiga Agent (seção 5 do PRD).

Um turno = uma chamada ao LLM + até uma chamada de ferramenta.
O loop controla orçamento, guardrails e persistência por turno.
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from formiga.agent.chat import ChatResponse
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

    def run(self, question: str) -> str:
        """Executa o loop até resposta final, orçamento esgotado ou interrupção.

        Cada chamada a `run` é uma nova mensagem do usuário: os orçamentos de
        ferramentas web são reiniciados (seção 7 do PRD).
        """
        # Reinicia orçamentos de tools web por mensagem do usuário.
        self.tool_budgets = ToolBudgets(
            max_deep_searches=self.tool_budgets.max_deep_searches,
            max_web_searches=self.tool_budgets.max_web_searches,
            max_web_fetches=self.tool_budgets.max_web_fetches,
        )
        self.anti_loop = AntiLoop()

        self.messages.append({"role": "user", "content": question})
        self.session.save_messages(self.messages)
        self.session.append_event("turn_started", {"turns": 0})

        while True:
            limit = self.budget.can_start_turn()
            if limit is not None:
                return self._final(limit)

            # chama o modelo com histórico + schemas das ferramentas
            self.budget.record_llm_call()
            self.on_event("llm_call", {"turns": self.budget.turns_used})
            response: ChatResponse = self.chat.chat(
                self.messages,
                tools=[t.schema() for t in self.tools.values()],
                max_tokens=self._max_tokens(),
            )

            if response.tool_calls:
                tool_call = response.tool_calls[0]  # uma por iteração (MVP)
                name = tool_call.name
                tool = self.tools.get(name)
                if tool is None:
                    context = f"ERRO: ferramenta desconhecida: {name}."
                else:
                    args, parse_err = parse_tool_call(
                        None,
                        [
                            {
                                "id": tool_call.id,
                                "name": name,
                                "arguments": tool_call.arguments,
                            }
                        ],
                        self.tools,
                    )
                    if parse_err is not None:
                        context = f"ERRO: {parse_err}"
                    else:
                        # guardrail anti-loop
                        action = self.anti_loop.register(name, tool_call.arguments)
                        if action == "stop":
                            context = (
                                "ERRO: anti-loop — mesma chamada repetida 4 vezes. "
                                "Responda ao usuário com o que tiver."
                            )
                        elif action == "nudge":
                            context = (
                                self.anti_loop.nudge_message(name)
                                + "\nResultado não útil; tente outro caminho ou responda."
                            )
                        else:
                            # orçamento da tool (web/deep_search); outras tools
                            # não têm orçamento próprio por mensagem.
                            if name in ("deep_search", "web_search", "web_fetch"):
                                budget_err = self.tool_budgets.consume(name)
                                if budget_err is not None:
                                    context = budget_err
                                    self.session.append_event(
                                        "tool_call",
                                        {
                                            "tool": name,
                                            "args": tool_call.arguments,
                                            "ok": False,
                                            "budget_exhausted": True,
                                        },
                                    )
                                else:
                                    started = monotonic()
                                    result = tool.execute(**args)
                                    elapsed = monotonic() - started
                                    # cap de resultado
                                    cap = self.tool_cap.cap_for(name)
                                    text = result.text
                                    if len(text) > cap:
                                        text = text[:cap] + f"\n…(truncado a {cap} chars)"
                                    result.text = text
                                    context = result_to_context(result)

                                    self.session.append_event(
                                        "tool_call",
                                        {
                                            "tool": name,
                                            "args": tool_call.arguments,
                                            "ok": result.ok,
                                            "seconds": round(elapsed, 3),
                                        },
                                    )
                            else:
                                started = monotonic()
                                result = tool.execute(**args)
                                elapsed = monotonic() - started
                                # cap de resultado
                                cap = self.tool_cap.cap_for(name)
                                text = result.text
                                if len(text) > cap:
                                    text = text[:cap] + f"\n…(truncado a {cap} chars)"
                                result.text = text
                                context = result_to_context(result)

                                self.session.append_event(
                                    "tool_call",
                                    {
                                        "tool": name,
                                        "args": tool_call.arguments,
                                        "ok": result.ok,
                                        "seconds": round(elapsed, 3),
                                    },
                                )

                # registra assistant + resultado da ferramenta no histórico
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in response.tool_calls
                        ],
                    }
                )
                self.messages.append({"role": "user", "content": context})
                self.session.save_messages(self.messages)
                self.budget.record_turn()
                continue

            # resposta final sem tool call
            final = response.content or "(sem resposta)"
            self.messages.append({"role": "assistant", "content": final})
            self.session.save_messages(self.messages)
            self.session.append_event("turn_ended", {"turns": self.budget.turns_used})
            return final

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
        self.session.append_event("budget_exhausted", {"reason": reason})
        return partial
