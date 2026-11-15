"""Cliente para llama.cpp (`llama-server`) via endpoint OpenAI-compatível.

Envia o schema JSON da tarefa em `response_format` — o llama-server o converte
em gramática GBNF e restringe a saída a JSON válido conforme o schema.
Builds antigas que só suportam `json_object` puro também funcionam: o campo
`schema` é ignorado pelo servidor e a validação fica no harness.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from formiga.config import Config
from formiga.llm import LLMError, LLMResponse


class LlamaCppError(LLMError):
    """Falha de comunicação com o llama-server."""


class LlamaCppClient:
    def __init__(
        self,
        config: Config,
        transport: httpx.BaseTransport | None = None,
        remaining_seconds: Callable[[], float] | None = None,
    ) -> None:
        self.url = config.llamacpp_url.rstrip("/")
        self.llm_timeout = config.llm_timeout
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
        payload: dict = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if json_schema is not None:
            payload["response_format"]["schema"] = json_schema
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            with httpx.Client(
                timeout=self._effective_timeout(), transport=self._transport
            ) as client:
                response = client.post(f"{self.url}/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LlamaCppError(f"Falha ao chamar o llama-server: {exc}") from exc
        except ValueError as exc:
            raise LlamaCppError(f"Resposta não-JSON do llama-server: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlamaCppError(f"Resposta do llama-server sem conteúdo: {data!r}") from exc
        usage = data.get("usage") or {}
        tokens = usage.get("completion_tokens")
        return LLMResponse(content=content, tokens=tokens if isinstance(tokens, int) else None)
