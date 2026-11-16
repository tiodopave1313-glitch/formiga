"""Fakes para testes do agente (offline, sem rede nem modelo real)."""

from __future__ import annotations

from formiga.agent.chat import ChatResponse, ToolCall


class FakeChatClient:
    """Responde com roteiros scriptados: texto final ou chamada de ferramenta."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict], list[dict] | None, int | None]] = []

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        self.calls.append((messages, tools, max_tokens))
        if not self.responses:
            raise AssertionError("FakeChatClient sem respostas restantes")
        return self.responses.pop(0)


def tool_call(name: str, arguments: str, call_id: str = "call_1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)
