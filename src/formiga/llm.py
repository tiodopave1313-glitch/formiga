"""Contratos das chamadas ao 8B (seção 10 do PRD).

O modelo não escolhe ferramentas nem altera o estado: retorna propostas
estruturadas em JSON, validadas pelo harness. Em caso de JSON inválido ou
schema incorreto, há uma única tentativa de correção com o erro objetivo.
"""

from __future__ import annotations

import enum
import json
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


@dataclass
class LLMResponse:
    content: str
    tokens: int | None = None  # `unknown` quando o backend não fornece contagem.


class LLMClient(Protocol):
    """Cliente de modelo: uma tarefa por chamada, sem histórico acumulado."""

    def complete(self, system: str, user: str) -> LLMResponse: ...


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
        on_call: callable[[TaskType, bool], None] | None = None,
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
        """Executa a tarefa e valida a saída; `None` indica falha registrada."""
        error_feedback: str | None = None
        attempts = 0
        last_error: str = ""
        for _ in range(1 + 1):  # tentativa original + 1 correção de formato
            attempts += 1
            prompt = user if error_feedback is None else (
                f"{user}\n\nA resposta anterior era inválida. Erro objetivo: "
                f"{error_feedback}\nCorrija e devolva novamente apenas o JSON."
            )
            response = self.client.complete(system, prompt)
            ok, parsed, err = _parse_and_validate(response.content, schema)
            if ok:
                self._record(task, True, attempts)
                self._notify(task, True)
                return parsed
            last_error = err
            self._notify(task, False)
            error_feedback = err
        self._record(task, False, attempts, last_error)
        return None

    def _record(self, task: TaskType, ok: bool, attempts: int, error: str | None = None) -> None:
        self.records.append(CallRecord(task=task, ok=ok, attempts=attempts, error=error))

    def _notify(self, task: TaskType, ok: bool) -> None:
        if self.on_call is not None:
            self.on_call(task, ok)


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
