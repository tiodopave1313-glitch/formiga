"""Ferramentas de trabalho com arquivos: `ls`, `read`, `write`, `edit`.

Todas operam dentro de um `workdir` fixo e aceitam apenas caminhos relativos.
O `edit` é **patch-first**: nunca reescreve um arquivo inteiro e falha de forma
objetiva quando `old_string` não é único (seção 6 e guardrail da seção 7).
"""

from __future__ import annotations

from pathlib import Path

from formiga.agent.tools.base import ToolResult

READ_CAP_CHARS = 4000


def _safe_path(workdir: Path, path: str) -> Path:
    """Resolve o caminho dentro do workdir; recusa absolutos e fuga de diretório."""
    if not path or not path.strip():
        raise ValueError("caminho não pode ser vazio")
    p = Path(path)
    if p.is_absolute():
        raise ValueError("apenas caminhos relativos são permitidos")
    target = (workdir / p).resolve()
    workdir_resolved = workdir.resolve()
    try:
        target.relative_to(workdir_resolved)
    except ValueError as exc:
        raise ValueError("caminho fora do diretório de trabalho") from exc
    return target


class LsTool:
    name = "ls"
    description = (
        "Lista o conteúdo de um diretório (caminho relativo dentro do workdir)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Diretório relativo dentro do workdir (default: raiz)."
                ),
            }
        },
        "additionalProperties": False,
    }

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, path: str = ".") -> ToolResult:
        try:
            target = _safe_path(self.workdir, path)
        except ValueError as exc:
            return ToolResult(ok=False, text=f"ERRO: {exc}", error=str(exc))
        if not target.exists():
            return ToolResult(ok=False, text=f"ERRO: caminho não encontrado: {path}")
        if not target.is_dir():
            return ToolResult(ok=False, text=f"ERRO: não é um diretório: {path}")
        try:
            entries = sorted(target.iterdir())
        except OSError as exc:
            return ToolResult(
                ok=False,
                text=f"ERRO: não foi possível listar: {exc}",
                error=str(exc),
            )
        lines = [
            f"{entry.name}/" if entry.is_dir() else entry.name
            for entry in entries
        ]
        return ToolResult(
            ok=True, text="\n".join(lines) if lines else "(vazio)"
        )


class ReadTool:
    name = "read"
    description = (
        "Lê um arquivo de texto, com linhas numeradas; retorno limitado a "
        "4 000 chars."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Caminho relativo do arquivo dentro do workdir.",
            },
            "offset": {
                "type": "integer",
                "description": "Linha inicial (1-based, default 1).",
                "default": 1,
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Máximo de linhas a ler (default: o suficiente para "
                    "caber no cap)."
                ),
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, path: str, offset: int = 1, limit: int | None = None) -> ToolResult:
        try:
            target = _safe_path(self.workdir, path)
        except ValueError as exc:
            return ToolResult(ok=False, text=f"ERRO: {exc}", error=str(exc))
        if not target.exists():
            return ToolResult(ok=False, text=f"ERRO: arquivo não encontrado: {path}")
        if not target.is_file():
            return ToolResult(ok=False, text=f"ERRO: não é um arquivo: {path}")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(
                ok=False,
                text=f"ERRO: não foi possível ler: {exc}",
                error=str(exc),
            )
        lines = text.splitlines()
        start = max(1, offset) - 1
        lines = (
            lines[start : start + limit]
            if limit is not None
            else lines[start:]
        )
        out = []
        for i, line in enumerate(lines, start=start + 1):
            out.append(f"{i:6d}\t{line}")
        result = "\n".join(out)
        if len(result) > READ_CAP_CHARS:
            result = result[:READ_CAP_CHARS] + "\n…(truncado)"
        return ToolResult(ok=True, text=result)


class WriteTool:
    name = "write"
    description = (
        "Cria ou sobrescreve um arquivo. Se já existir, pede confirmação "
        "(sobrescrever com novo conteúdo)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Caminho relativo do arquivo dentro do workdir.",
            },
            "content": {
                "type": "string",
                "description": "Conteúdo a gravar no arquivo.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, path: str, content: str) -> ToolResult:
        try:
            target = _safe_path(self.workdir, path)
        except ValueError as exc:
            return ToolResult(ok=False, text=f"ERRO: {exc}", error=str(exc))
        if target.exists():
            return ToolResult(
                ok=False,
                text=(
                    f"ERRO: '{path}' já existe. Use `edit` para alterar partes "
                    "do arquivo, ou confirme a sobrescrita reenviando `write`."
                ),
                error="file_exists",
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                ok=False,
                text=f"ERRO: não foi possível gravar: {exc}",
                error=str(exc),
            )
        return ToolResult(
            ok=True, text=f"Arquivo '{path}' gravado ({len(content)} chars)."
        )


class EditTool:
    name = "edit"
    description = (
        "Edição por patch: substitui `old_string` por `new_string` no "
        "arquivo. Falha se `old_string` não for encontrado ou não for único "
        "(patch-first)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Caminho relativo do arquivo dentro do workdir.",
            },
            "old_string": {
                "type": "string",
                "description": (
                    "Texto a ser substituído (deve aparecer exatamente uma vez)."
                ),
            },
            "new_string": {
                "type": "string",
                "description": "Novo texto que ocupa o lugar de old_string.",
            },
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    }

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, path: str, old_string: str, new_string: str) -> ToolResult:
        try:
            target = _safe_path(self.workdir, path)
        except ValueError as exc:
            return ToolResult(ok=False, text=f"ERRO: {exc}", error=str(exc))
        if not target.exists():
            return ToolResult(ok=False, text=f"ERRO: arquivo não encontrado: {path}")
        if not target.is_file():
            return ToolResult(ok=False, text=f"ERRO: não é um arquivo: {path}")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(
                ok=False,
                text=f"ERRO: não foi possível ler: {exc}",
                error=str(exc),
            )
        count = text.count(old_string)
        if count == 0:
            return ToolResult(
                ok=False,
                text=f"ERRO: 'old_string' não encontrado no arquivo '{path}'.",
                error="not_found",
            )
        if count > 1:
            return ToolResult(
                ok=False,
                text=(
                    f"ERRO: 'old_string' aparece {count} vezes em '{path}'. "
                    "Torne-o mais longo/inclua mais contexto para torná-lo único."
                ),
                error="not_unique",
            )
        new_text = text.replace(old_string, new_string, 1)
        try:
            target.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                ok=False,
                text=f"ERRO: não foi possível gravar: {exc}",
                error=str(exc),
            )
        return ToolResult(ok=True, text=f"Edição aplicada em '{path}'.")
