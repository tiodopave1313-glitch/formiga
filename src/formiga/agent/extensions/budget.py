"""Engine de orçamento de contexto e schemas (seção 9 do PRD v2).

Fornece contagem de tokens aproximada (chars/4), validação fail-fast de
orçamento de schemas no startup (nomeando a extensão responsável), teto de
seções de extensão no prompt (400 tokens cada) e uma função pura de eviction
para que o loop decida o que descartar quando a janela é excedida.

Nenhuma política de loop é aplicada aqui — somente cálculos e validações
puramente funcionais.
"""

from __future__ import annotations

from formiga.config import ConfigError


def estimate_tokens(text: str) -> int:
    """Conta tokens aproximados: 4 chars = 1 token.

    Útil quando o backend não informa `usage` real. Nunca inventa contagem
    quando o backend já informa; aqui serve só como estimativa conservadora.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def schema_tokens(schema: dict) -> int:
    """Estima o custo em tokens de um schema JSON Schema de tool.

    Serializa o schema e conta chars/4. É uma superestimativa intencional:
    schemas repetidos em cada turno consomem janela mesmo que o modelo não
    os leia por inteiro.
    """
    import json

    return estimate_tokens(json.dumps(schema, ensure_ascii=False, sort_keys=True))


def check_schema_budget(
    total_tokens: int, limit: int, offender: str | None = None
) -> None:
    """Lança `ConfigError` quando o total de schemas excede o orçamento.

    Nunca "estoura e segue": degradar o prompt silenciosamente seria o oposto
    da filosofia do projeto (seção 9.7 do PRD). A mensagem cita a extensão
    responsável quando conhecida, sugerindo `lazy = true` ou desativá-la.
    """
    if total_tokens <= limit:
        return
    if offender is None:
        sugestao = (
            "Considere marcar a extensão como `lazy = true` ou desativá-la em "
            "`[extensions].enabled`."
        )
    else:
        sugestao = (
            f"Extensão responsável: `{offender}`. Considere marcá-la como "
            "`lazy = true` ou removê-la de `[extensions].enabled`."
        )
    raise ConfigError(
        f"Orçamento de schemas de ferramentas excedido: {total_tokens} tokens "
        f"(limite {limit}). {sugestao}"
    )


def check_section_budget(section_text: str, limit: int = 400) -> None:
    """Lança `ValueError` quando uma seção de extensão no prompt excede o teto.

    Seções contribuídas por extensões via `before_agent_start` não podem
    inundar o prompt de um 8B (seção 9.1 da tabela de orçamento).
    """
    used = estimate_tokens(section_text)
    if used > limit:
        raise ValueError(
            f"Seção de extensão excede o teto de {limit} tokens "
            f"(usou {used})."
        )


def evict_pairs(
    messages: list[dict],
    max_context_tokens: int,
    reserve_ratio: float = 0.10,
    anchor_last_user: bool = True,
) -> list[dict]:
    """Função pura: descarta pares antigos para caber na janela útil.

    Remove pares consecutivos de `assistant` (com `tool_calls`) + `tool`
    (resultado) começando pelos mais antigos, preservando:
    - a mensagem de sistema (índice 0);
    - a última mensagem do usuário (âncora de objetivo, se `anchor_last_user`);
    - a resposta corrente do assistente (última mensagem, se for assistant).

    Devolve uma **nova lista**; nunca muta a entrada. Não garante o limite
    exato (contagem aproximada) — o loop chama antes de cada chamada LLM e
    para quando couber.

    `reserve_ratio` é a fração da janela nunca alocada (reserva operacional
    ≥ 10%, seção 9.1).
    """
    if not messages:
        return list(messages)

    janela_util = int(max_context_tokens * (1.0 - reserve_ratio))
    if janela_util <= 0:
        janela_util = max_context_tokens

    trabalho = list(messages)

    def custo(mensagens: list[dict]) -> int:
        total = 0
        for m in mensagens:
            total += estimate_tokens(m.get("content", "") or "")
            for tc in m.get("tool_calls", []) or []:
                total += estimate_tokens(
                    tc.get("function", {}).get("arguments", "") or ""
                )
        return total

    while len(trabalho) > 1 and custo(trabalho) > janela_util:
        # Encontra o par mais antigo: assistant(tool_calls) seguido de tool.
        par_mais_antigo: int | None = None
        for i in range(len(trabalho) - 1):
            atual = trabalho[i]
            seguinte = trabalho[i + 1]
            if (
                atual.get("role") == "assistant"
                and atual.get("tool_calls")
                and seguinte.get("role") == "tool"
            ):
                # Não descarte o par se envolver o usuário-âncora ou a
                # resposta corrente.
                if anchor_last_user and i + 1 == len(trabalho) - 1:
                    continue
                if i == 0:
                    continue  # nunca descarte a system
                par_mais_antigo = i
                break

        if par_mais_antigo is None:
            break  # não há mais pares descartáveis

        del trabalho[par_mais_antigo : par_mais_antigo + 2]

    return trabalho


class ContextBudget:
    """Orçamento de janela de contexto para uma sessão.

    Calcula a janela útil (reserva descontada) e expõe helpers para o loop
    decidir eviction. Não muta mensagens — só calcula.
    """

    def __init__(
        self,
        max_context_tokens: int,
        reserve_ratio: float = 0.10,
    ) -> None:
        if max_context_tokens <= 0:
            raise ValueError("max_context_tokens deve ser positivo.")
        if not 0 <= reserve_ratio < 1:
            raise ValueError("reserve_ratio deve estar em [0, 1).")
        self.max_context_tokens = max_context_tokens
        self.reserve_ratio = reserve_ratio
        self.janela_util = int(max_context_tokens * (1.0 - reserve_ratio)) or max_context_tokens

    def coube(self, mensagens: list[dict]) -> bool:
        """True se as mensagens cabem na janela útil (estimativa)."""
        return custo_mensagens(mensagens) <= self.janela_util

    def custo(self, mensagens: list[dict]) -> int:
        return custo_mensagens(mensagens)


def custo_mensagens(mensagens: list[dict]) -> int:
    """Custo aproximado (chars/4) de uma lista de mensagens."""
    total = 0
    for m in mensagens:
        total += estimate_tokens(m.get("content", "") or "")
        for tc in m.get("tool_calls", []) or []:
            total += estimate_tokens(
                tc.get("function", {}).get("arguments", "") or ""
            )
    return total


def reinject_anchor(
    messages: list[dict], anchor_content: str
) -> tuple[list[dict], bool]:
    """Re-injeta a última mensagem do usuário (âncora de objetivo).

    O hook `context` pode ter descartado a pergunta do usuário corrente ao
    windowar o histórico. A seção 9.1 do PRD exige que a âncora seja
    preservada: se ela não estiver mais presente, re-inseri-la após a system
    (índice 0) para que o modelo nunca perca o objetivo original.

    Devolve `(nova_lista, re_injetou)` — `re_injetou` indica se houve
    modificação, útil para o loop contar no evento `budget`.
    """
    if not messages:
        return list(messages), False

    ja_tem_usuario = any(m.get("role") == "user" for m in messages)
    if ja_tem_usuario:
        return list(messages), False

    trabalho = [{"role": "system", "content": messages[0].get("content", "")}]
    trabalho.append({"role": "user", "content": anchor_content})
    trabalho.extend(messages[1:])
    return trabalho, True
