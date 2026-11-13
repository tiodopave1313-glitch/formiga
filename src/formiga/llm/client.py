"""HTTP backend for a local ``llama-server`` chat-completions endpoint."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from formiga.config import Endpoint
from formiga.llm.base import LLM, BackendUnavailable, LLMError
from formiga.llm.types import Completion, CompletionRequest


class HTTPLLM(LLM):
    """Chat-completions client for one endpoint.

    If the server rejects ``response_format`` the request is retried once without it and
    ``supports_grammar`` flips to ``False`` for the process, so ``doctor`` can report the
    degradation instead of the pipeline silently losing its guarantees.
    """

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        profile_name: str = "fast",
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint_config = endpoint
        self.profile_name = profile_name
        self.supports_grammar = endpoint.supports_grammar
        self._client = client or httpx.Client(timeout=endpoint.request_timeout_s)

    @property
    def model(self) -> str:
        return self.endpoint_config.model or "unknown"

    @property
    def url(self) -> str:
        return f"{self.endpoint_config.endpoint.rstrip('/')}/v1/chat/completions"

    def close(self) -> None:
        self._client.close()

    def _payload(self, request: CompletionRequest, *, with_schema: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [message.as_dict() for message in request.messages],
            "temperature": request.temperature,
            "stream": False,
            "repeat_penalty": request.repeat_penalty,
        }
        if self.endpoint_config.model:
            payload["model"] = self.endpoint_config.model
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.stop:
            payload["stop"] = list(request.stop)
        if with_schema and request.response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "stage_output", "schema": request.response_schema},
            }
        return payload

    def complete(self, request: CompletionRequest) -> Completion:
        wants_schema = bool(request.response_schema) and self.supports_grammar
        try:
            response = self._post(request, with_schema=wants_schema)
        except httpx.HTTPError as exc:
            raise BackendUnavailable(str(exc)) from exc
        if response.status_code >= 400 and wants_schema:
            self.supports_grammar = False
            try:
                response = self._post(request, with_schema=False)
            except httpx.HTTPError as exc:
                raise BackendUnavailable(str(exc)) from exc
        if response.status_code >= 400:
            raise LLMError(f"endpoint returned {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("endpoint returned invalid JSON") from exc
        return _parse_completion(body)

    def _post(self, request: CompletionRequest, *, with_schema: bool) -> httpx.Response:
        return self._client.post(self.url, json=self._payload(request, with_schema=with_schema))

    def stream(self, request: CompletionRequest) -> Iterator[str]:
        payload = self._payload(request, with_schema=bool(request.response_schema))
        payload["stream"] = True
        try:
            with self._client.stream("POST", self.url, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        return
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = (data.get("choices") or [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise BackendUnavailable(str(exc)) from exc

    def healthy(self) -> bool:
        """Cheap liveness probe used by ``doctor`` and the role router."""
        try:
            response = self._client.get(
                f"{self.endpoint_config.endpoint.rstrip('/')}/health", timeout=3.0
            )
        except httpx.HTTPError:
            return False
        return response.status_code < 500


def _parse_completion(body: dict[str, Any]) -> Completion:
    choices = body.get("choices") or []
    if not choices:
        raise LLMError("endpoint returned no choices")
    choice = choices[0]
    message = choice.get("message") or {}
    usage = body.get("usage") or {}
    return Completion(
        content=message.get("content") or "",
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        finish_reason=choice.get("finish_reason"),
        raw=body,
    )


__all__ = ["HTTPLLM"]
