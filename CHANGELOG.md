# Changelog do Formiga

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
e este projeto adota [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [2.0.0] — 2026-11-17

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
- `pyproject.toml` → 2.0.0; `CHANGELOG.md`.
- `formiga research` confirmado intacto (smoke real com NIM executado).

### [0.1.0] — v1 inicial

- `formiga research`: pesquisa profunda controlada pelo programa com
  backends Ollama, llama.cpp e endpoint remoto OpenAI-compatível (NVIDIA NIM,
  OpenAI, DeepSeek, vLLM).
- SearXNG para busca, fetcher seguro, extração com Trafilatura, verificação
  determinística de evidências, relatório em Markdown com referências.
- Failover opt-in (circuit breaker), orçamentos de busca/páginas/chamadas.
- Testes offline com adaptadores falsos.

[2.0.0]: https://github.com/.../commits/2.0.0
[0.1.0]: https://github.com/.../commits/0.1.0
