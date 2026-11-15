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
    TaskType.PLAN: 1024,   # planejamento é o JSON mais verboso
    TaskType.QUERY: 128,
    TaskType.EXTRACT: 1536,  # extração gera muitos claims; 512/1024 truncavam
    TaskType.VERIFY: 128,
    TaskType.COMPARE: 160,
    TaskType.SYNTHESIZE: 900,
    TaskType.AUDIT: 512,
}

# Teto absoluto quando uma resposta truncada pede mais espaço (cap dobrado).
MAX_GENERATION_TOKENS = 2048

# Conteúdo bruto logado em evento quando a validação falha (diagnóstico).
RAW_LOG_CHARS = 300

# Modelos de raciocínio geram `reasoning_content` antes do JSON; quando o
# thinking está ligado, os caps por tarefa recebem esse adicional.
REASONING_EXTRA_TOKENS = 384


@dataclass
class LLMResponse:
    content: str
    tokens: int | None = None  # `unknown` quando o backend não fornece contagem.
    truncated: bool = False  # True quando terminou por limite de geração.


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
    truncated: bool = False
    raw: str | None = None  # conteúdo bruto (truncado) quando a validação falha.
    ts: str = field(default_factory=utc_now)


class StructuredCaller:
    """Envolve o cliente com validação de schema e uma correção de formato.

    Cada tentativa — inclusive falha e correção — é contabilizada pelo
    orçamento pelo chamador via `on_call`.
    """

    def __init__(
        self,
        client: LLMClient,
        on_call: Callable[[TaskType, bool, int | None, float | None, dict | None], None]
        | None = None,
        extra_tokens: int = 0,
    ) -> None:
        self.client = client
        self.on_call = on_call
        self.extra_tokens = extra_tokens  # folga p/ raciocínio (thinking ligado)
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
        last_raw: str | None = None
        last_truncated = False
        effective_cap = TASK_MAX_TOKENS.get(task)
        if effective_cap is not None:
            effective_cap += self.extra_tokens
        for _ in range(1 + 1):  # tentativa original + 1 correção de formato
            attempts += 1
            prompt = user if error_feedback is None else (
                f"{user}\n\nA resposta anterior era inválida. Erro objetivo: "
                f"{error_feedback}\nCorrija e devolva novamente apenas o JSON."
            )
            started = time.monotonic()
            try:
                response = self.client.complete(
                    system, prompt, schema.model_json_schema(), effective_cap
                )
            except LLMError as exc:
                seconds = time.monotonic() - started
                self._record(task, False, attempts, None, seconds, str(exc))
                self._notify(task, False, None, seconds, {"error": str(exc)})
                return None
            seconds = time.monotonic() - started
            ok, parsed, err = _parse_and_validate(response.content, schema)
            if ok:
                self._record(task, True, attempts, response.tokens, seconds)
                self._notify(task, True, response.tokens, seconds)
                return parsed
            last_error = err
            last_raw = response.content[:RAW_LOG_CHARS]
            last_truncated = response.truncated
            info = {"error": err, "raw": last_raw, "truncated": response.truncated}
            if effective_cap is not None:
                info["max_tokens"] = effective_cap
            self._notify(task, False, response.tokens, seconds, info)
            if response.truncated and effective_cap is not None:
                # JSON cortado no limite de geração: corrigir "formato" não
                # resolve; a segunda tentativa ganha mais espaço de saída.
                effective_cap = min(effective_cap * 2, MAX_GENERATION_TOKENS)
                error_feedback = None  # o erro não é de formato, é de espaço
            else:
                error_feedback = err
        self._record(
            task, False, attempts, None, None, last_error,
            truncated=last_truncated, raw=last_raw,
        )
        return None

    def _record(
        self,
        task: TaskType,
        ok: bool,
        attempts: int,
        tokens: int | None = None,
        seconds: float | None = None,
        error: str | None = None,
        truncated: bool = False,
        raw: str | None = None,
    ) -> None:
        self.records.append(
            CallRecord(
                task=task, ok=ok, attempts=attempts, tokens=tokens,
                seconds=seconds, error=error, truncated=truncated, raw=raw,
            )
        )

    def _notify(
        self,
        task: TaskType,
        ok: bool,
        tokens: int | None,
        seconds: float | None,
        info: dict | None = None,
    ) -> None:
        if self.on_call is not None:
            self.on_call(task, ok, tokens, seconds, info)


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
