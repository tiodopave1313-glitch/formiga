"""Contratos das chamadas ao 8B (seção 10 do PRD).

O modelo não escolhe ferramentas nem altera o estado: retorna propostas
estruturadas em JSON, validadas pelo harness. Em caso de JSON inválido ou
schema incorreto, há uma única tentativa de correção com o erro objetivo.
"""

from __future__ import annotations

import enum
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ValidationError

from formiga.models import utc_now


class TaskType(enum.StrEnum):
    PLAN = "plan"
    QUERY = "query"
    EXTRACT = "extract"
    VERIFY = "verify"
    COMPARE = "compare"
    SYNTHESIZE = "synthesize"
    AUDIT = "audit"


# Limites de geração por tarefa: travam loops de JSON e mantêm cada chamada
# dentro do timeout em geração lenta (CPU). Síntese é a saída mais longa.
TASK_MAX_TOKENS: dict[TaskType, int] = {
    TaskType.PLAN: 512,
    TaskType.QUERY: 128,
    TaskType.EXTRACT: 512,
    TaskType.VERIFY: 128,
    TaskType.COMPARE: 160,
    TaskType.SYNTHESIZE: 900,
    TaskType.AUDIT: 512,
}


@dataclass
class LLMResponse:
    content: str
    tokens: int | None = None  # `unknown` quando o backend não fornece contagem.


class LLMError(Exception):
    """Falha de transporte/protocolo com o backend do modelo."""


class LLMClient(Protocol):
    """Cliente de modelo: uma tarefa por chamada, sem histórico acumulado.

    `json_schema` é opcional: backends com restrição gramatical (llama.cpp)
    podem usá-lo; backends sem suporte o ignoram.
    """

    def complete(
        self,
        system: str,
        user: str,
        json_schema: dict | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


class StructuredCallError(Exception):
    """A chamada estruturada falhou mesmo após a tentativa de correção."""

    def __init__(self, task: TaskType, reason: str) -> None:
        self.task = task
        self.reason = reason
        super().__init__(f"{task.value}: {reason}")


@dataclass
class CallRecord:
    task: TaskType
    ok: bool
    attempts: int
    tokens: int | None = None  # `unknown` quando o backend não fornece contagem.
    seconds: float | None = None
    error: str | None = None
    ts: str = field(default_factory=utc_now)


class StructuredCaller:
    """Envolve o cliente com validação de schema e uma correção de formato.

    Cada tentativa — inclusive falha e correção — é contabilizada pelo
    orçamento pelo chamador via `on_call`.
    """

    def __init__(
        self,
        client: LLMClient,
        on_call: Callable[[TaskType, bool, int | None, float | None], None] | None = None,
    ) -> None:
        self.client = client
        self.on_call = on_call
        self.records: list[CallRecord] = []

    def call(
        self,
        task: TaskType,
        system: str,
        user: str,
        schema: type[BaseModel],
    ) -> BaseModel | None:
        """Executa a tarefa e valida a saída; `None` indica falha registrada.

        Falhas de transporte (timeout, conexão) tornam a *chamada* falha e
        retornam `None` — o orquestrador continua de forma conservadora.
        """
        error_feedback: str | None = None
        attempts = 0
        last_error: str = ""
        max_tokens = TASK_MAX_TOKENS.get(task)
        for _ in range(1 + 1):  # tentativa original + 1 correção de formato
            attempts += 1
            prompt = user if error_feedback is None else (
                f"{user}\n\nA resposta anterior era inválida. Erro objetivo: "
                f"{error_feedback}\nCorrija e devolva novamente apenas o JSON."
            )
            started = time.monotonic()
            try:
                response = self.client.complete(
                    system, prompt, schema.model_json_schema(), max_tokens
                )
            except LLMError as exc:
                seconds = time.monotonic() - started
                self._record(task, False, attempts, None, seconds, str(exc))
                self._notify(task, False, None, seconds)
                return None
            seconds = time.monotonic() - started
            ok, parsed, err = _parse_and_validate(response.content, schema)
            if ok:
                self._record(task, True, attempts, response.tokens, seconds)
                self._notify(task, True, response.tokens, seconds)
                return parsed
            last_error = err
            self._notify(task, False, response.tokens, seconds)
            error_feedback = err
        self._record(task, False, attempts, None, None, last_error)
        return None

    def _record(
        self,
        task: TaskType,
        ok: bool,
        attempts: int,
        tokens: int | None = None,
        seconds: float | None = None,
        error: str | None = None,
    ) -> None:
        self.records.append(
            CallRecord(
                task=task, ok=ok, attempts=attempts, tokens=tokens,
                seconds=seconds, error=error,
            )
        )

    def _notify(
        self, task: TaskType, ok: bool, tokens: int | None, seconds: float | None
    ) -> None:
        if self.on_call is not None:
            self.on_call(task, ok, tokens, seconds)


def _parse_and_validate(
    content: str, schema: type[BaseModel]
) -> tuple[bool, BaseModel | None, str]:
    try:
        data = _extract_json(content)
    except ValueError as exc:
        return False, None, f"JSON inválido: {exc}"
    try:
        return True, schema.model_validate(data), ""
    except ValidationError as exc:
        return False, None, f"Schema incorreto: {exc.error_count()} erro(s) — {exc}"


def _extract_json(content: str) -> object:
    """Aceita JSON puro ou cercado por ```json ... ```; recusa texto solto."""
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 2:
            raise ValueError("bloco de código vazio")
        body = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = body.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
