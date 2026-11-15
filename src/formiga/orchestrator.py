"""Orquestrador do loop de pesquisa (seção 8 do PRD).

O programa controla o fluxo; o modelo executa tarefas pequenas e delimitadas.
Toda ação verifica orçamento antes de iniciar; cada rodada concluída é salva
atomicamente; eventos operacionais vão para `events.jsonl`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from formiga import evidence as ev
from formiga import prompts
from formiga.budget import Budget
from formiga.config import Config
from formiga.extract import (
    Chunk,
    extract_main_text,
    find_quote,
    select_chunks,
    split_chunks,
    text_hash,
)
from formiga.fetch import FetchedPage, FetchError
from formiga.llm import LLMResponse, StructuredCaller, TaskType
from formiga.models import (
    Claim,
    ClaimType,
    Evidence,
    ExtractionStatus,
    Locator,
    Priority,
    Question,
    QuestionStatus,
    ResearchContract,
    ResearchState,
    Source,
    Verification,
    VerificationLabel,
)
from formiga.report import render_report, source_refs
from formiga.schemas import (
    AuditProposal,
    CompareProposal,
    ExtractProposal,
    PlanProposal,
    QueryProposal,
    SynthesizeProposal,
    VerifyProposal,
)
from formiga.search import SearchProvider, dedupe_results, normalize_query, normalize_url
from formiga.storage import append_event, prepare_output_dir, save_state

MAX_RESULTS_PER_QUERY = 10
MIN_TEXT_LENGTH = 200

Status = QuestionStatus
ProgressFn = Callable[[str], None]


class LLMClientProtocol(Protocol):
    def complete(
        self, system: str, user: str, json_schema: dict | None = None
    ) -> LLMResponse: ...


def build_llm_client(
    config: Config, remaining_seconds: Callable[[], float] | None = None
) -> LLMClientProtocol:
    """Escolhe o backend de modelo conforme `config.llm_backend`."""
    if config.llm_backend == "llamacpp":
        from formiga.llamacpp import LlamaCppClient

        return LlamaCppClient(config, remaining_seconds=remaining_seconds)
    from formiga.ollama import OllamaClient

    return OllamaClient(config, remaining_seconds=remaining_seconds)


@dataclass
class ResearchResult:
    status: str
    report_path: Path
    state_path: Path


def run_research(
    config: Config,
    progress: ProgressFn | None = None,
    *,
    client: LLMClientProtocol | None = None,
    search: SearchProvider | None = None,
    fetcher: object | None = None,
) -> ResearchResult:
    if progress is None:
        progress = lambda _m: None  # noqa: E731
    output_dir = prepare_output_dir(
        config.output or Path("./formiga-out"), overwrite=config.overwrite
    )
    budget = Budget.from_config(config)
    append_event(output_dir, "run_started", {"question": config.question})
    progress(f"Saída: {output_dir}")

    if client is None:
        client = build_llm_client(config, remaining_seconds=budget.remaining_seconds)
    if search is None:
        from formiga.searxng import SearxngSearch

        search = SearxngSearch(config)
    if fetcher is None:
        from formiga.fetcher import SafeFetcher

        fetcher = SafeFetcher(config, remaining_seconds=budget.remaining_seconds)

    def on_llm_call(_task: TaskType, _ok: bool, tokens: int | None) -> None:
        # Toda tentativa, inclusive falha e correção de formato, consome orçamento.
        reserved = _task in (TaskType.SYNTHESIZE, TaskType.AUDIT)
        budget.consume_llm(reserved=reserved)
        # Tokens: registrar quando disponíveis; `unknown` quando não fornecidos.
        if tokens is not None:
            state.token_usage["known_tokens"] = (
                state.token_usage.get("known_tokens", 0) + tokens
            )
        else:
            state.token_usage["unknown_calls"] = (
                state.token_usage.get("unknown_calls", 0) + 1
            )

    caller = StructuredCaller(client, on_call=on_llm_call)
    state = ResearchState(contract=ResearchContract(question=config.question or "", objective=""))

    # --- RF-01/RF-02: contrato e planejamento -------------------------------
    _plan(caller, state, config, output_dir, progress)
    save_state(output_dir, state)
    append_event(output_dir, "planned", {"questions": len(state.questions)})

    # --- loop de investigação ------------------------------------------------
    no_progress: dict[str, int] = {}
    stop_reason: str | None = None
    try:
        while budget.can_start_round() and _next_gap(state) is not None:
            gap = _next_gap(state)
            budget.start_round()
            state.round_number = budget.rounds
            append_event(output_dir, "round_started", {"round": budget.rounds, "question": gap.id})
            progress(
                f"Rodada {budget.rounds}: questões abertas, "
                f"buscas {budget.searches}/{config.max_searches}, "
                f"páginas {budget.pages_fetched}/{config.max_pages}"
            )
            made = _investigate_gap(
                caller, state, config, budget, gap.id, search, fetcher, output_dir, progress
            )
            if not made:
                no_progress[gap.id] = no_progress.get(gap.id, 0) + 1
                if no_progress[gap.id] >= config.no_progress_rounds:
                    _mark_no_progress(gap, state)
            else:
                no_progress.pop(gap.id, None)
            save_state(output_dir, state)
            append_event(
                output_dir,
                "round_ended",
                {"round": budget.rounds, "question": gap.id, "progress": made},
            )
        if not budget.can_start_round():
            stop_reason = _budget_stop_reason(budget, config)
        elif _next_gap(state) is None:
            stop_reason = "Todas as questões estão resolvidas, bloqueadas ou esgotadas."
    except KeyboardInterrupt:
        state.stop_reason = "Interrompido pelo usuário; checkpoint desta rodada permanece salvo."
        save_state(output_dir, state)
        append_event(output_dir, "interrupted", {})
        raise

    # --- RF-08: síntese e auditoria com chamadas reservadas ------------------
    answer = None
    if budget.can_call_llm(reserved=True) and ev_claims_for_synthesis(state):
        answer = _synthesize_and_audit(caller, state, output_dir, progress)
        if answer is None:
            state.operational_failures.append(
                "Síntese/auditoria falhou; relatório parcial montado a partir do material válido."
            )
    if state.stop_reason is None:
        state.stop_reason = stop_reason
    _finalize_status(state, synthesis_fallback=answer is None and bool(state.claims))
    state.budget = budget.snapshot()
    save_state(output_dir, state)

    report = render_report(state, answer)
    from formiga.storage import save_report

    path = save_report(output_dir, report)
    append_event(output_dir, "run_finished", {"status": state.status})
    progress(f"Status final: {state.status}")
    return ResearchResult(
        status=state.status, report_path=path, state_path=output_dir / "state.json"
    )


# --------------------------------------------------------------------------
# Planejamento


def _plan(
    caller: StructuredCaller,
    state: ResearchState,
    config: Config,
    output_dir: Path,
    progress: ProgressFn,
) -> None:
    proposal = caller.call(
        TaskType.PLAN,
        prompts.SYSTEM,
        prompts.plan_prompt(state.contract.question, []),
        PlanProposal,
    )
    if proposal is None:
        state.operational_failures.append(
            "Planejamento falhou (schema inválido após correção); pesquisa bloqueada."
        )
        state.stop_reason = "Falha no planejamento."
        return
    contract = ResearchContract(
        question=state.contract.question,
        objective=proposal.objective,
        assumptions=proposal.assumptions,
        restrictions=[],
        sufficiency_criteria=proposal.sufficiency_criteria,
    )
    state.contract = contract
    for pq in proposal.questions[: config.max_initial_questions]:
        qid = state.next_id("Q")
        state.questions.append(
            Question(
                id=qid,
                question=pq.question,
                priority=Priority(pq.priority),
                sufficiency=pq.sufficiency,
                depth=1,
            )
        )
    progress(f"Planejamento: {len(state.questions)} questões iniciais.")


# --------------------------------------------------------------------------
# Seleção de lacuna e atualização de estado


_TERMINAL = {Status.SUPPORTED, Status.BLOCKED, Status.EXHAUSTED}


def _next_gap(state: ResearchState) -> Question | None:
    """Política determinística: prioridade → menos tentativas → ordem de criação."""
    candidates = [q for q in state.questions if q.status not in _TERMINAL]
    if not candidates:
        return None
    order = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
    candidates.sort(key=lambda q: (order[q.priority], q.attempts, q.id))
    return candidates[0]


def _mark_no_progress(question: Question, state: ResearchState) -> None:
    """Após rodadas sem progresso: EXHAUSTED (buscas repetidas) ou BLOCKED."""
    had_failures = any("Busca" in f or "busca" in f for f in state.operational_failures)
    if had_failures:
        question.status = Status.BLOCKED
        question.limitation = question.limitation or "Falhas operacionais impediram novas buscas."
    else:
        question.status = Status.EXHAUSTED
        question.limitation = (
            question.limitation or "Buscas repetidas não produziram novas evidências relevantes."
        )


def _compare_conflict(
    caller: StructuredCaller,
    state: ResearchState,
    budget: Budget,
    question: Question,
    output_dir: Path,
) -> None:
    """RF-07: compara afirmações divergentes; nunca escolhe vencedora por fluência."""
    if not budget.can_call_llm():
        question.limitation = "Conflito não comparado por falta de orçamento."
        return
    divergent = [
        c for c in _claims_of_question(state, question.id)
        if c.verification
        and c.verification.label in (VerificationLabel.DIRECT_SUPPORT,
                                     VerificationLabel.CONTRADICTED)
    ]
    claim_rows = [
        {"id": c.id, "text": c.text, "label": c.verification.label.value} for c in divergent
    ]
    evidence_rows = []
    for c in divergent:
        for eid in c.evidence_ids:
            e = state.evidence_by_id(eid)
            evidence_rows.append({"id": e.id, "source_id": e.source_id, "quote": e.quote})
    proposal = caller.call(
        TaskType.COMPARE,
        prompts.SYSTEM,
        prompts.compare_prompt(claim_rows, evidence_rows),
        CompareProposal,
    )
    if proposal is None:
        question.limitation = "Conflito não resolvido (comparação falhou)."
        return
    if proposal.resolved:
        question.limitation = f"Conflito resolvido por escopo: {proposal.explanation}"
    else:
        question.limitation = f"Conflito não resolvido: {proposal.explanation}"
    append_event(
        output_dir,
        "conflict_compared",
        {"question": question.id, "resolved": proposal.resolved},
    )


def _claims_of_question(state: ResearchState, qid: str) -> list[Claim]:
    return [c for c in state.claims if qid in c.question_ids]


def _update_question_status(
    caller: StructuredCaller,
    state: ResearchState,
    budget: Budget,
    qid: str,
    output_dir: Path,
) -> bool:
    """Atualiza o estado da questão a partir das afirmações verificadas.

    Devolve True quando houve mudança justificada de estado (conta como progresso).
    """
    question = state.question(qid)
    claims = _claims_of_question(state, qid)
    supported = [c for c in claims if c.supported and c.verification]
    direct = [c for c in supported if c.verification.label == VerificationLabel.DIRECT_SUPPORT]
    contradicted = [c for c in claims if c.verification and
                    c.verification.label == VerificationLabel.CONTRADICTED]
    partial = [c for c in supported if c.verification.label == VerificationLabel.PARTIAL_SUPPORT]

    if direct and contradicted:
        new_status = Status.CONFLICTED
    elif direct:
        new_status = Status.SUPPORTED
    elif partial:
        new_status = Status.PARTIAL
    elif contradicted:
        new_status = Status.CONFLICTED
    else:
        return False
    if new_status != question.status:
        question.status = new_status
        append_event(output_dir, "question_status", {"question": qid, "status": new_status.value})
        if new_status == Status.CONFLICTED:
            _compare_conflict(caller, state, budget, question, output_dir)
        return True
    return False


# --------------------------------------------------------------------------
# Uma rodada de investigação sobre uma questão


def _investigate_gap(
    caller: StructuredCaller,
    state: ResearchState,
    config: Config,
    budget: Budget,
    qid: str,
    search: SearchProvider,
    fetcher: object,
    output_dir: Path,
    progress: ProgressFn,
) -> bool:
    """Executa uma rodada para a questão. Devolve True se houve progresso."""
    question = state.question(qid)
    question.attempts += 1
    question.status = Status.SEARCHING
    progress_signals: list[str] = []

    # Consultas (até 2 por rodada; sem repetir consulta normalizada).
    queries = _generate_queries(caller, state, budget, question)
    if not queries:
        return False
    for raw_query in queries:
        if not budget.can_search():
            state.operational_failures.append(
                f"Busca por '{raw_query}' não iniciada: orçamento de buscas esgotado."
            )
            break
        budget.consume_search()
        state.record_query(qid, raw_query, normalize_query(raw_query))
        append_event(output_dir, "search", {"question": qid, "query": raw_query})
        progress(f"Busca: {raw_query}")
        try:
            results = search.search(raw_query, MAX_RESULTS_PER_QUERY)
        except Exception as exc:  # SearchError e falhas de rede — sempre registradas.
            state.operational_failures.append(f"Busca '{raw_query}' falhou: {exc}")
            append_event(output_dir, "search_failed", {"query": raw_query, "error": str(exc)})
            continue
        results = _unseen_results(state, dedupe_results(results))
        if not results:
            continue
        for result in results:
            if not budget.can_fetch_page():
                break
            _process_page(
                caller, state, config, budget, question, result, fetcher, output_dir, progress,
                progress_signals,
            )
        if budget.pages_fetched >= config.max_pages:
            break
    changed = _update_question_status(caller, state, budget, qid, output_dir)
    if progress_signals:
        append_event(
            output_dir, "evidence_added", {"question": qid, "count": len(progress_signals)}
        )
    return changed or bool(progress_signals)


def _generate_queries(
    caller: StructuredCaller, state: ResearchState, budget: Budget, question: Question
) -> list[str]:
    if not budget.can_call_llm():
        return []
    prior = [h["query"] for h in state.query_history if h["question_id"] == question.id]
    proposal = caller.call(
        TaskType.QUERY,
        prompts.SYSTEM,
        prompts.query_prompt(state.contract.question, question.model_dump(mode="json"), prior),
        QueryProposal,
    )
    if proposal is None:
        return []
    seen: set[str] = set()
    queries: list[str] = []
    for raw in proposal.queries[:2]:
        normalized = normalize_query(raw)
        if not normalized or normalized in seen or state.has_query(question.id, normalized):
            continue
        seen.add(normalized)
        queries.append(raw)
    return queries


def _unseen_results(state: ResearchState, results: list) -> list:
    """Filtra URLs já solicitadas ou já registradas como fonte."""
    fetched = {normalize_url(s.requested_url) for s in state.sources}
    fetched |= {normalize_url(s.final_url) for s in state.sources if s.final_url}
    return [r for r in results if normalize_url(r.url) not in fetched]


def _process_page(
    caller: StructuredCaller,
    state: ResearchState,
    config: Config,
    budget: Budget,
    question: Question,
    result,
    fetcher: object,
    output_dir: Path,
    progress: ProgressFn,
    progress_signals: list[str],
) -> None:
    budget.consume_page()
    append_event(output_dir, "page_fetch", {"url": result.url})
    try:
        page: FetchedPage = fetcher.fetch(result.url)
    except FetchError as exc:
        state.operational_failures.append(f"Página inacessível ({exc.url}): {exc.reason}")
        append_event(output_dir, "page_failed", {"url": result.url, "reason": exc.reason})
        return False

    sid = state.next_id("S")
    try:
        text, title = extract_main_text(page.content)
    except Exception:
        state.sources.append(
            Source(
                id=sid,
                requested_url=result.url,
                final_url=page.final_url,
                title=None,
                extraction_status=ExtractionStatus.FAILED,
                failure_reason="Extração de texto falhou.",
            )
        )
        state.operational_failures.append(
            f"Extração de texto falhou para {result.url}; limitação registrada."
        )
        return False
    if len(text.strip()) < MIN_TEXT_LENGTH:
        state.sources.append(
            Source(
                id=sid,
                requested_url=result.url,
                final_url=page.final_url,
                title=title,
                extraction_status=ExtractionStatus.INSUFFICIENT_TEXT,
                failure_reason="Texto extraído insuficiente.",
            )
        )
        return False

    source = Source(
        id=sid,
        requested_url=result.url,
        final_url=page.final_url,
        title=title,
        extraction_status=ExtractionStatus.SUCCESS,
        text_hash=text_hash(text),
    )
    state.sources.append(source)
    ev.save_page_text(output_dir, sid, text)
    progress(f"Página lida: {result.url} ({sid})")

    chunks = split_chunks(text)
    selected: list[Chunk] = select_chunks(chunks, question.question, config.chunks_per_call)
    if not selected:
        return False
    proposal = None
    if budget.can_call_llm():
        proposal = caller.call(
            TaskType.EXTRACT,
            prompts.SYSTEM,
            prompts.extract_prompt(
                state.contract.question,
                question.model_dump(mode="json"),
                [
                    {
                        "index": c.index,
                        "source_id": sid,
                        "text": c.text,
                    }
                    for c in selected
                ],
            ),
            ExtractProposal,
        )
    if proposal is None:
        state.operational_failures.append(
            f"Extração de afirmações falhou para {sid} (schema inválido ou orçamento)."
        )
        return
    if _register_claims(
        state, output_dir, question, sid, text, chunks, proposal, progress_signals
    ):
        _verify_claims(caller, state, budget, question, output_dir, progress, progress_signals)


def _verify_claims(
    caller: StructuredCaller,
    state: ResearchState,
    budget: Budget,
    question: Question,
    output_dir: Path,
    progress: ProgressFn,
    progress_signals: list[str],
) -> None:
    """Verificação semântica: uma afirmação por vez, em contexto isolado.

    Cada chamada consome orçamento de investigação; o rótulo é registrado
    como está — não é validação independente da verdade.
    """
    for claim in _claims_of_question(state, question.id):
        if claim.verification is not None:
            continue
        if not budget.can_call_llm():
            return
        evidence_rows = []
        for eid in claim.evidence_ids:
            e = state.evidence_by_id(eid)
            evidence_rows.append(
                {"id": e.id, "source_id": e.source_id, "quote": e.quote}
            )
        proposal = caller.call(
            TaskType.VERIFY,
            prompts.SYSTEM,
            prompts.verify_prompt(claim.model_dump(mode="json"), evidence_rows),
            VerifyProposal,
        )
        if proposal is None:
            state.operational_failures.append(
                f"Verificação semântica falhou para {claim.id}; afirmação mantida sem rótulo."
            )
            continue
        claim.verification = Verification(
            label=VerificationLabel(proposal.label), caveat=proposal.caveat
        )
        claim.supported = claim.verification.label.value in (
            "DIRECT_SUPPORT",
            "PARTIAL_SUPPORT",
        )
        progress_signals.append(claim.id)
        append_event(
            output_dir,
            "claim_verified",
            {"claim": claim.id, "label": claim.verification.label.value},
        )
        progress(f"Afirmação {claim.id}: {claim.verification.label.value}")


def _register_claims(
    state: ResearchState,
    output_dir: Path,
    question: Question,
    sid: str,
    text: str,
    chunks: list[Chunk],
    proposal,
    progress_signals: list[str],
) -> bool:
    """Valida citações literalmente, cria evidências e registra afirmações.

    Devolve True quando pelo menos uma evidência válida foi adicionada.
    """
    added = False
    chunk_by_index = {c.index: c for c in chunks}
    for claim_prop in proposal.claims:
        evidence_ids: list[str] = []
        for quote_prop in claim_prop.quotes:
            if quote_prop.source_id != sid:
                continue  # citação deve pertencer ao trecho da fonte em processamento
            chunk = chunk_by_index.get(quote_prop.chunk_index)
            if chunk is None:
                continue
            span = find_quote(text, quote_prop.quote)
            if span is None or not (chunk.char_start <= span[0] and span[1] <= chunk.char_end):
                continue  # trecho literal não aparece no texto armazenado
            eid = state.next_id("E")
            evidence = Evidence(
                id=eid,
                source_id=sid,
                quote=quote_prop.quote,
                locator=Locator(chunk_index=chunk.index, char_start=span[0], char_end=span[1]),
                content_hash=text_hash(text),
                question_ids=[question.id],
            )
            state.evidence.append(evidence)
            evidence_ids.append(eid)
            question.evidence_ids.append(eid)
            added = True
            progress_signals.append(eid)
        if not evidence_ids:
            continue  # afirmação sem evidência válida é descartada
        cid = state.next_id("C")
        state.claims.append(
            Claim(
                id=cid,
                text=claim_prop.text,
                type=ClaimType(claim_prop.type),
                evidence_ids=evidence_ids,
                scope_or_caveat=claim_prop.scope_or_caveat,
                question_ids=[question.id],
            )
        )
        append_event(
            output_dir, "claim_registered", {"claim": cid, "evidence": evidence_ids}
        )
    return added


# --------------------------------------------------------------------------
# Síntese e auditoria


def ev_claims_for_synthesis(state: ResearchState) -> list[Claim]:
    return [c for c in state.claims if c.supported and c.verification]


def _synthesize_and_audit(
    caller: StructuredCaller,
    state: ResearchState,
    output_dir: Path,
    progress: ProgressFn,
) -> str | None:
    refs = source_refs(state)
    claims = ev_claims_for_synthesis(state)
    claim_rows = []
    for c in claims:
        sids = sorted({e.source_id for e in state.evidence if e.id in c.evidence_ids})
        claim_rows.append(
            {
                "id": c.id,
                "refs": ", ".join(refs[s] for s in sids if s in refs),
                "text": c.text,
                "caveat": c.scope_or_caveat,
            }
        )
    source_rows = [
        {"id": s.id, "label": f"{s.title or '(sem título)'}. {s.requested_url}"}
        for s in state.sources
        if s.extraction_status == ExtractionStatus.SUCCESS
    ]
    synth = caller.call(
        TaskType.SYNTHESIZE,
        prompts.SYSTEM,
        prompts.synthesize_prompt(state.contract.question, claim_rows, source_rows),
        SynthesizeProposal,
    )
    if synth is None:
        return None
    answer = synth.answer_markdown

    # Validação de referências: [S<n>] deve corresponder a fonte registrada.
    import re

    valid_refs = {f"[S{i}]" for i in range(1, len(state.sources) + 1)}
    used_refs = set(re.findall(r"\[S\d+\]", answer))
    if used_refs - valid_refs:
        state.operational_failures.append(
            f"Síntese citou fontes inexistentes: {sorted(used_refs - valid_refs)}."
        )
        return None  # fallback parcial
    if not used_refs:
        state.operational_failures.append("Síntese não citou fontes; relatório parcial.")
        return None

    # Auditoria em lote pequeno: manter, qualificar ou remover.
    audit = caller.call(
        TaskType.AUDIT,
        prompts.SYSTEM,
        prompts.audit_prompt(answer, [{"id": c.id, "text": c.text} for c in claims]),
        AuditProposal,
    )
    if audit is None:
        state.operational_failures.append("Auditoria falhou; resposta mantida sem qualificação.")
        return answer
    claim_by_id = {c.id: c for c in claims}
    for decision in audit.decisions:
        claim = claim_by_id.get(decision.claim_id)
        if claim is None:
            continue  # ID inexistente é ignorado, não reparado
        if decision.decision == "remove":
            claim.supported = False
        elif decision.decision == "qualify" and decision.note:
            claim.scope_or_caveat = decision.note
    append_event(output_dir, "audit_done", {"decisions": len(audit.decisions)})
    progress("Auditoria concluída.")

    # Refaz a resposta após remoções? Não no MVP: qualificações aparecem nas
    # seções de evidências; remoções só afetam a lista de afirmações suportadas.
    return answer


# --------------------------------------------------------------------------
# Encerramento


def _budget_stop_reason(budget: Budget, config: Config) -> str:
    if budget.deadline_exceeded():
        return "Tempo total esgotado."
    if budget.rounds >= config.max_rounds:
        return "Orçamento de rodadas esgotado."
    if budget.investigation_calls_left() <= 0:
        return "Orçamento de chamadas ao modelo esgotado."
    if budget.searches >= config.max_searches:
        return "Orçamento de buscas esgotado."
    return "Orçamento de investigação esgotado."


def _finalize_status(state: ResearchState, synthesis_fallback: bool = False) -> None:
    central = [q for q in state.questions if q.priority == Priority.HIGH]
    supported_central = [q for q in central if q.status == Status.SUPPORTED]

    if not state.questions:
        state.status = "bloqueada"
        return
    if not state.evidence:
        state.status = "bloqueada"
        state.stop_reason = state.stop_reason or "Nenhuma evidência válida foi obtida."
        return
    if synthesis_fallback:
        state.status = "parcial"
        return
    if central and len(supported_central) == len(central):
        state.status = "suficiente"
    else:
        state.status = "parcial"
