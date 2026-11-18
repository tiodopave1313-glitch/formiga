# Formiga

Harness minimalista de pesquisa profunda. Recebe uma pergunta, divide o trabalho
em lacunas investigáveis, busca e lê fontes públicas, registra evidências e
produz uma resposta em Markdown com referências e limitações.

> **O harness controla o processo. O modelo interpreta e redige. As evidências
> delimitam o que pode ser afirmado.**

O sistema não depende de um agente autônomo com ferramentas livres: o fluxo é
controlado pelo programa e o LLM (default: Nemotron 3.5 Bolt E4B, 8B totais —
Ollama, llama.cpp ou endpoint remoto OpenAI-compatível) executa tarefas
pequenas e delimitadas — planejar, formular consulta, extrair citações,
verificar, comparar, sintetizar e auditar.

## Instalação

Requer Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .              # sem o extra `gui`, só `formiga research`
pip install ".[gui]"          # com o extra `gui`, também `formiga agent --tui`
```

Os extras são opcionais: o extra `gui` instala o Textual, necessário apenas para
a TUI interativa (`formiga agent --tui`). Nem `uv` nem ferramentas além do `pip`
são exigidas.

## Uso

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
legível), mas **não são retomadas** no MVP.

### `formiga agent` — harness agêntico (CLI interativa, TUI ou headless)

```bash
formiga agent "qualquer pergunta sobre o projeto"
```

- Sem flags: **CLI interativa** — limpa a tela e mostra um painel de abertura
  (ferramentas, extensões, comandos e skills instaladas), depois `pergunta>`,
  streaming token a token, linhas de ferramenta em linha
  (`⚙ bash — command=…`), barra de orçamento
  (`turnos n/24 · llm n/120 · ctx Xk/Yk · ext N ferramentas`) e comandos `/`
  (`/help` lista tudo; `/tools`, `/ext`, `/budget`, `/new` etc.).
- Cores são usadas apenas em TTY; `--no-color` (ou `NO_COLOR=1`) desativa e
  `--no-clear` mantém a tela como está. `CLICOLOR_FORCE=1` força cor em pipes.
- `--print`: headless, imprime a resposta final no stdout (útil em scripts).
- `--tui`: TUI Textual (80×24, barra de status com perfil, eventos de extensão
  em linha, `Esc`/`Ctrl+C` cooperativos). Requer o extra `gui`.

Configuração via CLI, variáveis de ambiente (`FORMIGA_*`) ou `./formiga.toml`
(precedência: CLI > env > arquivo > defaults). Veja `formiga.toml.example`.

### `formiga gateway` — daemon local (Fase 6)

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
- Um gateway por diretório de trabalho; sem autenticação nem TLS no MVP
  (single-user, loopback).

### `formiga cron` — tarefas agendadas (Fase 7)

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
- Cada run grava em `sessoes/cron/<job>/<timestamp>/` (mesmos artefatos de
  sempre); eventos `job_start`/`job_end` são broadcast aos clientes anexados.
- Config: `[cron] catchup = "skip"`, `tz = "America/Sao_Paulo"`;
  env `FORMIGA_CRON_CATCHUP` / `FORMIGA_CRON_TZ`.

### `formiga memory` — memória estilo Hermes (Fase 8)

A memória tem três camadas: **recall** (busca FTS5 em sessões passadas),
**memória curada** (`MEMORY.md` com nudge + aprovação humana) e **perfil**
(`USER.md` injetado no prompt). Tudo fica em `~/.formiga/memory/` e o índice
em `~/.formiga/index.db`. É uma extensão builtin (`memory`) ligada por
default.

```bash
# Busque o que a gente falou sobre X em sessões passadas
formiga agent "o que a gente decidiu sobre o deploy?"  # o modelo usa /recall

# Veja o que está na memória curada e no perfil
formiga memory show

# Veja sugestões aguardando aprovação e as aplique
formiga memory pending
formiga memory save
```

- **Recall**: `recall(query, limit?)` encontra trechos do `messages.json` de
  sessões antigas (índice incremental por mtime, FTS5).
- **Nudge**: ao fim da sessão (e a cada 10 turnos), o harness sugere salvar
  o que aprendeu; a gravação só ocorre pelo comando humano `/memory save`
  (o modelo nunca grava sozinho — staging em `pending.json`).
- **Perfil**: `USER.md` vira seção do system prompt (≤ 600 tokens).
- **Guardrails**: memória é dado não confiável (cabeçalho de aviso), teto
  rígido (≤ 1 000 tokens memória + 600 tokens perfil, truncamento),
  credenciais recusadas, arquivo corrompido gera aviso e não derruba.
- Config: `[memory] recall = true`, `nudge = true`, `max_tokens = 1600`;
  env `FORMIGA_MEMORY_RECALL` / `FORMIGA_MEMORY_NUDGE` /
  `FORMIGA_MEMORY_MAX_TOKENS`.

### `formiga skills` — conhecimento declarativo (Fase 9)

Skills são procedimentos reutilizáveis em Markdown (`SKILL.md`), não código.
Ficam **fora do prompt** até serem chamadas: custo zero quando ociosas. São
carregadas de `~/.formiga/skills/` (globais) e de `.formiga/skills/` do projeto
(somente se o projeto estiver na allowlist de trust).

```bash
# Crie uma skill global manualmente
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

# Liste as skills disponíveis (globais + projeto confiável)
formiga skills list
```

Dentro do `formiga agent`, `/skills` lista as skills e `/revisar-pr` agenda a
expansão do conteúdo para a próxima mensagem (registrada no evento
`skill_expanded`). O modelo também pode propor novas skills com
`skill_manage(action="write")`: a proposta fica em
`~/.formiga/skills/pending.json` e **nada é gravado** até um humano aprovar com
`/skills approve <id>` (ou descartar com `/skills reject <id>`).

## Opções de `research`

| Opção | Finalidade |
|---|---|
| `--output PATH` | Diretório de saída (padrão `./formiga-out`) |
| `--config PATH` | Arquivo de configuração TOML (default: `./formiga.toml` se existir; ver abaixo) |
| `--model NAME` | Nome do modelo no Ollama ou ID do modelo no backend remoto (default: `nemotron-3.5-bolt`) |
| `--ollama-url URL` | Endpoint do Ollama |
| `--searxng-url URL` | Endpoint da instância SearXNG (JSON habilitado) |
| `--llm-backend {ollama,llamacpp,openai}` | Backend do modelo (default: ollama) |
| `--llm-base-url URL` | URL base do endpoint remoto OpenAI-compatível (ex.: `https://integrate.api.nvidia.com/v1`) |
| `--api-key-env NAME` | Nome da variável de ambiente com a chave do endpoint remoto (default: `NVIDIA_API_KEY`) |
| `--llm-thinking` | Deixar o modelo raciocinar antes do JSON (default: **ligado**; desligue com `--no-llm-thinking`) |
| `--fallback-backend {ollama,llamacpp,openai}` | Backup **opt-in**: ativa somente após falhas do backend principal (default: sem backup) |
| `--fallback-after-failures N` | Falhas consecutivas do principal antes do backup assumir (default 1) |
| `--llm-max-retries N` | Retries HTTP (429/5xx) no backend remoto, com backoff (default 2) |
| `--llamacpp-url URL` | Endpoint do llama-server (OpenAI-compatível) |
| `--llamacpp-thinking` | Deixar o modelo raciocinar antes do JSON (default: **ligado**; desligue com `--no-llamacpp-thinking`) |
| `--max-searches N` | Limite de buscas (default 12) |
| `--max-pages N` | Limite de páginas (default 18) |
| `--max-llm-calls N` | Limite total de chamadas (default 40; 8 reservadas para síntese/auditoria) |
| `--timeout-seconds N` | Tempo máximo da execução (default 900) |
| `--llm-timeout-seconds N` | Timeout por chamada ao modelo (default 300; CPU lenta pode exigir mais) |
| `--llm-temperature T` | Temperatura de amostragem (default 1.0, conforme a ficha do Nemotron 3.5 Bolt; 0.2 pode ajudar em JSON estruturado) |
| `--overwrite` | Autoriza sobrescrever um diretório de saída existente |
| `--verbose` | Eventos operacionais no stderr |

## Arquivo de configuração

Além da CLI e das variáveis de ambiente, o Formiga lê um arquivo TOML.
Precedência: **CLI > variáveis de ambiente > arquivo > defaults**. Sem
`--config`/`FORMIGA_CONFIG`, ele procura `./formiga.toml` e depois
`~/.config/formiga/config.toml`. Veja o exemplo completo em
`formiga.toml.example` (o `formiga.toml` real é ignorado pelo git, pois pode
conter uma chave de API com permissão `0600`).

```toml
[llm]
backend = "openai"                       # ollama | llamacpp | openai
model = "nvidia/nemotron-3.5-bolt-e4b"
base_url = "https://integrate.api.nvidia.com/v1"
api_key_env = "NVIDIA_API_KEY"           # nome da variável, nunca a chave
temperature = 1.0
timeout_seconds = 120.0
max_retries = 2
thinking = true                          # raciocínio antes do JSON (default)
# Backup opt-in (nunca automático): descomente para ativar.
# fallback_backend = "ollama"
# fallback_after_failures = 1

[search]
searxng_url = "http://localhost:8080"

[budget]
max_searches = 12
max_pages = 18
max_llm_calls = 40
timeout_seconds = 900

[extensions]
# Ordem de carregamento = ordem desta lista.
enabled = ["core", "web", "deepsearch", "memory", "skills"]
# Diretórios de projeto cujo .formiga/ carrega (allowlist global).
trusted_projects = []

[agent]
max_turns = 24
max_llm_calls = 120
timeout_seconds = 1800
max_deep_searches = 2
max_web_searches = 6
max_web_fetches = 8
tool_result_chars = 4000
workdir = "."

# Perfis de modelo (§9.6 do PRD): seleção por substring do nome do modelo.
[profile]
# active = "nemotron-3.5-bolt-e4b"   # sobrescreve a auto-seleção

[profiles.gemma4-e2b]
context_tokens = 32768                 # janela útil, não a anunciada
thinking = true                        # GGUF "IT ... Thinking": raciocínio ligado
temperature = 1.0
top_p = 0.95
max_tokens_per_turn = 8192             # thinking consome orçamento de geração
tool_schema_tokens = 1600

[profiles.gemma4-e4b]
context_tokens = 32768                 # janela útil, não a anunciada
thinking = false
temperature = 1.0
top_p = 0.95
max_tokens_per_turn = 4096
tool_schema_tokens = 1600

[profiles.nemotron-3.5-bolt-e4b]
thinking = true
temperature = 1.0
top_p = 0.95

[ext.core]
unsafe_bash = false                    # AGENT_UNSAFE=1 para permitir
```

## Configuração

Precedência: argumento da CLI > variável de ambiente > arquivo TOML > valor padrão.

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

```text
FORMIGA_CONFIG=caminho/formiga.toml
FORMIGA_ENV_FILE=caminho/secrets.env
FORMIGA_MODEL=nemotron-3.5-bolt
FORMIGA_OLLAMA_URL=http://localhost:11434
FORMIGA_SEARXNG_URL=http://localhost:8080
FORMIGA_LLM_BACKEND=ollama          # ou: llamacpp, openai
FORMIGA_LLAMACPP_URL=http://localhost:8080   # endpoint do llama-server
FORMIGA_OPENAI_URL=https://integrate.api.nvidia.com/v1   # backend remoto
FORMIGA_OPENAI_API_KEY_ENV=NVIDIA_API_KEY
FORMIGA_FALLBACK_BACKEND=           # backup opt-in: ollama | llamacpp | openai
FORMIGA_FALLBACK_AFTER_FAILURES=1   # falhas consecutivas antes do backup assumir
FORMIGA_LLM_TIMEOUT=300             # timeout por chamada ao modelo (segundos)
FORMIGA_LLM_TEMPERATURE=1.0         # temperatura de amostragem (ficha do modelo)
FORMIGA_LLM_THINKING=1              # 0 = desligar o raciocínio (default: 1)
FORMIGA_LLAMACPP_THINKING=1         # override do thinking só no llama.cpp
FORMIGA_AGENT_MAX_TURNS=24
FORMIGA_AGENT_MAX_LLM_CALLS=120
FORMIGA_AGENT_TIMEOUT_SECONDS=1800
FORMIGA_AGENT_MAX_CONTEXT_TOKENS=32768
FORMIGA_AGENT_TOOL_SCHEMA_TOKENS=1600
FORMIGA_PROFILE_MODEL_HINT=
FORMIGA_EXTENSIONS_ENABLED=core,web,deepsearch
```

A chave do backend remoto nunca vai na CLI. Fontes possíveis, em ordem de
preferência: variável de ambiente definida manualmente, `.env` do projeto
(nome indicado por `api_key_env` / `--api-key-env`, default
`NVIDIA_API_KEY`) ou `api_key = "..."` no arquivo TOML com permissão `0600`.

O modelo padrão é uma escolha inicial de implementação, não uma exigência de
qualidade. Instale-o antes no backend escolhido e configure uma instância
SearXNG própria com o formato JSON habilitado (`search.formats: [html, json]`).

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
.venv/bin/formiga research "..." \
  --llm-backend llamacpp --llamacpp-url http://127.0.0.1:9931 \
  --output ./pesquisa-formiga
```

Receita recomendada para o Nemotron 3.5 Bolt (thinking com orçamento de
raciocínio controlado no servidor):

```bash
llama-server -m Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf \
  --alias nemotron-bolt -c 65536 --jinja \
  --reasoning on --reasoning-budget 512
```

Builds antigas do llama-server que não suportam `schema` dentro de
`response_format` também funcionam — o campo é ignorado e a validação fica no
harness.

### Modelo adotado como padrão: Nemotron 3.5 Bolt E4B 4GB

O default é [`nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB`](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB)
(8B totais, 4B efetivos, Q4_K_M ~6,2 GB, contexto 64K), post-treinado pela
NVIDIA sobre a Gemma 4 E4B com RL em ambientes de saída estruturada,
instruction following e tool use. No Ollama: `nemotron-3.5-bolt`; na NIM
remota: `nvidia/nemotron-3.5-bolt-e4b`. Detalhes que afetam o Formiga:

- **Thinking**: o reasoning é controlado pelo chat template
  (`chat_template_kwargs: {"enable_thinking": true/false}`) e o **default do
  próprio modelo é ligado** — o Formiga segue esse default e envia o kwarg
  explicitamente no `llamacpp` e no `openai`, e `think: true` no Ollama.
  Endpoints que rejeitam o campo recebem uma repetição sem ele. Para desligar
  (respostas diretas, mais velocidade): `--no-llm-thinking`, `thinking = false`
  ou `FORMIGA_LLM_THINKING=0`. Com thinking ligado, os caps por tarefa ganham
  folga extra de tokens e o teto dobrado sobe para 4096.
- **Orçamento de raciocínio no llama-server**: opcionalmente limite o thinking
  no servidor com `--reasoning-budget N` (o servidor corta o raciocínio no
  teto, preservando espaço para o JSON).
- **Amostragem**: a ficha recomenda **temperature 1.0 e top_p 0.95** nos dois
  modos — é o default do Formiga (`--llm-temperature` para ajustar; 0.2 pode
  ajudar em JSON estruturado sem gramática).
- **Truncamento**: se o raciocínio consumir o teto e o JSON for cortado
  (`finish_reason: "length"`), a segunda tentativa dobra o cap. A resposta
  bruta falha aparece no evento `llm_call` de `events.jsonl`. Blocos
  `ANNELing ... ANNELs` inline no `content` são descartados antes do parse.

No agente, `reasoning_content` é mantido fora do histórico e do texto
mostrado ao usuário. Alguns GGUFs de thinking ignoram
`enable_thinking: false` — nesse caso o modelo raciocina mesmo assim; é
esperado e não é erro. Se o raciocínio esgotar o teto antes de produzir
texto, o agente responde com uma abstenção explícita e registra
`llm_truncated` em `events.jsonl`, em vez de devolver `"(sem resposta)"`.

## Smoke test manual

Com Ollama e SearXNG disponíveis:

```bash
ollama pull nemotron-3.5-bolt
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
usa proxies herdados do ambiente. Limitação do MVP: a validação ocorre antes de
cada conexão, sem fixação de IP na conexão TLS.

## Arquitetura

```text
formiga/
├── pyproject.toml
├── docs/prd.md            # especificação (fonte da verdade do escopo)
├── docs/prd_v2.md         # roteiro v2 (Fases 1–11 do Formiga Agent)
├── formiga.toml.example   # exemplo de arquivo de configuração
├── .env.example           # exemplo de arquivo de segredos
├── src/formiga/
│   ├── cli.py             # argparse, comandos (research, agent, trust, untrust)
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
│   ├── searxng.py         # cliente SearXNG JSON
│   ├── fetcher.py         # fetch seguro (seção 13 do PRD)
│   ├── extract.py         # Trafilatura, trechos, seleção lexical
│   ├── evidence.py        # verificação determinística + textos das fontes
│   ├── report.py          # relatório a partir de afirmações, não snippets
│   └── storage.py         # state.json atômico, events.jsonl
│   └── agent/             # harness agêntico (Formiga Agent, Fases 1–5)
│       ├── loop.py        # loop de turnos (orçamento, eviction, âncora)
│       ├── factory.py     # build_agent: discovery → registry → loop
│       ├── profiles.py    # perfis de modelo (gemma4-e2b, gemma4-e4b, nemotron-3.5-bolt-e4b)
│       ├── guardrails.py  # AgentBudget, ToolBudgets, AntiLoop
│       ├── session.py     # sessão em disco (messages.json, events.jsonl)
│       ├── ui.py          # cores, limpeza de tela e painel da CLI
│       ├── extensions/    # engine de extensões (registro, hooks, eventos)
│       │   ├── api.py     # ExtensionAPI (register_tool, on, ui.notify)
│       │   ├── registry.py# ExtensionRegistry, ExtensionContext, set_event_sink
│       │   ├── budget.py  # estimativa de tokens, schema_tokens, eviction
│       │   └── discovery.py# descoberta builtin / .formiga/extensions / entry-points
│       └── tui/           # TUI Textual (80×24, barra de status)
│           ├── app.py     # AgentApp, _handle_event, _update_status
│           └── controller.py
│   └── ext/               # extensões builtin
│       ├── core/          # bash, read, edit (+ /tools, /ext, /budget, /new)
│       ├── web/           # web_search
│       ├── deepsearch/    # deep_search com progresso em linha
│       ├── memory/        # recall + MEMORY.md/USER.md (Fase 8)
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

- Um 8B verificando afirmações não é validação independente: rótulos de
  verificação são sinais, não prova.
- O mesmo 8B sintetiza e audita — o relatório distingue afirmações diretas,
  inferências e recomendações, mas erros de leitura são possíveis.
- Execuções não são retomáveis; apenas inspecionáveis.
- Sem leitura de PDF/imagem, sem embeddings, sem reranking, sem execução
  paralela — por escolha do escopo do MVP.
- Avaliação formal de qualidade (perguntas anotadas, revisão humana) fica
  para depois do MVP, conforme a seção 14 do PRD.
- Gateway local com retomada de sessões (`formiga gateway`), tarefas agendadas
  (`formiga cron`), memória estilo Hermes (`ext/memory`), skills e adapters de
  plataformas de mensagem são fases 6–11 do PRD — pós-MVP, não incluídos.
