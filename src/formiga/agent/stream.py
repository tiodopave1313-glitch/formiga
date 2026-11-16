"""Consumo de stream OpenAI-compatível (SSE) para chat com streaming.

Usado pelos clientes `openai` e `llamacpp` (llama-server é OpenAI-compatível
no formato). Acumula `delta.content` (entregue ao callback em tempo real) e
monta tool_calls a partir dos fragments delta por `index`.

O callback pode levantar `AgentCancelled` — a exceção não é engolida aqui;
propaga para o loop, que a interpreta como interrupção do usuário.
"""

from __future__ import annotations

import json

from formiga.agent.chat import ChatResponse, DeltaCallback, ToolCall


def consume_sse_chat_stream(
    response,
    on_delta: DeltaCallback | None,
    error_cls: type[Exception],
) -> ChatResponse:
    """Lê um `httpx.Response` SSE de chat/completions e monta a resposta.

    `error_cls` é a classe de erro do backend (OpenAIError/LlamaCppError) para
    falhas de parse — coerente com o tratamento existente de cada cliente.
    """
    content_parts: list[str] = []
    tool_calls_acc: dict[int, dict] = {}
    truncated = False

    for line in response.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except ValueError as exc:
            raise error_cls(f"Evento SSE inválido do endpoint: {exc}") from exc
        choices = event.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            truncated = True
        delta = choice.get("delta") or {}
        piece = delta.get("content")
        if isinstance(piece, str) and piece:
            content_parts.append(piece)
            if on_delta is not None:
                on_delta(piece)
        for tc in delta.get("tool_calls") or []:
            index = tc.get("index", 0)
            acc = tool_calls_acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if tc.get("id"):
                acc["id"] = tc["id"]
            function = tc.get("function") or {}
            name = function.get("name")
            if name and not acc["name"]:
                acc["name"] = name
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments:
                acc["arguments"] += arguments

    tool_calls: list[ToolCall] | None = None
    if tool_calls_acc:
        tool_calls = [
            ToolCall(
                id=acc["id"],
                name=acc["name"],
                arguments=acc["arguments"] or "{}",
            )
            for _, acc in sorted(tool_calls_acc.items())
        ]
    content = "".join(content_parts)
    return ChatResponse(
        content=content if content else None,
        tool_calls=tool_calls,
        truncated=truncated,
    )
