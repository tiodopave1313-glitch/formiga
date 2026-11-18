"""Testes de skills: parser, descoberta, trust e guardrails."""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.ext.skills.skill import SkillError, parse_skill
from formiga.ext.skills.store import SkillStore


def _write_skill(path: Path, name: str, body: str = "Use passos claros.") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: Skill {name}\n"
        "when_to_use: Quando necessário\n---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


def test_parse_skill_frontmatter(tmp_path):
    path = _write_skill(tmp_path / "resumo" / "SKILL.md", "resumo")
    skill = parse_skill(path, "global")
    assert skill.name == "resumo"
    assert skill.description == "Skill resumo"
    assert skill.when_to_use == "Quando necessário"
    assert skill.body == "Use passos claros."
    assert skill.source == "global"


@pytest.mark.parametrize("name", ["", "Maiuscula", "tem espaço", "../escape"])
def test_parse_skill_rejeita_nome_invalido(tmp_path, name):
    path = _write_skill(tmp_path / "SKILL.md", name or "")
    with pytest.raises(SkillError, match="nome de skill inválido"):
        parse_skill(path)


def test_parse_skill_rejeita_segredo(tmp_path):
    path = _write_skill(tmp_path / "secret" / "SKILL.md", "secret", "api_key = abc123")
    with pytest.raises(SkillError, match="credencial"):
        parse_skill(path)


def test_store_carrega_global_e_ignora_projeto_sem_trust(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "project"
    _write_skill(home / ".formiga/skills/global/SKILL.md", "global")
    _write_skill(root / ".formiga/skills/local/SKILL.md", "local")

    store = SkillStore.discover(project_root=root, home=home)

    assert store.names() == ["global"]
    assert store.get("global").source == "global"
    assert any("fora da allowlist" in warning for warning in store.warnings)


def test_store_carrega_projeto_com_trust(tmp_path):
    home = tmp_path / "home"
    root = (tmp_path / "project").resolve()
    _write_skill(home / ".formiga/skills/global/SKILL.md", "global")
    _write_skill(root / ".formiga/skills/local/SKILL.md", "local")
    config = home / ".formiga/config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f'[extensions]\ntrusted_projects = ["{root}"]\n', encoding="utf-8"
    )

    store = SkillStore.discover(project_root=root, home=home)

    assert store.trusted
    assert store.names() == ["global", "local"]
    assert store.get("local").source == "project"


def test_skill_corrompida_gera_aviso_e_nao_interrompe_descoberta(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "project"
    _write_skill(home / ".formiga/skills/good/SKILL.md", "good")
    bad = home / ".formiga/skills/bad/SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text("sem frontmatter", encoding="utf-8")

    store = SkillStore.discover(project_root=root, home=home)

    assert store.names() == ["good"]
    assert store.warnings
