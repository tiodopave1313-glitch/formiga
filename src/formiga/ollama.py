"""Cliente Ollama (API HTTP): uma tarefa por chamada, sem histórico acumulado.

Solicita saída JSON estruturada ao backend (`format: "json"`) quando suportado.
Tokens são registrados quando o backend os fornece; caso contrário, `unknown`.
"""

from __future__ import annotations

import httpx

from formiga.config import Config
from formiga.llm import LLMResponse


class OllamaError(Exception):
    """Falha de comunicação com o Ollama."""


class OllamaClient:
    def __init__(self, config: Config, transport: httpx.BaseTransport | None = None) -> None:
        self.url = config.ollama_url.rstrip("/")
        self.model = config.model
        self.timeout = config.network_timeout
        self._transport = transport

    def complete(
        self, system: str, user: str, json_schema: dict | None = None
    ) -> LLMResponse:
        # O Ollama usa `format: "json"`; o schema é imposto pela validação do harness.
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
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
        return LLMResponse(content=content, tokens=tokens if isinstance(tokens, int) else None)
