# Relatório Completo: Melhores Práticas para Harness de Agentes com LLMs de 8B Parâmetros

## Sumário Executivo

Este relatório analisa **6 repositórios open-source** que implementam harnesses de agentes otimizados para LLMs pequenos (2B–35B, com foco em 8B), extraindo padrões arquiteturais, mecanismos de compensação de limitações e estratégias de engenharia comprovadas em produção. A conclusão central é unânime: **as falhas observadas em modelos pequenos são defeitos do harness, não do modelo** — e harnesses bem projetados permitem que modelos de 2B–8B completem tarefas reais em hardware de consumo (iGPU, 16–32 GB RAM).

---

## 1. Análise dos 6 Repositórios

### 1.1 Mingbird (mingbird/mingbird-agent) ⭐ **Referência Principal**
- **Foco**: Local-first, 2–9B models em integrated graphics
- **Arquitetura**: Python + GUI desktop (Tkinter) + WebUI experimental
- **Benchmark**: LRAB-288 (288 células públicas), τ²-bench (3 domínios)
- **Resultado-chave**: **Mesmo modelo 2B: 0.017 → 0.821** (harness foi o problema)
- **Paper**: arXiv:2610.02001

### 1.2 SmallCode (Doorman11991/smallcode)
- **Foco**: Terminal-native coding agent para 8B–35B local
- **Arquitetura**: Node.js/TypeScript + MarrowScript (DSL compilada) + TUI fullscreen
- **Inovação**: Camada de cognição declarativa (MarrowScript) → runtime TypeScript com cache, retry, validação, traces, budget enforcement
- **Recursos**: BoneScript (1 arquivo .bone → projeto completo), Model Escalation (fallback cloud opcional)

### 1.3 KWCode (val1813/kwcode) 🇨🇳
- **Foco**: "LLM só faz classificação e geração, pipeline determinístico decide e verifica"
- **Arquitetura**: Python + 5 meta-especialistas fixos + 15 SKILL.md (conhecimento de domínio)
- **Pipeline**: Gate → Locator (BM25+AST) → Generator → Verifier → Debugger → Reviewer
- **Inovações**: Debug Subagent (sys.settrace), DAG multi-tarefa, Flywheel (auto-otimização de prompts), Reflexão persistida

### 1.4 PicoClaw (sipeed/picoclaw)
- **Foco**: Ultra-leve (<10MB RAM, boot <1s, roda em hardware $10 RISC-V/ARM/MIPS)
- **Arquitetura**: **Go nativo** (95% gerado por agente), single binary multi-arch
- **Recursos**: 30+ providers, MCP nativo, vision pipeline, model routing, 19+ canais de chat
- **Diferencial**: Não é fork — reescrito do zero em Go via "self-bootstrapping"

### 1.5 Agentic Research Engine (TheAiSingularity/agentic-research-engine-oss)
- **Foco**: Research agent local-first ($0/query com Gemma 3 4B + Ollama)
- **Arquitetura**: Python + LangGraph (8 nós) + interfaces CLI/TUI/Web/MCP
- **Pipeline**: classify → plan → search → retrieve → fetch → compress → synthesize → verify
- **Técnicas SOTA**: HyDE, CoVe (Chain-of-Verification), FLARE, ThinkPRM, LongLLMLingua-lite, cross-encoder rerank
- **Domínios**: 6 presets YAML (general, medical, papers, financial, stock_trading, personal_docs)

### 1.6 Argus (subratamondal1/argus)
- **Foco**: Framework-free multi-agent deep research (sem LangChain/LangGraph)
- **Arquitetura**: Python 3.12 + LiteLLM + PostgreSQL/pgvector + FastAPI + Next.js
- **Loop**: Planner → Searcher agents paralelos (isolados) → Synthesizer → Reflect/Replan
- **Eval Gate**: RAGAS vocabulário in-repo + Cohen's κ calibrated LLM judge (κ ≥ 0.80 obrigatório)
- **Escala**: ARQ-on-Redis + KEDA autoscale searcher pods from zero

---

## 2. Problemas Canônicos de Modelos 8B e Soluções de Harness

| Problema | Causa Raiz | Solução de Harness (Consenso Multi-Repo) |
|----------|------------|------------------------------------------|
| **Context Window Overflow** | 8K–32K context; tool schemas + history + outputs enchem janela | **Budget Engine**: tool results capped (4K chars), mid-turn eviction, semantic compression (SmallCode, Mingbird, Agentic) |
| **Unreliable Tool Calling** | JSON malformado, parâmetros errados, formatos variados | **Forgiving Parser**: JSON/YAML/XML/Hermes/Liquid AI/text + auto-repair param names/types (SmallCode, KWCode, Mingbird) |
| **Self-Debug Failure** | Modelo não consegue corrigir próprio código | **Harness-run tests + exact failure feedback** (file:line + error text) (Mingbird, KWCode, SmallCode) |
| **Tool Demo Loops** | Modelo repete chamadas de ferramenta sem progresso | **Anti-loop ladder**: nudge → hard reset → graceful exit + signature-level detection (Mingbird, SmallCode quality monitor) |
| **Large File Emission** | Truncamento em arquivos grandes | **Chunked feedback**: "write skeleton, then append" + per-call output cap 8192 (Mingbird, SmallCode patch-first) |
| **Context Loss in Long Tasks** | Modelo "esquece" objetivo original | **Delivery self-check gate**: re-read task + verify work before claiming done (Mingbird, Agentic verify node) |
| **Destructive Impulses** | rm -rf, uninstalls, system mutations | **5-ring safety net**: sandbox, irreversible ops refused, behavior tiering, boundary confirmation, rollback everywhere (Mingbird, SmallCode snapshot) |
| **Hallucination on Missing Evidence** | Modelo confabula quando retrieval falha | **CoVe verification** + abstention training + rerank + local corpus (Agentic, Argus, KWCode) |
| **Reasoning Token Waste** | Thinking models gastam milhares de tokens em tarefas triviais | **Thinking budget caps** per call (Anthropic budget_tokens, OpenAI reasoning_effort, Qwen enable_thinking) (SmallCode, Agentic) |

---

## 3. Padrões Arquiteturais Comprovados

### 3.1 Pipeline Determinístico vs. ReAct Loop (Consenso: **Pipeline Determinístico**)

| Abordagem | Repositórios | Vantagem para 8B |
|-----------|--------------|------------------|
| **Pipeline Determinístico** (etapas fixas, LLM só em nós específicos) | **KWCode**, **Agentic Research Engine**, **Argus**, **Mingbird** (parcial) | Input/output format fixo por etapa; LLM faz uma coisa bem feita; testável, debuggável, checkpointável |
| **ReAct Loop** (LLM decide próxima ação livremente) | SmallCode (com guardrails), PicoClaw | Flexível mas propenso a loops; requer quality monitor + early-stop + cognitive gating |

**Recomendação**: Use **pipeline determinístico** (Gate → Locator → Generator → Verifier → Debugger → Reviewer estilo KWCode) ou **LangGraph com nós env-toggleable** (Agentic). O loop ReAct puro falha em 8B sem guardrails pesados.

### 3.2 Separação Estrita: Determinístico (Harness) vs. Probabilístico (LLM)

```
┌─────────────────────────────────────────────────────────────┐
│                    HARNESS (Determinístico)                 │
│  • Context budget management                                │
│  • Tool routing (2-stage: category → schema)                │
│  • Test execution + exact failure feedback                  │
│  • Patch application + syntax check + rollback              │
│  • Safety rings (bounds, confirmations, rollback)           │
│  • Anti-loop detection + early stop                         │
│  • Checkpoint/snapshot antes de cada turn                   │
│  • Eval gates (retrieval + generation independent)          │
└─────────────────────────────────────────────────────────────┘
                              │
                    LLM só faz:
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LLM (Probabilístico)                     │
│  • Classificação de tarefa (Gate)                           │
│  • Geração de patch/código (Generator)                      │
│  • Planejamento (Plan/Decompose)                            │
│  • Síntese de resposta (Synthesize)                         │
│  • Verificação CoVe (Verify)                                │
│  • Julgamento de qualidade (Judge)                          │
└─────────────────────────────────────────────────────────────┘
```

**Regra de ouro (KWCode RED-2)**: *LLM só faz classificação e geração, não decide fluxo do pipeline.*

### 3.3 Isolamento de Contexto por Especialista/Agente

| Repositório | Mecanismo |
|-------------|-----------|
| **KWCode** | Cada meta-especialista tem contexto independente; não herda histórico do anterior |
| **Argus** | Searcher agents com contexto isolado (parallel fan-out) |
| **Agentic** | Nós LangGraph com state passado explicitamente; compress entre nós |
| **SmallCode** | Working memory persistente (scratchpad) + evidence store separado do conversation history |
| **Mingbird** | Flat prefill por categoria; factory prefill pinned at 1250 tokens (CI fails on change) |

---

## 4. Mecanismos Específicos para 8B (Detalhados)

### 4.1 Context Budget Engine (SmallCode, Mingbird, Agentic)

```python
# SmallCode: bin/context/budget.ms (MarrowScript compilado)
# - Tool results capped at 4k chars
# - Mid-turn eviction: drop oldest results when context > budget
# - Semantic compression: summarize history instead of dropping
# - Per-cost-class enforcement: never overspend

# Mingbird: flat prefill loads by category
# - Factory prefill pinned at 1250 estimated tokens (CJK-calibrated)
# - CI fails on ANY change to prefill (growth OR shrinkage)
# - 2-stage tool routing halves schema context overhead

# Agentic: TOP_K_EVIDENCE auto (5 for small, 8 for large models)
# - ENABLE_RERANK opt-in (bge-reranker-v2-m3, 560MB)
# - LongLLMLingua-lite compression + per-chunk char cap (W6.2)
```

**Configuração recomendada para 8B (4K–8K context):**
- Tool result cap: **2K–4K chars**
- Max history turns: **6–8** (Agentic: "retain system + initial user + last 6 turns")
- Prefill budget: **1000–1500 tokens** (Mingbird: 1250 pinned)
- Compression trigger: **70% context usage**

### 4.2 2-Stage Tool Routing (SmallCode, Mingbird)

```
Turno do modelo:
  1. Modelo escolhe CATEGORIA: read | write | search | run | plan | code_intel
  2. Harness injeta APENAS schemas da categoria escolhida
  3. Modelo emite tool call específico
```

**Impacto**: Reduz schema context em ~50% (critical para 8K–16K context). SmallCode: "Halves the schema context overhead. Critical for models with 8-16k context."

### 4.3 Forgiving Tool Call Parser (SmallCode, KWCode, Mingbird)

Formatos suportados (SmallCode):
- JSON nativo
- YAML
- XML
- Hermes format
- Liquid AI: `<|tool_call_start|>[func(kw='val')]<|tool_call_end|>`
- Plain text (scan reasoning_content quando content vazio — LM Studio reasoning models)

Auto-repair: wrong param names, type mismatches, missing required fields.

### 4.4 Patch-First Editing (SmallCode, Mingbird, KWCode, Agentic)

**Por que**: Modelos 8B não reproduzem arquivos inteiros confiavelmente — truncam, alucinam, driftam.

**Mecanismo**:
- Search-and-replace (`patch`) como primitiva primária
- `write_file` só para arquivos novos
- Verifier executa syntax check + testes após patch
- Semantic merge fallback quando `old_str` não existe mais (SmallCode Rank 7, KWCode)

### 4.5 TODO-Driven Planning / Plan-Then-Execute (SmallCode, Agentic, KWCode, Argus)

```
Tarefa complexa →
  1. Modelo emite PLAN numerado (Plan node / /plan command)
  2. Harness re-injeta plan como âncora nos turns subsequentes
  3. Cada step validado (lint/compile/test) antes de prosseguir
  4. Model reads TODO file each turn to know where it is
```

**SmallCode**: `SMALLCODE_PLAN=true|false` (heuristic-based, simple tasks don't trigger)
**Agentic**: Plan node com T1 decompose + T2 HyDE + T4.1 critic + T4.5 refine-on-reject
**KWCode**: `/plan` mostra passos + risco (High/Medium/Low), confirma antes de executar
**Argus**: Planner → sub-questions → parallel searchers

### 4.6 Early-Stop Detection / Cognitive Gating (SmallCode, KWCode, Agentic)

| Detector | Ação |
|----------|------|
| **Repetition loops** | Inject steer / hard reset / graceful exit (Mingbird ladder) |
| **Patch spirals** (stuck on corrupted file) | Force rewrite (SmallCode) |
| **Greeting regression** (model lost context) | Re-inject task (SmallCode) |
| **Patch lines decreasing** (marginal returns) | Auto-stop (KWCode cognitive gate) |
| **Scope creep / repetitive fix / patch miss** | Wink injects correction hint (KWCode) |
| **ThinkPRM step critic** | Critica cada passo de raciocínio (Agentic T4.1) |

### 4.7 Thinking Budget Control (SmallCode, Agentic)

```bash
# SmallCode
SMALLCODE_THINKING_BUDGET=2000    # default cap per call
SMALLCODE_THINKING_DISABLE=true   # turn off entirely

# Suporta: Anthropic budget_tokens, OpenAI reasoning_effort, 
# Qwen enable_thinking, DeepSeek style — all set defensively
# Hard-truncates oversize thinking blocks before entering history
```

**Impacto**: Qwen3/DeepSeek R1/GPT-5 reasoning podem gastar 5K+ tokens "pensando" sobre tarefas triviais. Cap evita context overflow.

### 4.8 Model Capability Adaptation (KWCode, Agentic, SmallCode)

| Modelo | Estratégia Automática |
|--------|----------------------|
| **<10B (qwen3:8b, gemma3:4b)** | Forced plan confirm · task scope ≤2 files · 1st failure triggers search · thinking OFF |
| **10–30B (qwen3:14b)** | Optional plan · scope ≤4 files · 2nd failure triggers search |
| **>30B (qwen3:72b)** | Relaxed · scope ≤8 files · auto complex tasks |

**KWCode**: `model_capability.py` detecta tier → ctx adaptativo → prompt constraints
**Agentic**: `MODEL_SYNTHESIZER=gemma3:4b` local, swap to `gpt-5-mini` cloud for factoid accuracy
**SmallCode**: Tier-based routing (trivial→tiny, complex→medium), adaptive model select (Rank 8)

### 4.9 Retrieval-Augmented Context (KWCode, Argus, Agentic, PicoClaw)

**KWCode (BM25 + AST Call Graph — 2-phase, zero LLM):**
```
Query → BM25 keyword recall (ms) → AST call graph expand (ms) → precise file:line results
```
- tree-sitter multi-lang + ast-grep templates + rank-bm25 + SQLite call graph
- CodeCompass: graph traversal G3 99.4% vs BM25 76.2%

**Argus (Contextual RAG + Hybrid Retrieval):**
- Anthropic-style contextual chunking (LLM-written prefixes)
- Dense HNSW + Lexical FTS fused with RRF
- Optional bge-reranker-v2-m3 cross-encoder
- Single pgvector store

**Agentic**: SearXNG meta-search + trafilatura fetch + hybrid BM25/dense/RRF + cross-encoder opt-in

---

## 5. Estratégias de Verificação e Qualidade (Eval Gates)

### 5.1 Argus: Eval Gate Mais Rigoroso (Produção-Ready)

```bash
make eval  # 48-item benchmark, corpus-only, real retrieval + judged answer
```

**Métricas RAGAS in-repo (sem dependência RAGAS library):**

| Métrica | Threshold | gpt-5.4-mini | qwen3.5:4B (local $0) | qwen2.5:3B |
|---------|-----------|--------------|----------------------|------------|
| context_recall | ≥0.80 | **1.000** | 0.976 | 0.976 |
| context_precision | ≥0.20 | 0.662 | **0.676** | 0.624 |
| mrr | ≥0.60 | 0.948 | **0.952** | 0.952 |
| faithfulness | ≥0.70 | 0.976 | 0.976 | **1.000** |
| judge_pass_rate | ≥0.70 | **0.976** | 0.643 ❌ | 0.000 ❌ |
| abstention_rate (negatives) | ≥0.70 | **1.000** | 0.833 | 0.000 ❌ |

**Calibração do Judge (Cohen's κ ≥ 0.80 obrigatório):**
1. 20 triples human-annotated pass/fail
2. Judge runs same 20 → compute κ
3. κ < 0.80 → revise judge prompt → recalibrate (`make eval-calibrate`)
4. Só então judge scores remaining benchmark

**Insight crítico**: `qwen2.5:3b` colapsa em `abstention_rate = 0.000` — **fabrica resposta para TODAS perguntas não-respondíveis**. Este é o modo de falha canônico de RAG sem teste de abstention.

### 5.2 Mingbird: LRAB-288 (End-to-End Task Completion)

- 4 harnesses × 4 modelos (2B–35B) × 18 tarefas reais = **288 células públicas**
- Scoring determinístico de artefatos (não LLM-as-judge)
- **2B column é a história**: 0.821 vs 0.017–0.271 — único harness sem "small-model cliff"
- τ²-bench externo: retail 0.763 / airline 0.740 / telecom 1.000 (first or tied-first)

### 5.3 Agentic Research Engine: Honest Benchmarks

- SimpleQA-mini: Gemma 3 4B **0/20 strict pass rate** (verified_ratio 85.5%)
- **Gemma 3 4B confabula factóides específicos** quando SearXNG não retorna token certo
- Mitigação: (a) swap to cloud endpoint ($0.02–0.05/query), (b) LOCAL_CORPUS_PATH, (c) ENABLE_RERANK=1
- **CoVe verifica consistência interna, não ground truth** — se retrieval falha, CoVe valida resposta confiantemente errada

### 5.4 KWCode: Eval-Driven Development

- v2.1.0: Eval passou de **22% → 53%** (26/50 PASS, incl. Go 6/9, multi-file API 3/3)
- Bench diagnóstico system (`bench_diagnose.py`)
- Regressão guard: checkpoint não sobrescreve, syntax free retry, error[-3000:] tail

---

## 6. Segurança e Rollback (Mingbird 5-Ring Safety Net + SmallCode Snapshot)

| Ring | Mingbird | SmallCode Equivalente |
|------|----------|----------------------|
| 0 | Sub-agent sandbox (default-deny, fewer perms) | Tool permissions registry + trust decay |
| 1 | Irreversible ops refused (format, dd, diskpart, wsl --unregister, driver uninstall) | — |
| 2 | Behavior tiering: uninstalls/env changes confirm attended, deny unattended (`AGENT_ALLOW_ENV_MUTATION=1`) | — |
| 3 | Boundary confirmation: recursive deletes stay in working dir | Read-before-write guard (tracks read paths) |
| 4 | Rollback everywhere: `.bak` before writes, `.mingbird_trash/` for deletes, `replace=true` for large→short | Snapshot checkpoint before each turn; `SMALLCODE_SNAPSHOT_AUTO_ROLLBACK=true` reverts on hard fail |

**Escape hatch**: `AGENT_UNSAFE=1` (Mingbird) / `SMALLCODE_SNAPSHOT=false` (SmallCode) — at your own risk.

---

## 7. Hardware e Deployment para 8B

| Tier | Hardware | Modelos | Experiência |
|------|----------|---------|-------------|
| **Entry** | any iGPU · 16 GB RAM | **2–4B** (gemma3:4b, qwen3:4b) | Streaming, near raw-Ollama speed |
| **Base** | iGPU or entry dGPU · 32 GB RAM | **2–35B** (qwen3:8b, qwen3:14b) | 35B long tasks run end-to-end |
| **PicoClaw** | **$10 RISC-V/ARM** · <10MB RAM | Qualquer via API (Ollama/vLLM/OpenAI-compat) | 400x faster boot, single binary multi-arch |

**VRAM referência (Ollama):**
- 4GB: gemma3:4b
- 8GB: **qwen3:8b** ← sweet spot
- 16GB: qwen3:14b
- 24GB+: qwen3:30b-a3b

**macOS Apple Silicon**: Unified memory — sem VRAM separada. Ollama nativo suporta Metal.

---

## 8. Arquitetura de Referência Recomendada (Síntese)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENT HARNESS 8B - ARQUITETURA DE REFERÊNCIA        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  USER INPUT                                                                 │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ CLASSIFY (Gate) — LLM pequeno (tiny classifier) ou regex           │   │
│  │   → task_type: coding | editing | search | research | debug        │   │
│  │   → model_tier: small | medium | strong (adaptive routing)         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PLAN / DECOMPOSE (LLM 8B) — emite numbered plan + risk assessment  │   │
│  │   → TODO file / DAG JSON (persisted, re-injected each turn)        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ LOCATE / RETRIEVE (Determinístico — ZERO LLM)                      │   │
│  │   • BM25 + AST Call Graph (KWCode) — ms, precise file:line         │   │
│  │   • Hybrid RAG: Dense HNSW + Lexical FTS + RRF (Argus)             │   │
│  │   • SearXNG + trafilatura + cross-encoder rerank (Agentic)         │   │
│  │   • Contextual chunking (Anthropic-style)                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ GENERATE (LLM 8B) — Patch-first, bounded context                   │   │
│  │   • 2-stage tool routing: category → schema                        │   │
│  │   • Forgiving parser: JSON/YAML/XML/Hermes/Liquid/text             │   │
│  │   • Thinking budget cap (2000 tokens)                              │   │
│  │   • Working memory / scratchpad (persistent across turns)          │   │
│  │   • Evidence store: "what worked/failed" per task                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ VERIFY / EXECUTE (Determinístico)                                  │   │
│  │   • Syntax check (ast.parse / ruff / go vet / cargo check)         │   │
│  │   • Test execution + exact failure feedback (file:line + error)    │   │
│  │   • Semantic merge fallback when patch fails                       │   │
│  │   • Snapshot checkpoint before turn; auto-rollback on hard fail    │   │
│  │   • 5-ring safety net (bounds, confirmations, rollback)            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ DEBUG / REFLECT (LLM 8B + Determinístico)                          │   │
│  │   • Debug Subagent: sys.settrace capture runtime vars (KWCode)     │   │
│  │   • Error diagnosis: classify error_type → structured hint         │   │
│  │   • CoVe verification: decompose claims → verify against evidence  │   │
│  │   • ThinkPRM step critic: critique each reasoning step             │   │
│  │   • Cognitive gate: patch lines decreasing → auto-stop             │   │
│  │   • Wink monitor: scope creep / repetitive fix → inject correction │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ DELIVERY SELF-CHECK (Mingbird) / REFLECT / REPLAN                  │   │
│  │   • Re-read original task + verify work before claiming done       │   │
│  │   • If unverified claims → re-search (bounded by MAX_ITERATIONS)   │   │
│  │   • Persist REFLECTION.md: failure patterns + lessons learned      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Configuração Recomendada para DeepSeek 8B (ou Qwen3-8B, Gemma3-4B)

### 9.1 Model Server (Ollama / vLLM / llama.cpp)

```bash
# Ollama (simples)
ollama pull qwen3:8b          # ou deepseek-coder:6.7b, gemma3:4b
ollama pull nomic-embed-text  # para RAG local

# vLLM (throughput maior)
vllm serve Qwen/Qwen3-8B --tensor-parallel-size 1 --gpu-memory-utilization 0.9
```

### 9.2 Harness Config (Variáveis de Ambiente Unificadas)

```bash
# === Model Routing ===
export MODEL_PRIMARY="qwen3:8b"              # 8B local
export MODEL_STRONG="gpt-5-mini"             # Cloud fallback (opcional)
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_API_KEY="ollama"

# === Context Budget (8B ~ 8K-16K context) ===
export CONTEXT_WINDOW=8192
export TOOL_RESULT_MAX_CHARS=3000
export MAX_HISTORY_TURNS=6
export PREFILL_BUDGET_TOKENS=1200
export THINKING_BUDGET=2000
export THINKING_DISABLE=false          # Qwen3 thinking ON para tarefas complexas

# === Tool Routing ===
export TWO_STAGE_ROUTING=true
export PATCH_FIRST_EDITING=true
export FORGIVING_PARSER=true

# === Planning ===
export PLAN_THEN_EXECUTE=true
export TODO_DRIVEN=true
export AUTO_PLAN_THRESHOLD="multi_file_or_complex"

# === Verification ===
export SYNTAX_CHECK=true
export TEST_AUTO_DISCOVERY=true
export TEST_COMMAND_OVERRIDE=""        # Auto-detect from package.json/pytest.ini/etc
export COVE_VERIFICATION=true
export FLARE_ACTIVE_RETRIEVAL=true

# === Safety ===
export SNAPSHOT_BEFORE_TURN=true
export AUTO_ROLLBACK_ON_HARD_FAIL=true
export READ_BEFORE_WRITE_GUARD=true
export FIVE_RING_SAFETY=true
export WORKING_DIR_BOUNDARY=true

# === Anti-Loop ===
export QUALITY_MONITOR=true
export EARLY_STOP_DETECTION=true
export COGNITIVE_GATE=true
export TRUST_DECAY=true
export MAX_CONSECUTIVE_CORRECTIONS=2

# === Retrieval (se usar RAG) ===
export BM25_AST_GRAPH=true             # KWCode style
export HYBRID_RRF=true                 # Argus style
export CROSS_ENCODER_RERANK=false      # Opt-in (bge-reranker-v2-m3, 560MB)
export CONTEXTUAL_CHUNKING=true        # Anthropic style
export LOCAL_CORPUS_PATH=""            # Set to indexed corpus dir

# === Eval Gate (CI) ===
export EVAL_GATE_ENABLED=true
export JUDGE_CALIBRATION_KAPPA=0.80
export ABSTENTION_TEST_ENABLED=true
export NEGATIVE_CASES_REQUIRED=true
```

---

## 10. Lições Aprendidas por Repositório

### Mingbird: "Harness Defects, Not Model Defects"
- **Flat prefill pinned** em 1250 tokens (CI fails on any change) — estabilidade > otimização
- **Crawl guard v2** em byte budget (2× file size, clamped 64KB–512KB) — nunca recusa
- **Delivery self-check gate** antes de claim done — re-read task + verify
- **726-test regression suite** (435 unit + 26 integration + 265 added) — **zero live-Ollama e2e tests**
- **One-click offline mode** 🔒 — web tools nem montados no prompt, zero outbound by construction

### SmallCode: MarrowScript + BoneScript
- **MarrowScript**: DSL declarativa → 1400+ lines TypeScript com cache, retry, validation, traces, budget — "all for free"
- **BoneScript**: 1 arquivo `.bone` → projeto completo (routes, auth, DB, events, migrations, SDK, admin, Docker, CI) — reduz 8-15 tool calls para 1-2
- **Model Escalation**: Hard fail → retry + decompose → cloud fallback (opt-in, session-limited)
- **Plugin system**: 5 lifecycle hooks (pre/post request, on_error, session_start/end)
- **Per-tool trust score decay**: 3+ fails → soft-demote, 5+ fails → drop from schema

### KWCode: Deterministic Expert Pipeline
- **5 meta-especialistas fixos** (Gate, Locator, Generator, Verifier, Debugger, Reviewer) — não mudam
- **15 SKILL.md** (conhecimento de domínio) — extensível sem tocar pipeline
- **Debug Subagent**: `sys.settrace` captura variáveis runtime — não usa PDB, não modifica fonte
- **Flywheel**: Trajetórias → Pattern Detector → Expert Draft → Backtest Gate → AB Test Gate (10 runs, >10% lift) → Production
- **Reflexão persistida**: `REFLECTION.md` estruturado, lido em `/plan` como risk hints
- **Model capability adaptation**: Tier detectado → ctx adaptativo → prompt constraints

### PicoClaw: Go + Ultra-Leve
- **Single binary** multi-arch (x86_64, ARM64, MIPS, RISC-V, LoongArch)
- **<10MB RAM**, boot <1s em 0.6GHz single-core
- **AI-bootstrapped**: 95% core code gerado por agente + human-in-the-loop review
- **MCP nativo** + vision pipeline + model routing (simple→lightweight model)
- **30+ providers** + 19+ canais chat (Telegram, Discord, WhatsApp, WeChat, Slack, Matrix, etc.)

### Agentic Research Engine: LangGraph + SOTA Techniques
- **8-node pipeline** com env-toggleable para ablation (classify→plan→search→retrieve→fetch→compress→synthesize→verify)
- **Técnicas 2026-SOTA**: HyDE, CoVe, FLARE, ThinkPRM, LongLLMLingua-lite, cross-encoder rerank, contextual chunking
- **6 domain presets YAML** — escreva o seu em ~10 linhas
- **MCP server + Claude plugin** — 4 skills (/research, /cite-sources, /verify-claim, /set-domain)
- **Honest limits documented**: Gemma 4B ≠ GPT-5.4 Pro; confabula factóides; CoVe ≠ ground truth

### Argus: Framework-Free + Eval Gate Rigoroso
- **Sem LangChain/LangGraph** — loop é stateless reducer sobre `messages: list[dict]`
- **Testabilidade**: Feed canned messages, assert — 150 testes hermeticos (LLM/DB/search faked)
- **Durabilidade**: Lista serializável → checkpoint → resume after crash (DBOS opt-in)
- **Eval gate**: RAGAS in-repo + Cohen's κ calibrated judge (κ ≥ 0.80) — **falha build se regressão**
- **Escala horizontal**: ARQ-on-Redis + KEDA autoscale searcher pods from zero
- **Multi-tenant + auth**: argon2id + HS256 JWT httpOnly cookie + signed double-submit CSRF

---

## 11. Checklist de Implementação (Prioridade)

### Fase 1: Core Harness (Semana 1-2)
- [ ] Pipeline determinístico: Gate → Locate → Generate → Verify → Debug → Review
- [ ] Context budget engine: tool result cap, mid-turn eviction, semantic compression
- [ ] 2-stage tool routing (category → schema)
- [ ] Forgiving tool call parser (JSON/YAML/XML/Hermes/Liquid/text)
- [ ] Patch-first editing + semantic merge fallback
- [ ] Snapshot checkpoint antes de cada turn + auto-rollback on hard fail
- [ ] 5-ring safety net (bounds, confirmations, rollback)

### Fase 2: Qualidade e Confiabilidade (Semana 2-3)
- [ ] TODO-driven planning / Plan-then-execute
- [ ] Early-stop detection: repetition, patch spiral, greeting regression
- [ ] Cognitive gate: patch lines decreasing → auto-stop
- [ ] Quality monitor: empty turns, blank tool names, hallucinated tools, exact-repeat
- [ ] Thinking budget control (per-call cap + hard truncate)
- [ ] Model capability adaptation (tier detection → strategy)
- [ ] Trust score decay per tool

### Fase 3: Retrieval e Verificação (Semana 3-4)
- [ ] BM25 + AST call graph locator (zero LLM, ms-level)
- [ ] Hybrid RAG: dense HNSW + lexical FTS + RRF
- [ ] Contextual chunking (Anthropic-style)
- [ ] Cross-encoder rerank opt-in
- [ ] CoVe verification (decompose claims → verify against evidence)
- [ ] FLARE active retrieval (on hedges/uncertainty)
- [ ] ThinkPRM step critic

### Fase 4: Eval Gate e Produção (Semana 4-5)
- [ ] Golden set curado (48+ itens: positive, negative/unanswerable, near-miss)
- [ ] RAGAS metrics in-repo (context_recall, precision, mrr, faithfulness, answer_relevancy)
- [ ] LLM judge + Cohen's κ calibration (κ ≥ 0.80 obrigatório)
- [ ] Abstention rate gate (negative cases must be declined)
- [ ] CI integration: eval gate blocks merge on regression
- [ ] Benchmark harness: LRAB-style end-to-end task completion

### Fase 5: Observabilidade e UX (Semana 5-6)
- [ ] Structured traces (trace_id/span_id every LLM call)
- [ ] Streaming output + visible thinking (fold away when done)
- [ ] TUI / WebUI / CLI interfaces
- [ ] Session memory (searchable, replayable)
- [ ] Skills/MCP plugin system
- [ ] Voice input (STT local) + drag-drop attachments

---

## 12. Referências e Papers-Chave

| Paper/Projeto | Relevância para 8B Harness |
|---------------|---------------------------|
| **Mingbird** (arXiv:2610.02001) | Local-first harness enabling small open models to complete real tasks |
| **Agentless** (ICSE 2025) | Deterministic pipeline > complex agent for code tasks |
| **CodeCompass** (arXiv:2602.20048) | Graph traversal G3 99.4% vs BM25 76.2% — AST call graph works |
| **Debug2Fix** (Microsoft, ICML 2026) | Weak model + interactive debugger > strong model bare |
| **LLMCompiler** (ICML 2024) | Task decomposition + parallel scheduling boosts completion |
| **EE-MCP** (NeurIPS 2025) | Auto-extract experience from trajectories |
| **SICA** (arXiv:2504.15228) | Self-improving coding agent |
| **Reflexion** (NeurIPS 2023) | Failure pattern persistence + retry injection |
| **CoVe** (Dhuliawala et al 2023) | Chain-of-Verification reduces hallucination |
| **FLARE** (Jiang et al 2023) | Active retrieval on uncertain generations |
| **ThinkPRM** (2024) | Step-level critic for reasoning |
| **LongLLMLingua** (2024) | Compression for long context |
| **PENCIL** (2024) | Generate then erase intermediate states |
| **SpecEyes** (arXiv:2603.23483) | Cognitive gating based on answer divisibility |
| **Turn-Control Strategies** (arXiv:2510.16786) | Dynamic budget > fixed budget 12-24% |
| **Wink** (arXiv:2602.17037) | Self-correction monitoring (drift/reasoning/tool failures) |
| **ARCS** (arXiv:2504.20434) | Retrieval-before-generation, failure-type precise trigger |

---

## 13. Conclusão

**O harness é o multiplicador de força para modelos 8B.** Os seis repositórios analisados convergem para os mesmos princípios:

1. **Pipeline determinístico** com LLM confinado a nós específicos (classify, generate, verify)
2. **Context budget rigoroso** (prefill pinned, tool caps, compression, thinking limits)
3. **Patch-first editing** + verificação determinística (syntax + testes + rollback)
4. **Retrieval zero-LLM** (BM25 + AST graph / hybrid RAG) para definição precisa de escopo
5. **Anti-loop / early-stop / cognitive gating** em múltiplas camadas
6. **Eval gate rigoroso** com golden set curado, métricas RAGAS, judge calibrado (κ ≥ 0.80), abstention test
7. **Segurança em anéis** + snapshot/rollback automático
8. **Adaptação automática por tier de modelo** (8B: forced plan, scope ≤2 files, thinking OFF para tarefas simples)

**Resultado mensurável (Mingbird LRAB-288)**: Mesmo modelo 2B sai de **0.017 → 0.821** pass rate. Modelo 8B (qwen3:8b, gemma3:4b) atinge **>0.75** em tarefas reais de coding/research em hardware iGPU 16GB.

**Para o seu projeto DeepSeek 8B**: Implemente a arquitetura de referência da Seção 8, use a configuração da Seção 9, siga o checklist da Seção 11. Priorize **eval gate desde o dia 1** — sem métricas, você não sabe se o harness está melhorando ou piorando o modelo.

---

*Relatório gerado em 2025-01-XX baseado em análise de 6 repositórios GitHub ativos (Mingbird, SmallCode, KWCode, PicoClaw, Agentic Research Engine, Argus). Todos os códigos, benchmarks e papers citados são publicamente auditáveis.*