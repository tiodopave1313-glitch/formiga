# Smoke manual — Formiga Agent (MVP)

Procedimento final de validação contra um modelo real (PRD §12 e critérios de
aceite §13). Sem automação: é uma lista de verificação humana. Os testes
offline (`pytest`) já cobrem os mesmos caminhos com fakes; este smoke existe
para confirmar o comportamento com um modelo pequeno de verdade.

## Pré-requisitos

- Uma das duas: chave do NIM em `NVIDIA_API_KEY` **ou** Ollama/llama-server local
  com um modelo 8B (ex.: `Nemotron-3.5-Bolt-E4B` ou `Gemma-4-E4B`).
- SearXNG local para `web_search`/`deep_search` (ex.: `http://localhost:8080`).
- Terminal com pelo menos 80×24 (funciona menor, mas este é o alvo).

## 1. Headless (`--print`) fim a fim — backend remoto (NIM)

```bash
formiga agent --print \
  "Leia formiga.toml, diga qual backend está configurado e pesquise 'Nemotron NVIDIA NIM' na web." \
  --llm-backend openai \
  --llm-base-url https://integrate.api.nvidia.com/v1 \
  --model nvidia/nemotron-3.5-bolt-e4b \
  --searxng-url http://localhost:8080
```

Verificar:

- [ ] A resposta final cita o backend do arquivo e fundamentos da busca.
- [ ] A sessão existe em `sessoes/<timestamp>/` com `messages.json`,
      `events.jsonl` e `transcript.md` (turnos, `tool_call` com `ok`,
      durações; o transcript contém toda a conversa em Markdown).
- [ ] Nenhuma credencial aparece em `messages.json`, `events.jsonl`,
      `transcript.md` ou stdout.
- [ ] Nenhuma sequência de escape ANSI no stdout (rode com `NO_COLOR=1`
      e confira a saída limpa).

## 2. CLI interativa (padrão) com tarefa mista (`bash` + `deep_search`)

```bash
formiga agent \
  "Crie o arquivo prova.txt com 'conteudo-smoke' via bash, confirme com read e, se sobrar orçamento, faça um deep_search sobre 'trafilatura extração de conteúdo'." \
  --llm-backend openai \
  --llm-base-url https://integrate.api.nvidia.com/v1 \
  --model nvidia/nemotron-3.5-bolt-e4b \
  --searxng-url http://localhost:8080
```

Na CLI interativa, verificar (nesta ordem):

- [ ] O prompt `pergunta>` aparece; Enter inicia.
- [ ] O texto do agente aparece **enquanto é gerado** (stream token a token).
- [ ] Cada ferramenta aparece em linha **antes** de executar:
      `⚙ bash — command=echo …`, `⚙ read — path=prova.txt`, seguidas de
      duração (`(1.2 s)`); o progresso do `deep_search` aparece como linhas
      `· planejado · buscas · síntese`.
- [ ] A linha de orçamento reflete o loop real: `turnos n/24 · llm n/120 ·`
      `ctx Xk/Yk · ext N ferramentas` aparece entre turnos.
- [ ] `Ctrl+C` **durante a resposta** interrompe só o turno atual (parcial salva,
      `— interrompido pelo usuário —` no transcript, volta ao prompt).
- [ ] `Ctrl+C` **no prompt** sai do programa limpo.
- [ ] `Ctrl+D` (EOF) no prompt sai apontando o `transcript.md`.
- [ ] Com `NO_COLOR=1 formiga agent …`, tudo permanece legível.
- [ ] O relatório do `deep_search` fica em `sessoes/<timestamp>/`.
- [ ] Comando `/budget` imprime turnos/llm/ctx/ext e consumo por ferramenta.
- [ ] Comando `/new sim` inicia nova sessão em disco preservando a anterior.

## 3. Extensão externa (`.formiga/extensions/` + `formiga trust`)

```bash
mkdir -p .formiga/extensions
# copie para .formiga/extensions/minha_ext.py uma extensão com setup(pi) que
# registre uma tool e/ou um comando /xxx
formiga trust .
formiga agent "qualquer pergunta"
```

Verificar:

- [ ] A extensão carrega e aparece em `/ext`.
- [ ] Sua tool aparece no prompt do sistema e pode ser chamada.
- [ ] Seu comando `/xxx` responde na CLI.
- [ ] Um projeto fora de `trusted_projects` **não** carrega a extensão;
      `formiga trust <caminho>` resolve e a sessão avisa.

## 4. Perfis de modelo

```bash
formiga agent "pergunta curta" --profile gemma4-e4b
formiga agent "pergunta curta" --profile nemotron-3.5-bolt-e4b
```

Verificar:

- [ ] A barra de status da TUI exibe o perfil selecionado (`perfil X`).
- [ ] A auto-seleção por nome funciona (`model_hint = "gemma4"` → `gemma4-e4b`).
- [ ] O perfil `gemma4-e4b` usa `thinking = false`; o `nemotron-3.5-bolt-e4b`
      usa `thinking = true`.

## 5. Local: Gemma 4 E4B via llama-server (documentado; executar manualmente)

Receita (llama-server deve estar compilado em `~/llama.cpp/build/bin/`):

```bash
# 1. Baixe o GGUF (ex.: Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf)
# 2. Suba o servidor:
~/llama.cpp/build/bin/llama-server -m Gemma-4-E4B-*.gguf \
  --alias gemma4 -c 32768 --jinja --reasoning off

# 3. Rode o agent contra o backend local:
formiga agent "resuma o arquivo formiga.toml" \
  --llm-backend llamacpp \
  --llamacpp-url http://127.0.0.1:8080 \
  --model gemma4
```

Verificar:

- [ ] O perfil `gemma4-e4b` é auto-selecionado pelo nome `gemma4`.
- [ ] A resposta é gerada localmente (sem chave de API remota).
- [ ] A barra de status exibe `ctx` compatível com a janela de 32K do perfil.

## 6. TUI (`--tui`) — conferência visual manual

```bash
NO_COLOR=1 formiga agent --tui "qualquer pergunta"
```

Verificar (80×24):

- [ ] A barra de status exibe `turnos X/Y · chamadas X/Y · ctx Xk/Yk · ext N
      ferramentas · perfil X` e nunca excede 80 colunas.
- [ ] Eventos de extensão (`notification`, `extension_status`,
      `tool_progress`) aparecem em linha.
- [ ] `Esc` pede confirmação para interromper; segunda `Esc` confirma.
- [ ] `Ctrl+C` durante a resposta interrompe só o turno atual.
- [ ] O estado final nunca é "sucesso" após interrupção.
- [ ] Comandos `/tools`, `/ext`, `/budget`, `/new` funcionam.

## 7. Gateway local (`formiga gateway`)

O gateway é um daemon WebSocket local que possui o `AgentLoop` e as sessões,
sobrevivendo ao terminal. A CLI/TUI se anexam a ele.

```bash
# 1. Suba o gateway (background, persiste)
formiga gateway start

# 2. Verifique o status
formiga gateway status

# 3. Rode o agent (anexa ao gateway automaticamente)
formiga agent "qual é a capital do Brasil?"

# 4. Feche o terminal (Ctrl+C ou feche janela) — o turno continua no gateway.
#    Reabra e reanexe:
formiga agent "e qual é a população dela?"  # retoma a mesma sessão

# 5. Pare o gateway
formiga gateway stop
```

Verificar:

- [ ] `formiga gateway start` inicia o daemon; `status` mostra pid/porta.
- [ ] `formiga agent` anexa ao gateway e responde (streaming, ferramentas).
- [ ] Fechar o terminal no meio do turno **não cancela**; reanexar mostra a resposta.
- [ ] `--print` e `--local` rodam **sem** precisar do gateway.
- [ ] Nenhuma credencial aparece em logs ou sessões.

# 8. Tarefas agendadas (cron)

O cron agenda tarefas do agente, executadas pelo gateway em sessões isoladas.

```bash
# 1. Adicione um job
formiga cron add "diga olá do cron" --schedule "every 1m"

# 2. Liste
formiga cron list

# 3. Execute agora (in-process, offline)
formiga cron run <id>

# 4. Desabilite/remova
formiga cron disable <id>
formiga cron rm <id>
```

Verificar:

- [ ] `formiga cron add` cria o job e mostra o próximo `next_run`.
- [ ] `formiga cron list` exibe todos os jobs com status.
- [ ] `formiga cron run <id>` executa o job in-process (sem gateway).
- [ ] `formiga cron disable|enable|rm <id>` altera o estado do job.
- [ ] `jobs.json` persiste em `~/.formiga/`.

# 9. Memória estilo Hermes

A memória tem recall (busca FTS5 em sessões passadas), memória curada
(`MEMORY.md` com nudge + aprovação) e perfil (`USER.md` injetado no prompt).

```bash
# 1. Rode uma sessão que aprenda algo
formiga agent "anote que o usuário gosta de chá"

# 2. Veja sugestões pendentes e aprova
formiga memory pending
formiga memory save

# 3. Busque em sessões passadas (via recall dentro do agent)
formiga agent "o que o usuário gosta de beber?"

# 4. Inspecione
cat ~/.formiga/memory/MEMORY.md
```

Verificar:

- [ ] `formiga memory pending` lista sugestões stageadas pelo nudge.
- [ ] `formiga memory save` grava o fato em `~/.formiga/memory/MEMORY.md`.
- [ ] `formiga memory show` exibe perfil e memória curada.
- [ ] O modelo usa `recall` para achar fatos de sessão antiga.
- [ ] `USER.md` aparece como seção no prompt (ver `transcript.md`).
- [ ] Nenhuma credencial aparece em `MEMORY.md`.

## 10. Skills declarativas

Skills ficam fora do prompt até serem chamadas por `/nome-da-skill`; escritas
propostas pelo modelo exigem aprovação humana.

```bash
# 1. Instale uma skill global
mkdir -p ~/.formiga/skills/checklist
cat > ~/.formiga/skills/checklist/SKILL.md <<'EOF'
---
name: checklist
description: Checklist de entrega
when_to_use: Antes de fechar uma tarefa
---
- Rode a suíte de testes.
- Confira o diff e as credenciais.
EOF

# 2. Confira a listagem
formiga skills list

# 3. Use no agent
formiga agent
# pergunta> /skills
# pergunta> /checklist
# pergunta> aplique o checklist ao último commit

# 4. Peça ao modelo para propor uma skill e aprove
# pergunta> crie uma skill chamada "revisar" com o procedimento que você usou
# pergunta> /skills pending
# pergunta> /skills approve <id>
```

Verificar:

- [ ] `formiga skills list` mostra `/checklist` com descrição e origem.
- [ ] `/skills` lista a skill; `/checklist` agenda a expansão.
- [ ] A próxima mensagem contém o corpo da skill e o evento `skill_expanded`
      aparece em `events.jsonl`.
- [ ] `skill_manage` sem aprovação **não** cria `SKILL.md` (só `pending.json`).
- [ ] `/skills approve <id>` grava e a skill já expande na mesma sessão.
- [ ] `/skills reject <id>` descarta a proposta.
- [ ] Skill em `.formiga/skills/` de projeto fora da allowlist não carrega
      (aviso em `/skills`).
- [ ] Após tarefa bem-sucedida com ferramentas, o nudge sugere `skill_manage`.

## Aceite (marcar ao terminar)

- [ ] `formiga agent --print` responde com o modelo real (NIM ou local).
- [ ] Linha de orçamento imprime `ctx` e `ext`; `/budget` coerente com o loop.
- [ ] `pi.emit` de extensão chega à CLI e à TUI.
- [ ] Extensão externa carrega, aparece em `/ext`, tool e comando funcionam.
- [ ] `/new sim` cria sessão preservando a anterior.
- [ ] `NO_COLOR=1` sem sequências ANSI; 80×24 respeitado.
- [ ] `Ctrl+C`/`Esc` cooperativo; estado final correto.
- [ ] Gateway: `start`/`status`/`stop` funcionam; reanexo mostra resposta.
- [ ] Cron: `add`/`list`/`run`/`disable`/`rm` funcionam; `jobs.json` persiste.
- [ ] Memory: `memory pending`/`save`/`show` funcionam; `recall` acha fato de
      sessão antiga; `MEMORY.md`/`USER.md` em `~/.formiga/memory/`.
- [ ] Skills: `skills list` e `/skills` listam; `/nome` expande; `skill_manage`
      só grava após `/skills approve`; projeto sem trust não carrega skill.
- [ ] `--print` e `--local` rodam sem gateway.
- [ ] Nenhuma credencial em `messages.json`, `events.jsonl`, `transcript.md`
      nem stdout.

Esse teste demonstra integração, **não comprova qualidade factual**.
