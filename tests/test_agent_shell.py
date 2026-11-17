"""Testes da ferramenta `bash` (offline, disco temporário)."""

from __future__ import annotations

from pathlib import Path

from formiga.agent.tools.shell import BashTool


def test_bash_comando_simples(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("echo ola mundo")
    assert out.ok
    assert "ola mundo" in out.text


def test_bash_sem_saida(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("true")
    assert out.ok
    assert out.text == "(sem saída)"


def test_bash_codigo_nao_zero(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("false")
    assert not out.ok
    assert "código 1" in out.text


def test_bash_timeout(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("sleep 10", timeout=1)
    assert not out.ok
    assert "timeout" in out.text.lower()


def test_bash_recusa_rm_rf(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("rm -rf /")
    assert not out.ok
    assert "recusado" in out.text.lower()


def test_bash_recusa_mkfs(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("mkfs.ext4 /dev/sda1")
    assert not out.ok
    assert "recusado" in out.text.lower()


def test_bash_recusa_dd(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("dd if=/dev/zero of=/dev/sda")
    assert not out.ok
    assert "recusado" in out.text.lower()


def test_bash_recusa_shutdown(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("shutdown now")
    assert not out.ok
    assert "recusado" in out.text.lower()


def test_bash_recusa_pip_uninstall(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("pip uninstall alguma-coisa")
    assert not out.ok
    assert "recusado" in out.text.lower()


def test_bash_agent_unsafe_desativa_lista(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_UNSAFE", "1")
    tool = BashTool(tmp_path)
    # `rm -rf /` ainda é perigoso mas com AGENT_UNSAFE=1 tenta executar
    # (vai falhar por não existir, mas não deve ser recusado pela lista)
    out = tool.execute("rm -rf /tmp/nao_existe_xyz")
    # O erro será de execução (arquivo não existe), não de recusa da lista
    assert "recusado pela lista de negação" not in out.text


def test_bash_cap_saida_cauda(tmp_path: Path):
    # Gera saída maior que 8000 chars
    grande = "x" * 9000
    tool = BashTool(tmp_path)
    out = tool.execute(f"printf '%s' '{grande}'")
    assert out.ok
    assert len(out.text) <= 8000 + 30  # cap + sufixo de truncado
    assert "truncado" in out.text


def test_bash_cwd_no_workdir(tmp_path: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "arquivo.txt").write_text("conteudo")
    tool = BashTool(tmp_path)
    out = tool.execute("cat sub/arquivo.txt")
    assert out.ok
    assert "conteudo" in out.text


def test_bash_comando_vazio(tmp_path: Path):
    tool = BashTool(tmp_path)
    out = tool.execute("")
    assert not out.ok
    assert "vazio" in out.text.lower()
