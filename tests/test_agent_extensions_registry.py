"""Testes do registry de ferramentas e montagem de extensões builtin."""

from __future__ import annotations

import pytest

from formiga.agent.extensions.registry import ExtensionContext, ExtensionRegistry
from formiga.agent.session import Session
from formiga.agent.tools.base import ToolResult
from formiga.config import Config
from formiga.ext import core, deepsearch, web


class SampleTool:
    name = "sample"
    description = "Ferramenta de teste."
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

    def execute(self, **kwargs):
        return ToolResult(ok=True, text="ok")


def test_registry_preserva_ordem_e_limite_de_budget():
    registry = ExtensionRegistry()
    one, two = SampleTool(), SampleTool()
    one.name = "one"
    two.name = "two"
    registry.register_tool(one, budget_per_message=3, category="web")
    registry.register_tool(two)

    assert list(registry.tools) == ["one", "two"]
    assert [schema["function"]["name"] for schema in registry.schemas] == ["one", "two"]
    assert registry.budget_for("one") == 3
    assert registry.budget_for("two") is None


def test_registry_recusa_duplicata_e_budget_invalido():
    registry = ExtensionRegistry()
    registry.register_tool(SampleTool())
    with pytest.raises(ValueError, match="duplicada"):
        registry.register_tool(SampleTool())

    other = SampleTool()
    other.name = "other"
    with pytest.raises(ValueError, match="positivo"):
        registry.register_tool(other, budget_per_message=0)


def test_builtin_extensions_registram_todas_as_oito_tools(tmp_path):
    registry = ExtensionRegistry()
    config = Config(agent_workdir=str(tmp_path))
    session = Session(tmp_path / "sessions")
    api = ExtensionContext(registry, config, session)

    for extension in (core, web, deepsearch):
        extension.setup(api)

    assert list(registry.tools) == [
        "ls",
        "read",
        "write",
        "edit",
        "bash",
        "activate_tool",
        "web_search",
        "web_fetch",
        "deep_search",
    ]
    assert registry.budget_for("web_search") == config.agent_max_web_searches
    assert registry.budget_for("web_fetch") == config.agent_max_web_fetches
    assert registry.budget_for("deep_search") == config.agent_max_deep_searches


def test_factory_configuration_peut_desativar_deepsearch(tmp_path, monkeypatch):
    from formiga.agent import factory

    class FakeChat:
        pass

    monkeypatch.setattr(factory, "build_chat_client", lambda config: FakeChat())
    config = Config(agent_workdir=str(tmp_path), extensions_enabled=("core", "web"))
    loop = factory.build_agent(config, Session(tmp_path / "sessions"))

    assert "deep_search" not in loop.tools
    assert "web_search" in loop.tools
    assert "ls" in loop.tools
