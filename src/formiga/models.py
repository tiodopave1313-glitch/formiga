"""Schemas de estado da pesquisa: questões, fontes, evidências e afirmações.

Estes schemas são a fonte de verdade do `state.json`. O harness valida
toda proposta do modelo contra eles; IDs inexistentes são rejeitados.
"""

from __future__ import annotations

import enum
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

_ID_RE = re.compile(r"^[QSCE]\d+$")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_id(value: str) -> str:
    if not _ID_RE.match(value):
        raise ValueError(f"ID inválido: {value!r} (esperado: prefixo + número, ex. 'S1').")
    return value


class Priority(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QuestionStatus(enum.StrEnum):
    OPEN = "OPEN"
    SEARCHING = "SEARCHING"
    PARTIAL = "PARTIAL"
    SUPPORTED = "SUPPORTED"
    CONFLICTED = "CONFLICTED"
    BLOCKED = "BLOCKED"
    EXHAUSTED = "EXHAUSTED"


class ClaimType(enum.StrEnum):
    DIRECT = "direct"
    INFERENCE = "inference"
    RECOMMENDATION = "recommendation"


class VerificationLabel(enum.StrEnum):
    DIRECT_SUPPORT = "DIRECT_SUPPORT"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT = "INSUFFICIENT"


class ExtractionStatus(enum.StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INSUFFICIENT_TEXT = "INSUFFICIENT_TEXT"


class Locator(BaseModel):
    """Localizador do trecho dentro do texto extraído da fonte."""

    chunk_index: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)


class ResearchContract(BaseModel):
    """Contrato persistido da pesquisa (RF-01)."""

    question: str
    objective: str
    assumptions: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    sufficiency_criteria: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class Question(BaseModel):
    """Questão pesquisável (RF-02)."""

    id: str
    question: str
    priority: Priority
    sufficiency: str
    status: QuestionStatus = QuestionStatus.OPEN
    attempts: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    limitation: str | None = None
    depth: int = Field(default=1, ge=1)

    @field_validator("id")
    @classmethod
    def _id_ok(cls, value: str) -> str:
        return valid_id(value)


class Source(BaseModel):
    """Fonte registrada (RF-05). Datas desconhecidas permanecem desconhecidas."""

    id: str
    requested_url: str
    final_url: str | None = None
    title: str | None = None
    accessed_at: str = Field(default_factory=utc_now)
    published_at: str | None = None
    text_hash: str | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.PENDING
    failure_reason: str | None = None

    @field_validator("id")
    @classmethod
    def _id_ok(cls, value: str) -> str:
        return valid_id(value)


class Evidence(BaseModel):
    """Evidência: trecho literal com proveniência (RF-05)."""

    id: str
    source_id: str
    quote: str
    locator: Locator
    content_hash: str
    question_ids: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_ok(cls, value: str) -> str:
        return valid_id(value)

    @field_validator("quote")
    @classmethod
    def _quote_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Trecho literal vazio.")
        return value


class Verification(BaseModel):
    label: VerificationLabel
    caveat: str | None = None
    verified_at: str = Field(default_factory=utc_now)


class Claim(BaseModel):
    """Afirmação pequena vinculada a evidências (RF-06)."""

    id: str
    text: str
    type: ClaimType
    evidence_ids: list[str] = Field(min_length=1)
    scope_or_caveat: str | None = None
    verification: Verification | None = None
    question_ids: list[str] = Field(default_factory=list)
    supported: bool = True

    @field_validator("id")
    @classmethod
    def _id_ok(cls, value: str) -> str:
        return valid_id(value)


class ExecutionBudgetSnapshot(BaseModel):
    model_config = {"extra": "allow"}


class ResearchState(BaseModel):
    """Estado completo da execução, persistido em `state.json`."""

    contract: ResearchContract
    questions: list[Question] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, int] = Field(default_factory=dict)
    status: str = "parcial"
    stop_reason: str | None = None
    round_number: int = 0
    query_history: list[dict[str, str]] = Field(default_factory=list)
    operational_failures: list[str] = Field(default_factory=list)

    # --- consultas de ID -------------------------------------------------

    def question(self, qid: str) -> Question:
        for q in self.questions:
            if q.id == qid:
                return q
        raise KeyError(f"Questão inexistente: {qid}")

    def source(self, sid: str) -> Source:
        for s in self.sources:
            if s.id == sid:
                return s
        raise KeyError(f"Fonte inexistente: {sid}")

    def evidence_by_id(self, eid: str) -> Evidence:
        for e in self.evidence:
            if e.id == eid:
                return e
        raise KeyError(f"Evidência inexistente: {eid}")

    # --- numeração -------------------------------------------------------

    def next_id(self, prefix: str) -> str:
        n = 1
        existing = {q.id for q in self.questions} | {s.id for s in self.sources}
        existing |= {e.id for e in self.evidence} | {c.id for c in self.claims}
        while f"{prefix}{n}" in existing:
            n += 1
        return f"{prefix}{n}"

    def has_query(self, question_id: str, normalized_query: str) -> bool:
        return any(
            e["question_id"] == question_id and e["normalized_query"] == normalized_query
            for e in self.query_history
        )

    def record_query(self, question_id: str, raw: str, normalized: str) -> None:
        self.query_history.append(
            {"question_id": question_id, "query": raw, "normalized_query": normalized}
        )
