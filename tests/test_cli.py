"""Testes da CLI: comandos, códigos de saída e validação de entrada."""

from __future__ import annotations

from formiga.cli import main


def test_version(capsys):
    assert main(["version"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("formiga ")


def test_invalid_config_exit_2(monkeypatch, tmp_path):
    monkeypatch.setenv("FORMIGA_SEARXNG_URL", "notaurl")
    code = main(
        [
            "research",
            "pergunta",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2


def test_empty_question_exit_2():
    assert main(["research", "   "]) == 2


def test_existing_output_dir_exit_2(tmp_path):
    existing = tmp_path / "out"
    existing.mkdir()
    # Sem rede/modelo: deve falhar no prepare_output_dir antes de qualquer I/O externo.
    code = main(["research", "pergunta", "--output", str(existing)])
    assert code == 2
