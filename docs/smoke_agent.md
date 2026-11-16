# Smoke manual — Formiga Agent (MVP)

Procedimento final de validação contra um modelo real (PRD §12 e critérios de
aceite §13). Sem automação: é uma lista de verificação humana. Os testes
offline (`pytest`) já cobrem os mesmos caminhos com fakes; este smoke existe
para confirmar o comportamento com um modelo pequeno de verdade.

## Pré-requisitos

- Chave do NIM em `NVIDIA_API_KEY` (ou `--api-key-env` apontando outra variável).
- SearXNG local para `web_search`/`deep_search` (ex.: `http://localhost:8080`).
- Terminal com pelo menos 80×24 (funciona menor, mas este é o alvo).

## 1. Headless (`--print`) fim a fim

```bash
formiga agent --print \
  "Leia formiga.toml, diga qual backend está configurado e pesquise 'Nemotron NVIDIA NIM' na web." \
  --llm-backend openai \
  --llm-base-url https://integrate.api.nvidia.com/v1 \
  --model nvidia/nemotron-nano-9b-v2 \
  --searxng-url http://localhost:8080
```

Verificar:

- [ ] A resposta final cita o backend do arquivo e fundamentos da busca.
- [ ] A sessão existe em `sessoes/<timestamp>/` com `messages.json` e
      `events.jsonl` (turnos, `tool_call` com `ok`, durações).
- [ ] Nenhuma credencial aparece em `messages.json`, `events.jsonl` ou stdout.

## 2. TUI com tarefa mista (`bash` + `deep_search`)

```bash
formiga agent \
  "Crie o arquivo prova.txt com 'conteudo-smoke' via bash, confirme com read e, se sobrar orçamento, faça um deep_search sobre 'trafilatura extração de conteúdo'." \
  --llm-backend openai \
  --llm-base-url https://integrate.api.nvidia.com/v1 \
  --model nvidia/nemotron-nano-9b-v2 \
  --searxng-url http://localhost:8080
```

Na TUI, verificar (nesta ordem):

- [ ] A pergunta aparece pré-preenchida na entrada; Enter inicia.
- [ ] O texto do agente aparece **enquanto é gerado** (stream token a token).
- [ ] Cada ferramenta aparece em linha **antes** de executar:
      `⚙ bash — command=echo …`, `⚙ read — path=prova.txt`, seguidas de
      duração (`(1.2 s)`); o progresso do `deep_search` aparece como linhas
      `· planejado · buscas · síntese`.
- [ ] A barra de status reflete o loop real: `turnos n/24 · chamadas n/120`
      crescem a cada chamada; a entrada fica desabilitada durante a execução.
- [ ] `Ctrl+O` abre o overlay com o último resultado de ferramenta (completo,
      sem cap); `Esc` fecha o overlay.
- [ ] `Esc` durante a execução muda o estado para `interrompendo? Esc de novo
      confirma · outra tecla continua`; sem segunda pressão, volta a
      `executando` (padrão: continuar).
- [ ] Com `Esc Esc`, o estado final **nunca é "sucesso"**: a resposta é
      "Interrompido pelo usuário…" e o transcript mostra
      `— interrompido pelo usuário —`.
- [ ] `Ctrl+L` alterna rolagem livre; `Ctrl+Q` sai sem perder a sessão.
- [ ] Com `NO_COLOR=1 formiga agent …`, tudo permanece legível.
- [ ] O relatório do `deep_search` fica em
      `sessoes/<sessão>/research/<run>/report.md`.

## 3. Guardrails com modelo pequeno

Repetir uma instrução que induza loop (ex.: "liste `.` com ls cinco vezes"):

- [ ] Na 2ª chamada idêntica, o modelo recebe o nudge (mensagem "você já
      chamou … com os mesmos argumentos") e o transcript continua fluido.
- [ ] Na 4ª, o turno encerra com a resposta parcial e explicação de orçamento.

Esgotar orçamento de web (configurar `agent_max_web_searches = 1` no
`formiga.toml`, seção `[agent]`, e pedir duas buscas):

- [ ] A 2ª `web_search` não executa; o modelo recebe `ERRO: orçamento de
      web_search esgotado (1 por mensagem)` e responde com o que tem.

## 4. Anti-regressão rápida

```bash
uv run pytest          # 300+ testes offline, sem rede nem modelo
uv run ruff check src/ tests/
```

Se algum item falhar, registrar o caso em `sessoes/<sessão>/` (artefatos
já capturam o estado) e reproducir offline com um fake antes de corrigir.
