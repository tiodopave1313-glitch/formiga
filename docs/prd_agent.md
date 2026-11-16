# PRD — Formiga Agent

**Arquivo:** `prd_agent.md`
**Status:** proposta para implementação do MVP
**Interface:** TUI (terminal)
**Linguagem:** Python 3.11+, Linux
**Desenvolvimento:** OpenCode
**Modelo de teste:** [Nemotron 3.5 Bolt E4B](https://build.nvidia.com/nvidia/nemotron-3.5-bolt-e4b) via endpoint OpenAI-compatível (NIM); Ollama e llama.cpp também suportados

---

## 1. Visão

O **Formiga Agent** é um harness de agente genérico minimalista, inspirado no
pi: um loop agêntico enxuto — system prompt, ferramentas, array de mensagens,
streaming — com as compensações obrigatórias para LLMs pequenos documentadas
em `docs/RELATORIO_AGENTE_8B.md`.

Ele **não é um agente de código**. Ferramentas de arquivo e shell existem para
trabalho geral; a diferencial é a pesquisa profunda do Formiga disponível como
uma ferramenta:

```text
formiga agent
> O que muda na segurança ao migrar de SSH por senha para chaves?

  ⠿ deep_search — pesquisa iniciada (até 12 buscas, 18 páginas)
  ● deep_search — relatório pronto: ./sessoes/…/report.md
  O agente redige a resposta a partir do relatório…
```

> **O loop é minimalista. O harness compensa o modelo pequeno. A pesquisa
> profunda continua controlada pelo programa, não pelo modelo.**

Camadas de controle distintas:

- **Loop agêntico** — o modelo escolhe a próxima ferramenta (liberdade pi);
- **Guardrails** — o harness limita orçamento, resultados e repetições;
- **deep_search** — pipeline determinístico intacto dentro da ferramenta.

---

## 2. Problema

Agentes minimalistas de referência (pi e similares) assumem um modelo forte:
tool call sempre válido, contexto amplo, autocorreção confiável. Um modelo de
4B efetivos falha de outras formas:

- repete a mesma chamada de ferramenta sem progresso;
- enche o contexto com resultados brutos não truncados;
- emite tool calls malformados (JSON quebrado, parâmetros errados);
- perde o objetivo original em sessões longas;
- executa ações destrutivas quando tem `bash`.

O prd.md já provou a tese inversa: com o harness no comando, o mesmo modelo
produz pesquisa auditável. O desafio deste PRD é unir os dois mundos:
**liberdade de loop + compensação de harness.**

---

## 3. Objetivos

### 3.1 Objetivos do MVP

1. Loop agêntico: `messages[]` + tool calls + streaming, num núcleo pequeno
   (alvo: < 500 linhas em `loop.py` + `tools/`).
2. Oito ferramentas: `ls`, `read`, `write`, `edit`, `bash`, `web_search`,
   `web_fetch`, `deep_search`.
3. TUI minimalista (Textual): resposta em streaming no centro, eventos de
   ferramenta em linha, entrada única, `Esc` interrompe.
4. Guardrails de modelo pequeno (seção 7): orçamento, cap de resultado,
   parser tolerante, anti-loop, patch-first, bash delimitado.
5. deep_search como ferramenta: o motor atual encapsulado, sem alterá-lo.
6. Sessão persistida: `messages[]` + eventos em diretório de sessão.
7. Testável offline: loop e TUI contra fakes, sem rede nem modelo real.

### 3.2 Não objetivos

Ficam fora do MVP:

- ferramentas de código (grep/AST, testes automáticos, debug subagent);
- sub-agentes, paralelismo, MCP, plugins;
- retomada de sessão (persistida apenas para inspeção, como no prd.md);
- eval gate formal, RAG, rerank, embeddings;
- model escalation / fallback para modelo maior (o failover de backend
  opt-in já existente em `fallback.py` continua disponível);
- múltiplas sessões simultâneas na mesma TUI;
- memória entre sessões;
- interface web, desktop, voz.

---

## 4. Arquitetura

```text
src/formiga/
├── agent/                    # NOVO
│   ├── loop.py               # loop agêntico: turnos, tool calls, streaming
│   ├── tools/
│   │   ├── base.py           # Tool protocol: nome, schema, execute()
│   │   ├── files.py          # ls, read, write, edit (patch-first)
│   │   ├── shell.py          # bash delimitado
│   │   ├── web.py            # web_search + web_fetch (SearXNG, fetcher)
│   │   └── deepsearch.py     # ponte para o motor de pesquisa
│   ├── parser.py             # parser tolerante de tool calls
│   ├── guardrails.py         # anti-loop, result cap, budget do agente
│   ├── prompts.py            # system prompt (dados delimitados, PT-BR)
│   ├── session.py            # diretório de sessão (messages.json, events.jsonl)
│   └── tui/
│       ├── app.py            # Textual: stream, eventos, entrada
│       └── controller.py     # ponte loop ↔ TUI (thread de execução)
├── cli.py                    # + formiga agent [PERGUNTA] [--session-dir DIR]
└── (motor de pesquisa atual: orchestrator, budget, fetcher, evidence, …)
```

Regras de separação (herdadas do prd_tui.md):

- A TUI não decide fluxo do agente nem chama LLM/ferramentas diretamente.
- O loop não altera o motor de pesquisa; consome-o via interface estreita.
- CLI e TUI usam os mesmos schemas, limites e persistência.

---

## 5. Loop agêntico

```text
usário envia mensagem
        ↓
harness monta contexto: system + mensagens + schemas das 8 tools
        ↓
chamada ao LLM (streaming) ── texto ───────────────→ stream na TUI
        │
        └─ tool call → parser tolerante → guardrail de orçamento
                        ↓
                  execução da tool (cap no resultado)
                        ↓
                  resultado volta como mensagem `tool`
                        ↓
                  anti-loop verifica repetição → próximo turno
        ↓
modelo emite resposta final sem tool call → turno encerrado
```

Regras:

- Um turno = uma chamada ao LLM + até uma tool call por iteração
  (sem paralelismo de ferramentas no MVP).
- Resposta final termina o turno do usuário; nova mensagem inicia novo turno
  na mesma sessão.
- `MAX_TURNS` por mensagem do usuário (default: 24); orçamento global da
  sessão em chamadas ao LLM (default: 120) e tempo (default: 1800 s).
- Cancelamento cooperativo: `Esc` sinaliza o loop; a ferramenta em execução
  termina dentro do próprio timeout antes do encerramento.
- Erros de ferramenta voltam ao modelo como resultado com prefixo
  `ERRO:` — o modelo decide tentar de novo ou responder.

---

## 6. Ferramentas

Contratos curtos; schemas em JSON Schema no system prompt (8 tools ≈ 1600
tokens — cabe em 64K, sem roteamento em 2 estágios no MVP).

| Tool | Assinatura | Notas |
|---|---|---|
| `ls` | `(path?)` | Lista do diretório de trabalho; caminhos relativos apenas |
| `read` | `(path, offset?, limit?)` | Texto, linhas numeradas; cap 4K chars no retorno |
| `write` | `(path, content)` | Só cria/sobrescreve com confirmação se o arquivo já existir |
| `edit` | `(path, old_string, new_string)` | **Patch-first**: falha objetiva se `old_string` não for único |
| `bash` | `(command, timeout?)` | Working dir fixo; timeout default 60 s; cap de saída |
| `web_search` | `(query, max_results?=6)` | SearXNG; `título — url` + snippet; dedupe de `search.py` |
| `web_fetch` | `(url)` | Texto principal extraído; garantias do fetcher intocadas |
| `deep_search` | `(question)` | Motor atual; retorna resumo + caminho do `report.md` |

### 6.1 deep_search

- Encapsula `orchestrator` com a config atual (backend, SearXNG, orçamento
  de pesquisa próprio — defaults do `research`).
- É uma ação **pesada**: `MAX_DEEP_SEARCHES` por mensagem do usuário
  (default: 2). O orçamento de buscas/páginas/chamadas é o da pesquisa,
  não da sessão.
- Retorno para o modelo (cap 4K): status (suficiente/parcial/bloqueada),
  resumo do relatório, lista de fontes `[S#] título — url` e caminho do
  `report.md`. O relatório completo fica no disco para o `read`.
- Executa na thread do loop; a TUI recebe eventos do motor (plano, buscas,
  evidências) para exibir progresso em linha.

### 6.2 web_search e web_fetch

Ferramentas de web **leves**, de primeira intenção — o oposto do
deep_search, que é uma execução inteira de pesquisa:

- `web_search`: consulta o SearXNG configurado (o mesmo do motor de
  pesquisa); retorno capado a 4K com `título — url` + snippet por
  resultado; deduplicação e normalização de URL reutilizadas de
  `search.py`.
- `web_fetch`: baixa uma URL via `fetcher.py` (SSRF, caps de 2 MB/20 s,
  sem proxies herdados — intocados) e extrai o texto principal com
  `extract.py` (Trafilatura); retorno capado a 4K. Bloqueia
  `localhost` e redes privadas por construção do fetcher.
- Orçamentos próprios por mensagem do usuário: `MAX_WEB_SEARCHES`
  (default: 6) e `MAX_WEB_FETCHES` (default: 8). Exceder retorna `ERRO:`
  orçamental ao modelo, não encerra a sessão.
- O par é a via rápida para checar 1–2 fatos ou ler uma URL específica;
  snippets bastam em `web_search` — a leitura profunda é papel do
  `deep_search`.

### 6.3 Posicionamento no system prompt

O prompt orienta quando usar cada ferramenta de web (um 4B se confunde
com sobreposição de ferramentas sem isso):

| Situação | Ferramenta |
|---|---|
| Checagem rápida de 1–2 fatos; snippets bastam | `web_search` (+ `web_fetch` em 1–2 URLs promissoras) |
| URL específica informada pelo usuário | `web_fetch` direto |
| Resposta fundamentada, com fontes e relatório | `deep_search` |

Regra no prompt: se a pergunta pede uma resposta com referências ou
evidências, use `deep_search`; se pede um fato pontual, `web_search`
primeiro e `deep_search` só quando os snippets não bastarem.

---

## 7. Guardrails de modelo pequeno

| Guardrail | Parâmetro default | Origem |
|---|---|---|
| Orçamento do agente (turnos, chamadas, tempo) | 24 / 120 / 1800 s | `budget.py` (padrão prd.md) |
| Cap de resultado de tool | 4 000 chars (bash: 8 000, truncado na cauda) | Relatório §4.1 |
| Cap de tokens de geração por turno | 4096 (thinking liga o teto dobrado, como em `llm.py`) | `llm.py` |
| Parser tolerante | JSON; auto-repair de nomes/tipos de parâmetros; 1 correção com erro objetivo; falha vira `ERRO:` no contexto | Relatório §4.3 + `llm.py` |
| Anti-loop ladder | 2 chamadas idênticas (ferramenta+args) → nudge; 4 → turno encerrado com instrução de responder; repetição de resposta vazia conta igual | Relatório §4.6 |
| Patch-first | `edit` nunca reproduz arquivo inteiro; falha de unicidade volta como erro objetivo | Relatório §4.4 |
| bash delimitado | working dir fixo; recusa lista de padrões irreversíveis (`rm -rf /`, `mkfs`, `dd if=`, `shutdown`, uninstall de pacotes, mutação fora do workdir); `AGENT_UNSAFE=1` desliga a lista | Relatório §6 (anéis 1, 3, 4 — versão mínima) |
| Perda de objetivo | system prompt re-injetado a cada chamada; após turno anti-loop, última mensagem do usuário re-anexada | Relatório §2 |

O system prompt reafirma a disciplina do Formiga: uma tarefa por chamada,
abstenção é válida, não invente — cite o que a ferramenta retornou.

---

## 8. TUI

Textual, seguindo os princípios do `prd_tui.md` (uma tela, pouco ruído,
estado explícito, sem falsa precisão), adaptados ao agente:

```text
 formiga agent                     nemotron-3.5-bolt-e4b
──────────────────────────────────────────────────────────────
 Você
 Como faço para reduzir o consumo de RAM do meu servidor?

 Agent
 Vou primeiro inspecionar os serviços ativos.

  ⚙ bash — systemctl list-units --type=service          1.2 s
  ⚙ read — /etc/systemd/journald.conf                   0.1 s
  Vou verificar a configuração do journald…

──────────────────────────────────────────────────────────────
 turnos 3/24 · chamadas 5/120 · ⠿ executando
──────────────────────────────────────────────────────────────
 ❯ _
```

Requisitos:

- **Stream do texto do agente** no centro, token a token.
- **Eventos de ferramenta em linha**: símbolo, nome, argumento curto e
  duração; detalhes (saída completa, erros) sob `Ctrl+O` no evento.
- **Barra de status** com orçamento consumido (única barra percentual
  permitida — é valor conhecido) e estado:
  `ocioso · executando · interrompendo · erro`.
- Entrada única `❯`; histórico ↑/↓; desabilitada durante execução.
- `Esc`: confirmação de interrupção (padrão: continuar; cooperativo —
  a TUI só mostra "interrompida" após o loop confirmar).
- `Ctrl+L`: rolagem livre do buffer; `Ctrl+O`: último resultado de tool.
- `Ctrl+Q`: sai (sessão permanece no disco).
- Funciona sem cores (`NO_COLOR`); alvo 80×24; sem animações além de um
  spinner.
- Avisos: envio de conteúdo ao provedor de modelo remoto; comandos `bash`
  visíveis antes da execução no stream de eventos.

Fora do escopo da TUI: painéis permanentes, dashboards, múltiplas sessões,
visualização do relatório dentro da TUI (o `read` do agente e o `less`
cobrem).

---

## 9. Configuração

Reuso integral da precedência atual: **CLI > env > TOML > defaults**, com
`.env` (0600) preenchendo variáveis ausentes.

```bash
formiga agent                          # TUI, sessão nova
formiga agent "pergunta"               # TUI com pergunta pré-preenchida
formiga agent --print "pergunta"       # modo headless: resposta única no stdout
formiga agent --session-dir DIR       # retomar? não — apenas escolher diretório
```

```toml
# formiga.toml — seções reutilizadas e novas
[llm]                    # existente; default de teste: openai + NIM
backend = "openai"
model = "nvidia/nemotron-3.5-bolt-e4b"
base_url = "https://integrate.api.nvidia.com/v1"
api_key_env = "NVIDIA_API_KEY"
thinking = true

[agent]                  # NOVO
max_turns = 24
max_llm_calls = 120
timeout_seconds = 1800
max_deep_searches = 2
max_web_searches = 6
max_web_fetches = 8
tool_result_chars = 4000
workdir = "."            # raiz de ls/read/write/bash
```

Amostragem do modelo de teste: temperature 1.0, top_p 0.95 (ficha do
Nemotron 3.5 Bolt), já o default do backend.

---

## 10. Sessão e persistência

```text
sessoes/2026-11-16_140532_a1b2/
├── messages.json    # messages[] serializável (Argus: stateless reducer)
├── events.jsonl     # turnos, tool calls, erros, orçamento
└── research/*/      # saídas de deep_search (report.md, state.json, pages/)
```

- Cada tool call e cada turno gera evento; credenciais nunca aparecem.
- Sessão interrompida é **inspecionável, não retomável** (igual ao MVP do
  prd.md). Retomada fica para pós-MVP.
- `messages.json` é salvo atomicamente a cada turno.

---

## 11. Segurança e privacidade

- Fetch de páginas: garantias do fetcher atual (SSRF, caps, sem proxies
  herdados) — intocadas, agora acionadas via `deep_search` e `web_fetch`.
- `web_fetch` só aceita `http(s)` público; `localhost` e redes privadas
  são bloqueados a cada redirecionamento, como no `research`.
- `bash`: working dir fixo + lista de recusa (seção 7); a TUI mostra o
  comando antes de executá-lo; nada de prompts do sistema vindos de
  resultados de ferramenta (fontes são dados não confiáveis).
- Chave de API apenas no header; nunca em logs, eventos, repr ou TUI.
- Conteúdo de ferramentas e mensagens saem para o endpoint de modelo
  configurado — aviso explícito na TUI (herança do README).

---

## 12. Testes

Sem rede e sem modelo real, no padrão existente (`tests/fakes.py`):

- **Loop**: fake de LLM scriptado (sucessão de tool calls/texto) — cobre
  turno normal, erro de parser, anti-loop (nudge e encerramento),
  orçamento esgotado, cancelamento, cap de resultado.
- **Ferramentas**: casos reais de disco temporário — `edit` com
  `old_string` ambíguo, `read` truncado, `bash` com recusa e timeout,
  `write` em arquivo existente.
- **deep_search**: fake do motor (mesma estratégia de `tests/fakes.py`),
  verificando orçamento próprio e retorno capado.
- **web_search / web_fetch**: SearXNG e fetcher fakes — retorno capado,
  dedupe, orçamentos (`MAX_WEB_SEARCHES` / `MAX_WEB_FETCHES`) e bloqueio
  de loopback/redes privadas.
- **TUI**: Textual pilot — stream visível, eventos em linha, Esc com
  confirmação, estados da barra de status, NO_COLOR, 80×24.
- **Smoke manual documentado**: NIM (Nemotron E4B) + uma tarefa que exija
  `bash` + `deep_search`.

---

## 13. Fases de implementação

1. **Fase 1 — Loop + ferramentas de arquivo** (`loop.py`, `files.py`,
   `parser.py`, `guardrails.py`, sessão): headless `--print` funciona fim a
   fim contra o NIM.
2. **Fase 2 — bash delimitado + web_search + web_fetch + deep_search como
   tools**: ponte com o orquestrador e com SearXNG/fetcher, orçamentos
   próprios, eventos do motor reexpostos.
3. **Fase 3 — TUI**: stream, eventos em linha, barra de status, Esc
   cooperativo, avisos.
4. **Fase 4 — endurecimento**: anti-loop completo, caps, NO_COLOR,
   terminais pequenos, smoke test final.

### Critérios de aceite do MVP

- [ ] `formiga agent` abre a TUI; pergunta por argumento aparece pré-preenchida.
- [ ] Uma tarefa mista (ler arquivo, rodar comando, pesquisar) conclui com
      resposta fundamentada em eventos reais da execução.
- [ ] Orçamento exibido corresponde ao estado do loop; esgotamento encerra
      com resposta parcial e explicação.
- [ ] Duas chamadas idênticas de tool recebem nudge; quatro encerram o turno.
- [ ] `edit` nunca reescreve arquivo inteiro; `bash` recusa padrões da lista.
- [ ] `Esc` interrompe de forma cooperativa; estado final nunca é "sucesso".
- [ ] `deep_search` respeita `MAX_DEEP_SEARCHES` e o relatório fica no disco.
- [ ] Uma sessão que usa `web_search` → `web_fetch` → resposta direta
      funciona sem acionar `deep_search`; os orçamentos de web são
      respeitados e o esgotamento retorna `ERRO:` orçamental.
- [ ] Testes offline cobrem os caminhos acima; nenhum teste depende de rede.
- [ ] Credenciais não aparecem em nenhum artefato.

---

## 14. Limitações conhecidas

- Um 4B escolhendo ferramentas comete erros de planejamento; o MVP aceita
  isso e limita o dano (orçamento, anti-loop), não promete autocomposição.
- deep_search dentro do agente herda as limitações do prd.md (sem PDF,
  sem rerank, abstenção pode ocorrer).
- `web_search` entrega títulos e snippets, não leitura completa: a
  fundamentação com fontes é papel do `deep_search`; `web_fetch` cobre
  apenas páginas públicas acessíveis (sem paywall, PDF ou imagem).
- Sem retomada de sessão; sem memória entre sessões.
- A lista de recusa do `bash` é negação por padrão conhecido, não sandbox:
  não substitui contenção real (containers ficam para pós-MVP).
- O modelo de teste é remoto (NIM) por default: latência e privacidade
  dependem do provedor; local via Ollama/llama.cpp é igualmente suportado.

---

## 15. Referências

- `docs/prd.md` — motor de pesquisa (fonte da verdade do deep_search).
- `docs/prd_tui.md` — princípios de interface reutilizados (seção 8).
- `docs/RELATORIO_AGENTE_8B.md` — compensações de modelo pequeno (seções 2,
  3.1, 4 e 6; guardrails da seção 7 mapeiam §4.1, §4.3, §4.4, §4.6).
- `docs/relatorio_geral.md` — disciplina do loop de pesquisa.
- pi (harness minimalista de referência) — inspiração do loop e da TUI.
