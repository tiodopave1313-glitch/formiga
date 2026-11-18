"""Perfis de modelo (seção 9.6 do PRD v2).

Perfis builtin (`gemma4-e2b`, `gemma4-e4b`, `nemotron-3.5-bolt-e4b`) fornecem defaults
conservadores para janela de contexto, thinking, temperatura, etc. Perfis
do usuário em `[profiles.*]` mesclam sobre os builtin. A seleção é por
substring do nome do modelo ou por `[profile] model_hint`. CLI/env/arquivo
sempre sobrepõem o perfil (valores apenas preenchem campos ainda em default).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Profile:
    """Perfil de modelo com limites e comportamento de geração."""

    name: str
    context_tokens: int = 32768
    thinking: bool | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens_per_turn: int = 4096
    tool_schema_tokens: int = 1600


# Perfis builtin (seção 9.6 do PRD). Valores None = não definido pelo perfil
# (mantém o default do Formiga ou o que estiver em config).
BUILTIN_PROFILES: dict[str, Profile] = {
    "gemma4-e2b": Profile(
        name="gemma4-e2b",
        context_tokens=32768,
        thinking=True,  # GGUF "IT ... Thinking": o raciocínio fica ligado
        temperature=1.0,
        top_p=0.95,
        max_tokens_per_turn=8192,  # thinking come orçamento de geração
        tool_schema_tokens=1600,
    ),
    "gemma4-e4b": Profile(
        name="gemma4-e4b",
        context_tokens=32768,
        thinking=False,
        temperature=1.0,
        top_p=0.95,
        max_tokens_per_turn=4096,
        tool_schema_tokens=1600,
    ),
    "nemotron-3.5-bolt-e4b": Profile(
        name="nemotron-3.5-bolt-e4b",
        context_tokens=32768,
        thinking=True,
        temperature=1.0,
        top_p=0.95,
        max_tokens_per_turn=8192,
        tool_schema_tokens=1600,
    ),
}


def select_profile(
    model: str,
    model_hint: str | None = None,
    user_profiles: dict[str, Profile] | None = None,
) -> Profile | None:
    """Seleciona um perfil pelo nome do modelo ou `model_hint`.

    Busca por substring (case-insensitive, ignorando separadores) do modelo
    nos nomes dos perfis. Devolve None quando não há perfil aplicável.
    """
    model_norm = _norm(model)
    hint = (model_hint or "").lower()

    # Candidatos: perfis builtin + de usuário
    candidatos: dict[str, Profile] = {}
    candidatos.update(BUILTIN_PROFILES)
    if user_profiles:
        candidatos.update(user_profiles)

    # 1. model_hint exato (normalizado)
    if hint and _norm(hint) in {_norm(p.name) for p in candidatos.values()}:
        for perfil in candidatos.values():
            if _norm(perfil.name) == _norm(hint):
                return perfil

    # 2. substring normalizada do nome do modelo nos nomes de perfil
    for perfil in candidatos.values():
        if _norm(perfil.name) in model_norm:
            return perfil

    return None


def _norm(text: str) -> str:
    """Normaliza para comparação: minúsculo, alfanumérico apenas."""
    return "".join(c for c in text.lower() if c.isalnum())


def apply_profile(config, profile: Profile) -> None:
    """Aplica valores do perfil apenas em campos ainda em default.

    Não sobrepõe valores definidos explicitamente via arquivo, ambiente
    ou CLI. Atribui diretamente nos atributos do config (mutação).
    """
    # Defaults conhecidos do Formiga para comparação
    defaults = {
        "max_context_tokens": 32768,
        "tool_schema_tokens": 1600,
        "llm_thinking": True,
        "llm_temperature": 1.0,
    }

    # Mapeia campos do perfil para atributos do config
    mapeamento = {
        "context_tokens": ("max_context_tokens", defaults["max_context_tokens"]),
        "tool_schema_tokens": ("tool_schema_tokens", defaults["tool_schema_tokens"]),
        "thinking": ("llm_thinking", defaults["llm_thinking"]),
        "temperature": ("llm_temperature", defaults["llm_temperature"]),
    }

    for campo, (attr, default_val) in mapeamento.items():
        valor_perfil = getattr(profile, campo)
        if valor_perfil is None:
            continue
        valor_atual = getattr(config, attr)
        # Só aplica se o valor atual for o default do Formiga
        if valor_atual == default_val:
            setattr(config, attr, valor_perfil)

    # O cliente llamacpp lê `llamacpp_thinking`, não `llm_thinking`. Sem esse
    # espelho, um perfil "sem thinking" ainda enviaria enable_thinking=true.
    if (
        profile.thinking is not None
        and config.llamacpp_thinking == defaults["llm_thinking"]
    ):
        config.llamacpp_thinking = profile.thinking
