"""Descoberta determinística de skills globais e de projeto."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

from formiga.agent.extensions.discovery import global_trusted_projects
from formiga.ext.skills.skill import _SECRET_RE, Skill, SkillError, parse_skill, validar_nome


@dataclass
class SkillStore:
    """Carrega skills globais e, quando confiável, as do projeto atual."""

    global_dir: Path
    project_dir: Path
    trusted: bool = False
    skills: list[Skill] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def discover(
        cls,
        project_root: Path | None = None,
        home: Path | None = None,
    ) -> SkillStore:
        home = (home or Path.home()).expanduser().resolve()
        root = (project_root or Path.cwd()).expanduser().resolve()
        global_dir = home / ".formiga" / "skills"
        project_dir = root / ".formiga" / "skills"
        trusted = root in global_trusted_projects(home)

        store = cls(global_dir=global_dir, project_dir=project_dir, trusted=trusted)
        store._load_directory(global_dir, "global")
        if trusted:
            store._load_directory(project_dir, "project")
        elif project_dir.is_dir():
            store.warnings.append(
                f"skills de projeto ignoradas (projeto fora da allowlist): {project_dir}"
            )
        return store

    def _load_directory(self, directory: Path, source: str) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*/SKILL.md")):
            try:
                skill = parse_skill(path, source=source)
            except SkillError as exc:
                self.warnings.append(str(exc))
                continue
            existing = self.get(skill.name)
            if existing is not None:
                self.warnings.append(
                    f"skill duplicada ignorada: {skill.name} "
                    f"({source}; já veio de {existing.source})"
                )
                continue
            self.skills.append(skill)

    def get(self, name: str) -> Skill | None:
        normalized = name.strip().lower()
        return next((skill for skill in self.skills if skill.name == normalized), None)

    def names(self) -> list[str]:
        return [skill.name for skill in self.skills]

    def write(self, name: str, content: str, source: str = "global") -> Path:
        """Grava SKILL.md depois de validação; aprovação é responsabilidade do harness."""
        normalized = validar_nome_para_write(name)
        if _SECRET_RE.search(content):
            raise SkillError("conteúdo contém possível credencial")
        directory = (
            self.global_dir / normalized
            if source == "global"
            else self.project_dir / normalized
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "SKILL.md"
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        # Valida o arquivo recém-criado; em falha remove para evitar persistência inválida.
        try:
            parse_skill(path, source=source)
        except SkillError:
            path.unlink(missing_ok=True)
            raise
        return path

    def delete(self, name: str, source: str = "global") -> bool:
        normalized = validar_nome_para_write(name)
        directory = (
            self.global_dir / normalized
            if source == "global"
            else self.project_dir / normalized
        )
        path = directory / "SKILL.md"
        if not path.is_file():
            return False
        path.unlink()
        with contextlib.suppress(OSError):
            directory.rmdir()
        return True


def validar_nome_para_write(name: str) -> str:
    return validar_nome(name)
