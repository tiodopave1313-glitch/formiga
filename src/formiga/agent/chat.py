"""Camada de chat com histórico e chamadas de ferramenta (seção 5 do PRD).

Define o contrato `ChatClient` (protocol) e os tipos `ChatResponse` /
`ToolCall`. Cada backend (`openai.py`, `ollama.py`, `llamacpp.py`) implementa
`chat(messages, tools, max_tokens)` reutilizando seu próprio transport,
thinking, timeouts e retries — sem alterar o contrato `complete` existente.

O histórico é uma lista de mensagens `{role, content[, tool_calls, tool_call_id]}`.
Uma resposta é texto puro ou uma (ou mais) chamada de ferramenta; nunca ambas
no MVP (uma tool call por iteração).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from formiga.llm import LLMError

# Callback de streaming: recebe pedaços de texto do `content` do modelo.
DeltaCallback = Callable[[str], None]


class AgentCancelled(Exception):
    """Usuário pediu interrupção durante o stream — não é falha do LLM.

    Os backends não devem engoli-la (não é `httpx.HTTPError` nem
    `ValueError`) nem tratá-la como falha de fallback (`LLMError`).
    """

    def __init__(self) -> None:
        super().__init__("Execução interrompida pelo usuário.")


@dataclass
class ToolCall:
    """Uma única chamada de ferramenta pedida pelo modelo."""
    id: str
    name: str
    arguments: str  # payload JSON serializado (string)


@dataclass
class ChatResponse:
    """Resposta do modelo a uma rodada de chat."""
    content: str | None = None      # texto do assistente (sem tool call)
    tool_calls: list[ToolCall] | None = None  # chamada(s) de ferramenta
    truncated: bool = False         # terminou por limite de geração
    deltas: list[str] | None = None  # pedaços roteirizados (fakes de teste)
    # Raciocínio separado (`reasoning_content`) de modelos thinking. Não é
    # entregue ao usuário nem entra no histórico: serve para distinguir
    # "resposta vazia" de "raciocínio comeu o teto de geração".
    reasoning: str | None = None


class ChatClient(Protocol):
    """Cliente de modelo com histórico e ferramentas.

    `messages` é o histórico acumulado; `tools` são os schemas JSON das
    ferramentas disponíveis (formato OpenAI/Ollama/llama-server). Com
    `on_delta`, o backend usa streaming e entrega pedaços de texto em tempo
    real (a resposta final continua completa ao fim da chamada).
    """

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> ChatResponse: ...


def build_chat_client(
    config, remaining_seconds=None
) -> ChatClient:
    """Escolhe o backend de chat conforme `config.llm_backend`; fallback opt-in.

    Espelha `build_llm_client` do orquestrador: sem `fallback_backend`,
    devolve apenas o cliente principal.
    """

    backend = config.llm_backend
    if backend == "openai":
        from formiga.openai import OpenAIClient

        primary = OpenAIClient(
            config,
            remaining_seconds=remaining_seconds,
        )
    elif backend == "ollama":
        from formiga.ollama import OllamaClient

        primary = OllamaClient(
            config,
            remaining_seconds=remaining_seconds,
        )
    elif backend == "llamacpp":
        from formiga.llamacpp import LlamaCppClient

        primary = LlamaCppClient(
            config,
            remaining_seconds=remaining_seconds,
        )
    else:  # pragma: no cover — validado pelo Config
        raise LLMError(f"Backend de chat não suportado: {backend!r}.")

    fallback_backend = config.fallback_backend
    if fallback_backend is None:
        return primary

    if fallback_backend == "openai":
        from formiga.openai import OpenAIClient

        fallback = OpenAIClient(
            config,
            remaining_seconds=remaining_seconds,
        )
    elif fallback_backend == "ollama":
        from formiga.ollama import OllamaClient

        fallback = OllamaClient(
            config,
            remaining_seconds=remaining_seconds,
        )
    elif fallback_backend == "llamacpp":
        from formiga.llamacpp import LlamaCppClient

        fallback = LlamaCppClient(
            config,
            remaining_seconds=remaining_seconds,
        )
    else:  # pragma: no cover
        raise LLMError(f"Backend de fallback de chat não suportado: {fallback_backend!r}.")

    return FallbackChatClient(primary, fallback, after_failures=config.fallback_after_failures)


class FallbackChatClient:
    """Envolve principal + backup com disjuntor (circuit breaker)."""

    def __init__(
        self,
        primary: ChatClient,
        fallback: ChatClient,
        after_failures: int = 1,
        on_fallback=None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.after_failures = after_failures
        self.on_fallback = on_fallback
        self._consecutive_failures = 0
        self.using_fallback = False

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> ChatResponse:
        if self.using_fallback:
            return self.fallback.chat(messages, tools, max_tokens, on_delta)
        try:
            return self.primary.chat(messages, tools, max_tokens, on_delta)
        except LLMError as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.after_failures:
                self.using_fallback = True
                if self.on_fallback is not None:
                    self.on_fallback(str(exc))
                return self.fallback.chat(messages, tools, max_tokens, on_delta)
            raise
