"""Testes de aceitação da Fase 2 — sistema de extensões completo (PRD §20.1).

Aceites cobertos:
- extensão externa com tool + comando carrega, aparece em /ext e funciona;
- projeto fora da allowlist nao carrega extensões locais;
- ordem de carga fica registrada em events.jsonl (extension_loaded com order);
- entry-point pip (formiga.extensions) carrega como fonte "pip";
- comandos /tools e /ext funcionam na CLI interativa.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from formiga.agent.extensions import discovery as discovery_mod
from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.session import Session
from formiga.agent.tools.base import ToolResult
from formiga.cli import main
from formiga.config import Config
from formiga.configfile import write_global_config

FIXTURES = Path(__file__).parent / "fixtures"


def _trust(home: Path, *projects: Path) -> None:
    """Escreve [extensions].trusted_projects em ~/.formiga/config.toml."""
    write_global_config(
        {"extensions": {"trusted_projects": [str(p) for p in projects]}}
    )


def _projeto_com_extensao(tmp_path: Path, nome: str = "todo") -> Path:
    project = tmp_path / "projeto"
    ext_dir = project / ".formiga" / "extensions"
    ext_dir.mkdir(parents=True)
    (ext_dir / f"{nome}.py").write_text(
        (FIXTURES / "extensions" / f"{nome}.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return project


def test_extensao_externa_carrega_executa_e_aparece_em_ext(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = _projeto_com_extensao(tmp_path)
    _trust(home, project)

    from formiga.agent import factory

    class FakeChat:
        pass

    monkeypatch.setattr(factory, "build_chat_client", lambda config: FakeChat())

    cfg = Config(agent_workdir=str(project), extensions_enabled=("core",))
    loop = factory.build_agent(cfg, Session(project / "sessoes"))
    registry = loop.registry

    assert "todo_add" in registry.tools
    resultado = registry.tools["todo_add"].execute(item="ler o PRD v2")
    assert resultado.ok and "anotado" in resultado.text
    todos = loop.session.dir / "todos.txt"
    assert todos.is_file()
    assert "ler o PRD v2" in todos.read_text(encoding="utf-8")

    saida = registry.dispatch_command("ext", "")
    assert "todo" in saida and "project" in saida


def test_projeto_nao_confiado_nao_carrega_extensao_local(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = _projeto_com_extensao(tmp_path)  # sem _trust

    cfg = Config(agent_workdir=str(project), extensions_enabled=("core",))
    registry = ExtensionRegistry()
    session = Session(project / "sessoes")
    discover_extensions(cfg, session, registry, root=project, home=home)

    nomes = [rec.name for rec in registry.extensions]
    assert "todo" not in nomes
    assert "todo_add" not in registry.tools


def test_ordem_de_carga_registrada_em_events_jsonl(tmp_path):
    cfg = Config(extensions_enabled=("web", "core", "deepsearch"))
    registry = ExtensionRegistry()
    session = Session(tmp_path / "sessoes")
    discover_extensions(cfg, session, registry)

    carregados = []
    for linha in session.events_path.read_text(encoding="utf-8").splitlines():
        evento = json.loads(linha)
        if evento.get("type") == "extension_loaded":
            carregados.append(evento["data"])
    assert [c["name"] for c in carregados] == ["web", "core", "deepsearch"]
    assert [c["order"] for c in carregados] == [1, 2, 3]


def test_entry_point_pip_carrega_como_fonte_pip(monkeypatch, tmp_path):
    modulo = types.ModuleType("pip_exemplo_modulo")

    def setup(pi):
        class PipTool:
            name = "pip_tool"
            description = "tool de um entry point pip."
            parameters = {"type": "object", "properties": {}}

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
                return ToolResult(ok=True, text="pip ok")

        pi.register_tool(PipTool())

    modulo.setup = setup
    ponto = types.SimpleNamespace(name="pip_exemplo", load=lambda: modulo)
    monkeypatch.setattr(
        discovery_mod.importlib.metadata,
        "entry_points",
        lambda group=None: [ponto],
    )

    cfg = Config(extensions_enabled=("core",))
    registry = ExtensionRegistry()
    session = Session(tmp_path / "sessoes")
    discover_extensions(cfg, session, registry)

    assert "pip_tool" in registry.tools
    registro = [r for r in registry.extensions if r.name == "pip_exemplo"][0]
    assert registro.source == "pip"
    assert registro.status == "loaded"


def test_comandos_tools_e_ext(monkeypatch, tmp_path):
    from formiga.agent import factory

    class FakeChat:
        pass

    monkeypatch.setattr(factory, "build_chat_client", lambda config: FakeChat())
    cfg = Config(extensions_enabled=("core",))
    loop = factory.build_agent(cfg, Session(tmp_path / "sessoes"))

    saida = loop.registry.dispatch_command("tools", "")
    assert "ls" in saida and "bash" in saida

    saida = loop.registry.dispatch_command("ext", "")
    assert "core" in saida

    with pytest.raises(KeyError):
        loop.registry.dispatch_command("nao_existe", "")


def test_cli_interativa_comandos_slash(tmp_path, monkeypatch, capsys):
    from formiga.agent import factory

    class FakeChat:
        pass

    monkeypatch.setattr(factory, "build_chat_client", lambda config: FakeChat())

    respostas = iter(["/tools", "/ext", "/nao_existe"])

    def fake_input(prompt: str) -> str:
        valor = next(respostas, None)
        if valor is None:
            raise EOFError
        return valor

    monkeypatch.setattr("builtins.input", fake_input)

    rc = main(
        ["agent", "--session-dir", str(tmp_path / "sessoes")]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Ferramentas registradas" in out
    assert "ls" in out
    assert "Extensões carregadas" in out
    assert "core" in out
    assert "Comando desconhecido: /nao_existe" in out
