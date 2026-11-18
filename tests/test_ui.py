"""Testes da apresentação da CLI: cores, limpeza de tela, painel e /help."""

from __future__ import annotations

from pathlib import Path

import pytest

from formiga.agent import ui
from formiga.agent.chat import ChatResponse
from formiga.agent.extensions.discovery import discover_extensions
from formiga.agent.extensions.registry import ExtensionRegistry
from formiga.agent.session import Session
from formiga.agent.ui import (
    cores_ativas,
    estado_sessao,
    limpar_tela,
    linhas_ajuda,
    linhas_painel,
    pintar,
)
from formiga.config import Config
from tests.fakes_agent import FakeChatClient


@pytest.fixture(autouse=True)
def _reset_sem_cor():
    ui.sem_cor(False)
    yield
    ui.sem_cor(False)


def _write_skill(home: Path, name: str, description: str) -> None:
    path = home / ".formiga/skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n"
        "when_to_use: Quando fizer sentido\n---\nCorpo da skill.\n",
        encoding="utf-8",
    )


def _monta_registry(tmp_path, monkeypatch) -> tuple[ExtensionRegistry, Session, Path]:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    _write_skill(home, "resumir", "Resume textos longos")
    config = Config(agent_workdir=project, extensions_enabled=("core", "skills"))
    session = Session(project / "sessoes", session_id="sess_ui")
    registry = ExtensionRegistry()
    discover_extensions(config, session, registry, root=project, home=home)
    return registry, session, project


def test_pintar_respeita_tty_e_no_color(monkeypatch):
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert pintar("ok", "cyan") == "ok"

    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    assert "\x1b[36m" in pintar("ok", "cyan", negrito=True)

    monkeypatch.setenv("NO_COLOR", "1")
    assert pintar("ok", "cyan") == "ok"
    assert not cores_ativas()


def test_sem_cor_desliga_mesmo_com_clicolor_force(monkeypatch):
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    ui.sem_cor(True)
    assert pintar("ok", "red") == "ok"
    ui.sem_cor(False)
    assert "\x1b[31m" in pintar("ok", "red")


def test_limpar_tela_so_em_terminal_de_controle(monkeypatch):
    class Fluxo:
        def __init__(self, tty: bool) -> None:
            self.tty = tty
            self.saida = ""

        def isatty(self) -> bool:
            return self.tty

        def write(self, texto: str) -> None:
            self.saida += texto

        def flush(self) -> None:
            pass

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    sem_tty = Fluxo(False)
    limpar_tela(sem_tty)
    assert sem_tty.saida == ""

    com_tty = Fluxo(True)
    limpar_tela(com_tty)
    assert com_tty.saida == "\x1b[2J\x1b[H"

    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    forçado = Fluxo(False)
    limpar_tela(forçado)
    assert forçado.saida == "\x1b[2J\x1b[H"


def test_painel_lista_ferramentas_extensoes_comandos_e_skills(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    registry, session, _project = _monta_registry(tmp_path, monkeypatch)

    estado = estado_sessao(registry, session)
    texto = "\n".join(linhas_painel(estado))

    assert "formiga agent · sessão:" in texto
    assert "transcript:" in texto
    assert "FERRAMENTAS" in texto and "ls" in texto and "skill_manage" in texto
    assert "EXTENSÕES" in texto and "core" in texto and "skills" in texto
    assert "COMANDOS" in texto and "/skills" in texto
    assert "SKILLS (1)" in texto
    assert "resumir — Resume textos longos" in texto
    assert "Ctrl+C interrompe" in texto
    assert "\x1b[" not in texto  # fora de TTY, nada de ANSI


def test_linhas_ajuda_lista_comandos_e_resumos(tmp_path, monkeypatch):
    registry, _session, project = _monta_registry(tmp_path, monkeypatch)

    import formiga.agent.factory as factory

    monkeypatch.setattr(
        factory, "build_chat_client", lambda config: FakeChatClient([])
    )
    loop = factory.build_agent(
        Config(agent_workdir=project, extensions_enabled=("core", "skills")),
        Session(project / "sessoes", session_id="sess_help"),
    )
    texto = "\n".join(linhas_ajuda(loop.registry))

    assert "/tools" in texto
    assert "/skills" in texto
    assert "/help" in texto
    assert "resumir — Resume textos longos" in texto


def _roda_cli(tmp_path, monkeypatch, *flags: str, respostas=("oi",)) -> int:
    import formiga.agent.factory as factory
    from formiga.cli import main

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        factory,
        "build_chat_client",
        lambda config: FakeChatClient([ChatResponse(content="ok")]),
    )
    restantes = iter(respostas)

    def fake_input(_prompt: str) -> str:
        try:
            return next(restantes)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr("builtins.input", fake_input)
    return main(
        ["agent", "--local", "--session-dir", str(tmp_path / "sessoes"), *flags]
    )


def test_cli_limpa_tela_e_colore_em_terminal_forcado(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert _roda_cli(tmp_path, monkeypatch) == 0

    out = capsys.readouterr().out
    assert "\x1b[2J\x1b[H" in out
    assert "\x1b[36m" in out
    assert "FERRAMENTAS" in out


def test_cli_no_clear_mantem_cores(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert _roda_cli(tmp_path, monkeypatch, "--no-clear") == 0

    out = capsys.readouterr().out
    assert "\x1b[2J\x1b[H" not in out
    assert "\x1b[36m" in out


def test_cli_no_color_nao_emite_ansi(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert _roda_cli(tmp_path, monkeypatch, "--no-color") == 0

    out = capsys.readouterr().out
    assert "\x1b[" not in out
    assert "formiga agent · sessão:" in out


def test_help_via_cli_mostra_skills(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    _write_skill(home, "checklist", "Checklist de entrega")

    assert _roda_cli(
        tmp_path, monkeypatch, respostas=("/help", "/checklist")
    ) == 0

    out = capsys.readouterr().out
    assert "/skills" in out
    assert "Checklist de entrega" in out
    assert "será expandida na próxima mensagem" in out
