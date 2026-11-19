# Formiga

Harness minimalista de pesquisa profunda. Recebe uma pergunta, divide o trabalho
em lacunas investigáveis, busca e lê fontes públicas, registra evidências e
produz uma resposta em Markdown com referências e limitações.

> **O harness controla o processo. O modelo interpreta e redige. As evidências
> delimitam o que pode ser afirmado.**

O sistema não depende de um agente autônomo com ferramentas livres: o fluxo é
controlado pelo programa e o LLM executa tarefas pequenas e delimitadas —
planejar, formular consulta, extrair citações, verificar, comparar, sintetizar
e auditar. Três superfícies de uso: `formiga research` (processo 100%
controlado), `formiga agent` (harness agêntico com ferramentas) e
`formiga gateway`/`cron` (daemon e agendamento). O modelo roda no Ollama,
llama.cpp ou em qualquer endpoint OpenAI-compatível (NVIDIA NIM, OpenAI,
DeepSeek, vLLM...).

## Modelos: a família Gemma 4 como foco

O Formiga é dimensionado para **modelos pequenos locais**, com a família
**Gemma 4** (E2B/E4B) como alvo principal:

- **Gemma 4 E4B — modelo padrão.**
  [`google/gemma-4-E4B-it`](https://huggingface.co/google/gemma-4-E4B-it):
  4,5B parâmetros efetivos (8B contando embeddings), contexto anunciado de
  128K, texto/imagem/áudio, thinking configurável, amostragem recomendada
  1.0/0.95. No Ollama: `gemma4:e4b` (tag `latest` da biblioteca oficial).
- **Gemma 4 E2B — variante mais leve.**
  [`google/gemma-4-E2B-it`](https://huggingface.co/google/gemma-4-E2B-it):
  2,3B efetivos (5,1B contando embeddings), 128K. No Ollama: `gemma4:e2b`.
- **Nemotron 3.5 Bolt E4B — alternativa, não o foco.**
  [`nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB`](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB)
  é um **pós-treinamento da NVIDIA feito a partir do `Gemma-4-E4B-it`**:
  RL (GRPO) em ambientes de tool use multi-turno, instruction following e
  saída estruturada/ancorada em entrada. Mesmo tier de tamanho do E4B
  (4B efetivos / 8B totais). No Ollama: `nemotron-3.5-bolt`.

### Perfis de modelo

O harness agêntico aplica um **perfil** com defaults conservadores de
contexto, thinking e geração. Perfis builtin:

| Perfil | Modelo | Thinking | tok/turno | Contexto útil |
|---|---|---|---|---|
| `gemma4-e4b` **(default)** | Ollama `gemma4:e4b` | desligado | 4096 | 32768 |
| `gemma4-e2b` | Ollama `gemma4:e2b` | ligado | 8192 | 32768 |
| `nemotron-3.5-bolt-e4b` | Ollama `nemotron-3.5-bolt` (+ `model_hint`) | ligado | 8192 | 32768 |

Os três usam `temperature = 1.0` e `top_p = 0.95` (fichas dos modelos).

**Seleção do perfil** (nesta ordem):

1. `[profile] model_hint` no TOML ou `FORMIGA_PROFILE_MODEL_HINT` — força um
   perfil pelo **nome exato** (ex.: `gemma4-e4b`);
2. em segundo, `[profile] active` no TOML (ou `--profile` no `cron add`) —
   mesma força, para quem prefere o nome do perfil como "ativo";
3. senão, **substring normalizada** do nome do modelo: `gemma4:e4b` →
   `gemma4-e4b`, `gemma4:e2b` → `gemma4-e2b`, `nvidia/nemotron-3.5-bolt-e4b` →
   `nemotron-3.5-bolt-e4b`.

Atenção à regra da auto-seleção: o nome do modelo precisa **conter** o nome
do perfil. A tag do Ollama `nemotron-3.5-bolt` (sem o sufixo `-e4b`) não casa
— nesse caso use `model_hint = "nemotron-3.5-bolt-e4b"`.

Perfis definidos em `[profiles.*]` no TOML **mesclam sobre os builtin**.
Depois, CLI > env > arquivo sempre sobrepõem o perfil (o perfil só preenche
campos ainda em default). Os perfis são aplicados pelo harness agêntico
(`formiga agent`); no `research` valem `[llm]`/env/CLI diretamente.

```toml
[profile]
model_hint = "gemma4-e2b"    # força um perfil builtin ou de usuário

[profiles.meu-modelo]        # mescla sobre o builtin com o mesmo nome
context_tokens = 16384
thinking = false
```

## Instalação

Requer Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .              # todos os comandos, exceto a TUI
pip install ".[gui]"          # + Textual, para `formiga agent --tui`
```

O extra `gui` é o único opcional: sem ele, `research`, `agent` (CLI
interativa e `--print`), `gateway`, `cron`, `skills` e `trust` funcionam
normalmente. O repositório também versiona `uv.lock` — com `uv` instalado,
`uv sync` cria o ambiente e `uv run formiga ...` roda sem ativar o venv.

## Quickstart

```bash
# 1. Modelo (default: Gemma 4 E4B) e busca
ollama pull gemma4:e4b
# SearXNG local com JSON habilitado, ex.: http://localhost:8080

# 2. Pesquisa controlada pelo programa
formiga research \
  "O que muda na segurança ao migrar de SSH por senha para SSH com chaves?" \
  --output ./pesquisa-formiga --verbose

# 3. Harness agêntico
formiga agent "leia o formiga.toml deste projeto e resuma a configuração"
```

## Comandos

### `formiga research` — pesquisa controlada pelo programa

```bash
formiga research \
  "Quais são os trade-offs entre busca lexical e busca híbrida?" \
  --output ./pesquisa-formiga
```

Saída (no diretório informado):

- `report.md` — relatório final em Markdown;
- `state.json` — questões, fontes, evidências, afirmações e consumo de orçamento;
- `events.jsonl` — eventos operacionais da execução;
- `pages/S*.txt` — textos extraídos das fontes (proveniência das citações).

O terminal informa o status final: **suficiente**, **parcial** ou **bloqueada**.
Códigos de saída: `0` relatório gerado (mesmo parcial/bloqueado), `2` entrada ou
configuração inválida, `1` falha operacional, `130` interrompido pelo usuário.

Execuções interrompidas podem ser inspecionadas (o checkpoint permanece
legível), mas **não são retomadas**.

### `formiga agent` — harness agêntico (CLI interativa, TUI ou headless)

```bash
formiga agent "qualquer pergunta sobre o projeto"
```

- Sem flags: **CLI interativa** — limpa a tela e mostra um painel de abertura
  (ferramentas, extensões, comandos e skills instaladas), depois `pergunta>`,
  streaming token a token, linhas de ferramenta em linha
  (`⚙ bash — command=…`), barra de orçamento
  (`turnos n/24 · llm n/120 · ctx Xk/Yk · ext N ferramentas`) e comandos `/`
  (veja "Comandos de sessão" abaixo).
- `--print`: headless, imprime a resposta final no stdout (útil em scripts).
- `--tui`: TUI Textual (80×24, barra de status com perfil, eventos de extensão
  em linha, `Esc`/`Ctrl+C` cooperativos). Requer o extra `gui`.

Flags de sessão e ambiente:

| Flag | Efeito |
|---|---|
| `--continue` | Retoma a última sessão do workdir (in-process) |
| `--resume ID` | Retoma a sessão com o ID informado (in-process) |
| `--session-dir PATH` | Diretório da sessão (default `sessoes/<timestamp_id>`) |
| `--local` | Execução in-process, sem usar o daemon do gateway |
| `--no-color` | Desativa cores (equivale a `NO_COLOR=1`) |
| `--no-clear` | Não limpa a tela ao iniciar |
| `--verbose` | Eventos operacionais adicionais |

O agent anexa ao `formiga gateway` automaticamente quando ele está no ar
(sobe on-demand se necessário); `--print` e `--local` sempre rodam
in-process. As demais flags (`--model`, `--llm-backend`, `--searxng-url`...)
são as mesmas do `research`, listadas na seção de referência.

Configuração via CLI, variáveis de ambiente (`FORMIGA_*`) ou `./formiga.toml`
(precedência: CLI > env > arquivo > defaults). Veja `formiga.toml.example`.

### `formiga gateway` — daemon local

O gateway é um processo WebSocket apenas em loopback que **possui o `AgentLoop`
e as sessões**, sobrevivendo ao terminal. A CLI e a TUI se tornam clientes que
se anexam a ele.

```bash
# Suba o daemon (background, persiste entre terminais)
formiga gateway start

# Verifique o estado (pid, porta, versão)
formiga gateway status

# Rode o agent: anexa ao gateway automaticamente (sobe on-demand se necessário)
formiga agent "qualquer pergunta sobre o projeto"

# Feche o terminal no meio de um turno: não cancela. Reabra e reanexe para ver
# a resposta. Pare o daemon quando terminar:
formiga gateway stop
```

- **Desconectar ≠ cancelar**: fechar o terminal no meio do turno não interrompe
  o agente; o turno termina no gateway e pode ser reanexado.
- **Fila crash-durable**: prompts enviados são gravados em disco antes de
  executar; sobrevivem a uma queda do gateway.
- **`--print` e `--local`**: continuam in-process (sem depender do daemon),
  ideais para scripts e testes.
- Um gateway por diretório de trabalho; sem autenticação nem TLS (single-user,
  loopback).

### `formiga cron` — tarefas agendadas

O cron agenda tarefas do agente (prompt + orçamento + sessão própria), executadas
pelo gateway. Não é cron de shell: cada job roda como uma sessão de agente
isolada, com resultado persistido em disco.

```bash
# Adicione um job (cron 5 campos, intervalo ou one-shot)
formiga cron add "resuma as notícias do dia" --schedule "0 8 * * 1-5"

# Liste os jobs
formiga cron list

# Execute um job agora (in-process, offline)
formiga cron run <id>

# Habilite/desabilite ou remova
formiga cron enable <id>
formiga cron disable <id>
formiga cron rm <id>
```

- **Schedules**: `0 7 * * 1-5` (cron 5 campos), `every 30m` (intervalo),
  `at 2026-12-01T09:00` (one-shot).
- **Catchup**: com o gateway parado na hora marcada, o disparo é skipado
  (default) ou executado uma vez ao voltar (`--catchup once`).
- **Orçamento por job**: `--max-turns`, `--max-llm-calls`, `--timeout-seconds`.
- **Modelo/perfil por job**: `--model`, `--profile` (ex. `--profile gemma4-e2b`).
- Cada run grava em `sessoes/cron/<job>/<timestamp>/` (mesmos artefatos de
  sempre); eventos `job_start`/`job_end` são broadcast aos clientes anexados.
- Config: `[cron] catchup = "skip"`, `tz = "America/Sao_Paulo"`;
  env `FORMIGA_CRON_CATCHUP` / `FORMIGA_CRON_TZ`.

### `formiga skills`, `trust`/`untrust`, `version`

```bash
formiga skills list         # skills globais + do projeto confiável
formiga trust ./meu-proj    # allowlist global: carrega .formiga/extensions
                            # e .formiga/skills do projeto
formiga untrust ./meu-proj  # remove da allowlist
formiga version             # versão instalada
```

Skills são procedimentos reutilizáveis em Markdown (`SKILL.md`), não código.
Ficam **fora do prompt** até serem chamadas: custo zero quando ociosas. São
carregadas de `~/.formiga/skills/` (globais) e de `.formiga/skills/` do projeto
(somente se o projeto estiver na allowlist de trust).

```bash
mkdir -p ~/.formiga/skills/revisar-pr
cat > ~/.formiga/skills/revisar-pr/SKILL.md <<'EOF'
---
name: revisar-pr
description: Checklist de revisão de pull request
when_to_use: Ao revisar um PR
---
1. Leia o diff completo.
2. Verifique testes e casos de borda.
3. Aponte riscos com arquivo e linha.
EOF
```

Dentro do `formiga agent`, `/skills` lista as skills e `/revisar-pr` agenda a
expansão do conteúdo para a próxima mensagem (registrada no evento
`skill_expanded`). O modelo também pode propor novas skills com
`skill_manage(action="write")`: a proposta fica em
`~/.formiga/skills/pending.json` e **nada é gravado** até um humano aprovar
com `/skills approve <id>` (ou descartar com `/skills reject <id>`).

## Comandos de sessão (dentro do `formiga agent`)

Digitando `/` na CLI interativa (e na TUI). `Ctrl+C` interrompe o turno em
andamento; `Ctrl+D` sai.

| Comando | O que faz |
|---|---|
| `/help` | Lista comandos, skills e seções contribuídas pelas extensões |
| `/tools` | Ferramentas registradas, por extensão |
| `/ext` | Extensões carregadas (fonte, status, erros) |
| `/budget` | Orçamento da sessão: turnos, chamadas LLM, contexto, consumo por ferramenta |
| `/new sim` | Nova sessão (exige a confirmação `sim`; a anterior permanece em disco) |
| `/cron` | Lista as tarefas agendadas (`~/.formiga/jobs.json`) |
| `/recall <query>` | Busca FTS5 em sessões passadas (memória de sessões) |
| `/memory [show\|pending\|save [id]\|clear\|edit]` | Memória curada (`MEMORY.md`) e perfil (`USER.md`); `save` aplica sugestões pendentes — o modelo nunca grava sozinho |
| `/skills [list\|pending\|approve <id>\|reject <id>]` | Skills disponíveis e aprovação de propostas |
| `/<skill>` | Expande a skill correspondente na próxima mensagem |

### Memória (extensão `memory`, ligada por default)

A memória tem três camadas: **recall** (busca FTS5 em sessões passadas),
**memória curada** (`MEMORY.md` com nudge + aprovação humana) e **perfil**
(`USER.md` injetado no prompt). Tudo fica em `~/.formiga/memory/` e o índice
em `~/.formiga/index.db`.

- **Ferramentas do modelo**: `recall(query, limit?)` e `memory_save` (grava
  em `pending.json` — staging, nunca direto no `MEMORY.md`).
- **Nudge**: ao fim da sessão (e a cada 10 turnos), o harness sugere salvar
  o que aprendeu; a gravação só ocorre pelo comando humano `/memory save`.
- **Perfil**: `USER.md` vira seção do system prompt (≤ 600 tokens).
- **Guardrails**: memória é dado não confiável (cabeçalho de aviso), teto
  rígido (≤ 1 000 tokens memória + 600 tokens perfil, truncamento),
  credenciais recusadas, arquivo corrompido gera aviso e não derruba.
- Config: `[memory] recall = true`, `nudge = true`, `max_tokens = 1600`;
  env `FORMIGA_MEMORY_RECALL` / `FORMIGA_MEMORY_NUDGE` /
  `FORMIGA_MEMORY_MAX_TOKENS`.

## Referência

### Flags de `formiga research` (e `formiga agent`)

| Opção | Finalidade |
|---|---|
| `--output PATH` | Diretório de saída (padrão `./formiga-out`) — só no `research` |
| `--config PATH` | Arquivo de configuração TOML (default: `./formiga.toml` se existir; ver abaixo) |
| `--model NAME` | Nome do modelo no Ollama ou ID no backend remoto (default: `gemma4:e4b`) |
| `--ollama-url URL` | Endpoint do Ollama (default `http://localhost:11434`) |
| `--searxng-url URL` | Endpoint da instância SearXNG (JSON habilitado) |
| `--llm-backend {ollama,llamacpp,openai}` | Backend do modelo (default: ollama) |
| `--llm-base-url URL` | URL base do endpoint remoto OpenAI-compatível (ex.: `https://integrate.api.nvidia.com/v1`) |
| `--api-key-env NAME` | Nome da variável de ambiente com a chave do endpoint remoto (default: `NVIDIA_API_KEY`) |
| `--llm-thinking` / `--no-llm-thinking` | Raciocínio antes da resposta (default: **ligado**; no agent o perfil `gemma4-e4b` o desliga) |
| `--fallback-backend {ollama,llamacpp,openai}` | Backup **opt-in**: ativa somente após falhas do backend principal (default: sem backup) |
| `--fallback-after-failures N` | Falhas consecutivas do principal antes do backup assumir (default 1) |
| `--llm-max-retries N` | Retries HTTP (429/5xx) no backend remoto, com backoff (default 2) |
| `--llamacpp-url URL` | Endpoint do llama-server (OpenAI-compatível) |
| `--llamacpp-thinking` / `--no-llamacpp-thinking` | Thinking só no llama.cpp (default: ligado) |
| `--max-searches N` | Limite de buscas (default 12) — só no `research` |
| `--max-pages N` | Limite de páginas (default 18) — só no `research` |
| `--max-llm-calls N` | Limite total de chamadas (default 40; 8 reservadas para síntese/auditoria; no agent: 120) |
| `--timeout-seconds N` | Tempo máximo da execução (default 900; no agent: 1800) |
| `--llm-timeout-seconds N` | Timeout por chamada ao modelo (default 300; CPU lenta pode exigir mais) |
| `--llm-temperature T` | Temperatura de amostragem (default 1.0, conforme as fichas dos modelos; 0.2 pode ajudar em JSON estruturado) |
| `--overwrite` | Autoriza sobrescrever um diretório de saída existente (só no `research`) |
| `--verbose` | Eventos operacionais no stderr |

### Variáveis de ambiente

Todas são lidas por `Config.from_env`; o `.env` do projeto apenas preenche
variáveis ausentes (ver "Arquivo de segredos").

```text
# Configuração geral
FORMIGA_CONFIG=caminho/formiga.toml     # arquivo TOML explícito
FORMIGA_ENV_FILE=caminho/secrets.env    # arquivo de segredos explícito

# Backend e endpoints
FORMIGA_LLM_BACKEND=ollama              # ollama | llamacpp | openai
FORMIGA_MODEL=gemma4:e4b                # default
FORMIGA_OLLAMA_URL=http://localhost:11434
FORMIGA_SEARXNG_URL=http://localhost:8080
FORMIGA_LLAMACPP_URL=http://localhost:8080
FORMIGA_OPENAI_URL=https://integrate.api.nvidia.com/v1
FORMIGA_OPENAI_API_KEY_ENV=NVIDIA_API_KEY
FORMIGA_LLM_TIMEOUT=300                 # timeout por chamada ao modelo (segundos)
FORMIGA_LLM_TEMPERATURE=1.0             # amostragem (fichas: 1.0 / top_p 0.95)
FORMIGA_LLM_THINKING=1                  # 0 = desligar o raciocínio (default: 1)
FORMIGA_LLAMACPP_THINKING=1             # override do thinking só no llama.cpp

# Failover opt-in (backup; nunca automático)
FORMIGA_FALLBACK_BACKEND=               # ollama | llamacpp | openai
FORMIGA_FALLBACK_AFTER_FAILURES=1       # falhas consecutivas antes do backup assumir

# Harness agêntico
FORMIGA_AGENT_MAX_TURNS=24
FORMIGA_AGENT_MAX_LLM_CALLS=120
FORMIGA_AGENT_TIMEOUT_SECONDS=1800
FORMIGA_AGENT_MAX_DEEP_SEARCHES=2
FORMIGA_AGENT_MAX_WEB_SEARCHES=6
FORMIGA_AGENT_MAX_WEB_FETCHES=8
FORMIGA_AGENT_TOOL_RESULT_CHARS=4000
FORMIGA_AGENT_WORKDIR=.
FORMIGA_AGENT_MAX_CONTEXT_TOKENS=32768
FORMIGA_AGENT_TOOL_SCHEMA_TOKENS=1600

# Extensões e perfis
FORMIGA_EXTENSIONS_ENABLED=core,web,deepsearch,memory,skills   # default
FORMIGA_PROFILE_MODEL_HINT=            # força um perfil (ex.: gemma4-e2b)

# Cron e memória
FORMIGA_CRON_CATCHUP=skip              # skip | once
FORMIGA_CRON_TZ=America/Sao_Paulo
FORMIGA_MEMORY_RECALL=1
FORMIGA_MEMORY_NUDGE=1
FORMIGA_MEMORY_MAX_TOKENS=1600
```

### Arquivo de configuração

Precedência: **CLI > variáveis de ambiente > arquivo > defaults**. Sem
`--config`/`FORMIGA_CONFIG`, ele procura `./formiga.toml` e depois
`~/.config/formiga/config.toml`. Veja o exemplo completo em
`formiga.toml.example` (o `formiga.toml` real é ignorado pelo git, pois pode
conter uma chave de API com permissão `0600`).

```toml
[llm]
backend = "ollama"                      # ollama | llamacpp | openai
model = "gemma4:e4b"                    # default (Ollama local, sem chave)
temperature = 1.0
timeout_seconds = 120.0
max_retries = 2
# thinking = false                      # override manual do perfil
# Para backend remoto (NIM, OpenAI, vLLM...):
# backend = "openai"
# base_url = "https://integrate.api.nvidia.com/v1"
# api_key_env = "NVIDIA_API_KEY"        # nome da variável, nunca a chave
# fallback_backend = "ollama"           # backup opt-in (nunca automático)
# fallback_after_failures = 1

[search]
searxng_url = "http://localhost:8080"

[budget]
max_searches = 12
max_pages = 18
max_llm_calls = 40
timeout_seconds = 900

[agent]
max_turns = 24
max_llm_calls = 120
timeout_seconds = 1800
max_deep_searches = 2
max_web_searches = 6
max_web_fetches = 8
tool_result_chars = 4000
workdir = "."
max_context_tokens = 32768
tool_schema_tokens = 1600

[extensions]
# Ordem de carregamento = ordem desta lista.
enabled = ["core", "web", "deepsearch", "memory", "skills"]
# Diretórios de projeto cujo .formiga/ carrega (allowlist global).
trusted_projects = []

[profile]
# model_hint = "gemma4-e4b"             # força um perfil (nome exato)
# active = "gemma4-e2b"                  # alternativa: perfil "ativo"
# (sem nenhum dos dois, o perfil é escolhido pela substring do modelo)

# Perfis de modelo: mesclam sobre os builtin (§9.6 do PRD).
[profiles.gemma4-e2b]
context_tokens = 32768                 # janela útil, não a anunciada
thinking = true                        # GGUF "IT ... Thinking": raciocínio ligado
temperature = 1.0
top_p = 0.95
max_tokens_per_turn = 8192             # thinking consome orçamento de geração
tool_schema_tokens = 1600

[profiles.gemma4-e4b]
context_tokens = 32768
thinking = false
temperature = 1.0
top_p = 0.95
max_tokens_per_turn = 4096
tool_schema_tokens = 1600

[profiles."nemotron-3.5-bolt-e4b"]
thinking = true
temperature = 1.0
top_p = 0.95

[ext.core]
unsafe_bash = false                    # AGENT_UNSAFE=1 para permitir

[cron]
catchup = "skip"                       # skip | once
tz = "America/Sao_Paulo"

[memory]
recall = true
nudge = true
max_tokens = 1600
```

### Arquivo de segredos (`.env`)

A chave da API fica em um arquivo `.env` no diretório do projeto (ignorada
pelo git, permissão `0600` exigida). Copie `.env.example` para `.env` e
preencha:

```text
NVIDIA_API_KEY=nvapi-...
```

- O `.env` apenas **preenche variáveis ausentes** — o que já estiver definido
  no ambiente vence (`export NVIDIA_API_KEY=...` sobrepõe o arquivo).
- Outras variáveis `FORMIGA_*` também podem ir no `.env`.
- Caminho alternativo: `FORMIGA_ENV_FILE=caminho/para/secrets.env`.
- A chave nunca aparece em `repr(Config)`, mensagens de erro, `state.json`
  nem `events.jsonl`.

A chave do backend remoto nunca vai na CLI. Fontes possíveis, em ordem de
preferência: variável de ambiente definida manualmente, `.env` do projeto
(nome indicado por `api_key_env` / `--api-key-env`, default
`NVIDIA_API_KEY`) ou `api_key = "..."` no arquivo TOML com permissão `0600`.

Instale o modelo escolhido no backend correspondente (`ollama pull gemma4:e4b`
para o default) e configure uma instância SearXNG própria com o formato JSON
habilitado (`search.formats: [html, json]`).

### Busca: SearXNG e motores

O Formiga **não integra APIs de busca diretamente**: ele consulta uma
instância SearXNG própria (`[search] searxng_url` / `FORMIGA_SEARXNG_URL`,
default `http://localhost:8080`) com o formato JSON habilitado
(`search.formats: [html, json]` no `settings.yml` da SearXNG).

A requisição é `GET /search?q=<consulta>&format=json` — **sem parâmetro de
categoria**, portanto a SearXNG responde com os motores da categoria
`general`. Os snippets servem apenas para **selecionar páginas**; nunca
viram evidência final (as citações saem dos textos baixados em `pages/`).
As consultas enviadas ficam registradas em `events.jsonl`.

**Motores da instância local de referência** (estado e medição de
2026-11-19 com SearXNG `2026.11.14`; liste a qualquer momento com
`curl 'http://localhost:8080/config?format=json'`):

| Motor (categoria `general`) | Estado | Observação |
|---|---|---|
| `google cse` | habilitado | **respondente estável** — Custom Search Engine configurado na instância |
| `brave` | habilitado | responde bem, mas o SearXNG o **suspende temporariamente** após rate-limit (`Suspended: too many requests`) e volta após o cooldown |
| `duckduckgo` | habilitado | idem: pode devolver `CAPTCHA` e ficar suspenso temporariamente |
| `google` | **desabilitado** no `settings.yml` (não resolvia: `access denied`) | — |
| `bing` | **desabilitado** no `settings.yml` | — |
| `currency`, `dictzone`, `lingva`, `mymemory translated` | habilitados em `general` (moeda/tradução); respondem a consultas do tipo | — |

Como as suspensões do SearXNG são temporárias (cooldown automático), a
composição que **responde em cada consulta varia** — na medição de 19/11 o
`google cse` foi o único estável. Se quiser mais redundância, reabilite
`bing` ou `google` no `settings.yml`.

A mesma instância carrega ~250 motores em outras categorias (`news`,
`science`, `images`, `videos`, `it`, `social media`...), mas o Formiga **não**
consulta essas categorias — hoje apenas `general`.

Para trocar os motores, edite o `settings.yml` da SearXNG (habilitar e
desabilitar por motor) e/ou configure seu próprio Google CSE. O Formiga não
guarda nenhuma chave de busca: tudo passa pela instância (ver "Privacidade").

## Apêndice: backends e geração

### Backends de modelo

| Backend | Endpoint | Formato estruturado | Thinking |
|---|---|---|---|
| `ollama` (default) | `POST /api/chat` com `format: "json"` | JSON; schema imposto pela validação do harness | `think: true` no payload; 400 citando "think" → repete sem o campo |
| `llamacpp` | `POST /v1/chat/completions` (OpenAI-compatível) | `response_format: {"type": "json_object", "schema": ...}` — builds com suporte convertem o schema em gramática GBNF; sem suporte, a validação fica no harness | `chat_template_kwargs: {"enable_thinking": ...}` explícito |
| `openai` | `POST {base_url}/chat/completions` com `Authorization: Bearer` | `response_format: {"type": "json_object"}`; se o servidor rejeitar, repete uma vez sem o campo. O schema não é imposto remotamente — a validação fica no harness. Retries (default 2) para 429/5xx com backoff e `Retry-After` | `chat_template_kwargs: {"enable_thinking": true}` + `skip_special_tokens: false`; 400 citando os campos → repete sem eles |

### Backend remoto (NVIDIA NIM, OpenAI, DeepSeek, vLLM...)

O backend `openai` funciona com qualquer endpoint OpenAI-compatível. Exemplo
com a API da NVIDIA:

```bash
export NVIDIA_API_KEY=nvapi-...
formiga research "..." \
  --llm-backend openai \
  --llm-base-url https://integrate.api.nvidia.com/v1 \
  --model nvidia/nemotron-3.5-bolt-e4b \
  --output ./pesquisa-formiga
```

Equivalentemente via `formiga.toml` (seção acima) ou `FORMIGA_OPENAI_URL` +
`FORMIGA_MODEL` + `FORMIGA_LLM_BACKEND=openai`. A URL base pode terminar em
`/v1` (o cliente acrescenta `/chat/completions`) ou incluir o caminho completo.

### Failover opt-in (backup)

Por padrão **não há failover**: falhas do backend principal degradam a
execução como sempre. Definindo `fallback_backend` (arquivo, env
`FORMIGA_FALLBACK_BACKEND` ou `--fallback-backend`), após
`fallback_after_failures` falhas consecutivas do principal o backup assume e
**permanece** pelo resto da execução (circuit breaker — evita retestar um
backend lento a cada chamada e queimar o orçamento de tempo). A migração é
registrada como evento `llm_fallback` em `events.jsonl`; o timeout do backup
respeita o tempo restante da execução. Exemplo: API remota como principal e
Ollama local como backup.

### llama.cpp local (llama-server)

Para usar um `llama-server` compilado localmente:

```bash
llama-server -m caminho/Gemma-4-E4B-Q4_K_M.gguf \
  --alias gemma4-e4b -c 32768 --jinja

.venv/bin/formiga research "..." \
  --llm-backend llamacpp --llamacpp-url http://127.0.0.1:8080 \
  --output ./pesquisa-formiga
```

Para o Nemotron 3.5 Bolt (thinking com orçamento de raciocínio controlado no
servidor):

```bash
llama-server -m Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf \
  --alias nemotron-bolt -c 65536 --jinja \
  --reasoning on --reasoning-budget 512
```

Builds antigas do llama-server que não suportam `schema` dentro de
`response_format` também funcionam — o campo é ignorado e a validação fica no
harness.

### Thinking e amostragem

- **Default do Formiga**: thinking **ligado** a nível de config
  (`--no-llm-thinking` / `thinking = false` / `FORMIGA_LLM_THINKING=0`
  desligam); com thinking ligado, os caps por tarefa ganham folga extra de
  tokens e o teto dobrado sobe para 4096.
- **Perfil `gemma4-e4b` (default)**: desliga o thinking no harness agêntico
  para respostas diretas e mais velocidade — é o comportamento que você vê
  ao rodar `formiga agent` sem mudar nada. Force o raciocínio com
  `thinking = true` no perfil ou `--llm-thinking`.
- **Perfis `gemma4-e2b` e `nemotron-3.5-bolt-e4b`**: thinking ligado
  (GGUFs "IT ... Thinking" e o template do Bolt nascem com raciocínio ativo).
- **Amostragem**: as fichas da família Gemma 4 e do Bolt recomendam
  **temperature 1.0 e top_p 0.95** — é o default do Formiga
  (`--llm-temperature` para ajustar; 0.2 pode ajudar em JSON estruturado sem
  gramática).
- **Truncamento**: se o raciocínio consumir o teto e o JSON for cortado
  (`finish_reason: "length"`), a segunda tentativa dobra o cap. A resposta
  bruta falha aparece no evento `llm_call` de `events.jsonl`. Blocos
  `ANNELing ... ANNELs` inline no `content` são descartados antes do parse.
- **Orçamento de raciocínio no llama-server**: opcionalmente limite o thinking
  no servidor com `--reasoning-budget N` (o servidor corta o raciocínio no
  teto, preservando espaço para o JSON).

No agente, `reasoning_content` é mantido fora do histórico e do texto
mostrado ao usuário. Alguns GGUFs de thinking ignoram
`enable_thinking: false` — nesse caso o modelo raciocina mesmo assim; é
esperado e não é erro. Se o raciocínio esgotar o teto antes de produzir
texto, o agente responde com uma abstenção explícita e registra
`llm_truncated` em `events.jsonl`, em vez de devolver `"(sem resposta)"`.

## Smoke test manual

Com Ollama e SearXNG disponíveis:

```bash
ollama pull gemma4:e4b
# SearXNG com JSON habilitado, ex.: http://localhost:8080

formiga research \
  "O que muda na segurança ao migrar de SSH por senha para SSH com chaves?" \
  --output ./smoke-formiga --verbose
```

Para testar com o **backend remoto** (sem Ollama local), veja a seção
"Backend remoto" acima — basta a chave em `.env`/ambiente.

Depois inspecione:

- `report.md` — resposta com referências `[S1]`, conflitos e limitações;
- `state.json` — estados das questões, evidências com localizadores e hashes;
- `events.jsonl` — buscas, páginas, chamadas e falhas registradas.

Esse teste demonstra integração, **não comprova qualidade factual**.

O smoke do harness agêntico (`formiga agent`, com `/budget`, `/new`,
extensões, perfis e `NO_COLOR`) está em `docs/smoke_agent.md`.

## Privacidade

- A pergunta e os trechos de páginas são enviados ao backend de modelo
  configurado — **incluindo um provedor remoto** quando `llm_backend` é
  `openai` (NVIDIA, OpenAI, etc.): saiba que o conteúdo sai da sua máquina.
- A chave do backend remoto é enviada apenas no header `Authorization` da
  chamada; nunca aparece em logs, eventos ou relatórios.
- As consultas geradas são enviadas à instância SearXNG configurada e,
  dependendo da instância, a outros mecanismos de busca.
- Não inclua dados sensíveis sem confiar nesses serviços.
- Logs e eventos não incluem variáveis de ambiente nem credenciais.

## Segurança do fetcher

O acesso a páginas é separado dos endpoints configurados (que podem ser
`localhost`). O fetcher aceita apenas HTTP/HTTPS, bloqueia loopback, redes
privadas, link-local e endereços reservados **a cada redirecionamento**, limita
tamanho (2 MB), tempo (20 s), redirecionamentos (5) e tipos de conteúdo, e não
usa proxies herdados do ambiente. Limitação: a validação ocorre antes de cada
conexão, sem fixação de IP na conexão TLS.

## Arquitetura

```text
formiga/
├── pyproject.toml
├── docs/prd.md            # especificação (fonte da verdade do escopo)
├── docs/prd_v2.md         # roteiro v2 (Fases 1–11 do Formiga Agent)
├── docs/prd_agent.md      # PRD do harness agêntico
├── docs/smoke_agent.md    # smoke manual do agent
├── formiga.toml.example   # exemplo de arquivo de configuração
├── .env.example           # exemplo de arquivo de segredos
├── src/formiga/
│   ├── cli.py             # argparse: research, agent, gateway, cron,
│   │                      #   skills, trust, untrust, version
│   ├── config.py          # precedência CLI > env > default
│   ├── configfile.py      # arquivo de config TOML (default < arquivo < env < CLI)
│   ├── envfile.py         # arquivo .env que só preenche variáveis ausentes
│   ├── models.py          # schemas de estado (Pydantic)
│   ├── orchestrator.py    # loop de pesquisa controlado pelo programa
│   ├── budget.py          # orçamentos verificados antes de cada ação
│   ├── llm.py             # chamadas estruturadas + 1 correção de formato
│   ├── prompts.py         # prompts por tarefa (dados delimitados)
│   ├── schemas.py         # schemas das propostas do modelo
│   ├── ollama.py          # cliente Ollama
│   ├── llamacpp.py        # cliente llama-server (OpenAI-compatível)
│   ├── openai.py          # cliente remoto OpenAI-compatível (NVIDIA, etc.)
│   ├── fallback.py        # failover opt-in entre backends (circuit breaker)
│   ├── search.py          # protocolo de busca (provedor via adaptador)
│   ├── searxng.py         # cliente SearXNG JSON
│   ├── fetch.py           # protocolo de fetch de páginas
│   ├── fetcher.py         # fetch seguro (seção 13 do PRD)
│   ├── extract.py         # Trafilatura, trechos, seleção lexical
│   ├── evidence.py        # verificação determinística + textos das fontes
│   ├── report.py          # relatório a partir de afirmações, não snippets
│   ├── storage.py         # state.json atômico, events.jsonl
│   └── agent/             # harness agêntico (Formiga Agent)
│       ├── loop.py        # loop de turnos (orçamento, eviction, âncora)
│       ├── factory.py     # build_agent: discovery → registry → loop
│       ├── profiles.py    # perfis: gemma4-e2b, gemma4-e4b, nemotron-3.5-bolt-e4b
│       ├── guardrails.py  # AgentBudget, ToolBudgets, AntiLoop
│       ├── session.py     # sessão em disco (messages.json, events.jsonl)
│       ├── chat.py        # construção do chat client por backend
│       ├── client.py      # cliente de rede do agent
│       ├── stream.py      # streaming de respostas
│       ├── parser.py      # parse de tool calls
│       ├── prompts.py     # system prompt do agente
│       ├── cron.py        # JobStore das tarefas agendadas
│       ├── gateway.py     # daemon WebSocket em loopback (Fase 6)
│       ├── ui.py          # cores, limpeza de tela e painel da CLI
│       ├── tools/         # contratos (Tool, ToolResult) e compatibilidade
│       ├── extensions/    # engine de extensões (registro, hooks, eventos)
│       │   ├── api.py     # ExtensionAPI (register_tool, on, ui.notify)
│       │   ├── registry.py# ExtensionRegistry, ExtensionContext, event sink
│       │   ├── budget.py  # estimativa de tokens, schema_tokens, eviction
│       │   ├── discovery.py# descoberta builtin / .formiga/extensions / entry-points
│       │   └── events.py  # eventos do ciclo de extensão
│       └── tui/           # TUI Textual (80×24, barra de status)
│           ├── app.py     # AgentApp, _handle_event, _update_status
│           └── controller.py
│   └── ext/               # extensões builtin
│       ├── core/          # bash, read, edit (+ /tools, /ext, /budget, /new)
│       ├── web/           # web_search
│       ├── deepsearch/    # deep_search com progresso em linha
│       ├── memory/        # recall, memory_save, /recall, /memory (Fase 8)
│       └── skills/        # SKILL.md + skill_manage com aprovação (Fase 9)
└── tests/                 # testes offline com adaptadores falsos
```

Princípios: minimalismo; uma tarefa por chamada ao modelo; estado fora do
contexto; proveniência antes de fluência; abstenção é válida; limites
explícitos; fontes são dados não confiáveis; verificação é falível.

## Testes

```bash
.venv/bin/python -m pytest
```

Os testes automatizados rodam **sem rede e sem modelo real**, com fixtures e
adaptadores falsos (`tests/fakes.py`, `tests/fixtures/`).

## Limitações conhecidas

- Um modelo pequeno verificando afirmações não é validação independente:
  rótulos de verificação são sinais, não prova.
- O mesmo modelo sintetiza e audita — o relatório distingue afirmações diretas,
  inferências e recomendações, mas erros de leitura são possíveis.
- Execuções de `research` não são retomáveis; apenas inspecionáveis.
- Sem leitura de PDF/imagem, sem embeddings, sem reranking, sem execução
  paralela — por escolha do escopo do MVP.
- Avaliação formal de qualidade (perguntas anotadas, revisão humana) fica
  para depois do MVP, conforme a seção 14 do PRD.
- Gateway local sem autenticação nem TLS (single-user, loopback); token/pairing
  ficam para a Fase 10.
- Integração com plataformas de mensagem (Fase 10) e expansões avançadas
  (Fase 11) não estão incluídas.
