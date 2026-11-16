"""Schemas das propostas retornadas pelo modelo (seção 10 do PRD).

O harness valida contra estes schemas; IDs inexistentes e campos com
significado alterado são rejeitados, nunca "reparados" silenciosamente.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PlanQuestion(BaseModel):
    question: str = Field(min_length=1)
    priority: str = Field(pattern="^(high|medium|low)$")
    sufficiency: str = Field(min_length=1)


class PlanProposal(BaseModel):
    objective: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    sufficiency_criteria: list[str] = Field(default_factory=list)
    questions: list[PlanQuestion] = Field(min_length=1)


class QueryProposal(BaseModel):
    queries: list[str] = Field(min_length=1)


class ExtractQuote(BaseModel):
    source_id: str = Field(pattern="^S\\d+$")
    chunk_index: int = Field(ge=0)
    quote: str = Field(min_length=1)


class ExtractClaim(BaseModel):
    text: str = Field(min_length=1)
    type: str = Field(pattern="^(direct|inference|recommendation)$")
    quotes: list[ExtractQuote] = Field(min_length=1)
    scope_or_caveat: str | None = None


class ExtractProposal(BaseModel):
    # Obrigatória: abstinência válida é `{"claims": []}` explícito — um `{}`
    # vago não pode passar como extração.
    claims: list[ExtractClaim]


class VerifyProposal(BaseModel):
    label: str = Field(
        pattern="^(DIRECT_SUPPORT|PARTIAL_SUPPORT|CONTRADICTED|INSUFFICIENT)$"
    )
    caveat: str | None = None


class CompareProposal(BaseModel):
    resolved: bool
    explanation: str = Field(min_length=1)


class SynthesizeProposal(BaseModel):
    answer_markdown: str = Field(min_length=1)


class AuditDecision(BaseModel):
    claim_id: str = Field(pattern="^C\\d+$")
    decision: str = Field(pattern="^(keep|qualify|remove)$")
    note: str | None = None


class AuditProposal(BaseModel):
    decisions: list[AuditDecision] = Field(default_factory=list)

    @field_validator("decisions")
    @classmethod
    def _unique_ids(cls, value: list[AuditDecision]) -> list[AuditDecision]:
        ids = [d.claim_id for d in value]
        if len(ids) != len(set(ids)):
            raise ValueError("decisions repetidas para o mesmo claim_id")
        return value
