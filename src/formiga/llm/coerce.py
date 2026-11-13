"""Validate a decoded JSON object against a dataclass.

Small and strict on purpose: unknown keys are rejected (a model inventing a field is a
schema violation, not a hint), missing required fields are rejected, and unions other
than ``Optional[T]`` are refused at schema build time so this function never has to
guess. It performs *no* repair - that is the caller's single-retry decision.
"""

from __future__ import annotations

import types
from dataclasses import MISSING, fields, is_dataclass
from typing import Any, Union, get_args, get_origin, get_type_hints

_SCALARS: dict[type, tuple[type, ...]] = {
    str: (str,),
    int: (int,),
    float: (int, float),
    bool: (bool,),
}


class CoercionError(ValueError):
    """Raised when a payload does not satisfy the dataclass schema."""


def from_dict(model: type, payload: Any, *, path: str = "") -> Any:
    """Build ``model`` from ``payload``, raising :class:`CoercionError` on mismatch."""
    where = path or model.__name__
    if not is_dataclass(model):
        raise CoercionError(f"{where}: expected a dataclass")
    if not isinstance(payload, dict):
        raise CoercionError(f"{where}: expected an object, got {type(payload).__name__}")

    hints = get_type_hints(model)
    known = {spec.name: spec for spec in fields(model)}
    unknown = set(payload) - set(known)
    if unknown:
        raise CoercionError(f"{where}: unexpected field(s) {sorted(unknown)}")

    kwargs: dict[str, Any] = {}
    for name, spec in known.items():
        if name in payload:
            kwargs[name] = _convert(hints[name], payload[name], path=f"{where}.{name}")
            continue
        if spec.default is MISSING and spec.default_factory is MISSING:
            raise CoercionError(f"{where}: missing required field {name!r}")
    return model(**kwargs)


def _convert(annotation: Any, value: Any, *, path: str) -> Any:
    if annotation in _SCALARS:
        expected = _SCALARS[annotation]
        if annotation is float and isinstance(value, str):
            try:
                return float(value)
            except ValueError as exc:
                raise CoercionError(f"{path}: expected a number") from exc
        if isinstance(value, bool) and annotation is not bool:
            raise CoercionError(f"{path}: expected {annotation.__name__}, got boolean")
        if not isinstance(value, expected):
            raise CoercionError(f"{path}: expected {annotation.__name__}")
        return value

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Union or origin is types.UnionType:
        non_none = [arg for arg in args if arg is not type(None)]
        if value is None and len(non_none) != len(args):
            return None
        if len(non_none) != 1:
            raise CoercionError(f"{path}: unsupported union")
        return _convert(non_none[0], value, path=path)

    if origin in (list, tuple):
        if not isinstance(value, list):
            raise CoercionError(f"{path}: expected an array")
        if len(args) == 1:
            return [
                _convert(args[0], item, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ]
        return list(value)

    if origin is dict:
        if not isinstance(value, dict):
            raise CoercionError(f"{path}: expected an object")
        value_type = args[1] if len(args) == 2 else str
        return {
            str(key): _convert(value_type, item, path=f"{path}.{key}")
            for key, item in value.items()
        }

    if isinstance(annotation, type) and is_dataclass(annotation):
        return from_dict(annotation, value, path=path)

    if isinstance(annotation, type) and issubclass(annotation, str) and hasattr(
        annotation, "__members__"
    ):
        allowed = [member.value for member in annotation]
        if value not in allowed:
            raise CoercionError(f"{path}: expected one of {allowed}")
        return annotation(value)

    raise CoercionError(f"{path}: unsupported annotation {annotation!r}")


__all__ = ["CoercionError", "from_dict"]
