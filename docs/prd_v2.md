# PRD — Formiga 2.0

**Arquivo:** `docs/prd_v2.md`
**Branch:** `prd-formiga-v2`
**Status:** proposta para implementação
**Base de código:** evolução direta deste repositório — **não é um rewrite**. O motor de
pesquisa, o loop, as interfaces, os backends e a suíte de testes do v1 continuam;
o v2 os desacopla, os generaliza e acrescenta extensibilidade, gateway e memória.
**Interface:** CLI interativa (padrão) · TUI Textual via `--tui` (extra `gui`) · `--print`
headless · gateway local (Fase 6 do pós-MVP)
**Linguagem:** Python 3.11+, Linux · **sem gerenciador de ambiente obrigatório**
(`python3 -m venv` + `pip install -e .` basta; o `uv` é conveniência de
desenvolvimento, não requisito de runtime — decisão explícita, diferente do Hermes,
cujo instalador amarra tudo ao uv/PM)
**Desenvolvimento:** OpenCode
**Modelo de teste:** Gemma 4 E4B (Ollama local, default — sem chave) ·
Nemotron 3.5 Bolt E4B (NIM remoto, alternativa)
**Versão alvo do pacote:** `formiga` 2.0.0

---

## 1. Visão

O **Formiga 2.0** é um **harness de agente completo, minimalista no MVP e
extensível**, projetado para LLMs de **8 bilhões de parâmetros totais** —
modelos de eficiência tipo Gemma 4 E2B/E4B e Nemotron Bolt E4B (2–4B efetivos,
tool calling instável, janela útil curta na prática).

O Formiga 2.0 conversa, lê e escreve arquivos, executa comandos, busca e lê a
web e **pesquisa profundamente** — tudo com o mesmo modelo pequeno. Ele **não é
um agente de código**: é um agente de trabalho geral (arquivos, terminal, web,
pesquisa, escrita), e suas ferramentas refletem isso.

Três influências diretas, já absorvidas nos PRDs do v1:

- **pi (earendil-works)** — núcleo minúsculo e **sistema de extensões** como
  mecanismo central: API com `register_tool`/`register_command`, eventos de
  ciclo de vida encadeados como middleware, descoberta em diretórios, trust de
  projeto. No 2.0, **nenhuma ferramenta é fixa no core** — tudo vem do registry.
- **Hermes (NousResearch)** — o agente cresce com o usuário: **gateway** que
  mantém sessões vivas quando o terminal fecha, **memória** (busca nas sessões
  passadas + memória curada com nudges + perfil), **tarefas agendadas** (cron),
  execução observável e interrompível.
- **Relatório de 8B (`RELATORIO_AGENTE_8B.md`)** — as falhas de um modelo
  pequeno são, em grande parte, defeitos do harness: orçamento, caps, parser
  tolerante, anti-loop, patch-first, bash delimitado.

A tese central, herdada do v1:

> **O harness controla o processo. O modelo interpreta e redige. As evidências
> delimitam o que pode ser afirmado. A extensibilidade não inunda o contexto.**

## 2. Problema

Um harness minimalista de referência (pi e similares) assume um modelo forte:
tool call sempre válido, janela ampla, autocorreção confiável. Um 8B de
eficiência (2–4B efetivos) falha de outras formas:

- repete a mesma chamada de ferramenta sem progresso;
- enche o contexto com resultados brutos e schemas acumulados;
- emite tool calls malformados (JSON quebrado, parâmetros errados);
- perde o objetivo original em sessões longas;
- executa ações destrutivas quando tem `bash`;
- confabula quando a busca falha.

O v1 já resolveu o **loop**: 8 ferramentas, guardrails, parser tolerante,
CLI/TUI/--print, sessão persistida — fases 1–4 implementadas e testadas
(`tests/test_agent_*.py`). O v1 atacou o problema inverso e provou a tese
(`docs/prd.md`): com o harness no comando, o mesmo modelo produz pesquisa
auditável.

O 2.0 ataca o que o v1 não pôde atacar sem reescrita:

1. **Crescer além das 8 ferramentas fixas** — `factory.py` importa tudo
   diretamente e `BUDGETED_TOOLS` está hardwired no loop. Sem um sistema de
   extensões, cada ferramenta nova é uma modificação no core, e cada modificação
   aumenta o prompt de um modelo que já é o limitado.
2. **Ser um agente "vivo"** — sem gateway, a sessão morre com o terminal;
   sem daemon não há tarefas agendadas; sem índice não há memória entre sessões.
3. **Escalar funcionalmente sem escalar o modelo** — ferramentas, memória,
   skills e agendamento entram como camadas sobre o loop, cada uma orçamentada.

## 3. Objetivos

### 3.1 Objetivos do MVP

1. **Núcleo desacoplado**: `agent/` (loop, parser, guardrails, sessão,
   prompts, chat) sem **nenhuma** ferramenta importada ou referenciada por
   nome; o único caminho do loop até uma ferramenta é o registry.
2. **Sistema de extensões** completo: API de extensão, registry, descoberta
   (builtin → pip → global → projeto), seis eventos encadeados, trust de
   projeto, comandos de inspeção.
3. **Três extensões embutidas**, todas pelo mesmo mecanismo que uma extensão de
   terceiros usaria:
   - `core` — `ls`, `read`, `write`, `edit`, `bash`;
   - `web` — `web_search`, `web_fetch`;
   - `deepsearch` — `deep_search`, ponte para o **motor de pesquisa do v1,
     intacto e reusado**.
4. **Compensação de 8B aplicada à extensibilidade**: cap de resultado uniforme,
   orçamento do agente, anti-loop em escada, patch-first, bash delimitado,
   eviction de contexto com âncora de objetivo, **orçamento de tokens de
   schemas** e **ferramentas lazy** via meta-ferramenta `activate_tool`.
5. **Perfis de modelo**: janela útil conservadora, thinking, amostragem e teto
   de geração por modelo, auto-selecionados pelo nome, com override.
6. **Interfaces**: CLI interativa padrão, TUI Textual (`--tui`, extra `gui`),
   `--print` headless; comandos `/tools`, `/ext`, `/budget`, `/new`.
7. **Backends do v1 mantidos**: Ollama, llama.cpp, OpenAI-compatível remoto
   (retries, backoff, failover opt-in, regra de wire corrigida do v1).
8. **Suíte do v1 continua verde**: os testes existentes (`test_agent_*`,
   `test_orchestrator`, `test_security`, ...) passam sem reescrever o que já
   está correto; um teste de caracterização garante equivalência.

### 3.2 Não objetivos do MVP

Ficam fora do MVP (fases 6–11 na seção 20):

- gateway de sessão, retomada de sessão, tarefas agendadas (cron);
- memória entre sessões, busca nas sessões passadas, perfil do usuário;
- skills (declarativas ou assistidas);
- sub-agentes, paralelismo de ferramentas, MCP;
- roteamento de ferramentas em 2 estágios (com ≤10 ativas o orçamento resolve;
  o lazy cobre o crescimento), compaction semântica (eviction resolve o MVP);
- eval gate formal, RAG, embeddings, rerank;
- escalada para modelo maior (failover de backend opt-in continua);
- plataformas de mensagem (Telegram/Discord/...), interface web/desktop;
- ferramentas de código avançadas (grep/AST, runner de testes, debugger,
  review de diff) — ver §3.3.

### 3.3 "Agente completo" — e o que não é

**Funções completas de agente** significa, neste PRD:

| Função | Estado |
|---|---|
| Conversa multi-turno com streaming e interrupção cooperativa | MVP (v1) |
| Ferramentas de arquivo: listar, ler, criar, **editar por patch** | MVP (v1 → ext `core`) |
| Shell com contenção e timeout | MVP (v1 → ext `core`) |
| Web: busca leve + leitura de páginas | MVP (v1 → ext `web`) |
| Pesquisa profunda com relatório auditável | MVP (v1 → ext `deepsearch`) |
| Sistema de extensões (ferramentas, comandos, eventos) | MVP (novo) |
| Sessão persistida, inspecionável, transcript legível | MVP (v1) |
| Anexar a sessões vivas via gateway | Pós-MVP (Fase 6) |
| Tarefas agendadas | Pós-MVP (Fase 7) |
| Memória e perfil entre sessões | Pós-MVP (Fase 8) |
| Skills | Pós-MVP (Fase 9) |
| Plataformas de mensagem | Pós-MVP (Fase 10) |

**Ele não é um agente de código.** Não há gravidade especial para repositórios:
nada de AST/grep estruturado, runner de testes integrado, debugger, lint gate
ou review de diff como centros de fluxo. As ferramentas de arquivo e shell
existem como **trabalho geral** — configurar serviços, mexer em notes, rodar
comandos, editar configs, autônomos escritos — e o `edit` patch-first é tão
bom para texto e configuração quanto para código. Quem quiser um harness de
código tem ferramentas para isso; o Formiga 2.0 não disputa esse espaço.

## 4. Princípios de produto

1. **Minimalismo**: núcleo pequeno; sem framework de agentes; dependências
   enxutas (httpx, trafilatura, pydantic; textual só no extra `gui`).
2. **O harness compensa o modelo pequeno** — inclusive na extensibilidade.
3. **Extensão é cidadã de primeira classe**: `deepsearch` não é privilegiada no
   código; tudo que o modelo chama vem do registry, pela mesma API de terceiros.
4. **Uma tarefa por chamada**: o modelo não decide fluxo de pipeline; o
   harness decide o que acontece quando.
5. **Estado fora do contexto**: histórico não é banco de dados; o estado da
   pesquisa vive em `state.json`; a memória (Fase 8) vive em arquivos.
6. **Proveniência antes de fluência**; **abstenção é válida**.
7. **Limites explícitos**: toda busca, leitura, chamada, extensão e sessão
   agendada consome orçamento verificável.
8. **Fontes e resultados de ferramentas são dados não confiáveis** — nunca
   instruções; memória de sessões passadas também é dado não confiável.
9. **Prompt estável por turno**: seções mudam entre turnos apenas por patch
   explicitamente causado (ativação lazy, eviction, nova extensão), registrado
   em evento — nunca silenciosamente.
10. **Execução observável e interrompível**: todo tool call visível; `Esc`/
    `Ctrl+C` cooperativo em qualquer interface.
11. **Zero dogma de ferramenta de dev ambiente**: funciona com venv+pip;
    não exige uv, Nix, Docker nem systemd.

## 5. Arquitetura

### 5.1 Estrutura alvo e transformação do código atual

```text
src/formiga/
├── cli.py                 # entrypoint: agent|research|cron|trust|gateway|version
├── config.py              # CLI > env > TOML > defaults (+ .env 0600)
├── configfile.py, envfile.py, envfile, models.py   # v1, mantidos
├── llm.py, ollama.py, llamacpp.py, openai.py, fallback.py   # backends v1, mantidos
│
├── agent/                 # NÚCLEO — não conhece nenhuma ferramenta concreta
│   ├── loop.py             # v1 + hooks de evento + eviction (perde BUDGETED_TOOLS)
│   ├── parser.py           # v1, endurecido
│   ├── guardrails.py       # v1 + budgets genéricos + eviction + âncora
│   ├── prompts.py          # SYSTEM_PROMPT estático → montagem por seções
│   ├── session.py          # v1 (messages.json, events.jsonl, transcript.md)
│   ├── chat.py             # v1 (3 backends, wire, streaming)
│   ├── profiles.py         # NOVO — perfis de modelo
│   ├── factory.py          # REESCRITO: discovery → registry → loop → interface
│   ├── tui/                # v1 (app.py, controller.py) — consumidor de eventos
│   └── extensions/         # NOVO — o coração do 2.0
│       ├── api.py          # ExtensionAPI
│       ├── registry.py     # extensões ativas, hooks encadeados, orçamentos
│       ├── discovery.py    # builtin → pip → global → projeto (+ trust)
│       ├── events.py       # tipos de evento e regras de encadeamento
│       └── budget.py       # tokens de schemas, lazy, eviction
│
├── ext/                    # EXTENSÕES EMBUTIDAS (mesma API de terceiros)
│   ├── core/               # ls, read, write, edit, bash  (hoje agent/tools/files+shell)
│   ├── web/                # web_search, web_fetch        (hoje agent/tools/web)
│   └── deepsearch/         # deep_search                  (hoje agent/tools/deepsearch)
│
├── orchestrator.py, budget.py, fetch.py, extract.py, evidence.py, report.py,
├── storage.py, search.py, searxng.py, fetcher.py, fetcher..., schemas.py, ...
│   # MOTOR DE PESQUISA v1 — INTACTO na raiz (contratos do prd.md inalterados)
│
└── (pós-MVP) gateway.py, cron.py, memory/ ...

~/.formiga/                 # config global, trust, extensões, memória, skills
.formiga/                   # extensões e skills do projeto (trust-gated)
```

| Código atual (branch `agente`) | Destino no 2.0 |
|---|---|
| `agent/loop.py` + `BUDGETED_TOOLS` | mantém; perde a lista hardwired, ganha hooks e eviction |
| `agent/factory.py` (8 tools importadas) | reescrito: `discovery → registry → AgentLoop` |
| `agent/tools/files.py`, `shell.py` | `ext/core/` |
| `agent/tools/web.py` | `ext/web/` |
| `agent/tools/deepsearch.py` | `ext/deepsearch/` (protocolo `Tool` idêntico) |
| `agent/tools/base.py` (`Tool`, `ToolResult`) | mantém (mesmo contrato para extensões) |
| `agent/prompts.py` (`SYSTEM_PROMPT`) | base de seções + contribuições de extensão |
| `agent/guardrails.py` | estendido (eviction, budgets declarados) |
| `agent/parser.py`, `session.py`, `chat.py`, `tui/` | mantidos, evolução pontual |
| `orchestrator.py` e cia. (raiz) | **intocados** — consumidos pela ext `deepsearch` |
| `llm.py`, `ollama.py`, `llamacpp.py`, `openai.py`, `fallback.py` | mantidos |
| `config.py`, `configfile.py`, `envfile.py` | estendidos (`[extensions]`, `[ext.*]`, `[profile]`) |
| `cli.py` | estendido (`trust`; pós-MVP: `gateway`, `cron`) |
| `tests/` (34 arquivos) | mantidos — regressão; + `test_ext_*`, `test_gateway_*`, ... |

Mover é preferível a copiar: `git mv` preserva histórico; os imports das
ferramentas são ajustados para `formiga.ext.*` e as classes são idênticas por
construção.

### 5.2 Regras de separação

- O core (`agent/`) não importa nada de `ext/` nem do motor de pesquisa; somente
  `factory.py` aciona a descoberta. Uma checagem estática em teste garante
  (`importlib` + assert de ausência de `formiga.ext` em `agent.loop`).
- `ext/deepsearch` é a única ponte para o motor; o motor não conhece o loop.
- A interface (CLI/TUI) não decide fluxo do agente; consome eventos.
- Extensões de terceiros têm exatamente a mesma API das embutidas; nenhuma
  classe embutida tem import privilegiado no loop.

## 6. Loop agêntico

Semântica do v1 (PRD do agente §5), com acoplamento invertido e hooks:

```text
usuário envia mensagem
        ↓
hooks: input (transformar / interceptar)                [extensões]
        ↓
before_agent_start: montagem do system prompt por seções [extensões]
        ↓
chamada ao LLM (streaming) ── texto ─────→ stream na interface
        │
        └─ tool call → parser tolerante → hooks tool_call (gate/mutar args)
                        ↓
                  orçamento declarado da tool → execução (cap uniforme)
                        ↓
                  hooks tool_result → mensagem `tool` no contexto
                        ↓
                  anti-loop verifica repetição → próximo turno | encerra
        ↓
modelo responde sem tool call → hooks turn_end → fim do turno
```

Regras (todas herdadas do v1, nenhuma removida):

- Um turno = uma chamada ao LLM + **até uma** tool call (sem paralelismo no MVP).
- `max_turns` por mensagem (24); orçamento da sessão: 120 chamadas LLM, 1800 s
  (relógio monotônico). Esgotamento encerra com resposta parcial explicada.
- Cancelamento cooperativo: `Esc`/`Ctrl+C` sinaliza; a ferramenta em curso
  termina no próprio timeout; a confirmação vem na fronteira seguinte.
- Erro de ferramenta → `ERRO: ...` no contexto (o modelo decide); erro de LLM
  degrada a chamada, não a sessão.
- Persistência atômica por turno (`messages.json`) + espelho em `transcript.md`
  + evento em `events.jsonl`.
- `messages[0]` é sempre a system message com as seções vigentes; um reenvio
  completo por chamada (regra v1) mantém o prompt estável e o cache local
  previsível.

## 7. Sistema de extensões

### 7.1 API de extensão

Uma extensão é um módulo Python com `setup(pi)`:

```python
# ~/.formiga/extensions/stress.py
def setup(pi):
    pi.register_tool(MyTool(),
                     budget_per_message=4,   # orçamento por mensagem (opcional)
                     category="geral",       # agrupamento p/ display e lazy
                     lazy=False)             # True → ativa via activate_tool
    pi.register_command("stress", handler)   # /stress na CLI e na TUI
    pi.on("before_agent_start", patch_prompt)  # contribuir seção do prompt
    pi.on("tool_call", gate)                   # {block, reason} ou mutar args
    pi.emit("stress_progress", {"step": 2})     # evento de UI
    pi.ui.notify("extensão carregada", "info")  # notify / setStatus
    cfg = pi.config                             # seção [ext.stress] do TOML
    dirs = pi.session                           # session_dir, research_dir, root
```

Contrato de ferramenta: **o protocolo do v1 sem alterações** — `name`,
`description`, `parameters` (JSON Schema), `schema()`, `execute(**kwargs) ->
ToolResult` (`ok`, `text`, `error`). Ferramentas do v1 migram sem mudar.

Superfície completa do MVP:

| Membro | Propósito |
|---|---|
| `register_tool(tool, *, budget_per_message, category, lazy)` | declara ferramenta ao registry |
| `register_command(name, handler)` | comando `/name` na CLI/TUI |
| `on(event, handler)` | subscreve um dos 6 eventos (§7.2) |
| `emit(event, data)` | evento customizado → interface + `events.jsonl` |
| `ui.notify(text, level)` / `ui.setStatus(key, text)` | feedback visual |
| `config` | seção `[ext.<nome>]` da extensão (dict, somente leitura) |
| `session` | diretórios e metadados da sessão corrente |

`register_tool` **não** aceita tocar em orçamentos do core, prompts base nem
guardrails: a API não expõe esses alvos (princípio de acoplamento frouxo).

### 7.2 Eventos (subconjunto essencial, encadeados)

| Evento | Momento | Retorno pode |
|---|---|---|
| `input` | entrada do usuário | transformar texto ou interceptar (gate) |
| `before_agent_start` | antes do turno | acrescentar seção ao system prompt |
| `context` | antes de cada chamada LLM | filtrar/windowar `messages[]` |
| `tool_call` | antes de executar | `{block, reason}` ou mutar `args` |
| `tool_result` | após executar | transformar o resultado |
| `turn_end` | fim do turno | observar (não bloqueia) |

Eventos de observação (sem retorno; para UI e logs): `llm_call`, `stream`,
`tool_start`, `tool_end`, `budget`, `interrupted`, `extension_loaded`, e os
customizados de `pi.emit` (o progresso do motor de pesquisa chega à TUI por
aqui — `deep_search_progress`, como no v1).

Encadeamento (herdado do pi): handlers rodam na **ordem de carga** (§7.3);
transformações encadeiam (o próximo vê o valor do anterior); um `block` de
`tool_call` interrompe a cadeia daquele call; erro em um handler é registrado
em `events.jsonl` e a cadeia continua — **extensão não derruba a sessão**.

> Fases pós-MVP podem ampliar a tabela (ex.: `session_end` na Fase 8,
> `job_start` na Fase 7) — o MVP a congela como as seis acima.

### 7.3 Descoberta e ordem de carga

Ordem **determinística** (fixa desde o dia 1 — o encadeamento depende dela):

1. **Builtin** — `formiga.ext.*`, conforme `[extensions].enabled`
   (default `["core", "web", "deepsearch"]`).
2. **Pip** — entry-points `formiga.extensions` (pacotes instalados pelo usuário).
3. **Global** — `~/.formiga/extensions/*.py` (um arquivo por extensão).
4. **Projeto** — `.formiga/extensions/*.py`, trust-gated (§7.4).

Dentro de cada fonte, ordem alfabética. Duplicata por nome: a primeira vence,
a segunda é ignorada com aviso. Falha de import ou de `setup()` **desabilita
apenas aquela extensão**, com aviso visível em `/ext` e `events.jsonl` — nunca
aborta o startup.

### 7.4 Trust de projeto

Extensões Python rodam com a permissão total do usuário (igual no pi — o README
documenta em destaque; não há sandbox no MVP):

- extensões de `.formiga/` só carregam se o diretório estiver em
  `[extensions].trusted_projects` do **config global** (`~/.formiga/config.toml`);
- sem pergunta interativa no MVP: `formiga trust <dir>` lista o que foi
  encontrado e grava na allowlist; `formiga untrust <dir>` remove;
- a sessão imprime extensões de projeto carregadas (e `events.jsonl` registra
  nome, fonte e ordem de todas — o ambiente é auditável).

### 7.5 Comandos de inspeção

- `/tools` — ferramentas ativas, origem (builtin/extensão), orçamento, estado
  (ativa / latente / expirada);
- `/ext` — extensões carregadas na ordem, fonte, falhas de carga;
- `/budget` — turnos, chamadas, tokens de contexto vs. janela, consumo por
  ferramenta orçamentada;
- `/new` — nova sessão (com confirmação, como no v1).

## 8. Ferramentas

### 8.1 `core` — primitivas de trabalho geral

| Tool | Assinatura | Notas (invariantes do v1) |
|---|---|---|
| `ls` | `(path?)` | Lista do `agent.workdir`; caminhos relativos apenas |
| `read` | `(path, offset?, limit?)` | Linhas numeradas; cap 4K de chars |
| `write` | `(path, content)` | Cria/sobrescreve; confirmação se o arquivo já existir |
| `edit` | `(path, old_string, new_string)` | **Patch-first**: falha objetiva se `old_string` não for único; nunca reescreve o arquivo inteiro |
| `bash` | `(command, timeout?)` | Workdir fixo; timeout 60 s; saída capada 8K na cauda; recusa lista de padrões irreversíveis (`rm -rf /`, `mkfs`, `dd if=`, shutdown, uninstall de pacotes, mutação fora do workdir); `AGENT_UNSAFE=1` desliga a lista |

Sem orçamento por mensagem (são primitivas); cap, anti-loop e `tool_call`
gate aplicam-se como a qualquer outra ferramenta.

### 8.2 `web` — via rápida

| Tool | Assinatura | Orçamento/mensagem |
|---|---|---|
| `web_search` | `(query, max_results?=6)` | 6 |
| `web_fetch` | `(url)` | 8 |

SearXNG configurado pelo usuário (o mesmo do motor); retorno capado 4K com
`título — url` + snippet; dedupe do `search.py`; fetcher com garantias do v1
intocadas (SSRF, caps 2 MB/20 s, sem proxies herdados, bloqueio de
loopback/privadas/link-local a cada redirecionamento). Exceder orçamento →
`ERRO:` orçamental, sem encerrar a sessão.

### 8.3 `deepsearch` — a vitrine do sistema de extensões

- Empacota o **motor de pesquisa do v1 sem alterá-lo**: planejar → buscar →
  extrair → verificar → sintetizar → auditar; saídas idênticas
  (`report.md`, `state.json`, `events.jsonl`, `pages/`).
- `budget_per_message = 2` (`[ext.deepsearch].max_per_message`).
- Execução na thread do loop; progresso do motor reexposto via `pi.emit`
  (plano, buscas, evidências) — a TUI mostra `⠿ deep_search — planejando…`.
- Retorno capado 4K: status (suficiente/parcial/bloqueada), progresso,
  fontes `[S#] título — url` (até 6) e caminho do `report.md` (o modelo usa
  `read` para o texto integral).
- `[ext.deepsearch]` repassa os orçamentos do motor (12 buscas, 18 páginas,
  40 chamadas, 900 s — defaults do `prd.md` v1). A ponte desliga o fallback
  de backend na pesquisa (orçamento da pesquisa não compõe com o da sessão).

### 8.4 Posicionamento no system prompt

Seção fixa do prompt base — um 8B se confunde com sobreposição de ferramentas
sem isso:

| Situação | Ferramenta |
|---|---|
| Checagem rápida de 1–2 fatos; snippets bastam | `web_search` (+ `web_fetch` em 1–2 URLs) |
| URL específica informada pelo usuário | `web_fetch` direto |
| Resposta fundamentada, com fontes e relatório | `deep_search` |
| Trabalho local: arquivos, comandos, configuração | `core` |
| Ferramenta latente do catálogo | `activate_tool` |

Regra no prompt: pergunta com referências/evidências → `deep_search`; fato
pontual → `web_search` primeiro, `deep_search` só se os snippets não bastarem.

## 9. Compensações de modelo 8B

### 9.1 Engine de orçamento de contexto

| Mecanismo | Default | Observação |
|---|---|---|
| Cap de resultado por tool | 4 000 chars (bash 8 000) | uniforme, aplicado pelo registry a **qualquer** extensão |
| Janela de contexto (`max_context_tokens`) | 32 768 | conservadora por perfil; contagem chars/4, `usage` real registrado quando o backend informa |
| Eviction | ao passar da janela | descarta tool results mais antigos (mantém última mensagem do usuário e resposta corrente); registra evento `budget`; **re-injeta a última mensagem do usuário como âncora de objetivo** (guardrail anti-perda do v1, agora automático) |
| Schemas de ferramentas | ≤ 1 600 tokens | §9.7 |
| Seções de extensão no prompt | ≤ 400 tokens cada | `before_agent_start` estoura com erro claro |
| Saída por turno | 4 096 (8 192 com thinking) | regra do `llm.py` |
| Reserva operacional | ≥ 10% da janela nunca alocada | absorve variação de tokenização |

Compaction semântica (resumir histórico) é pós-MVP; eviction estrutural resolve
o MVP. O hook `context` permite que extensões refinem a janela.

### 9.2 Parser tolerante

Herdado do v1: JSON nativo com auto-repair de nomes/tipos de parâmetros;
**1** correção com erro objetivo no contexto; falha persistente vira `ERRO:`.
A regra de wire do v1 (formato correto de `tool_calls` — correção do 400 no
NIM) permanece. Formatos textuais (YAML/XML/Hermes/Liquid) ficam para a
Fase 11.

### 9.3 Anti-loop em escada

- 2 chamadas idênticas (ferramenta + args) → nudge no contexto;
- 4 → turno encerrado com instrução de responder;
- resposta vazia repetida conta igual;
- `activate_tool` conta no anti-loop e tem teto próprio (3 ativações por turno).

### 9.4 Patch-first e bash delimitado

Sem mudanças: `edit` nunca reproduz arquivo inteiro (falha de unicidade é erro
objetivo); `bash` com recusa por lista de padrões conhecidos — contenção fraca,
não sandbox (containers ficam pós-MVP).

### 9.5 Thinking e amostragem

- `thinking` por perfil: Gemma 4 sem thinking; Nemotron Bolt ligado por default,
  desligável; teto de geração dobra com thinking (regra v1).
- Tokens de thinking contam no orçamento quando informados; senão `unknown`,
  sem inventar contagem.

### 9.6 Perfis de modelo

```toml
[profiles.gemma4-e4b]        # seleção por substring do nome (model_hint)
context_tokens = 32768       # janela útil, não a anunciada
thinking = false
temperature = 1.0
top_p = 0.95
max_tokens_per_turn = 4096
tool_schema_tokens = 1600

[profiles.nemotron-3.5-bolt-e4b]
thinking = true
temperature = 1.0
top_p = 0.95
```

Auto-seleção pelo nome do modelo; CLI/env sobrepõem; perfis do usuário
mesclam sobre os builtin. Serve o princípio "janela anunciada ≠ capacidade
útil" (`relatorio_geral.md` §12.1). `agent/profiles.py` novo.

### 9.7 Orçamento de schemas e ferramentas lazy

- **Orçamento** (`tool_schema_tokens`, default 1 600): o registry soma os
  schemas das ferramentas ativas a cada turno; exceder falha rápido no startup
  nomeando a extensão responsável e sugerindo `lazy = true` ou desativá-la.
  Nunca "estoura e segue" — degradar o prompt silenciosamente seria o oposto
  da filosofia do projeto.
- **Lazy**: `lazy = true` → a ferramenta fica fora da lista de schemas; entra
  a meta-ferramenta única:

  ```text
  activate_tool(name: string)
  Carrega uma ferramenta latente pelos próximos 6 turnos.
  Latentes: <nome — descrição de 1 linha>...
  ```

- Ativação: patch de seção no prompt (mudança registrada, prompt estável por
  turno); expira por inatividade (6 turnos, renovável); registrada em
  `/tools` como `latente/ativa/expirada`.
- Desenho completo no MVP; **nenhuma** extensão embutida nasce lazy (5–8
  schemas cabem no orçamento) — o mecanismo existe para o crescimento.

## 10. Interfaces

Desenho do v1 mantido (PRD do agente §8), agora sobre o registry.

### 10.1 CLI interativa (padrão)

Texto corrido, sem tela cheia: streaming token a token; eventos de ferramenta
em linha (`⚙ nome — args` + duração, `✗ erro`); progresso de extensões via
`pi.emit`; linha de orçamento entre turnos:

```text
turnos 3/24 · llm 5/120 · ctx 18k/32k · ext 6 ferramentas
```

`Ctrl+C` no prompt sai; na resposta interrompe só o turno; `Ctrl+D` sai
apontando o `transcript.md`. Funciona sem cores; alvo 80×24.

### 10.2 TUI Textual (`--tui`, extra `gui`)

Barra de status fixa (estado: `ocioso · executando · interrompendo · erro` +
orçamento + modelo + ferramentas ativas), `Esc` com confirmação, `Ctrl+L`
rolagem, `Ctrl+O` detalhe do último resultado, `Ctrl+Q` sai (sessão fica no
disco). A TUI continua não decidindo fluxo: consome `on_event`.

### 10.3 `--print` (headless)

`formiga agent "pergunta" --print` → resposta final no stdout, eventos em
`events.jsonl`. Sempre in-process (nunca depende de gateway) — é o caminho de
scripts, CI e testes.

### 10.4 CLI de gestão

```bash
formiga agent [--tui|--print] [PERGUNTA]     # interativo
formiga research "PERGUNTA" [...]            # motor direto (v1, mantido)
formiga trust <dir> | untrust <dir>          # allowlist de extensões de projeto
formiga version
# pós-MVP: formiga gateway ..., formiga cron ...
```

## 11. Gateway local — Fase 6 (padrão Hermes)

**Por que:** sem um processo que sobreviva ao terminal, não há retomada,
não há anexo múltiplo e **não há tarefas agendadas** (cron precisa de um daemon
vivo). O Formiga v2 adota o padrão do Hermes: o agente vive no gateway, as
interfaces são clientes.

### 11.1 Modelo de processo

```text
┌────────────────┐  anexa / cria   ┌────────────────────────────────┐
│ formiga agent  │ ───────────────▶│ formiga gateway (daemon)       │
│ (CLI = client) │ ◀───────────────│  · possui sessoes/             │
│ formiga --tui  │  eventos (WS)   │  · executa o AgentLoop         │
│ (mesmo proto)  │                 │  · fila de prompts persistida  │
└────────────────┘                 └────────────────────────────────┘
```

- `formiga gateway start | stop | status` — daemon manual (persiste);
  `formiga agent` com gateway ausente **sobe on-demand** ("ensure") com
  idle-shutdown de 10 min sem sessão ativa; um daemon iniciado manualmente não
  se autoencerra.
- Bind **somente em loopback**, porta aleatória gravada em
  `~/.formiga/gateway-<hash(cwd)>.json` (pid + porta + versão). Um gateway por
  diretório de trabalho.
- **`--local`** força execução in-process (modo v1); **`--print` sempre
  in-process**. Scripts e testes nunca dependem do daemon.

### 11.2 Protocolo (WebSocket, frames JSON)

| Direção | Mensagem |
|---|---|
| client → gateway | `attach {session?}`, `create {profile/model/toolset}`, `submit {prompt}`, `cancel`, `detach`, `list_sessions`, `queue {prompt}` |
| gateway → client | `attached {snapshot, replay?}`, `queued`, `turn_done`, e **os mesmos eventos de `on_event`** (`llm_call`, `stream`, `tool_start`, `tool_end`, `budget`, `interrupted`, `deep_search_progress`, `emit` customizados) |

O `AgentLoop` não muda: o gateway injeta um `on_event` que empacota em frames e
faz broadcast para os clientes anexados. CLI e TUI passam a consumir o mesmo
transporte — multi-interface quase de graça.

### 11.3 Fila, retomada e anexo

- **Desconectar ≠ cancelar**: fechar terminal = `detach`; o turno termina no
  gateway; ao reanexar, o snapshot inclui a resposta finalizada.
- **Fila crash-durable**: `submit` é gravado em `events.jsonl` (+ `queue.json`
  da sessão) **antes** de executar — prompt enfileirado sobrevive a queda do
  gateway.
- **Sessão congelada na criação**: backend/modelo/ferramentas fixados no
  `create`; `attach` não muda (só `/new` cria outra sessão) — preserva
  estabilidade de prompt.
- **Retomada in-process**: `formiga agent --continue | --resume <id>` carrega
  `messages.json` (entra junto na Fase 6 — o gateway e a retomada são a mesma
  questão de continuidade).
- Multi-client: duas interfaces anexadas à mesma sessão veem o mesmo stream;
  entrada concorrente vai para a fila.

### 11.4 Limites do MVP do gateway

1 gateway por workdir; loopback sem auth (single-user); sem LAN/remoto,
sem TLS, sem desktop — token/pairing entram só na Fase 10 (plataformas).

## 12. Tarefas agendadas (cron) — Fase 7

Depende do gateway (§11). Não é cron de shell: é **tarefa do agente** — o job
tem prompt, extensões, orçamento e sessão próprios, como no Hermes.

- **Armazenamento**: `~/.formiga/jobs.json` (id, prompt, schedule, enabled,
  model/profile, budget override, diretório de saída).
- **Formatos de schedule**: expressão cron (`0 7 * * 1-5`), intervalo
  (`every 30m`), one-shot (`at 2026-12-01T09:00`); timezone do sistema com
  override `tz`.
- **Execução**: o gateway cria **sessão nova** (sem histórico), injeta o prompt
  do job + seção de contexto (data, cwd), roda o loop normalmente e grava em
  `sessoes/cron/<job>/<timestamp>/` (mesmos artefatos de sempre).
- **Política de atraso**: com o gateway parado na hora marcada → **skip**
  (default; `catchup: once` opcional: roda uma vez ao voltar).
- **Entrega**: MVP da fase = resultado em disco + evento; a Fase 10 pluga
  entrega em plataforma de mensagem.
- **Comandos**: `formiga cron add "PROMPT" --schedule "..." [--at ...]`,
  `formiga cron list|rm|enable|disable|run <id>` (o `run` manual também
  permite testar sem esperar o relógio); `/cron` na CLI anexada ao gateway.
- **Isolação e orçamento**: cada run é uma sessão com orçamento próprio
  (defaults do §9.1; override por job); um job que estoura para `ERRO:` não
  afeta outros nem a fila interativa.

Aceite da fase: job criado roda no horário com gateway vivo; output persistido
e legível; com gateway parado, skip é registrado em `jobs.json`/log; `cron run`
manual funciona offline.

## 13. Memória estilo Hermes — Fase 8

Três camadas, cada uma com guarda própria. Implementada **como extensão**
(`ext/memory/`) — se o sistema de extensões do MVP estiver bom, a memória não
precisa tocar no core além de um evento `session_end` novo (§7.2).

### 13.1 Recall — busca nas sessões passadas (FTS5)

- Índice SQLite+FTS5 em `~/.formiga/index.db` sobre `messages.json` e
  `transcript.md` de todas as sessões (atualização incremental por timestamp).
- Ferramenta `recall(query, limit?=5)` → trechos com sessão, data e score;
  comando `/recall <query>` para o usuário.
- O modelo usa `recall` quando o usuário pergunta "o que a gente falou sobre
  X?" — barato: só encontra; a leitura é `read`/`recall detail`.

### 13.2 Memória curada — nudge e `MEMORY.md`

- `~/.formiga/memory/MEMORY.md`: fatos duráveis, formato delimitado:

  ```markdown
  ## <categoria>
  - <fato> · fonte: sessão <id> · 2026-11-17
  ```

- **Nudge**: no `session_end` (e a cada 10 turnos), o harness propõe — o
  modelo não grava sozinho: `pi.ui.confirm`/`/memory save` com as sugestões
  ("você aprendeu Y nesta sessão; salvar?"). Escrita só por ferramenta
  dedicada `memory_save(entries)` com aprovação, ou pelo comando `/memory`.
- `/memory show | edit | clear` — inspeção e correção humana sempre possível.

### 13.3 Perfil do usuário

- `~/.formiga/memory/USER.md` (preferências, contexto, estilo), injetado como
  seção do prompt (≤ 600 tokens, LRU por categoria).
- Atualização segue o mesmo nudge (só com aprovação) — o Hermes modela o
  usuário sozinho; o Formiga **sugere** e o usuário aprova (produto de
  confiança, dado local).

### 13.4 Guardrails de memória (obrigatórios)

1. **Memória é dado não confiável**: texto gerado em sessão anterior; entra
   como seção de dados com cabeçalho, nunca como instrução de sistema com
   autoridade.
2. Validar formato antes de injetar; entrada inválida é ignorada com aviso —
   arquivo corrompido **não** derruba startup.
3. Teto rígido (≤ 600 tokens de perfil + 1 000 de memória) — memória não pode
   comer a janela do 8B; excesso vira resumo determinístico com truncamento.
4. Nada de credenciais em memória (a checagem de segredos do v1 se estende).
5. Nunca promover conclusão de pesquisa a "verdade permanente" sem fonte
   (`relatorio_geral.md` §18.4): entradas preservam origem e data.

Aceite da fase: `recall` encontra fato de sessão antiga; nudge aparece no fim
de sessão e `memory_save` exige aprovação; `USER.md` aparece como seção;
corromper `MEMORY.md` gera aviso e sessão segue; orçamento de memória respeitado.

## 14. Skills — Fase 9

- **Skill = conhecimento declarativo**, não código: pasta com `SKILL.md`
  (frontmatter `name`, `description`, `when to use`) + exemplos anexos.
  Locais: `~/.formiga/skills/` (global) e `.formiga/skills/` (projeto,
  trust-gated como extensões).
- **Custo zero quando ociosa**: skill não fica no prompt; vira comando
  `/nome-da-skill` que expande o conteúdo no contexto do turno (expansão
  registrada em evento, como o pi faz com templates).
- Ferramenta `skill_manage(write|list|delete)` com **aprovação obrigatória** —
  criação assistida: após uma tarefa complexa bem-sucedida, o harness
  **sugere** persistir o procedimento como skill (nudge, não autônomo).
- Formato compatível com o espírito do padrão agentskills.io (frontmatter
  simples), permitindo importar skills existentes depois.
- Comando `formiga skills list`.

Aceite: skill instalada aparece em `/skills` e executa via comando; skill de
projeto fora da allowlist não carrega; `skill_manage` sem aprovação é bloqueado.

## 15. Plataformas de mensagem — Fase 10

Adapters como **clientes do gateway** (mesmo protocolo do §11.2), um por
extensão/plataforma:

- `formiga gateway` + adapter Telegram/Discord → `submit`/`queue` vindos do
  chat, entrega da resposta de volta (broadcast de `stream`/`turn_done`);
- autorização: allowlist de chat-id + pareamento (primeiro contato responde
  com código de pareamento, como o Hermes);
- entrada concorrente → fila da sessão (§11.3);
- cada plataforma é opt-in (`[gateway.platforms]`), sem 25 adaptadores
  embutidos: começamos por **um** (Telegram) para provar o protocolo.

## 16. Configuração

Precedência **CLI > env > TOML > defaults**, `.env` (0600) preenchendo
ausentes (mecanismos do v1, `configfile.py`/`envfile.py`, mantidos).
Novo no 2.0: **config global** `~/.formiga/config.toml` (trust, extensões
globais, gateway, memória) além do `formiga.toml` do projeto.

```toml
[llm]
backend = "ollama"                 # ollama | llamacpp | openai
model = "gemma4:e4b"               # default 2.0 (local, sem chave)
# base_url / api_key_env para backend openai (NIM, OpenAI, vLLM...)
temperature = 1.0
timeout_seconds = 120.0
max_retries = 2
thinking = false                   # override manual do perfil

[profile]
model_hint = "gemma4"              # auto-seleção de perfil (§9.6)

[agent]
max_turns = 24
max_llm_calls = 120
timeout_seconds = 1800
tool_result_chars = 4000
max_context_tokens = 32768
tool_schema_tokens = 1600
workdir = "."

[extensions]
enabled = ["core", "web", "deepsearch"]
trusted_projects = []              # dirs cujo .formiga/ carrega

[ext.core]
unsafe_bash = false                # AGENT_UNSAFE=1

[ext.web]
max_searches_per_message = 6
max_fetches_per_message = 8

[ext.deepsearch]
max_per_message = 2
max_searches = 12                  # orçamentos do motor (prd.md v1)
max_pages = 18
max_llm_calls = 40
timeout_seconds = 900

[search]
searxng_url = "http://localhost:8080"

[fallback]                         # opt-in, circuit breaker (v1)
# backend = "ollama"
# after_failures = 1

# --- pós-MVP ---
# [gateway]  idle_shutdown = 600, loopback-only, porta automática
# [cron]     catchup = "skip", tz = "America/Sao_Paulo"
# [memory]   recall = true, nudge = true, max_tokens = 1600
```

Variáveis `FORMIGA_*` espelham as chaves (convenções do `.env.example` do v1;
`FORMIGA_EXTENSIONS_ENABLED`, `FORMIGA_AGENT_*` novas).

## 17. Sessão e persistência

```text
sessoes/2026-11-17_143012_a1b2/
├── messages.json     # messages[] serializável; escrita atômica por turno
├── events.jsonl      # turnos, tools, erros, orçamento, extensões, emit
├── transcript.md     # sessão completa legível (v1)
├── queue.json        # (Fase 6) prompts enfileirados, persistidos antes de rodar
└── research/<n>-<slug>/   # saídas do deep_search (motor v1)
```

- Cada tool call e turno gera evento; credenciais nunca aparecem.
- Sessão interrompida é inspecionável; retomada entra na Fase 6
  (`--resume` in-process e `attach` via gateway).
- `events.jsonl` registra a lista de extensões (nome, fonte, ordem) no início
  de cada sessão — reprodução do ambiente é auditável.

## 18. Segurança e privacidade

Heranças do v1 (PRDs §11/§13), mantidas como invariantes:

- **Fetch de páginas**: só HTTP(S) público; loopback/privadas/link-local
  bloqueados a cada redirecionamento; caps 2 MB/20 s; sem proxies herdados;
  credenciais nunca enviadas a páginas.
- **`bash` delimitado**: workdir fixo + lista de recusa; comando visível antes
  de executar; `AGENT_UNSAFE=1` explícito e registrado.
- **Conteúdo não confiável**: resultados de ferramenta, fontes e (Fase 8)
  memória nunca viram instrução de sistema; seções de extensão são atribuídas
  à extensão, não ao conteúdo executado.
- **Extensões**: poder total do usuário (documentado em destaque no README);
  trust de projeto explícito; API não expõe mutação de guardrails.
- **Chave de API**: só no header; nunca em logs, eventos, transcript, TUI.
- **Privacidade**: conteúdo vai ao endpoint configurado (aviso na interface) e
  consultas ao SearXNG configurado; README alerta sobre dados sensíveis.
- **Gateway (Fase 6)**: loopback-only, sem auth no MVP (single-user); a Fase 10
  adiciona pareamento/allowlist ao expor para mensagens.

## 19. Testes

Sem rede e sem modelo real, no padrão do v1 (`tests/fakes_agent.py` etc.).
A suíte existente é **regressão obrigatória** — roda sem reescrever o que já
está correto.

1. **Equivalência (novo, central)**: com apenas `core` habilitada, o
   comportamento observável (eventos, sessão, resposta a fakes) é igual ao do
   v1 nos mesmos cenários — caracterização antes do refator, verde depois.
2. **Loop/parser/guardrails v1**: mantidos (turno, anti-loop, orçamento,
   cancelamento, cap, wire, retries) + novos: eviction com âncora, contagem
   de tokens.
3. **Extensões (novo)**: descoberta nas 4 fontes; ordem determinística;
   duplicata ignorada; falha de `setup()` não derruba startup; orçamento de
   schemas estoura nomeando a extensão; hooks encadeados (cada um dos 6);
   `block`/mutação de `tool_call`; trust (`trust`/`untrust`, projeto fora da
   allowlist não carrega); lazy (ativação, expiração, anti-loop, `/tools`).
4. **Ferramentas**: casos de disco temporário do v1 (`edit` ambíguo, `read`
   truncado, `bash` recusa/timeout, `write` existente) + orçamentos de web e
   deepsearch + fetcher bloqueando loopback.
5. **Motor de pesquisa**: suíte v1 inteira, inalterada.
6. **Interfaces**: CLI (stream, eventos, `/tools` `/ext` `/budget`, Ctrl+C) e
   TUI (pilot: stream, status, Esc, NO_COLOR, 80×24).
7. **Gateway (Fase 6)**: servidor com cliente fake — attach/detach, fila
   persistida sobrevive a restart do gateway, broadcast multi-client, idle
   shutdown.
8. **Cron (Fase 7)**: relógio fake — disparo, skip com gateway parado,
   `catchup: once`, orçamento por job.
9. **Memória (Fase 8)**: FTS indexa/recupera; nudge exige aprovação; corrupção
   de `MEMORY.md` não derruba startup; teto de tokens.

### Smoke manual (README, atualizar `docs/smoke_agent.md`)

Com **Gemma 4 E4B local via Ollama** (sem chave) + SearXNG: tarefa mista
(`read` → `bash` → `web_search` → `deep_search`) conferindo sessão, transcript,
orçamento, ausência de credenciais; repetir com Nemotron Bolt via NIM;
pós-Fase 6, smoke de detach/resume.

## 20. Fases de implementação

### 20.1 MVP

#### Fase 1 — Desacoplamento e registry

O loop já existe; inverter o acoplamento é a mudança fundadora.

- `agent/extensions/` mínimo: `api.py` (`register_tool`, `on` stub),
  `registry.py` (ferramentas, budgets declarados), `events.py`.
- `git mv` de `agent/tools/*` → `ext/{core,web,deepsearch}/`, com `setup(pi)`
  em cada pacote; protocolo `Tool` intocado.
- `factory.py` reescrito: `discovery` só-builtin → registry → `AgentLoop`.
- `loop.py` perde `BUDGETED_TOOLS` (budget vem declarado por ferramenta).
- Teste de equivalência (§19.1) + suíte v1 verde.

**Aceite:** `formiga agent --print` igual ao v1; `grep -r "tools" agent/loop.py`
não encontra nomes de ferramentas; desativar `deepsearch` no TOML remove a
tool do prompt e do orçamento.

#### Fase 2 — Sistema de extensões completo

- Descoberta: pip entry-points, `~/.formiga/extensions/`, `.formiga/extensions/`
  com trust (`formiga trust/untrust`, config global).
- Os 6 eventos com encadeamento + observação (`extension_loaded` etc.);
  erros de handler isolados.
- `register_command` → comandos `/tools`, `/ext` na CLI e TUI.
- Extensão de exemplo documentada (`~/.formiga/extensions/todo.py`).

**Aceite:** extensão externa com tool+comando carrega, aparece em `/ext`,
funciona; projeto fora da allowlist não carrega; ordem de carga registrada em
`events.jsonl`.

#### Fase 3 — Compensação de 8B na extensibilidade

- `budget.py`: contagem de tokens (chars/4), orçamento de schemas com
  fail-fast, seções de extensão com teto.
- Eviction de contexto + re-injeção da âncora de objetivo (hook `context`).
- Lazy: meta-ferramenta `activate_tool`, expiração, anti-loop estendido.
- `prompts.py` por seções (base + contribuições), patches registrados.
- `profiles.py` + seção `[profiles.*]`.

**Aceite:** janela excedida eviciona e mantém a última pergunta; schema acima
do teto falha no startup citando a extensão; ferramenta lazy carregável e
expira; perfil selecionado pelo nome aparece na barra de status.

#### Fase 4 — Interfaces e orçamento visível

- CLI: linha `turnos/llm/ctx/ext`, comandos novos, `pi.emit` em linha.
- TUI: ferramentas ativas na barra, eventos de extensão, `/tools` `/ext`.
- `NO_COLOR`, terminais 80×24, `Ctrl+C` cooperativo verificado nos dois.

**Aceite:** os cenários de smoke do v1 passam nas duas interfaces com as
extensões ativas; `/budget` reflete o estado real do loop.

#### Fase 5 — Endurecimento e docs

- Smoke completo com Gemma 4 E4B local + NIM; smoke de extensão externa.
- README 2.0 (instalação sem uv, extensões, trust, perfis), `formiga.toml.example`,
  `.env.example`, `docs/smoke_agent.md` atualizados; limitations documentadas.
- `pyproject.toml` → 2.0.0; changelog; `formiga research` confirmado intacto.

**Aceite:** checklist agregado (§20.3) verde; suíte completa offline verde.

### 20.2 Pós-MVP

Ordem por dependência: 6 → 7 (cron precisa do gateway) → 8 → 9 → 10 → 11.

#### Fase 6 — Gateway local + retomada

`gateway.py` (daemon WS loopback, sessões, fila persistida, idle shutdown),
`client.py` (anexo usado por CLI/TUI), `--local`/`--print` preservados,
`--continue/--resume` in-process, comandos `formiga gateway start|stop|status`.
Detalhamento na §11. Aceite: fechar o CLI no meio do turno não cancela;
reanexar mostra a resposta; fila sobrevive a restart do gateway; duas
interfaces anexadas veem o mesmo stream; scripts nunca precisam do daemon.

#### Fase 7 — Tarefas agendadas

`cron.py` + `formiga cron ...` + `/cron`, `jobs.json`, schedules
cron/intervalo/one-shot, execução em sessão nova, `catchup` (skip default),
entrega em disco. Detalhamento na §12. Aceite lá.

#### Fase 8 — Memória estilo Hermes

`ext/memory/`: índice FTS5 (`recall`), `MEMORY.md` com nudge+aprovação,
`USER.md` como seção, `/memory`, evento `session_end`. Guardrails da §13.4
obrigatórios. Aceite na §13.

#### Fase 9 — Skills

`SKILL.md` em `~/.formiga/skills/` e `.formiga/skills/` (trust), expansão por
comando, `skill_manage` com aprovação, nudge pós-tarefa. Aceite na §14.

#### Fase 10 — Plataformas de mensagem

Adapter Telegram sobre o gateway, allowlist+pareamento, fila compartilhada.
Aceite: mensagem do Telegram vira turno no gateway e a resposta volta;
sessão também visível no CLI anexado ao mesmo tempo.

#### Fase 11 — Expansão avançada (lista priorizada)

MCP (client → `register_tool`); eval gate (golden set com casos
não-responíveis + métricas determinísticas + review humana — não usar o mesmo
8B como juiz único); parser multi-formato; trust decay por ferramenta;
compaction semântica; 2-stage routing se o toolset crescer; gateway remoto com
token/TLS; plataformas adicionais.

### 20.3 Critérios de aceite do MVP (agregado)

- [ ] `formiga agent` abre a CLI; `--tui` a TUI; `--print` a resposta.
- [ ] O core não importa ferramentas (checagem estática no teste).
- [ ] Desativar `deepsearch` no TOML remove a tool do prompt, orçamento e sessão.
- [ ] Extensão externa (`~/.formiga/extensions/`) carrega, aparece em `/ext`,
      tool e comando funcionam.
- [ ] Projeto fora de `trusted_projects` não carrega; `formiga trust` resolve;
      aviso na sessão.
- [ ] Orçamento de schemas falha no startup citando a extensão; lazy
      (`activate_tool`) ativa, expira e conta no anti-loop.
- [ ] Eviction preserva última pergunta e resposta; âncora re-injetada;
      `/budget` coerente com o loop.
- [ ] Tarefa mista (arquivo + bash + web + deep_search) conclui fundamentada;
      progresso do deepsearch visível em CLI e TUI.
- [ ] Duas chamadas idênticas → nudge; quatro → fim do turno.
- [ ] `edit` nunca reescreve arquivo inteiro; `bash` recusa a lista.
- [ ] `Esc`/`Ctrl+C` cooperativo; estado final nunca é "sucesso" pós-interrupção.
- [ ] Suíte do v1 verde (incl. motor de pesquisa) + teste de equivalência.
- [ ] Smoke com Gemma 4 E4B local e com NIM; nenhuma credencial em artefato.

## 21. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Extensões inundam o prompt e degradam o 8B | orçamento de schemas fail-fast, teto de seções, lazy, teste de equivalência como regressão |
| Hooks com ordem dependente de ambiente | ordem de carga determinística + registrada; testes de ordem |
| Extensão malfeita quebra a sessão | falha isolada (aviso, não crash); API não expõe guardrails |
| Refator do Fase 1 quebrar o v1 | caracterização escrita **antes** do `git mv`; suíte v1 como porta de passagem |
| Eviction agressiva perde contexto | âncora de objetivo, janela por perfil, hook `context` |
| Gateway adiciona modo de falha (daemon morto, porta ocupada) | `--local`/`--print` in-process first-class; pidfile com versão; ensure com erro claro |
| Cron sem daemon perde execuções | skip explícito + registro; `catchup: once` opcional; `cron run` manual p/ testes |
| Memória envenenada (modelo lendo a própria antiga) | seção de dados não-confiável, validação, teto, aprovação humana para gravar, corrupção não derruba sessão |
| Escopo vira "Hermes completo" | fases 6–11 são gates sequenciais; cada uma fecha com aceite próprio |

## 22. Limitações conhecidas

- Um 8B de eficiência erra planejamento; o MVP limita o dano, não promete
  autocomposição.
- Tokens estimados por chars/4 até o backend informar `usage`.
- Sem sandbox real: recusa de bash + trust de extensões são contenção fraca.
- Memória, skills, cron e gateway não existem no MVP (fases 6–9).
- `deepsearch` herda os limites do motor v1 (sem PDF, sem rerank; abstenção
  pode ocorrer).
- Janela útil < janela anunciada: defaults conservadores e configuráveis.
- Gateway MVP é single-user loopback — não é um serviço multi-tenant.

## 23. Referências

- `docs/prd.md` (v1) — motor de pesquisa; fonte da verdade do `deepsearch`,
  reusado intacto.
- `docs/prd_agent.md` (v1) — loop, guardrails, interfaces, sessão; base do 2.0
  com acoplamento invertido.
- `docs/RELATORIO_AGENTE_8B.md` — compensações (orçamento §4.1, parser §4.3,
  patch-first §4.4, anti-loop §4.6, tier §4.8, anéis §6).
- `docs/relatorio_geral.md` — disciplina do loop; janela conservadora (§12.1–12.3);
  "2 estágios não compensa com poucas ferramentas" (§8.2); memória não vira
  verdade permanente (§18.4).
- pi (earendil-works) — API de extensão, eventos encadeados, descoberta, trust.
- Hermes (NousResearch) — gateway como dono de sessão, CLI como cliente,
  cron de agente, memória (FTS5 + nudge + perfil), skills, prompt estável.
