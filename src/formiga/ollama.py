"""Cliente Ollama (API HTTP): uma tarefa por chamada, sem histórico acumulado.

Solicita saída JSON estruturada ao backend (`format: "json"`) quando suportado.
Tokens são registrados quando o backend os fornece; caso contrário, `unknown`.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from formiga.agent.chat import ChatResponse, ToolCall
from formiga.config import Config
from formiga.llm import LLMError, LLMResponse


class OllamaError(LLMError):
    """Falha de comunicação com o Ollama."""


class OllamaClient:
    def __init__(
        self,
        config: Config,
        transport: httpx.BaseTransport | None = None,
        remaining_seconds: Callable[[], float] | None = None,
    ) -> None:
        self.url = config.ollama_url.rstrip("/")
        self.model = config.model
        self.llm_timeout = config.llm_timeout
        self.temperature = config.llm_temperature
        # Modelos de raciocínio (Nemotron Bolt): pedir thinking explicitamente.
        # Modelos sem suporte respondem 400; aí desliga para o resto da run.
        self.think = config.llm_thinking
        self._remaining = remaining_seconds
        self._transport = transport

    def _effective_timeout(self) -> float:
        """Timeout da geração limitado ao tempo restante da execução."""
        if self._remaining is None:
            return self.llm_timeout
        return max(0.05, min(self.llm_timeout, self._remaining()))

    def complete(
        self,
        system: str,
        user: str,
        json_schema: dict | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # O Ollama usa `format: "json"`; o schema é imposto pela validação do harness.
        # top_k/top_p seguem a recomendação de amostragem da Gemma 4.
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperature,
                "top_k": 64,
                "top_p": 0.95,
            },
        }
        if self.think:
            payload["think"] = True
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        try:
            with httpx.Client(
                timeout=self._effective_timeout(), transport=self._transport
            ) as client:
                response = client.post(f"{self.url}/api/chat", json=payload)
                if response.status_code == 400 and self.think:
                    body = response.text.lower()
                    if "think" in body:
                        # Modelo sem suporte a thinking: repetir sem o campo e
                        # não voltar a pedi-lo nesta execução.
                        self.think = False
                        del payload["think"]
                        response = client.post(f"{self.url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Falha ao chamar o Ollama: {exc}") from exc
        except ValueError as exc:
            raise OllamaError(f"Resposta não-JSON do Ollama: {exc}") from exc
        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise OllamaError(f"Resposta do Ollama sem conteúdo: {data!r}") from exc
        # Tokens: registrar quando o backend fornece; `unknown` caso contrário.
        tokens = data.get("eval_count")
        # `done_reason: "length"` = cortado no limite de geração (builds recentes).
        truncated = data.get("done_reason") == "length"
        return LLMResponse(
            content=content, tokens=tokens if isinstance(tokens, int) else None,
            truncated=truncated,
        )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """Chat com histórico e (opcional) chamadas de ferramenta no Ollama."""
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_k": 64,
                "top_p": 0.95,
            },
        }
        if tools:
            payload["tools"] = tools
        if self.think:
            payload["think"] = True
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        try:
            with httpx.Client(
                timeout=self._effective_timeout(), transport=self._transport
            ) as client:
                response = client.post(f"{self.url}/api/chat", json=payload)
                if response.status_code == 400 and self.think:
                    body = response.text.lower()
                    if "think" in body:
                        self.think = False
                        del payload["think"]
                        response = client.post(f"{self.url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Falha ao chamar o Ollama: {exc}") from exc
        except ValueError as exc:
            raise OllamaError(f"Resposta não-JSON do Ollama: {exc}") from exc
        try:
            message = data["message"]
        except (KeyError, TypeError) as exc:
            raise OllamaError(f"Resposta do Ollama sem mensagem: {data!r}") from exc
        content = message.get("content")
        tool_calls_raw = message.get("tool_calls")
        truncated = data.get("done_reason") == "length"
        tool_calls: list[ToolCall] | None = None
        if tool_calls_raw:
            tool_calls = [
                ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("function", {}).get("name", ""),
                    arguments=tc.get("function", {}).get("arguments", "{}"),
                )
                for tc in tool_calls_raw
            ]
        return ChatResponse(
            content=content if isinstance(content, str) else None,
            tool_calls=tool_calls,
            truncated=truncated,
        )
