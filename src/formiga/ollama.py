"""Cliente Ollama (API HTTP): uma tarefa por chamada, sem histórico acumulado.

Solicita saída JSON estruturada ao backend (`format: "json"`) quando suportado.
Tokens são registrados quando o backend os fornece; caso contrário, `unknown`.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

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
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        try:
            with httpx.Client(
                timeout=self._effective_timeout(), transport=self._transport
            ) as client:
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
