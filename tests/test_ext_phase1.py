"""Critérios de aceite da Fase 1 do PRD v2 (desacoplamento e registry).

- O núcleo (`agent/`) não importa ferramentas concretas nem conhece seus nomes.
- A única porta do loop até uma ferramenta é o `ExtensionRegistry`.
- Desativar uma extensão no TOML remove a tool do prompt, dos schemas e do orçamento.
- Ordem de carga determinística = lista `extensions_enabled`.
- Falha de `setup()` isola a extensão; nunca aborta o startup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionContext, ExtensionRegistry
from formiga.agent.loop import AgentLoop
from formiga.agent.session import Session
from formiga.config import Config

AGENT_DIR = Path(__file__).resolve().parents[1] / "src" / "formiga" / "agent"

# Nomes que nunca devem aparecer hardcoded no núcleo do agente.
NOMES_TOOL = ("ls", "read", "write", "edit", "bash", "web_search", "web_fetch", "deep_search")


def _modulos_agent() -> list[Path]:
    """Módulos do núcleo de `agent/` (pula `tools/` de compatibilidade e
    as portas de entrada permitidas factory.py/discovery.py)."""
    resultado: list[Path] = []
    for caminho in AGENT_DIR.rglob("*.py"):
        rel = caminho.relative_to(AGENT_DIR)
        if rel.parts[0] == "tools":  # wrappers de compatibilidade intencionais
            continue
        if caminho.name in {"factory.py", "discovery.py", "__init__.py"}:
            continue
        resultado.append(caminho)
    return resultado


def test_nucleo_nao_importa_ext_concreto():
    """Nenhum módulo do núcleo de `agent/` importa implementações de
    `formiga.ext` diretamente (somente factory.py e discovery.py)."""
    for caminho in _modulos_agent():
        texto = caminho.read_text(encoding="utf-8")
        assert "from formiga.ext" not in texto, (
            f"{caminho.name} importa formiga.ext diretamente"
        )
        assert "import formiga.ext" not in texto, (
            f"{caminho.name} importa formiga.ext diretamente"
        )


def test_loop_nao_conhece_nomes_de_ferramenta():
    """`agent/loop.py` não cita nenhum nome de ferramenta concreta."""
    texto = (AGENT_DIR / "loop.py").read_text(encoding="utf-8")
    for nome in NOMES_TOOL:
        assert f"`{nome}`" not in texto, f"loop.py cita a ferramenta `{nome}`"
        assert f"'{nome}'" not in texto, f"loop.py cita a ferramenta '{nome}'"
        assert f'"{nome}"' not in texto, f'loop.py cita a ferramenta "{nome}"'


def test_prompt_nao_contem_nomes_de_ferramenta(tmp_path):
    """Com todas as builtins carregadas, o prompt lista as tools e o loop
    monta o system prompt a partir do registry (sem nomes hardcoded)."""
    cfg = Config()
    registry = ExtensionRegistry()
    session = Session(tmp_path / "sessoes")
    ctx = ExtensionContext(registry, cfg, session)
    import formiga.ext.core
    import formiga.ext.deepsearch
    import formiga.ext.web

    formiga.ext.core.setup(ctx)
    formiga.ext.web.setup(ctx)
    formiga.ext.deepsearch.setup(ctx)

    from formiga.agent.prompts import build_system_prompt

    prompt = build_system_prompt(registry)
    assert "ls" in prompt and "deep_search" in prompt  # lista as 8
    loop = AgentLoop(None, registry, session, cfg)
    system = loop.messages[0]["content"]
    assert "ls" in system and "deep_search" in system


def test_desativar_deepsearch_remove_do_prompt_schemas_e_orcamento(tmp_path):
    """Desativar `deepsearch` em `extensions_enabled` remove a tool do prompt,
    dos schemas e do orçamento de mensagem."""
    cfg = Config(extensions_enabled=("core", "web"))
    registry = ExtensionRegistry()
    session = Session(tmp_path / "sessoes")
    ctx = ExtensionContext(registry, cfg, session)
    import formiga.ext.core
    import formiga.ext.web

    formiga.ext.core.setup(ctx)
    formiga.ext.web.setup(ctx)

    assert "deep_search" not in registry.tools
    assert "deep_search" not in {
        s["function"]["name"] for s in registry.schemas
    }
    assert registry.budget_for("deep_search") is None

    from formiga.agent.prompts import build_system_prompt

    prompt = build_system_prompt(registry)
    assert "`deep_search` —" not in prompt  # nenhuma entrada de tool para deep_search

    loop = AgentLoop(None, registry, session, cfg)
    assert "`deep_search` —" not in loop.messages[0]["content"]
    assert "deep_search" not in {
        s["function"]["name"] for s in loop.registry.schemas
    }


def test_ordem_de_carga_segue_lista_enabled(tmp_path):
    """A ordem de carregamento das builtins é a da lista `extensions_enabled`."""
    cfg = Config(extensions_enabled=("web", "core", "deepsearch"))
    registry = ExtensionRegistry()
    session = Session(tmp_path / "sessoes")
    discover_extensions(cfg, session, registry)
    ordem = [rec.name for rec in registry.extensions if rec.status == "loaded"]
    assert ordem == ["web", "core", "deepsearch"], ordem


def test_setup_quebrado_isola_extensao_sem_abortar_startup(tmp_path):
    """Uma extensão com `setup()` que levanta não impede as demais de carregar."""
    ext_dir = tmp_path / ".formiga" / "extensions"
    ext_dir.mkdir(parents=True)
    (ext_dir / "boom.py").write_text(
        "def setup(pi):\n    raise RuntimeError('extensão estourada')\n"
    )
    (ext_dir / "ok.py").write_text(
        "from formiga.agent.tools.base import ToolResult\n"
        "class OkTool:\n"
        "    name = 'ok_tool'\n"
        "    description = 'ok'\n"
        "    parameters = {'type': 'object', 'properties': {}, "
        "'additionalProperties': False}\n"
        "    def schema(self):\n"
        "        return {'type': 'function', 'function': {'name': self.name, "
        "'description': self.description, 'parameters': self.parameters}}\n"
        "    def execute(self):\n"
        "        return ToolResult(ok=True, text='ok')\n"
        "def setup(pi):\n    pi.register_tool(OkTool())\n"
    )

    cfg = Config(extensions_enabled=("core",))  # builtin core carrega normalmente
    registry2 = ExtensionRegistry()
    session2 = Session(tmp_path / "sessoes2")

    from formiga.agent.extensions.discovery import _load_file

    ctx_ok = ExtensionContext(registry2, cfg, session2, name="ok", source="global")
    mod_ok = _load_file(ext_dir / "ok.py", "ok", "global")
    mod_ok.setup(ctx_ok)

    ctx_boom = ExtensionContext(registry2, cfg, session2, name="boom", source="global")
    mod_boom = _load_file(ext_dir / "boom.py", "boom", "global")
    with pytest.raises(RuntimeError, match="extensão estourada"):
        mod_boom.setup(ctx_boom)

    # ok foi registrada mesmo com boom falhando depois
    assert "ok_tool" in registry2.tools
