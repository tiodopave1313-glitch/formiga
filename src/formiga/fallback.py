"""Failover opt-in entre backends de modelo.

Só é usado quando `config.fallback_backend` está definido (arquivo, env ou
CLI). Sem essa opção, o Formiga usa apenas o backend principal — o
comportamento não muda por padrão.

Semântica:

- o backend principal é tentado primeiro; em falha de transporte (`LLMError`),
  o backup assume e permanece pelo resto da execução (circuit breaker) —
  retestar um backend lento a cada chamada queimaria o orçamento de tempo;
- `after_failures > 1` exige N falhas consecutivas antes da primeira migração
  (a falha intermediária é propagada, sem backup);
- o backup usa o mesmo parâmetro de timeout (limitado ao tempo restante do
  orçamento) e o mesmo contrato `LLMClient`.
"""

from __future__ import annotations

from collections.abc import Callable

from formiga.llm import LLMClient, LLMError, LLMResponse


class FallbackLLMClient:
    """Envolve principal + backup com o contrato `LLMClient`."""

    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient,
        after_failures: int = 1,
        on_fallback: Callable[[LLMError], None] | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._after_failures = max(1, after_failures)
        self._failures = 0
        self._active: LLMClient = primary
        self.on_fallback = on_fallback

    @property
    def fallback(self) -> LLMClient:
        """Cliente de backup (para wiring de eventos pelo orquestrador)."""
        return self._fallback

    @property
    def using_fallback(self) -> bool:
        """True quando o circuit breaker já migrou para o backup."""
        return self._active is self._fallback

    def complete(
        self,
        system: str,
        user: str,
        json_schema: dict | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        try:
            return self._active.complete(system, user, json_schema, max_tokens)
        except LLMError as exc:
            if self._active is self._fallback:
                raise  # backup também falhou: falha conservadora, como sempre.
            self._failures += 1
            if self._failures < self._after_failures:
                raise
            self._active = self._fallback
            if self.on_fallback is not None:
                self.on_fallback(exc)
            # O backup assume já nesta chamada: a tarefa não é perdida.
            return self._fallback.complete(system, user, json_schema, max_tokens)
