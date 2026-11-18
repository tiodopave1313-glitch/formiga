"""Extensão builtin para skills declarativas (Fase 9, PRD §14)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from formiga.agent.extensions.api import ExtensionAPI
from formiga.agent.tools.base import ToolResult
from formiga.ext.skills.skill import SkillError, parse_skill, validar_nome
from formiga.ext.skills.store import SkillStore

_MAX_SKILL_CHARS = 24_000


class SkillManageTool:
    """Lista skills ou stageia gravação/exclusão para aprovação explícita."""

    name = "skill_manage"
    description = (
        "Lista skills ou propõe criar/remover uma skill declarativa. "
        "Write/delete não alteram arquivos sem aprovação humana em /skills."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "write", "delete"]},
            "name": {"type": "string", "description": "Nome kebab-case da skill."},
            "content": {
                "type": "string",
                "description": "SKILL.md completo com frontmatter (para write).",
            },
            "source": {
                "type": "string",
                "enum": ["global", "project"],
                "description": "Destino; project exige trust explícito.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: SkillStore, pending_path: Path) -> None:
        self.store = store
        self.pending_path = pending_path
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.pending_path.exists():
            self.pending_path.write_text("[]\n", encoding="utf-8")

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def pending(self) -> list[dict[str, str]]:
        try:
            value = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(value, list):
            return []
        return [
            item
            for item in value
            if isinstance(item, dict)
            and {"id", "action", "name", "source", "content"}.issubset(item)
            and item["action"] in {"write", "delete"}
            and item["source"] in {"global", "project"}
            and isinstance(item["id"], str)
            and isinstance(item["name"], str)
            and isinstance(item["content"], str)
        ]

    def save_pending(self, items: list[dict[str, str]]) -> None:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.pending_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.pending_path)

    def execute(
        self,
        action: str,
        name: str = "",
        content: str = "",
        source: str = "global",
    ) -> ToolResult:
        action = action.strip().lower()
        if action == "list":
            lines = [
                f"/{skill.name} — {skill.description} [{skill.source}]"
                for skill in self.store.skills
            ]
            return ToolResult(ok=True, text="\n".join(lines) or "Nenhuma skill instalada.")
        if action not in {"write", "delete"}:
            return ToolResult(ok=False, text="ERRO: action deve ser list, write ou delete.")
        try:
            name = validar_nome(name)
        except SkillError as exc:
            return ToolResult(ok=False, text=f"ERRO: {exc}")
        if source not in {"global", "project"}:
            return ToolResult(ok=False, text="ERRO: source deve ser global ou project.")
        if source == "project" and not self.store.trusted:
            return ToolResult(ok=False, text="ERRO: projeto não está na allowlist de trust.")
        if action == "write":
            if not content or len(content) > _MAX_SKILL_CHARS:
                return ToolResult(
                    ok=False,
                    text=f"ERRO: conteúdo vazio ou maior que {_MAX_SKILL_CHARS} caracteres.",
                )
            validation_path = self.pending_path.parent / f".{name}.validate.SKILL.md"
            try:
                validation_path.write_text(content, encoding="utf-8")
                parsed = parse_skill(validation_path, source=source)
                if parsed.name != name:
                    return ToolResult(
                        ok=False,
                        text=(
                            f"ERRO: o nome do frontmatter ({parsed.name}) "
                            f"não corresponde ao nome solicitado ({name})."
                        ),
                    )
            except (OSError, SkillError) as exc:
                return ToolResult(ok=False, text=f"ERRO: skill inválida: {exc}")
            finally:
                validation_path.unlink(missing_ok=True)
        else:
            skill = self.store.get(name)
            if skill is None:
                return ToolResult(ok=False, text=f"ERRO: skill não encontrada: {name}")
            if skill.source != source:
                return ToolResult(
                    ok=False,
                    text=f"ERRO: skill {name} não pertence à origem {source}.",
                )

        proposal = {
            "id": uuid.uuid4().hex[:10],
            "action": action,
            "name": name,
            "source": source,
            "content": content if action == "write" else "",
        }
        proposals = self.pending()
        proposals.append(proposal)
        self.save_pending(proposals)
        return ToolResult(
            ok=True,
            text=(
                f"Proposta {proposal['id']} stageada, sem alterar arquivos. "
                f"Aprove com /skills approve {proposal['id']} ou descarte com "
                f"/skills reject {proposal['id']}."
            ),
        )


def setup(pi: ExtensionAPI) -> None:
    """Registra `/skills`, expansão sob demanda e `skill_manage`."""
    root = Path(getattr(pi.runtime_config, "agent_workdir", ".")).expanduser().resolve()
    store = SkillStore.discover(project_root=root)
    pending_path = Path.home() / ".formiga" / "skills" / "pending.json"
    manager = SkillManageTool(store, pending_path)
    pending_expansion: list[str] = []

    def reload_store() -> None:
        fresh = SkillStore.discover(project_root=root)
        store.skills = fresh.skills
        store.warnings = fresh.warnings
        store.trusted = fresh.trusted
        for skill in store.skills:
            if skill.name == "skills" or skill.name in pi.registry.commands:
                continue
            pi.register_command(
                skill.name,
                lambda _args="", skill_name=skill.name: expand_skill(skill_name),
            )

    def expand_skill(name: str) -> str:
        skill = store.get(name)
        if skill is None:
            return f"Skill não encontrada: {name}. Veja /skills."
        pending_expansion.append(skill.name)
        return f"Skill /{skill.name} será expandida na próxima mensagem."

    def command_skills(arguments: str = "") -> str:
        parts = arguments.split(None, 1)
        subcommand = parts[0].lower() if parts else "list"
        argument = parts[1].strip() if len(parts) > 1 else ""

        if subcommand == "list":
            lines = [
                f"/{skill.name} — {skill.description}"
                + (f" (quando usar: {skill.when_to_use})" if skill.when_to_use else "")
                + f" [{skill.source}]"
                for skill in store.skills
            ]
            lines.extend(f"Aviso: {warning}" for warning in store.warnings)
            if lines:
                lines.append("Use /nome-da-skill para expandir uma skill no próximo turno.")
            return "\n".join(lines) if lines else "Nenhuma skill instalada."

        if subcommand == "pending":
            proposals = manager.pending()
            if not proposals:
                return "Nenhuma proposta de skill pendente."
            return "\n".join(
                f"{item['id']} {item['action']} {item['name']} [{item['source']}]"
                for item in proposals
            )

        if subcommand in {"approve", "reject"}:
            if not argument:
                return f"Uso: /skills {subcommand} <id>"
            proposals = manager.pending()
            proposal = next((item for item in proposals if item["id"] == argument), None)
            if proposal is None:
                return f"Proposta não encontrada: {argument}"
            if subcommand == "reject":
                manager.save_pending([item for item in proposals if item["id"] != argument])
                return f"Proposta {argument} descartada."
            if proposal["source"] == "project" and not store.trusted:
                return "Aprovação recusada: projeto não confiável."
            try:
                proposal["name"] = validar_nome(proposal["name"])
                if proposal["action"] == "write":
                    parse_path = manager.pending_path.parent / (
                        f".{proposal['id']}.approve.SKILL.md"
                    )
                    try:
                        parse_path.write_text(proposal["content"], encoding="utf-8")
                        parsed = parse_skill(parse_path, source=proposal["source"])
                    finally:
                        parse_path.unlink(missing_ok=True)
                    if parsed.name != proposal["name"]:
                        return "Aprovação recusada: nome no frontmatter não corresponde."
                    store.write(
                        proposal["name"], proposal["content"], proposal["source"]
                    )
                elif not store.delete(proposal["name"], proposal["source"]):
                    manager.save_pending(
                        [item for item in proposals if item["id"] != argument]
                    )
                    return "A skill já não existe; proposta removida."
            except (OSError, SkillError) as exc:
                return f"Falha ao aplicar proposta: {exc}"
            manager.save_pending([item for item in proposals if item["id"] != argument])
            reload_store()
            pi.emit(
                "skill_manage_approved",
                {"id": argument, "action": proposal["action"], "name": proposal["name"]},
            )
            return f"Proposta {argument} aprovada e aplicada."

        return "Uso: /skills [list|pending|approve <id>|reject <id>]"

    pi.register_command("skills", command_skills)

    def resumo_skills() -> list[str]:
        return [
            f"{skill.name} — {skill.description}"
            + (" [projeto]" if skill.source == "project" else "")
            for skill in store.skills
        ]

    pi.register_summary("skills", resumo_skills)

    for skill in store.skills:
        if skill.name == "skills" or skill.name in pi.registry.commands:
            store.warnings.append(
                f"comando de skill ignorado por conflito: /{skill.name}"
            )
            continue
        pi.register_command(
            skill.name,
            lambda _args="", skill_name=skill.name: expand_skill(skill_name),
        )

    def on_input(question: str) -> str:
        if not pending_expansion:
            return question
        name = pending_expansion.pop(0)
        skill = store.get(name)
        if skill is None:
            return question
        pi.emit(
            "skill_expanded",
            {"name": skill.name, "source": skill.source, "path": str(skill.path)},
        )
        body = skill.body[:_MAX_SKILL_CHARS]
        return (
            f"[Skill expandida: {skill.name} — {skill.description}]\n"
            f"{body}\n\nPedido do usuário: {question}"
        )

    pi.on("input", on_input)
    pi.register_tool(manager)

    def on_task_end(data: dict) -> None:
        if data.get("successful") and data.get("successful_tools", 0):
            pi.ui.notify(
                "Tarefa concluída com uso de ferramentas. Se o procedimento for "
                "reutilizável, proponha uma skill com skill_manage(action='write'); "
                "nada será gravado sem /skills approve <id>."
            )

    pi.on("task_end", on_task_end)
