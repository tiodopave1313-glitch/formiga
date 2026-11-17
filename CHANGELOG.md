# Changelog do Formiga

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
e este projeto adota [Versionamento Semântico](https://semver.org/lang/pt-BR/).

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

### [0.1.0] — v1 inicial

- `formiga research`: pesquisa profunda controlada pelo programa com
  backends Ollama, llama.cpp e endpoint remoto OpenAI-compatível (NVIDIA NIM,
  OpenAI, DeepSeek, vLLM).
- SearXNG para busca, fetcher seguro, extração com Trafilatura, verificação
  determinística de evidências, relatório em Markdown com referências.
- Failover opt-in (circuit breaker), orçamentos de busca/páginas/chamadas.
- Testes offline com adaptadores falsos.

[0.2.0a1]: https://github.com/.../commits/0.2.0a1
[0.1.0]: https://github.com/.../commits/0.1.0
