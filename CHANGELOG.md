# Changelog do Formiga

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
e este projeto adota [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [0.5.0a2] — 2026-11-18

### Padrão — Gemma 4 E4B

- `DEFAULT_MODEL` passou de `nemotron-3.5-bolt` para **`gemma4:e4b`**
  (Gemma 4 E4B, `google/gemma-4-E4B-it` — família-alvo do harness). O nome
  seleciona por substring o perfil builtin `gemma4-e4b` (thinking desligado,
  4096 tok/turno) no `formiga agent`.
- Posicionamento documentado: a família **Gemma 4 E2B/E4B** é o foco e o
  **Nemotron 3.5 Bolt E4B** é um pós-treinamento (RL/GRPO) da NVIDIA feito a
  partir do `Gemma-4-E4B-it` — alternativa, não o modelo principal.

### Perfis — força explícita

- `[profile] active` no TOML agora é aceito por `configfile` (antes: erro
  "chave desconhecida") e vira `Config.active_profile`.
- `build_agent` usa `active_profile` como fallback do `model_hint`: o
  `--profile` do `formiga cron add` (e o perfil vindo do gateway) agora
  efetivamente escolhe o perfil quando a auto-seleção por substring do nome
  do modelo não casa (ex.: a tag do Ollama `nemotron-3.5-bolt`, sem `-e4b`).

### Documentação

- `README.md` reorganizado por audiência (modelos → quickstart → comandos →
  comandos de sessão → referência → apêndices → arquitetura/limitações) com a
  família Gemma 4 como foco e Gemma 4 E4B como default.
- Corrigidos claims falsos: `formiga memory ...` não é subcomando CLI (a
  memória vive na sessão via `/memory` e `/recall`); instalação sem extra
  `gui` não se resume ao `research`; "gateway/cron/memória/skills não
  incluídos" nas limitações (tudo já implementado); env vars e flags
  inexistentes removidas (`FORMIGA_MAX_SEARCHES` etc.); auto-seleção de
  perfil documentada conforme o código real.
- `formiga.toml.example` e `.env.example` atualizados para o default
  Gemma 4 E4B (perfis `gemma4-e2b`/`gemma4-e4b`/Bolt, extensões
  `memory,skills`, vars de orçamento do agent, cron e memória).
- `docs/smoke_agent.md`: removidos `formiga agent --profile` e
  `formiga memory ...` (não existem); smoke alinhado ao `gemma4:e4b`.
- Nova subseção "Busca: SearXNG e motores" no README: requisição
  `GET /search?format=json` sem categoria (só `general`), motores medidos na
  instância local de referência (`google cse` respondente estável; `brave` e
  `duckduckgo` com suspensão temporária por rate-limit/CAPTCHA; `google` e
  `bing` desabilitados no `settings.yml`) e como verificá-los em
  `/config?format=json`.

### Correções — backend llama.cpp

- `formiga agent --llm-backend llamacpp` falhava sempre com
  `httpx.ReadError: [Errno 9] Bad file descriptor`: `raise_for_status()`,
  `.json()` e o consumo do SSE ocorriam depois de fechar o `httpx.Client`.
  O processamento da resposta agora acontece dentro do `with`, como já
  faziam os backends `ollama` e `openai`.
- `reasoning_content` de modelos thinking (Gemma 4 E2B IT Thinking, Nemotron)
  agora é capturado separadamente de `content`, tanto no stream quanto na
  resposta única. O raciocínio não é entregue ao callback de streaming nem
  entra no histórico de mensagens — não consome contexto nas chamadas
  seguintes.
- Quando o raciocínio consome todo o teto de geração sem produzir texto, o
  agente responde com abstenção explícita e registra o evento `llm_truncated`
  (`reasoning_chars`, `turns`) em vez de devolver `"(sem resposta)"` e marcar
  a tarefa como concluída.
- Teste de streaming do `llamacpp` passou a usar um servidor HTTP real em
  porta efêmera: `httpx.MockTransport` não tem socket e mascarava o bug do
  client fechado.

### Perfis de modelo

- Seções `[profiles.*]` do TOML eram carregadas como configuração de
  extensão e chegavam vazias ao `build_agent`; agora vão para
  `Config.profiles`, e o `name` do `Profile` é derivado da chave da seção.
- Novo perfil builtin `gemma4-e2b` para o GGUF Gemma 4 E2B IT Thinking:
  thinking ligado e `max_tokens_per_turn = 8192` para acomodar o raciocínio.
- O `thinking` do perfil agora é espelhado em `llamacpp_thinking` (campo
  efetivamente lido pelo backend); uma flag explícita na CLI continua
  sobrepondo o perfil.

## [0.5.0a1] — 2026-11-18

### CLI interativa — cores, limpeza de tela e painel de abertura

- Painel de abertura na CLI (local e retomada): sessão/transcript, ferramentas,
  extensões, comandos e seções contribuídas pelas extensões (skills com nome e
  descrição). O gateway envia o estado estruturado no frame `attached`; o
  cliente formata e colore localmente.
- Cores apenas em TTY (ou `CLICOLOR_FORCE=1`), desativadas por `--no-color` ou
  `NO_COLOR`; `--no-clear` mantém a tela. Fora de TTY a saída continua sem
  nenhuma sequência ANSI (regra do PRD §8).
- Novo comando `/help`: lista comandos registrados, skills e seções de resumo.
- API `register_summary` no registry/`ExtensionContext` para extensões
  contribuírem seções do painel sem acoplar o núcleo a nomes concretos.
- `AgentLoop` não mudou; TUI permanece intocada.

### Fase 9 — Skills declarativas (PRD §14)

- `ext/skills/`: skill = pasta com `SKILL.md` (frontmatter `name`,
  `description`, `when_to_use`) + corpo Markdown, sem código; parser valida
  nome kebab-case, exige descrição e recusa credenciais.
- Descoberta determinística em `~/.formiga/skills/` (global) e
  `.formiga/skills/` (projeto, carregado só se o projeto estiver na allowlist
  de trust); skills corrompidas/duplicadas geram aviso e não derrubam a sessão.
- Custo zero quando ociosas: `/nome-da-skill` agenda a expansão do corpo na
  próxima mensagem e registra o evento `skill_expanded` (não entra no prompt
  até ser chamada). `/skills` lista, mostra pendentes e aprova/descarta.
- Ferramenta `skill_manage(action=list|write|delete)` com **staging** em
  `~/.formiga/skills/pending.json`: nada é gravado ou removido do disco sem
  `/skills approve <id>` (humano); `/skills reject <id>` descarta.
- Nudge pós-tarefa: novo evento `task_end` (com `successful` e
  `successful_tools`) disparado pelo `AgentLoop` ao final de cada turno;
  após uso bem-sucedido de ferramentas, o harness sugere persistir o
  procedimento como skill — sempre com aprovação.
- `/skills` e comandos por skill na CLI/TUI; `formiga skills list` no CLI.
- Extensão builtin `skills` habilitada por default
  (`DEFAULT_ENABLED_EXTENSIONS`), sem config própria.
- 424 testes verdes (incluindo 20 de skills) + `ruff check` limpo.

## [0.2.0a1] — 2026-11-17

### MVP do Formiga Agent (PRD v2, Fases 1–5)

**Fase 1 — Desacoplamento e registry**
- Loop agêntico sem conhecer nomes de ferramentas; núcleo acessa ferramentas
  apenas pelo `ExtensionRegistry` (populado por descoberta).
- `agent/extensions/` mínimo: `api.py`, `registry.py`, `events.py`.
- `factory.py` reescrito: descoberta → registry → `AgentLoop`.
- Teste de equivalência com o v1.

**Fase 2 — Sistema de extensões completo**
- Descoberta builtin, `~/.formiga/extensions/` e `.formiga/extensions/` com
  trust (`formiga trust/untrust`, config global).
- 6 eventos com encadeamento + observação; erros de handler isolados.
- `register_command` → `/tools`, `/ext` na CLI e TUI.
- Extensão de exemplo em `docs/smoke_agent.md`.

**Fase 3 — Compensação de 8B na extensibilidade**
- `budget.py`: contagem de tokens (chars/4), orçamento de schemas com
  fail-fast, teto de seções de extensão.
- Eviction de contexto + re-injeção da âncora de objetivo (hook `context`).
- Meta-ferramenta `activate_tool` (lazy, expiração, anti-loop estendido).
- `profiles.py` + `[profile]` / `[profiles.*]` (`gemma4-e4b`,
  `nemotron-3.5-bolt-e4b`).

**Fase 4 — Interfaces e orçamento visível**
- CLI: linha `turnos/llm/ctx/ext`, `/budget`, `/new`, `pi.emit` em linha.
- TUI: barra de status com `ctx`/`ext`/perfil, eventos de extensão em linha.
- `NO_COLOR`, alvo 80×24, `Ctrl+C`/`Esc` cooperativo.

**Fase 5 — Endurecimento e docs**
- Suíte completa offline verde (367 testes) + `ruff check` limpo.
- `pythonpath = ["tests"]` no pytest (coleta sem `PYTHONPATH`).
- `write_global_config` suporta sub-tabelas e arrays de tabelas
  (`formiga trust` funciona em config globais pré-existentes).
- README 2.0: instalação sem uv, seção Agente, arquitetura `agent/`/`ext/`.
- `formiga.toml.example` e `.env.example` com perfis, `trusted_projects`,
  `max_context_tokens`, `tool_schema_tokens`.
- `docs/smoke_agent.md` 2.0: cenários do agente, extensão externa, perfis,
  TUI, smoke local Gemma 4 E4B (documentado) e NIM.
- `pyproject.toml` → 0.2.0a1; `CHANGELOG.md`.
- `formiga research` confirmado intacto (smoke real com NIM executado).

**Fase 6 — Gateway local + retomada (PRD §11)**
- `gateway.py`: daemon WebSocket apenas em loopback que possui o `AgentLoop`
  e as sessões; pidfile com pid/porta/versão (`~/.formiga/gateway-<hash>.json`);
  um gateway por workdir; idle-shutdown de 10 min sem sessão ativa.
- `client.py`: `GatewayClient` (handshake WS, create/attach/submit/cancel/
  detach/list_sessions) e `ensure_gateway()` (não sobe subprocesso por padrão;
  `formiga gateway start` sobe manualmente).
- CLI: `formiga gateway start|stop|status`; modo padrão anexa ao gateway
  (input via `run_in_executor`); `--local` e `--print` continuam in-process.
- Retomada: `formiga agent --continue` (última sessão) e `--resume <id>`
  carregam `messages.json` e continuam o loop; `list_sessions` ordena por mtime.
- Desconectar ≠ cancelar: fechar o terminal no meio do turno não interrompe;
  reanexar mostra a resposta; fila crash-durable sobrevive a restart.
- Broadcast de eventos (`stream`, `tool_start`, `budget`, `notification`, …)
  para múltiplos clientes anexados à mesma sessão.
- `turn_done` garantido mesmo quando o loop de um turno falha.
- 378 testes verdes (incluindo 11 de aceitação do gateway) + `ruff check` limpo.

## [0.4.0a1] — 2026-11-17

### Fase 8 — Memória estilo Hermes (PRD §13)

- `ext/memory/`: índice FTS5 (`~/.formiga/index.db`) sobre `messages.json` e
  `transcript.md` de sessões passadas; ferramenta `recall(query, limit?)`
  e comando `/recall <query>` (busca incrementada por mtime).
- Memória curada: `~/.formiga/memory/MEMORY.md` (fatos duráveis) e
  `USER.md` (perfil), injetadas como seções do system prompt com cabeçalho
  de "dado não confiável" (guardrail §13.4); tetos rígidos (≤ 1 000 tokens
  memória + 600 tokens perfil, truncamento determinístico).
- Nudge: `session_end` (evento novo) e a cada 10 turnos sugerem salvar o
  aprendizado; `memory_save(entries)` apenas *stageia* em `pending.json` —
  a gravação ocorre só pelo comando humano `/memory save` (modelo não grava
  sozinho). Comandos `/memory show | pending | save | clear | edit`.
- `session_end` adicionado a `OBSERVATION_EVENTS`; `AgentLoop.end_session()`
  emitido nos pontos de saída da CLI/TUI e ao parar o gateway.
- Extensão builtin `memory` habilitada por default
  (`DEFAULT_ENABLED_EXTENSIONS`); config `[memory] recall/nudge/max_tokens`;
  env `FORMIGA_MEMORY_RECALL` / `FORMIGA_MEMORY_NUDGE` /
  `FORMIGA_MEMORY_MAX_TOKENS`.
- **Correção**: seções `[cron]` e `[memory]` agora são lidas do
  `formiga.toml` (antes causavam "seções desconhecidas").
- 404 testes verdes (incluindo 13 de aceitação da memória) + `ruff check`
  limpo.

## [0.3.0a1] — 2026-11-17

### Fase 7 — Tarefas agendadas (cron) (PRD §12)

- `cron.py`: dataclass `Job` (id, prompt, schedule, enabled, model/profile,
  orçamento override, catchup, tz, next_run/last_run/last_status/last_error);
  `JobStore` com persistência atômica em `~/.formiga/jobs.json`;
  `Schedule` com parser cron 5 campos (croniter), `every N[mhd]` e
  `at <ISO-8601>`; `next_run` com relógio injetável (`now_fn`) para testes
  determinísticos; one-shot `at` no passado não se repete.
- Scheduler no daemon (`gateway.py`): task asyncio dispara jobs no horário,
  cria sessão nova em `sessoes/cron/<job>/<timestamp>/` com contexto (data,
  cwd) e orçamento do job; eventos `job_start`/`job_end` (PRD §7.2);
  gateway parado na hora → `skip` (default) ou `catchup: once` (roda 1× ao
  voltar); exceções de turno isoladas (não derrubam o daemon).
- CLI: `formiga cron add|list|rm|enable|disable|run <id>`; `run` é
  in-process (offline, sem depender do daemon); `[cron] catchup/tz` no
  `formiga.toml`; env `FORMIGA_CRON_CATCHUP` / `FORMIGA_CRON_TZ`.
- `/cron` registrado na fábrica (ao lado de `/tools` `/ext` `/budget` `/new`);
  comandos `/` anexados ao gateway despacham via ação `command` →
  `command_result` (WS).
- 391 testes verdes (incluindo 13 de aceitação do cron) + `ruff check` limpo.

### [0.1.0] — v1 inicial

- `formiga research`: pesquisa profunda controlada pelo programa com
  backends Ollama, llama.cpp e endpoint remoto OpenAI-compatível (NVIDIA NIM,
  OpenAI, DeepSeek, vLLM).
- SearXNG para busca, fetcher seguro, extração com Trafilatura, verificação
  determinística de evidências, relatório em Markdown com referências.
- Failover opt-in (circuit breaker), orçamentos de busca/páginas/chamadas.
- Testes offline com adaptadores falsos.

[0.3.0a1]: https://github.com/.../commits/0.3.0a1
[0.2.0a1]: https://github.com/.../commits/0.2.0a1
[0.1.0]: https://github.com/.../commits/0.1.0
