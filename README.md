# Formiga

Harness minimalista de pesquisa profunda. Recebe uma pergunta, divide o trabalho
em lacunas investigáveis, busca e lê fontes, registra evidências e produz uma
resposta em Markdown com referências e limitações.

> **O harness controla o processo. O modelo interpreta e redige. As evidências
> delimitam o que pode ser afirmado.**

## Status

Implementação em andamento, conforme `docs/prd.md`.

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

Saída: `report.md` (relatório), `state.json` (estado da pesquisa),
`events.jsonl` (eventos operacionais).

## Configuração

Precedência: argumento da CLI > variável de ambiente > valor padrão.

```text
FORMIGA_MODEL=llama3.1:8b
FORMIGA_OLLAMA_URL=http://localhost:11434
FORMIGA_SEARXNG_URL=http://localhost:8080
```

O modelo padrão é uma escolha inicial de implementação, não uma garantia de
qualidade. O usuário deve instalá-lo previamente no Ollama e fornecer uma
instância SearXNG com o formato JSON habilitado.

## Privacidade

- A pergunta e os trechos das páginas são enviados ao endpoint do Ollama configurado.
- As consultas geradas são enviadas à instância SearXNG configurada e, dependendo
  da instância, a outros mecanismos de busca.
- Não inclua dados sensíveis sem confiar nesses serviços.

## Testes

```bash
.venv/bin/python -m pytest
```

Os testes automatizados rodam sem rede e sem modelo real.
