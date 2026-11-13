"""JSON Schema derived from dataclasses, plus the schema hash used by the cache.

The core uses ``dataclasses`` (PRD §9), so this is the single place that knows how a
dataclass maps to the JSON the model must emit. Selection-only stages produce tiny flat
objects, which is exactly what this subset covers.
"""

from __future__ import annotations

import hashlib
import types
from dataclasses import MISSING, fields, is_dataclass
from typing import Any, Union, get_args, get_origin, get_type_hints

from formiga.storage.idempotency import canonical_json

_SCALARS: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def schema_hash(schema: dict[str, Any]) -> str:
    """Stable hash of a JSON Schema document; feeds the grammar part of the cache key."""
    return hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()[:16]


def dataclass_schema(model: type) -> dict[str, Any]:
    """Return the JSON Schema of a dataclass, rejecting unsupported annotations."""
    if not is_dataclass(model):
        raise TypeError(f"expected a dataclass, got {model!r}")
    return _object_schema(model)


def _object_schema(model: type) -> dict[str, Any]:
    hints = get_type_hints(model)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for spec in fields(model):
        properties[spec.name] = _schema_for_type(hints[spec.name], spec.name)
        if spec.default is MISSING and spec.default_factory is MISSING:
            required.append(spec.name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _schema_for_type(annotation: Any, name: str) -> dict[str, Any]:
    if annotation in _SCALARS:
        return {"type": _SCALARS[annotation]}
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Union or origin is types.UnionType:
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) != 1:
            raise TypeError(f"{name}: unions other than Optional[T] are not supported")
        schema = _schema_for_type(non_none[0], name)
        return {**schema, "nullable": True}

    if origin in (list, tuple):
        if len(args) == 1:
            return {"type": "array", "items": _schema_for_type(args[0], f"{name}[]")}
        if origin is tuple and args == ():
            return {"type": "array", "items": {}}
        return {"type": "array", "items": {}}

    if origin is dict:
        value_type = args[1] if len(args) == 2 else str
        return {"type": "object", "additionalProperties": _schema_for_type(value_type, name)}

    if isinstance(annotation, type) and is_dataclass(annotation):
        return _object_schema(annotation)

    if isinstance(annotation, type) and issubclass(annotation, str) and hasattr(
        annotation, "__members__"
    ):
        return {"type": "string", "enum": [member.value for member in annotation]}

    raise TypeError(f"{name}: unsupported annotation {annotation!r}")


__all__ = ["dataclass_schema", "schema_hash"]
