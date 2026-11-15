"""Verificação de afirmações e proveniência (RF-06).

Camada determinística: IDs existem, o trecho literal aparece no texto
armazenado (após normalização de espaços), a evidência está ligada à fonte
correta e o localizador é válido. Correspondência literal não prova suporte
semântico — isso é papel da camada do modelo.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from formiga.extract import normalize_ws
from formiga.models import Evidence, ResearchState


class VerificationProblem(BaseModel):
    claim_index: int
    reason: str


def page_file(output_dir: Path, source_id: str) -> Path:
    return output_dir / "pages" / f"{source_id}.txt"


def save_page_text(output_dir: Path, source_id: str, text: str) -> None:
    path = page_file(output_dir, source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_page_text(output_dir: Path, source_id: str) -> str | None:
    path = page_file(output_dir, source_id)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def verify_quote_literal(
    state: ResearchState, output_dir: Path, evidence: Evidence
) -> str | None:
    """Verifica a camada determinística de uma evidência.

    Devolve None se tudo ok, ou uma descrição do problema.
    """
    try:
        source = state.source(evidence.source_id)
    except KeyError:
        return f"Evidência {evidence.id} aponta para fonte inexistente {evidence.source_id}."
    if source.extraction_status != "SUCCESS":
        return f"Fonte {source.id} não tem extração bem-sucedida."
    text = load_page_text(output_dir, evidence.source_id)
    if text is None:
        return f"Texto da fonte {source.id} não está armazenado."
    hay = normalize_ws(text)
    needle = normalize_ws(evidence.quote)
    start = hay.find(needle)
    if start == -1:
        return f"Trecho literal não aparece no texto da fonte {source.id}."
    end = start + len(needle)
    if not (evidence.locator.char_start <= start and end <= evidence.locator.char_end):
        return f"Localizador da evidência {evidence.id} é inválido."
    return None


def claim_evidence_ids_valid(state: ResearchState, claim_evidence_ids: list[str]) -> str | None:
    for eid in claim_evidence_ids:
        try:
            evidence = state.evidence_by_id(eid)
        except KeyError:
            return f"Evidência inexistente: {eid}"
        try:
            state.source(evidence.source_id)
        except KeyError:
            return f"Evidência {eid} aponta para fonte inexistente."
    return None
