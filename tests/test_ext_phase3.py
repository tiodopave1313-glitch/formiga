"""Testes de aceitação da Fase 3 — compensações de 8B na extensibilidade
(PRD §20.1 Fase 3).

Aceites cobertos:
- Janela excedida eviciona e mantém a última pergunta (âncora).
- Schema acima do teto falha no startup citando a extensão.
- Ferramenta lazy carregável e expira.
- Perfil selecionado pelo nome aparece na barra de status da TUI.
"""

from __future__ import annotations

from formiga.agent.extensions.budget import (
    ContextBudget,
    evict_pairs,
    schema_tokens,
)
from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.profiles import BUILTIN_PROFILES, select_profile
from formiga.agent.session import Session
from formiga.agent.tools.base import ToolResult
from formiga.config import Config


class BigSchemaTool:
    """Ferramenta com schema grande para testar orçamento de schemas."""

    name = "big_schema_tool"
    description = "Ferramenta com schema muito grande."
    parameters = {
        "type": "object",
        "properties": {
            f"campo_{i}": {"type": "string", "description": "x" * 200}
            for i in range(50)
        },
    }

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self):
        return ToolResult(ok=True, text="ok")


class LazyTool:
    """Ferramenta lazy para testar activate_tool."""

    name = "lazy_tool"
    description = "Ferramenta latente."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, registry):
        self._registry = registry

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self):
        return ToolResult(ok=True, text="lazy executado")


def _setup_lazy_in_registry(registry: ExtensionRegistry):
    """Registra uma ferramenta lazy e a meta-ferramenta activate_tool."""
    registry.register_tool(LazyTool(registry), lazy=True)
    from formiga.ext.core import ActivateTool

    registry.register_tool(
        ActivateTool(registry), extension="builtin", source="builtin"
    )


def test_janela_excedida_eviciona_mantem_ultima_pergunta():
    """Eviction descarta pares antigos preservando a última mensagem do usuário."""
    mensagens = [
        {"role": "system", "content": "system instruction"},
        {"role": "user", "content": "pergunta 1"},
        {"role": "assistant", "content": "resp 1", "tool_calls": []},
        {"role": "tool", "tool_call_id": "c1", "content": "resultado 1"},
        {"role": "user", "content": "pergunta 2"},  # âncora — deve ser mantida
        {"role": "assistant", "content": "resp 2", "tool_calls": []},
        {"role": "tool", "tool_call_id": "c2", "content": "resultado 2"},
    ]

    orcamento = ContextBudget(max_context_tokens=100)  # janela muito pequena
    resultado = evict_pairs(mensagens, orcamento.max_context_tokens)

    # Última mensagem do usuário preservada
    textos_usuario = [m for m in resultado if m.get("role") == "user"]
    assert len(textos_usuario) >= 1
    assert textos_usuario[-1]["content"] == "pergunta 2"
    # System preservada
    assert resultado[0]["role"] == "system"
    # Não é vazia
    assert len(resultado) >= 3


def test_schema_acima_do_teto_falha_startup_citando_extensao(tmp_path):
    """check_schema_budget lança ConfigError citando a extensão responsável."""

    cfg = Config(agent_workdir=str(tmp_path), tool_schema_tokens=100)
    registry = ExtensionRegistry()
    session = Session(tmp_path / "sessoes")
    discover_extensions(cfg, session, registry)

    # Registra uma ferramenta com schema grande
    registry.register_tool(
        BigSchemaTool(),
        extension="big_ext",
        source="test",
    )

    total = sum(
        schema_tokens(reg.tool.schema())
        for reg in registry.registrations.values()
        if reg.state == "ativa"
    )
    # O schema de BigSchemaTool é muito grande para o teto de 100 tokens
    assert total > 100

    try:
        from formiga.agent.extensions.budget import check_schema_budget

        check_schema_budget(total, cfg.tool_schema_tokens, offender="big_ext")
        raise AssertionError("deveria ter lançado ConfigError")
    except Exception as exc:
        assert "big_ext" in str(exc), f"extensão não citada: {exc}"


def test_ferramenta_lazy_ativa_e_expira(tmp_path):
    """Ferramenta lazy começa fora dos schemas, activate_tool ativa, TTL expira."""
    cfg = Config(agent_workdir=str(tmp_path), extensions_enabled=("core",))
    registry = ExtensionRegistry()
    session = Session(tmp_path / "sessoes")
    discover_extensions(cfg, session, registry)

    # Registra uma ferramenta lazy
    lazy = LazyTool(registry)
    registry.register_tool(lazy, lazy=True, extension="test", source="test")

    # Lazy não aparece nos schemas inicialmente
    schema_names = [s["function"]["name"] for s in registry.schemas]
    assert "lazy_tool" not in schema_names

    # Ativa via activate_tool
    ok = registry.activate_lazy_tool("lazy_tool", registry.current_turn, ttl=2)
    assert ok
    schema_names = [s["function"]["name"] for s in registry.schemas]
    assert "lazy_tool" in schema_names

    # Usar a ferramenta renova o TTL
    resultado = lazy.execute()
    assert resultado.ok

    # TTL de 2 turnos expira após current_turn alcançar expires_at
    expirados = registry.expire_lazy_tools(registry.current_turn + 2)
    assert "lazy_tool" in expirados

    # Depois de expirar, volta a não aparecer nos schemas
    schema_names = [s["function"]["name"] for s in registry.schemas]
    assert "lazy_tool" not in schema_names


def test_perfil_builtin_gemma4():
    """select_profile encontra gemma4-e4b por substring do nome do modelo."""
    perfil = select_profile("gemma4:e4b", model_hint=None)
    assert perfil is not None
    assert perfil.name == "gemma4-e4b"
    assert perfil.thinking is False
    assert perfil.context_tokens == 32768


def test_perfil_builtin_nemotron():
    """select_profile encontra nemotron-3.5-bolt-e4b por substring."""
    perfil = select_profile("nemotron-3.5-bolt-e4b", model_hint=None)
    assert perfil is not None
    assert perfil.name == "nemotron-3.5-bolt-e4b"
    assert perfil.thinking is True


def test_select_profile_por_model_hint():
    """model_hint sobrepõe a detecção por substring do nome do modelo."""
    perfil = select_profile("qualquer-modelo", model_hint="gemma4-e4b")
    assert perfil is not None
    assert perfil.name == "gemma4-e4b"


def test_select_profile_sem_match_retorna_none():
    """Sem match, devolve None."""
    perfil = select_profile("modelo-desconhecido-xyz", model_hint=None)
    assert perfil is None


def test_builtin_profiles_estao_disponiveis():
    """BUILTIN_PROFILES contém os dois perfis do PRD."""
    assert "gemma4-e4b" in BUILTIN_PROFILES
    assert "nemotron-3.5-bolt-e4b" in BUILTIN_PROFILES


def test_cli_tui_status_exibe_perfil(tmp_path, monkeypatch):
    """Perfil selecionado pelo nome está disponível para a barra de status."""
    from formiga.agent.tui.controller import AgentController

    cfg = Config(
        agent_workdir=str(tmp_path),
        model="gemma4:e4b",
        profile_model_hint="gemma4-e4b",
    )
    session = Session(tmp_path / "sessoes")

    from formiga.agent import factory

    class FakeChat:
        pass

    monkeypatch.setattr(factory, "build_chat_client", lambda config: FakeChat())

    loop = factory.build_agent(cfg, session)

    # O perfil gemma4-e4b deve ter sido selecionado e aplicado
    assert cfg.active_profile == "gemma4-e4b"
    assert cfg.llm_thinking is False  # perfil gemma4 desliga thinking

    # O controller expõe o config para a TUI ler active_profile no status
    controller = AgentController(cfg, session, loop=loop)
    assert controller.config.active_profile == "gemma4-e4b"
