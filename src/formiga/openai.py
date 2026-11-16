"""Cliente para endpoints remotos OpenAI-compatíveis (NVIDIA NIM, OpenAI, etc.).

POST em `{base_url}/chat/completions` com `Authorization: Bearer <chave>`.
A chave vem de `config.resolve_api_key()` — variável de ambiente indicada por
`api_key_env` ou valor embutido no arquivo de config (permissão 0600).

Diferenças do cliente `llamacpp` (que é OpenAI-compatível só no formato):

- envia `model` (obrigatório em endpoints remotos);
- com thinking ligado (default), envia `chat_template_kwargs` +
  `skip_special_tokens` (ficha do Nemotron 3.5 Bolt); endpoints que rejeitam
  esses campos recebem uma repetição sem eles;
- `json_schema` é ignorado: a restrição gramatical fica por conta da validação
  do harness (StructuredCaller + Pydantic), que já cobre todos os backends;
- se o servidor rejeitar `response_format` com HTTP 400, repete a chamada uma
  única vez sem o campo (modo JSON livre);
- retries com backoff para 429/5xx, honrando `Retry-After`; cada retry é
  reportado via callback `on_retry` (evento `llm_retry`) e consome tempo do
  deadline — o contador de chamadas do orçamento permanece por tarefa.

O timeout é limitado ao tempo restante da execução, como nos demais clientes.
Mensagens de erro incluem status HTTP e trecho limitado do corpo — nunca a
chave de API.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from formiga.config import Config, ConfigError
from formiga.llm import LLMError, LLMResponse

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
ERROR_SNIPPET_CHARS = 200


class OpenAIError(LLMError):
    """Falha de comunicação com o endpoint remoto OpenAI-compatível."""


class OpenAIClient:
    """Backend remoto: mesmo contrato `LLMClient` dos clientes locais."""

    def __init__(
        self,
        config: Config,
        transport: httpx.BaseTransport | None = None,
        remaining_seconds: Callable[[], float] | None = None,
        on_retry: Callable[[int, int, float], None] | None = None,
    ) -> None:
        self.url = config.openai_url.rstrip("/")
        self.model = config.model
        self.llm_timeout = config.llm_timeout
        self.temperature = config.llm_temperature
        self.max_retries = config.llm_max_retries
        # Modelos de raciocínio (Nemotron Bolt na NIM): kwarg de chat template
        # ligando o thinking (default do template do modelo). Endpoints que
        # rejeitam o campo recebem uma repetição sem ele.
        self.thinking = config.llm_thinking
        self.on_retry = on_retry
        api_key = config.resolve_api_key()
        if not api_key:
            raise ConfigError(
                "API key não encontrada: defina a variável de ambiente "
                f"{config.openai_api_key_env!r} (ou 'api_key' no arquivo de "
                "configuração com permissão 0600)."
            )
        self._api_key = api_key
        self._remaining = remaining_seconds
        self._transport = transport

    def _endpoint(self) -> str:
        """Compõe a URL sem duplicar `/v1` nem sufixo de caminho."""
        base = self.url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

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
        del json_schema  # schema não é imposto remotamente; validação no harness
        with_format = True
        with_thinking = self.thinking
        attempt = 0
        while True:
            attempt += 1
            payload = self._payload(
                system, user, max_tokens, with_format, with_thinking
            )
            try:
                response = self._request(payload)
            except httpx.HTTPError as exc:
                raise OpenAIError(f"Falha ao chamar o endpoint remoto: {exc}") from exc
            status = response.status_code
            if status in RETRYABLE_STATUSES and attempt <= self.max_retries:
                delay = self._retry_delay(response, attempt)
                if self.on_retry is not None:
                    self.on_retry(status, attempt, delay)
                time.sleep(delay)
                continue
            body = response.content.lower()
            if status == 400 and with_format and b"response_format" in body:
                # Servidor não suporta `response_format`: tentar sem, uma vez.
                with_format = False
                continue
            if status == 400 and with_thinking and (
                b"chat_template_kwargs" in body
                or b"skip_special_tokens" in body
                or b"thinking" in body
            ):
                # Endpoint sem suporte ao kwarg de raciocínio: repetir sem.
                with_thinking = False
                continue
            if status >= 400:
                raise OpenAIError(f"HTTP {status} do endpoint remoto: {_snippet(response)}")
            try:
                data = response.json()
            except ValueError as exc:
                raise OpenAIError(f"Resposta não-JSON do endpoint remoto: {exc}") from exc
            return self._parse(data)

    def _payload(
        self,
        system: str,
        user: str,
        max_tokens: int | None,
        with_format: bool,
        with_thinking: bool = False,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "top_p": 0.95,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if with_format:
            payload["response_format"] = {"type": "json_object"}
        if with_thinking:
            # Ficha do Nemotron 3.5 Bolt: reasoning via chat template e
            # `skip_special_tokens: false` para o raciocínio não sumir.
            payload["chat_template_kwargs"] = {"enable_thinking": True}
            payload["skip_special_tokens"] = False
        return payload

    def _request(self, payload: dict) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        with httpx.Client(
            timeout=self._effective_timeout(), transport=self._transport
        ) as client:
            return client.post(self._endpoint(), json=payload, headers=headers)

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), MAX_BACKOFF_SECONDS))
            except ValueError:
                pass
        return min(DEFAULT_BACKOFF_SECONDS * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIError(f"Resposta do endpoint remoto sem conteúdo: {data!r}") from exc
        content = message.get("content") if isinstance(message, dict) else None
        usage = data.get("usage") or {}
        tokens = usage.get("completion_tokens")
        truncated = choice.get("finish_reason") == "length"
        if not isinstance(content, str) or not content.strip():
            if truncated:
                # O raciocínio consumiu o teto antes do JSON: sinalizar o
                # truncamento para o chamador dobrar o cap e tentar de novo.
                return LLMResponse(
                    content="", tokens=tokens if isinstance(tokens, int) else None,
                    truncated=True,
                )
            reasoning = (
                message.get("reasoning_content") if isinstance(message, dict) else None
            )
            hint = (
                " (apenas reasoning_content: raciocínio consumiu o teto de geração)"
                if reasoning
                else ""
            )
            raise OpenAIError(f"Resposta do endpoint remoto sem conteúdo{hint}.")
        return LLMResponse(
            content=content, tokens=tokens if isinstance(tokens, int) else None,
            truncated=truncated,
        )


def _snippet(response: httpx.Response) -> str:
    """Trecho limitado do corpo de erro para diagnóstico (sem credenciais)."""
    return response.text[:ERROR_SNIPPET_CHARS].replace("\n", " ")
