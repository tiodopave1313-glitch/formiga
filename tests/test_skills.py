"""Testes de skills: parser, descoberta, trust, comandos e aprovação."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.session import Session
from formiga.config import Config
from formiga.ext.skills.skill import SkillError, parse_skill
from formiga.ext.skills.store import SkillStore


def _write_skill(path: Path, name: str, body: str = "Use passos claros.") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_skill_content(name, body), encoding="utf-8")
    return path


def _skill_content(name: str, body: str = "Use passos claros.") -> str:
    return (
        f"---\nname: {name}\ndescription: Skill {name}\n"
        "when_to_use: Quando necessário\n---\n"
        f"{body}\n"
    )


@pytest.fixture
def skills_env(tmp_path, monkeypatch):
    """Monta a extensão skills com HOME e workdir isolados."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    config = Config(agent_workdir=project, extensions_enabled=("skills",))
    session = Session(project / "sessoes", session_id="sess_001")
    registry = ExtensionRegistry()
    discover_extensions(config, session, registry, root=project, home=home)
    return home, project, registry, session


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


# ---------------------------------------------------------------------- #
# Aceite §14: skill instalada, expansão, trust e aprovação               #
# ---------------------------------------------------------------------- #


def test_skill_instalada_aparece_em_skills_e_executa_via_comando(skills_env):
    home, _project, registry, session = skills_env
    _write_skill(
        home / ".formiga/skills/resumir/SKILL.md",
        "resumir",
        "Use tópicos curtos e cite as fontes.",
    )
    # Recarrega a extensão já com a skill instalada.
    fresh = ExtensionRegistry()
    discover_extensions(
        Config(agent_workdir=skills_env[1], extensions_enabled=("skills",)),
        session,
        fresh,
        root=skills_env[1],
        home=home,
    )

    listagem = fresh.dispatch_command("skills", "list")
    assert "/resumir" in listagem
    assert "quando usar" in listagem.lower()

    eventos: list[tuple[str, dict]] = []
    fresh._event_sink = lambda event, data: eventos.append((event, data))
    assert "resumir" in fresh.commands
    aviso = fresh.dispatch_command("resumir", "")
    assert "próxima mensagem" in aviso

    expandida = fresh.chain("input", "resuma o relatório")
    assert "Use tópicos curtos" in expandida
    assert "Pedido do usuário: resuma o relatório" in expandida
    assert any(event == "skill_expanded" for event, _ in eventos)


def test_skill_de_projeto_fora_da_allowlist_nao_carrega(skills_env):
    home, project, _registry, session = skills_env
    _write_skill(
        project / ".formiga/skills/local/SKILL.md", "local", "conteúdo privado"
    )
    registry = ExtensionRegistry()
    discover_extensions(
        Config(agent_workdir=project, extensions_enabled=("skills",)),
        session,
        registry,
        root=project,
        home=home,
    )

    listagem = registry.dispatch_command("skills", "list")
    assert "local" not in registry.commands
    assert "/local" not in listagem
    assert "fora da allowlist" in listagem


def test_skill_de_projeto_carrega_com_trust(skills_env):
    home, project, _registry, session = skills_env
    _write_skill(project / ".formiga/skills/local/SKILL.md", "local", "conteúdo")
    config = home / ".formiga/config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f'[extensions]\ntrusted_projects = ["{project.resolve()}"]\n',
        encoding="utf-8",
    )
    registry = ExtensionRegistry()
    discover_extensions(
        Config(agent_workdir=project, extensions_enabled=("skills",)),
        session,
        registry,
        root=project,
        home=home,
    )

    assert "local" in registry.commands
    assert "[project]" in registry.dispatch_command("skills", "list")


def test_skill_manage_sem_aprovacao_nao_altera_disco(skills_env):
    home, _project, registry, _session = skills_env
    tool = registry.tools["skill_manage"]

    resultado = tool.execute(
        action="write", name="nova", content=_skill_content("nova"), source="global"
    )

    assert resultado.ok
    assert "stageada" in resultado.text
    assert not (home / ".formiga/skills/nova/SKILL.md").exists()
    assert "nova" not in registry.commands
    pendentes = json.loads(
        (home / ".formiga/skills/pending.json").read_text(encoding="utf-8")
    )
    assert pendentes[0]["name"] == "nova"
    assert "nova" in registry.dispatch_command("skills", "pending")


def test_skills_approve_grava_e_registra_comando(skills_env):
    home, _project, registry, _session = skills_env
    tool = registry.tools["skill_manage"]
    tool.execute(
        action="write", name="nova", content=_skill_content("nova"), source="global"
    )
    proposal_id = json.loads(
        (home / ".formiga/skills/pending.json").read_text(encoding="utf-8")
    )[0]["id"]

    eventos: list[tuple[str, dict]] = []
    registry._event_sink = lambda event, data: eventos.append((event, data))
    saida = registry.dispatch_command("skills", f"approve {proposal_id}")

    assert "aprovada" in saida
    assert (home / ".formiga/skills/nova/SKILL.md").exists()
    assert "nova" in registry.commands
    assert "/nova" in registry.dispatch_command("skills", "list")
    assert any(event == "skill_manage_approved" for event, _ in eventos)

    # Aprovada na mesma sessão, a skill já expande no próximo input.
    assert registry.dispatch_command("nova", "")
    assert "Use passos claros" in registry.chain("input", "aplique a skill")
    assert any(event == "skill_expanded" for event, _ in eventos)
    assert json.loads(
        (home / ".formiga/skills/pending.json").read_text(encoding="utf-8")
    ) == []


def test_skills_reject_descarta_proposta(skills_env):
    home, _project, registry, _session = skills_env
    tool = registry.tools["skill_manage"]
    tool.execute(
        action="write", name="descartar", content=_skill_content("descartar")
    )
    proposal_id = json.loads(
        (home / ".formiga/skills/pending.json").read_text(encoding="utf-8")
    )[0]["id"]

    saida = registry.dispatch_command("skills", f"reject {proposal_id}")

    assert "descartada" in saida
    assert not (home / ".formiga/skills/descartar/SKILL.md").exists()
    assert json.loads(
        (home / ".formiga/skills/pending.json").read_text(encoding="utf-8")
    ) == []


def test_skill_manage_recusa_credencial_e_nome_divergente(skills_env):
    _home, _project, registry, _session = skills_env
    tool = registry.tools["skill_manage"]

    segredo = tool.execute(
        action="write",
        name="segredo",
        content=_skill_content("segredo", "api_key = abc123"),
    )
    divergente = tool.execute(
        action="write", name="nome-a", content=_skill_content("nome-b")
    )
    projeto = tool.execute(
        action="write", name="projeto", content=_skill_content("projeto"), source="project"
    )

    assert not segredo.ok and "credencial" in segredo.text
    assert not divergente.ok and "não corresponde" in divergente.text
    assert not projeto.ok and "allowlist" in projeto.text


def test_skill_manage_delete_exige_aprovacao(skills_env):
    home, project, _registry, session = skills_env
    path = _write_skill(home / ".formiga/skills/antiga/SKILL.md", "antiga")
    registry = ExtensionRegistry()
    discover_extensions(
        Config(agent_workdir=project, extensions_enabled=("skills",)),
        session,
        registry,
        root=project,
        home=home,
    )
    tool = registry.tools["skill_manage"]

    resultado = tool.execute(action="delete", name="antiga", source="global")
    assert resultado.ok
    assert path.exists()

    proposal_id = json.loads(
        (home / ".formiga/skills/pending.json").read_text(encoding="utf-8")
    )[0]["id"]
    registry.dispatch_command("skills", f"approve {proposal_id}")
    assert not path.exists()


def test_nudge_task_end_so_com_tarefa_bem_sucedida(skills_env):
    _home, _project, registry, _session = skills_env
    notificacoes: list[tuple[str, dict]] = []
    registry._event_sink = lambda event, data: notificacoes.append((event, data))

    registry.observe("task_end", {"successful": False, "successful_tools": 3})
    assert not any(event == "notification" for event, _ in notificacoes)

    registry.observe("task_end", {"successful": True, "successful_tools": 0})
    assert not any(event == "notification" for event, _ in notificacoes)

    registry.observe("task_end", {"successful": True, "successful_tools": 2})
    nudges = [
        data["text"] for event, data in notificacoes if event == "notification"
    ]
    assert any("skill_manage" in text for text in nudges)


def test_cli_skills_list(tmp_path, monkeypatch, capsys):
    from formiga.cli import main

    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(project)
    _write_skill(home / ".formiga/skills/cli/SKILL.md", "cli", "corpo")

    assert main(["skills", "list"]) == 0
    saida = capsys.readouterr()
    assert "/cli" in saida.out

