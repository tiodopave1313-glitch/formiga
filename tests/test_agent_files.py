"""Testes das ferramentas de arquivo (offline, disco temporário)."""

from __future__ import annotations

from pathlib import Path

from formiga.agent.tools.files import EditTool, LsTool, ReadTool, WriteTool


def test_ls_listagem(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "sub").mkdir()
    tool = LsTool(tmp_path)
    out = tool.execute(".")
    assert out.ok
    nomes = out.text.splitlines()
    assert "a.txt" in nomes
    assert "sub/" in nomes


def test_ls_caminho_fora_do_workdir_rejeitado(tmp_path: Path):
    tool = LsTool(tmp_path)
    out = tool.execute("../")
    assert not out.ok
    assert "fora do diretório" in out.text or "apenas caminhos relativos" in out.text


def test_read_linhas_numeradas(tmp_path: Path):
    arquivo = tmp_path / "f.txt"
    arquivo.write_text("\n".join(f"linha {i}" for i in range(1, 101)))
    tool = ReadTool(tmp_path)
    out = tool.execute("f.txt", offset=10, limit=5)
    assert out.ok
    linhas = out.text.splitlines()
    assert any("linha 10" in linha for linha in linhas)
    assert any("linha 14" in linha for linha in linhas)
    assert len(linhas) == 5


def test_read_truncado_ao_cap(tmp_path: Path):
    arquivo = tmp_path / "grande.txt"
    arquivo.write_text("x" * 5000)
    tool = ReadTool(tmp_path)
    out = tool.execute("grande.txt")
    assert out.ok
    assert len(out.text) <= 4000 + 20  # cap + sufixo de truncado
    assert "truncado" in out.text


def test_write_novo_arquivo(tmp_path: Path):
    tool = WriteTool(tmp_path)
    out = tool.execute("novo.txt", "conteúdo inicial")
    assert out.ok
    assert (tmp_path / "novo.txt").read_text() == "conteúdo inicial"


def test_write_recusa_arquivo_existente(tmp_path: Path):
    (tmp_path / "existe.txt").write_text("antigo")
    tool = WriteTool(tmp_path)
    out = tool.execute("existe.txt", "novo")
    assert not out.ok
    assert "já existe" in out.text
    assert (tmp_path / "existe.txt").read_text() == "antigo"  # inalterado


def test_edit_sucesso(tmp_path: Path):
    (tmp_path / "f.txt").write_text("olá mundo\nsegunda linha\n")
    tool = EditTool(tmp_path)
    out = tool.execute("f.txt", "mundo", "there")
    assert out.ok
    assert (tmp_path / "f.txt").read_text() == "olá there\nsegunda linha\n"


def test_edit_nao_encontrado(tmp_path: Path):
    (tmp_path / "f.txt").write_text("olá mundo\n")
    tool = EditTool(tmp_path)
    out = tool.execute("f.txt", "inexistente", "x")
    assert not out.ok
    assert "não encontrado" in out.text


def test_edit_nao_unico(tmp_path: Path):
    (tmp_path / "f.txt").write_text("aa\naa\n")
    tool = EditTool(tmp_path)
    out = tool.execute("f.txt", "aa", "bb")
    assert not out.ok
    assert "aparece 2 vezes" in out.text or "não é único" in out.text
