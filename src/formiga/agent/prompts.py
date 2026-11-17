"""System prompt do agente Formiga (PT-BR, seção 7 e 6.3 do PRD).

O texto base (regras de disciplina e formato de resposta) é estático. A lista
de ferramentas disponíveis é montada dinamicamente a partir dos registros do
registry (`build_system_prompt`), para que nenhuma ferramenta concreta seja
conhecida pelo núcleo do agente.
"""

from __future__ import annotations

from formiga.agent.extensions.registry import ExtensionRegistry

BASE = """\
Você é o Formiga Agent, um harness agêntico mínimo. Você executa tarefas por
meio de ferramentas, uma por iteração.

REGRAS DE DISCIPLINA:
- Uma tarefa por chamada ao modelo. Se a tarefa acabar, responda com texto
  final (sem chamar ferramenta).
- Abstenção é válida: não invente fatos. Cite apenas o que as ferramentas
  retornaram.
- Se uma ferramenta falhar com `ERRO:`, tente uma vez com correção ou responda
  com o que tiver.
- Não execute ações destrutivas. O `bash` recusa padrões perigosos.
- Mantenha o foco no objetivo original da sessão; não se disperse.

FERRAMENTAS DISPONÍVEIS (escolha UMA por iteração):

{ferramentas}

FORMATO DE RESPOSTA:
- Se precisar chamar uma ferramenta, chame apenas uma e aguarde o resultado.
- Quando a tarefa estiver completa, responda em texto final, em português,
  fundamentado nos resultados das ferramentas.
"""


def _parameter_resumo(parameters: dict) -> str:
    """Renderiza um resumo legível do JSON Schema de parâmetros."""
    props = parameters.get("properties", {}) or {}
    required = set(parameters.get("required", []) or [])
    if not props:
        return "sem parâmetros."
    partes = []
    for nome, spec in props.items():
        tipo = spec.get("type", "?")
        obrigatorio = "obrigatório" if nome in required else "opcional"
        descricao = spec.get("description", "")
        trecho = f"`{nome}` ({tipo}, {obrigatorio})"
        if descricao:
            trecho += f" — {descricao}"
        default = spec.get("default")
        if default is not None:
            trecho += f" (default {default})"
        partes.append(trecho)
    return "; ".join(partes) + "."


def build_system_prompt(registry: ExtensionRegistry) -> str:
    """Monta o system prompt a partir dos specs registrados no registry.

    Cada ferramenta ativa (não lazy) gera um parágrafo numerado com nome,
    descrição, parâmetros e, quando houver, o `prompt_hint` contribuído pela
    extensão. A ordem de exibição segue a ordem de carga do registry.
    """
    specs = [
        item
        for item in registry.registrations.values()
        if not item.lazy
    ]
    if not specs:
        ferramentas = "(nenhuma ferramenta ativa — responda diretamente ao usuário.)"
    else:
        linhas = []
        for indice, registro in enumerate(specs, start=1):
            tool = registro.tool
            linhas.append(
                f"{indice}) `{tool.name}` — {tool.description}\n"
                f"   Parâmetros: {_parameter_resumo(tool.parameters)}"
            )
            if registro.prompt_hint:
                linhas.append(f"   {registro.prompt_hint}")
        ferramentas = "\n\n".join(linhas)
    return BASE.format(ferramentas=ferramentas)


def system_prompt_com_extensoes(registry: ExtensionRegistry) -> str:
    """Alias explícito para `build_system_prompt` (nome descritivo)."""
    return build_system_prompt(registry)
