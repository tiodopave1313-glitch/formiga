"""JSON Schema -> GBNF.

Used for endpoints that accept a raw grammar but not ``json_schema``. The grammar only
has to be *valid* and to constrain the shapes small models get wrong: flat objects,
closed string enums, small number ranges. Anything richer degrades to a permissive
:data:`VALUE_RULE`, because syntax is validated in code anyway - a grammar is a latency
optimisation, never the correctness boundary (ADR 002).
"""

from __future__ import annotations

import json
from typing import Any

#: Generic JSON rules appended to every grammar so degraded nodes stay parseable.
GENERIC_RULES = """
value ::= object | array | number | boolean | null | string
object ::= "{" ws ( pair ( ws "," ws pair )* )? ws "}"
pair ::= string ws ":" ws value
array ::= "[" ws ( value ( ws "," ws value )* )? ws "]"
number ::= "-"? ( "0" | [1-9] [0-9]* ) ( "." [0-9]+ )?
boolean ::= "true" | "false"
null ::= "null"
string ::= "\\"" ( [^"\\\\] | "\\\\" . )* "\\""
ws ::= [ \\t\\n]*
"""

_SCALARS = {"string": "string", "integer": "number", "number": "number", "boolean": "boolean"}


def quote(literal: str) -> str:
    """Escape ``literal`` as a GBNF string literal."""
    return '"' + literal.replace("\\", "\\\\").replace('"', '\\"') + '"'


def gbnf_for(schema: dict[str, Any], *, root: str = "root") -> str:
    """Translate a JSON Schema subset into a GBNF grammar string."""
    rules: dict[str, str] = {}
    counter = {"n": 0}

    def new_rule(body: str) -> str:
        counter["n"] += 1
        name = f"s{counter['n']}"
        rules[name] = body
        return name

    def enum_rule(values: list[Any]) -> str:
        literals = sorted({json.dumps(value, ensure_ascii=False) for value in values})
        return new_rule("( " + " | ".join(quote(lit) for lit in literals) + " )")

    def value_rule(node: dict[str, Any], depth: int) -> str:
        if depth > 4:
            return "value"
        if "enum" in node:
            return enum_rule(node["enum"])
        node_type = node.get("type")
        if isinstance(node_type, list):
            node_type = next((item for item in node_type if item != "null"), None)
        if node_type == "object" and node.get("properties"):
            return object_rule(node, depth)
        if node_type == "array":
            items = node.get("items") or {}
            inner = value_rule(items, depth + 1) if items else "value"
            return new_rule(f'"[" ws ( {inner} ( ws "," ws {inner} )* )? ws "]"')
        if node_type in _SCALARS:
            return _SCALARS[node_type]
        return "value"

    def object_rule(node: dict[str, Any], depth: int) -> str:
        properties: dict[str, Any] = node.get("properties") or {}
        required = set(node.get("required") or ())
        members: list[str] = []
        for name, prop in properties.items():
            inner = value_rule(prop, depth + 1)
            member = new_rule(f"{quote(json.dumps(name))} ws \":\" ws {inner}")
            members.append(member if name in required else f"( {member} )?")
        if not members:
            return new_rule('"{" ws "}"')
        sequence = ' ws "," ws '.join(members)
        return new_rule(f'"{{" ws {sequence} ws "}}"')

    rules[root] = value_rule(schema, 0)
    body = "\n".join(f"{name} ::= {body_text}" for name, body_text in rules.items())
    return f"{body}\n{GENERIC_RULES.strip()}\n"


__all__ = ["GENERIC_RULES", "gbnf_for", "quote"]
