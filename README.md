# Formiga

Harness minimalista de pesquisa profunda. Recebe uma pergunta, divide o trabalho
em lacunas investigáveis, busca e lê fontes públicas, registra evidências e
produz uma resposta em Markdown com referências e limitações.

> **O harness controla o processo. O modelo interpreta e redige. As evidências
> delimitam o que pode ser afirmado.**

O sistema não depende de um agente autônomo com ferramentas livres: o fluxo é
controlado pelo programa e o LLM (8B, via Ollama) executa tarefas pequenas e
delimitadas — planejar, formular consulta, extrair citações, verificar,
comparar, sintetizar e auditar.

## Instalação

Requer Python 3.11+.

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e .
```

## Uso

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

## Opções de `research`

| Opção | Finalidade |
|---|---|
| `--output PATH` | Diretório de saída (padrão `./formiga-out`) |
| `--model NAME` | Nome do modelo no Ollama |
| `--ollama-url URL` | Endpoint do Ollama |
| `--searxng-url URL` | Endpoint da instância SearXNG (JSON habilitado) |
| `--llm-backend {ollama,llamacpp}` | Backend do modelo (default: ollama) |
| `--llamacpp-url URL` | Endpoint do llama-server (OpenAI-compatível) |
| `--max-searches N` | Limite de buscas (default 12) |
| `--max-pages N` | Limite de páginas (default 18) |
| `--max-llm-calls N` | Limite total de chamadas (default 40; 8 reservadas para síntese/auditoria) |
| `--timeout-seconds N` | Tempo máximo da execução (default 900) |
| `--overwrite` | Autoriza sobrescrever um diretório de saída existente |
| `--verbose` | Eventos operacionais no stderr |

## Configuração

Precedência: argumento da CLI > variável de ambiente > valor padrão.

```text
FORMIGA_MODEL=llama3.1:8b
FORMIGA_OLLAMA_URL=http://localhost:11434
FORMIGA_SEARXNG_URL=http://localhost:8080
FORMIGA_LLM_BACKEND=ollama          # ou: llamacpp
FORMIGA_LLAMACPP_URL=http://localhost:8080   # endpoint do llama-server
```

O modelo padrão é uma escolha inicial de implementação, não uma exigência de
qualidade. Instale-o antes no backend escolhido e configure uma instância
SearXNG própria com o formato JSON habilitado (`search.formats: [html, json]`).

### Backends de modelo

| Backend | Endpoint | Formato estruturado |
|---|---|---|
| `ollama` (default) | `POST /api/chat` com `format: "json"` | JSON; schema imposto pela validação do harness |
| `llamacpp` | `POST /v1/chat/completions` (OpenAI-compatível) | `response_format: {"type": "json_object", "schema": ...}` — o llama-server converte o schema em gramática GBNF |

Para usar um `llama-server` compilado localmente:

```bash
.venv/bin/formiga research "..." \
  --llm-backend llamacpp --llamacpp-url http://127.0.0.1:9931 \
  --output ./pesquisa-formiga
```

Builds antigas do llama-server que não suportam `schema` dentro de
`response_format` também funcionam — o campo é ignorado e a validação fica no
harness.

## Smoke test manual

Com Ollama e SearXNG disponíveis:

```bash
ollama pull llama3.1:8b
# SearXNG com JSON habilitado, ex.: http://localhost:8080

formiga research \
  "O que muda na segurança ao migrar de SSH por senha para SSH com chaves?" \
  --output ./smoke-formiga --verbose
```

Depois inspecione:

- `report.md` — resposta com referências `[S1]`, conflitos e limitações;
- `state.json` — estados das questões, evidências com localizadores e hashes;
- `events.jsonl` — buscas, páginas, chamadas e falhas registradas.

Esse teste demonstra integração, **não comprova qualidade factual**.

## Privacidade

- A pergunta e os trechos de páginas são enviados ao Ollama configurado.
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
├── src/formiga/
│   ├── cli.py             # argparse, códigos de saída
│   ├── config.py          # precedência CLI > env > default
│   ├── models.py          # schemas de estado (Pydantic)
│   ├── orchestrator.py    # loop de pesquisa controlado pelo programa
│   ├── budget.py          # orçamentos verificados antes de cada ação
│   ├── llm.py             # chamadas estruturadas + 1 correção de formato
│   ├── prompts.py         # prompts por tarefa (dados delimitados)
│   ├── schemas.py         # schemas das propostas do modelo
│   ├── ollama.py          # cliente Ollama
│   ├── llamacpp.py        # cliente llama-server (OpenAI-compatível)
│   ├── searxng.py         # cliente SearXNG JSON
│   ├── fetcher.py         # fetch seguro (seção 13 do PRD)
│   ├── extract.py         # Trafilatura, trechos, seleção lexical
│   ├── evidence.py        # verificação determinística + textos das fontes
│   ├── report.py          # relatório a partir de afirmações, não snippets
│   └── storage.py         # state.json atômico, events.jsonl
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
