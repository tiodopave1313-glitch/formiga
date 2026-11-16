"""Parser tolerante de chamadas de ferramenta (seção 5 e guardrail §4.3 do PRD).

Aceita:
- chamada estruturada (`tool_calls` do backend, já com `name` + `arguments`);
- texto do modelo com JSON num bloco ```json ... ``` ou inline.

Faz até uma correção de formato com o erro objetivo; se ainda falhar,
retorna um erro que o loop transforma em `ERRO:` no contexto.
"""

from __future__ import annotations

import json
import re
from typing import Any

from formiga.agent.tools.base import Tool, ToolResult

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


def _extract_json_text(text: str) -> str:
    """Extrai o primeiro bloco JSON de um texto (bloco de código ou inline)."""
    text = text.strip()
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    # fallback: procura o primeiro '{' e o último '}'
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _coerce_types(args: dict, schema: dict) -> dict:
    """Ajusta tipos de parâmetros conforme o JSON Schema (int↔str, etc.)."""
    props = schema.get("properties", {})
    coerced: dict[str, Any] = {}
    for key, value in args.items():
        expected = props.get(key, {}).get("type")
        if expected is None:
            coerced[key] = value
            continue
        if expected == "integer" and isinstance(value, str):
            try:
                coerced[key] = int(value)
            except (ValueError, TypeError):
                coerced[key] = value
        elif expected == "number" and isinstance(value, str):
            try:
                coerced[key] = float(value)
            except (ValueError, TypeError):
                coerced[key] = value
        elif expected == "boolean" and isinstance(value, str):
            coerced[key] = value.strip().lower() in ("true", "1", "yes", "on")
        elif expected == "array" and isinstance(value, str):
            try:
                coerced[key] = json.loads(value)
            except (ValueError, TypeError):
                coerced[key] = [value]
        else:
            coerced[key] = value
    return coerced


def parse_tool_call(
    raw: str | None,
    tool_calls: list[dict] | None,
    available: dict[str, Tool],
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Extrai e valida uma chamada de ferramenta.

    Retorna `(args_dict, None)` em caso de sucesso ou `(None, erro_objetivo)`
    em caso de falha. `raw` é o texto do modelo; `tool_calls` são chamadas
    estruturadas vindas do backend (precedência sobre `raw`).
    """
    if tool_calls:
        for tc in tool_calls:
            name = tc.get("name", "") if isinstance(tc, dict) else ""
            arguments = tc.get("arguments", "{}") if isinstance(tc, dict) else "{}"
            tool = available.get(name)
            if tool is None:
                return None, f"ferramenta desconhecida: {name!r}. Use uma de: {sorted(available)}."
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError as exc:
                return None, f"argumentos não são JSON válido para '{name}': {exc}."
            if not isinstance(args, dict):
                return None, f"argumentos de '{name}' devem ser um objeto JSON."
            args = _coerce_types(args, tool.parameters)
            return args, None
        return None, "nenhuma chamada de ferramenta válida encontrada."

    if not raw:
        return None, "resposta vazia: nem texto nem chamada de ferramenta."

    json_text = _extract_json_text(raw)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return None, (
            f"JSON inválido na resposta: {exc}. "
            "Envie apenas o JSON da ferramenta ou texto simples."
        )

    if not isinstance(data, dict):
        return None, "a resposta deve ser um objeto JSON com 'name' e 'arguments'."
    name = data.get("name")
    arguments = data.get("arguments", "{}")
    tool = available.get(name) if name else None
    if tool is None:
        return None, f"ferramenta desconhecida: {name!r}. Use uma de: {sorted(available)}."
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError as exc:
        return None, f"argumentos não são JSON válido para '{name}': {exc}."
    if not isinstance(args, dict):
        return None, f"argumentos de '{name}' devem ser um objeto JSON."
    args = _coerce_types(args, tool.parameters)
    return args, None


def result_to_context(result: ToolResult) -> str:
    """Converte o resultado de uma ferramenta na mensagem de contexto para o modelo."""
    if result.ok:
        return result.text
    prefix = "ERRO: "
    return prefix + result.text if not result.text.startswith(prefix) else result.text
