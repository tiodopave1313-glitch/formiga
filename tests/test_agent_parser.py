"""Testes do parser tolerante de chamadas de ferramenta."""

from __future__ import annotations

from pathlib import Path

from formiga.agent.parser import parse_tool_call
from formiga.agent.tools.files import LsTool, WriteTool


def _tools() -> dict:
    return {t.name: t for t in [LsTool(Path("."))]}


def test_chamada_estruturada_valida():
    args, err = parse_tool_call(
        None,
        [{"id": "c1", "name": "ls", "arguments": '{"path": "."}'}],
        _tools(),
    )
    assert err is None
    assert args == {"path": "."}


def test_texto_com_bloco_json():
    args, err = parse_tool_call(
        'Aqui vai o resultado:\n```json\n{"name": "ls", "arguments": {"path": "src"}}\n```',
        None,
        _tools(),
    )
    assert err is None
    assert args == {"path": "src"}


def test_ferramenta_desconhecida():
    args, err = parse_tool_call(
        None,
        [{"id": "c1", "name": "inexistente", "arguments": "{}"}],
        _tools(),
    )
    assert args is None
    assert "ferramenta desconhecida" in err


def test_json_invalido():
    args, err = parse_tool_call("{não é json", None, _tools())
    assert args is None
    assert "JSON inválido" in err


def test_coercao_tipo_inteiro():
    # `max_results` é integer; o modelo envia string "6" → deve virar int

    tools = {"write": WriteTool(Path("."))}
    args, err = parse_tool_call(
        None,
        [{"id": "c1", "name": "write", "arguments": '{"path": "x.txt", "content": "ola"}'}],
        tools,
    )
    assert err is None
    assert args["content"] == "ola"
