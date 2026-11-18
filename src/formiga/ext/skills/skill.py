"""Modelo e parser de skills declarativas (PRD v2, §14)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|senha|chave)\s*[:=]\s*\S+"
)
_FRONTMATTER_KEYS = {
    "name": "name",
    "description": "description",
    "when_to_use": "when_to_use",
    "when-to-use": "when_to_use",
    "when to use": "when_to_use",
}


class SkillError(ValueError):
    """Frontmatter ou conteúdo de skill inválido."""


@dataclass(frozen=True)
class Skill:
    """Conhecimento declarativo, carregado de um diretório de skill."""

    name: str
    description: str
    when_to_use: str
    body: str
    path: Path
    source: str

    @property
    def directory(self) -> Path:
        return self.path.parent


def validar_nome(name: str) -> str:
    """Normaliza e valida o nome usado no comando `/nome-da-skill`."""
    normalized = name.strip()
    if not _NAME_RE.fullmatch(normalized):
        raise SkillError(
            f"nome de skill inválido: {name!r}; use minúsculas, dígitos e hífens"
        )
    return normalized


def parse_skill(path: Path, source: str = "global") -> Skill:
    """Lê SKILL.md com frontmatter simples `---` e valida metadados."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillError(f"não foi possível ler {path}: {exc}") from exc

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError(f"{path}: frontmatter ausente (esperado '---' na primeira linha)")

    end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if end is None:
        raise SkillError(f"{path}: frontmatter não fechado")

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        canonical = _FRONTMATTER_KEYS.get(key.strip().lower())
        if canonical:
            fields[canonical] = value.strip().strip("\"'")

    missing = [key for key in ("name", "description") if key not in fields]
    if missing:
        raise SkillError(f"{path}: frontmatter sem campo(s): {', '.join(missing)}")
    if not fields["description"]:
        raise SkillError(f"{path}: campo 'description' não pode ser vazio")

    name = validar_nome(fields["name"])
    body = "\n".join(lines[end + 1 :]).strip()
    if _SECRET_RE.search(content):
        raise SkillError(f"{path}: conteúdo contém possível credencial")

    return Skill(
        name=name,
        description=fields["description"],
        when_to_use=fields.get("when_to_use", ""),
        body=body,
        path=path,
        source=source,
    )
