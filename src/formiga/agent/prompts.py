"""System prompt do agente Formiga (PT-BR, seção 7, 6.3 e 8.4 do PRD v2).

O texto base (regras de disciplina, tabela de posicionamento e formato de
resposta) é estático. A lista de ferramentas disponíveis e as seções
contribuídas por extensões são montadas dinamicamente a partir dos registros
do registry, para que nenhuma ferramenta concreta seja conhecida pelo núcleo
do agente.

Cada seção contribuída por extensão (via hook `before_agent_start`) é
validada contra o teto de 400 tokens (seção 9.1 do PRD).
"""

from __future__ import annotations

from formiga.agent.extensions.budget import check_section_budget
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

POSICIONAMENTO DE FERRAMENTAS (seção 8.4 do PRD):
- Checagem rápida de 1–2 fatos; snippets bastam → `web_search` (+ `web_fetch`
  em 1–2 URLs).
- URL específica informada pelo usuário → `web_fetch` direto.
- Resposta fundamentada, com fontes e relatório → `deep_search`.
- Trabalho local: arquivos, comandos, configuração → `core`.
- Ferramenta latente do catálogo → `activate_tool`.

Regra: pergunta com referências/evidências → `deep_search`; fato pontual →
`web_search` primeiro, `deep_search` só se os snippets não bastarem.

FERRAMENTAS DISPONÍVEIS (escolha UMA por iteração):

{ferramentas}

SEÇÕES DE EXTENSÃO:
{secoes_extensao}

FORMATO DE RESPOSTA:
- Se precisar chamar uma ferramenta, chame apenas uma e aguarde o resultado.
- Quando a tarefa estiver completa, responda em texto final, em português,
  fundamentado nos resultados das ferramentas.
"""

SECOES_EXTENSAO_PLACEHOLDER = "(nenhuma seção de extensão contribuída.)"


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


def _ferramentas_texto(specs) -> str:
    """Renderiza a lista de ferramentas ativas a partir dos registros."""
    if not specs:
        return "(nenhuma ferramenta ativa — responda diretamente ao usuário.)"
    linhas = []
    for indice, registro in enumerate(specs, start=1):
        tool = registro.tool
        linhas.append(
            f"{indice}) `{tool.name}` — {tool.description}\n"
            f"   Parâmetros: {_parameter_resumo(tool.parameters)}"
        )
        if registro.prompt_hint:
            linhas.append(f"   {registro.prompt_hint}")
    return "\n\n".join(linhas)


def _secoes_extensao_texto(secoes: dict[str, str]) -> str:
    """Renderiza as seções contribuídas por extensões, validadas contra o teto."""
    if not secoes:
        return SECOES_EXTENSAO_PLACEHOLDER
    linhas = []
    for nome, texto in secoes.items():
        check_section_budget(texto)
        linhas.append(f"## {nome}\n{texto}")
    return "\n\n".join(linhas)


def build_system_prompt(
    registry: ExtensionRegistry,
    secoes_extensao: dict[str, str] | None = None,
) -> str:
    """Monta o system prompt a partir dos specs do registry e seções de extensão.

    Cada ferramenta ativa (não lazy) gera um parágrafo numerado com nome,
    descrição, parâmetros e, quando houver, o `prompt_hint` contribuído pela
    extensão. A ordem de exibição segue a ordem de carga do registry.

    `secoes_extensao` é um mapa `nome_da_extensão -> texto da seção`,
    contribuído via hook `before_agent_start`. Cada seção é validada contra
    o teto de 400 tokens (seção 9.1 do PRD).
    """
    specs = [
        item
        for item in registry.registrations.values()
        if not item.lazy
    ]
    secoes = secoes_extensao or {}
    return BASE.format(
        ferramentas=_ferramentas_texto(specs),
        secoes_extensao=_secoes_extensao_texto(secoes),
    )


def system_prompt_com_extensoes(
    registry: ExtensionRegistry, secoes_extensao: dict[str, str] | None = None
) -> str:
    """Alias explícito para `build_system_prompt` (nome descritivo)."""
    return build_system_prompt(registry, secoes_extensao=secoes_extensao)
