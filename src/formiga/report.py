"""Geração do relatório Markdown (RF-09).

O relatório é montado a partir de afirmações e evidências registradas, nunca
diretamente de snippets. Referências [S1], [S2]... correspondem a fontes
registradas no estado.
"""

from __future__ import annotations

from formiga.models import Claim, QuestionStatus, ResearchState


def source_refs(state: ResearchState) -> dict[str, str]:
    """Mapeia cada fonte registrada para sua referência [S1], [S2]..."""
    return {s.id: f"[S{i}]" for i, s in enumerate(state.sources, start=1)}


def _claims_for_report(state: ResearchState) -> list[Claim]:
    """Afirmações permitidas: suportadas direta ou parcialmente, com ressalva."""
    allowed = []
    for c in state.claims:
        if not c.supported:
            continue
        label = c.verification.label if c.verification else None
        if label is None or label.value in ("DIRECT_SUPPORT", "PARTIAL_SUPPORT"):
            allowed.append(c)
    return allowed


def render_report(
    state: ResearchState,
    answer_markdown: str | None,
) -> str:
    refs = source_refs(state)
    lines: list[str] = []

    lines.append(f"# Pesquisa: {state.contract.question}")
    lines.append("")
    lines.append("## Resposta")
    lines.append("")
    lines.append(answer_markdown.strip() if answer_markdown and answer_markdown.strip() else
                 "Não há evidência suficiente para uma resposta apoiada nesta execução.")
    lines.append("")

    lines.append("## Evidências e análise")
    lines.append("")
    allowed = _claims_for_report(state)
    if allowed:
        for c in allowed:
            marker = {
                "direct": "Afirmado nas fontes",
                "inference": "Inferência",
                "recommendation": "Recomendação",
            }[c.type.value]
            refs_inline = ", ".join(refs.get(eid, "") for eid in c.evidence_ids)
            source_ids = sorted(
                {state.evidence_by_id(eid).source_id for eid in c.evidence_ids if eid in
                 {e.id for e in state.evidence}}
            )
            source_refs_inline = ", ".join(refs.get(sid, "") for sid in source_ids)
            caveat = f" *({c.scope_or_caveat})*" if c.scope_or_caveat else ""
            lines.append(f"- **{marker}**{caveat}: {c.text} ({source_refs_inline})")
    else:
        lines.append("Nenhuma afirmação com suporte suficiente foi registrada.")
    lines.append("")

    lines.append("## Conflitos e limitações")
    lines.append("")
    limitations: list[str] = []
    contradicted = [c for c in state.claims if c.verification and
                    c.verification.label.value == "CONTRADICTED"]
    for c in contradicted:
        source_ids = sorted(
            {state.evidence_by_id(eid).source_id for eid in c.evidence_ids}
        )
        refs_inline = ", ".join(refs.get(sid, "") for sid in source_ids)
        caveat = f" ({c.verification.caveat})" if c.verification.caveat else ""
        limitations.append(
            f"- Posição divergente (contradita pelas evidências {refs_inline}){caveat}: {c.text}"
        )
    unresolved = [
        q for q in state.questions
        if q.status in (QuestionStatus.BLOCKED, QuestionStatus.EXHAUSTED)
        or (q.limitation and q.status not in (QuestionStatus.SUPPORTED,))
    ]
    for q in unresolved:
        limitations.append(
            f"- Questão {q.id} ({q.status.value}): "
            f"{q.limitation or 'sem resolução nesta execução.'}"
        )
    conflicted = [q for q in state.questions if q.status == QuestionStatus.CONFLICTED]
    for q in conflicted:
        limitations.append(
            f"- Conflito não resolvido na questão {q.id}: fontes divergem; ver Evidências."
        )
    for failure in state.operational_failures:
        limitations.append(f"- {failure}")
    for assumption in state.contract.assumptions:
        limitations.append(f"- Premissa adotada: {assumption}")
    lines.extend(limitations or ["Nenhuma limitação material registrada."])
    lines.append("")

    lines.append("## Fontes")
    lines.append("")
    if state.sources:
        for s in state.sources:
            i = list(state.sources).index(s) + 1
            title = s.title or "(sem título)"
            accessed = s.accessed_at[:10]
            lines.append(f"- [S{i}] {title}. {s.requested_url}. Acessado em {accessed}.")
    else:
        lines.append("Nenhuma fonte acessada.")
    lines.append("")

    lines.append("## Execução")
    lines.append("")
    lines.append(f"- Status: {state.status}")
    lines.append(f"- Motivo de encerramento: {state.stop_reason or '—'}")
    b = state.budget
    lines.append(f"- Buscas: {b.get('searches', 0)} de {b.get('max_searches', '?')}")
    lines.append(f"- Páginas lidas: {b.get('pages_fetched', 0)} de {b.get('max_pages', '?')}")
    llm_total = b.get("llm_investigation_calls", 0) + b.get("llm_reserved_calls", 0)
    lines.append(f"- Chamadas ao modelo: {llm_total} de {b.get('max_llm_calls', '?')}")
    lines.append("")
    return "\n".join(lines)
