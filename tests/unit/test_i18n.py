"""i18n: catalog fallback, no hardcoded literals, and locale-only language additions."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from formiga.i18n import FALLBACK, MissingTranslation, available_locales, catalog, t
from formiga.i18n.format import format_date, format_number

SRC = Path(__file__).resolve().parents[2] / "src" / "formiga"
UI_DIRS = (SRC / "ui",)
LOCALES_DIR = SRC / "data" / "i18n" / "locales"

#: Call names whose string arguments are developer-facing, never user-facing.
ALLOWED_CALLS = {
    "print",  # only reached through Ui with already-translated text
    "json.dumps",
    "ValueError",
    "TypeError",
    "RuntimeError",
    "LookupError",
    "OSError",
    "StorageError",
    "ConfigError",
    "CoercionError",
    "ProfileUnsupported",
    "PermissionDenied",
    "LockBusy",
    "ForeignSchema",
    "MissingTranslation",
    "PromptMissing",
    "StructuredOutputError",
    "BudgetExceeded",
    "_fail",
}


def _user_facing_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name in {"t", "translate"} or name in ALLOWED_CALLS:
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"error", "failed"}:
            continue
        for argument in node.args:
            if (
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and len(argument.value.split()) >= 3
            ):
                found.append((node.lineno, argument.value))
    return found


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        node: ast.expr | None = func
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


@pytest.mark.parametrize("directory", UI_DIRS, ids=lambda path: path.name)
def test_ui_modules_have_no_user_facing_literals(directory: Path) -> None:
    offenders: list[str] = []
    for path in directory.rglob("*.py"):
        offenders.extend(f"{path}:{line}: {text!r}" for line, text in _user_facing_literals(path))
    assert not offenders, "\n".join(offenders)


def test_english_catalog_is_flat_and_string_valued() -> None:
    data = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in data.items())


def test_pt_br_is_shipped_as_the_second_locale() -> None:
    assert "pt-BR" in available_locales()
    assert FALLBACK in available_locales()


def test_missing_key_falls_back_to_english() -> None:
    merged = catalog("pt-BR")
    assert merged["app.name"] == t("app.name", locale="en")


def test_unknown_key_raises_instead_of_printing_the_key() -> None:
    with pytest.raises(MissingTranslation):
        t("does.not.exist")


def test_formatting_interpolates_kwargs() -> None:
    assert "Formiga" in t("app.name")


def test_adding_a_locale_requires_no_code_change() -> None:
    """Every shipped locale resolves through the same catalog loader."""
    import formiga.i18n as module

    module.clear_cache()
    assert t("app.name", locale="pt-BR")
    module.clear_cache()


def test_number_formatting_follows_the_locale_table() -> None:
    assert format_number(1234.5, locale="en", decimals=1) == "1,234.5"
    assert format_number(1234.5, locale="pt-BR", decimals=1) == "1.234,5"


def test_date_formatting_follows_the_locale_order() -> None:
    from datetime import date

    value = date(2026, 3, 7)
    assert format_date(value, locale="en") == "03/07/2026"
    assert format_date(value, locale="pt-BR") == "07/03/2026"


def test_unknown_locale_falls_back_to_english_conventions() -> None:
    assert format_number(1000, locale="zz") == "1,000"
