# PRD — Formiga

**Arquivo:** `prd.md`  
**Status:** proposta para implementação do MVP  
**Interface:** CLI  
**Linguagem:** Python  
**Desenvolvimento:** OpenCode  
**Modelo:** um único LLM de aproximadamente 8 bilhões de parâmetros

---

## 1. Visão geral

O **Formiga** é um harness minimalista de pesquisa profunda. Ele recebe uma pergunta, divide o trabalho em lacunas investigáveis, busca e lê fontes, registra evidências e produz uma resposta em Markdown com referências e limitações.

O sistema não depende de um agente autônomo com acesso irrestrito a ferramentas. O fluxo é controlado pelo programa; o LLM executa tarefas pequenas e delimitadas.

> **O harness controla o processo. O modelo interpreta e redige. As evidências delimitam o que pode ser afirmado.**

A arquitetura parte das recomendações dos relatórios anexados, especialmente o uso de contexto isolado, orçamentos explícitos e verificação de evidências. As alegações de benchmark presentes nos relatórios não são tratadas como resultados comprovados para o Formiga. [1] [2]

---

## 2. Problema

Um modelo 8B pode responder perguntas amplas de maneira superficial ou confiante demais. Em pesquisas com várias fontes, também pode:

- perder o objetivo original;
- repetir buscas sem obter novas informações;
- confundir fontes e atribuições;
- extrapolar uma conclusão além do trecho encontrado;
- inventar informações quando a busca falha;
- encerrar a pesquisa antes de investigar lacunas centrais.

O Formiga deve reduzir esses riscos por meio de um processo explícito e auditável. Ele **não garante** que o modelo interpretará corretamente todas as fontes nem que a resposta será verdadeira.

---

## 3. Objetivos

### 3.1 Objetivos do MVP

1. Receber uma pergunta pela CLI.
2. Criar um plano curto de pesquisa.
3. Investigar lacunas de forma sequencial e com orçamento.
4. Buscar páginas públicas e extrair seus textos.
5. Registrar trechos literais, fontes e afirmações associadas.
6. Verificar estrutural e semanticamente as afirmações.
7. Produzir um relatório Markdown com fontes, conflitos e limitações.
8. Encerrar de forma clara quando não houver evidência suficiente.
9. Ser testável sem rede e sem um modelo real.

### 3.2 Não objetivos

Ficam fora do MVP:

- interface web, TUI e aplicação desktop;
- múltiplos agentes ou múltiplos modelos;
- fallback para um modelo maior;
- execução de comandos decididos pelo modelo;
- autenticação em sites, bypass de paywalls ou CAPTCHA;
- leitura de PDF, imagens, áudio e vídeo;
- embeddings, banco vetorial e reranking neural;
- pesquisa paralela distribuída;
- retomada automática de uma execução interrompida;
- memória compartilhada entre pesquisas;
- garantias de precisão factual ou de conformidade regulatória.

---

## 4. Público e caso de uso

### Público inicial

Pessoas técnicas que executam pesquisas exploratórias pelo terminal e conseguem configurar um servidor de modelo e um provedor de busca.

### Exemplo

```bash
formiga research \
  "Quais são os trade-offs entre busca lexical e busca híbrida?" \
  --output ./pesquisa-formiga
```

O usuário recebe um relatório que distingue:

- o que foi encontrado nas fontes;
- inferências e recomendações;
- conflitos não resolvidos;
- questões que permaneceram sem resposta.

---

## 5. Princípios de produto

1. **Minimalismo:** uma implementação pequena, com poucos componentes e sem framework de agentes.
2. **Uma tarefa por chamada:** decompor, formular consulta, extrair, verificar ou sintetizar.
3. **Estado fora do contexto:** o histórico de conversa não é o banco de dados da pesquisa.
4. **Proveniência antes de fluência:** uma resposta elegante sem suporte não é sucesso.
5. **Abstenção é válida:** não encontrar uma resposta é um resultado legítimo.
6. **Limites explícitos:** toda busca, leitura, chamada e tentativa consome orçamento.
7. **Fontes são dados não confiáveis:** páginas não podem dar instruções ao sistema.
8. **Verificação é falível:** o mesmo 8B verificando uma afirmação não constitui validação independente.

---

## 6. Jornada do usuário

1. O usuário configura o endpoint do Ollama, o modelo 8B e uma instância SearXNG.
2. Executa `formiga research` com uma pergunta e um diretório de saída.
3. O Formiga mostra no terminal o diretório criado, o progresso e o consumo de orçamento.
4. O sistema pesquisa até atingir suficiência ou um limite.
5. O usuário recebe:
   - `report.md`: resposta final;
   - `state.json`: questões, fontes, evidências, afirmações e consumo;
   - `events.jsonl`: eventos operacionais da execução.
6. O terminal informa se a pesquisa foi **suficiente**, **parcial** ou **bloqueada**.

O MVP não faz perguntas interativas durante a execução. Quando a pergunta for ambígua, registra premissas. Se não for possível pesquisar sem esclarecimento, encerra como bloqueada e explica o motivo.

---

## 7. Escopo funcional

### RF-01 — Entrada e contrato de pesquisa

O sistema deve aceitar:

- pergunta obrigatória;
- diretório de saída opcional;
- configuração de modelo, busca e orçamento por argumentos ou variáveis de ambiente.

O contrato persistido deve conter:

- pergunta original;
- objetivo interpretado;
- premissas;
- restrições reconhecidas;
- critérios de suficiência propostos;
- orçamento efetivo.

O Formiga não deve remover silenciosamente restrições explícitas do usuário.

### RF-02 — Planejamento

O modelo propõe questões pesquisáveis:

- perguntas amplas: até **4 questões iniciais**;
- perguntas simples: pelo menos **1 questão**;
- expansão máxima: **6 questões totais**;
- profundidade máxima: **2 níveis**, incluindo questões iniciais.

Cada questão contém:

| Campo | Descrição |
|---|---|
| `id` | Identificador estável |
| `question` | Pergunta específica |
| `priority` | `high`, `medium` ou `low` |
| `sufficiency` | O que permitiria respondê-la |
| `status` | Estado atual |
| `attempts` | Tentativas realizadas |
| `evidence_ids` | Evidências relacionadas |
| `limitation` | O que impede a conclusão, se aplicável |

Estados do MVP:

- `OPEN`
- `SEARCHING`
- `PARTIAL`
- `SUPPORTED`
- `CONFLICTED`
- `BLOCKED`
- `EXHAUSTED`

`SUPPORTED` significa que a questão foi considerada suficientemente sustentada **para o escopo da execução**, não que sua resposta seja uma verdade absoluta.

### RF-03 — Busca

O MVP usa uma instância **SearXNG configurada pelo usuário**, com endpoint de busca JSON habilitado.

- O Formiga gera até **2 consultas por rodada**.
- O harness executa as consultas e limita a quantidade de resultados.
- URLs repetidas são descartadas após normalização conservadora.
- Snippets servem para seleção de páginas, não como evidência final.
- Se uma página estiver inacessível, o Formiga registra a falha e tenta outra dentro do orçamento.
- Consultas enviadas ao provedor são registradas nos eventos.

Não é necessário fornecer ou instalar uma instância SearXNG dentro do projeto.

### RF-04 — Leitura e seleção de trechos

O MVP lê páginas HTML públicas.

O sistema deve:

1. baixar apenas conteúdo permitido;
2. extrair texto principal, preservando títulos e seções quando possível;
3. dividir o texto em trechos com identificadores e localizadores;
4. selecionar trechos relevantes por correspondência lexical;
5. fornecer poucos trechos por chamada ao modelo.

Não usar apenas o início da página como estratégia de recuperação. Se a extração falhar ou produzir texto insuficiente, registrar a limitação.

### RF-05 — Fontes e evidências

Para cada fonte, registrar:

- ID;
- URL solicitada e URL final;
- título, quando disponível;
- data de acesso;
- data de publicação, apenas quando identificada;
- hash do texto extraído;
- status da extração.

Para cada evidência, registrar:

- ID;
- ID da fonte;
- trecho literal;
- localizador no texto extraído;
- hash ou referência à versão do conteúdo;
- IDs das questões relacionadas.

Datas e autores desconhecidos devem permanecer desconhecidos.

### RF-06 — Afirmações e verificação

Cada afirmação deve ser pequena e vinculada a uma ou mais evidências.

Campos mínimos:

- `id`;
- `text`;
- `type`: `direct`, `inference` ou `recommendation`;
- `evidence_ids`;
- `scope_or_caveat`;
- `verification`.

A verificação tem duas camadas:

**Determinística**

- IDs existem e pertencem à execução;
- o trecho literal aparece no texto armazenado, após normalização de espaços;
- a evidência está ligada à fonte correta;
- o localizador é válido.

**Semântica**

O 8B avalia uma afirmação por vez, em contexto isolado:

- `DIRECT_SUPPORT`
- `PARTIAL_SUPPORT`
- `CONTRADICTED`
- `INSUFFICIENT`

Uma correspondência literal não prova suporte semântico. Uma classificação do modelo também não prova que a afirmação é verdadeira.

### RF-07 — Conflitos

Quando houver afirmações materialmente divergentes, o sistema deve:

1. comparar escopo, data, versão ou condições disponíveis;
2. evitar escolher uma vencedora apenas por fluência;
3. registrar as duas posições se o conflito permanecer;
4. explicar a divergência no relatório, quando relevante.

O MVP não precisa construir um sistema automático de identificação de independência entre fontes. Não deve, porém, contar URLs duplicadas como fontes independentes.

### RF-08 — Síntese e auditoria

O relatório deve ser gerado a partir de afirmações e evidências registradas, não diretamente de snippets.

Antes da entrega:

- o harness valida IDs e referências;
- o modelo audita as afirmações factuais do texto em lotes pequenos;
- afirmações sem suporte suficiente são removidas ou qualificadas;
- conflitos e lacunas centrais permanecem visíveis.

Se a síntese ou auditoria falhar, o sistema deve entregar um relatório parcial montado a partir das afirmações e evidências válidas disponíveis, sem inventar texto para preencher lacunas.

### RF-09 — Resultado final

O `report.md` deve conter:

```markdown
# Pesquisa: [pergunta]

## Resposta

[Resposta proporcional à evidência, com referências como [S1].]

## Evidências e análise

[Principais achados, condições e inferências identificadas.]

## Conflitos e limitações

[Conflitos, falhas de acesso, pressupostos e perguntas não respondidas.]

## Fontes

- [S1] Título. URL. Acessado em AAAA-MM-DD.

## Execução

- Status: suficiente | parcial | bloqueada
- Motivo de encerramento: ...
- Buscas: ...
- Páginas lidas: ...
- Chamadas ao modelo: ...
```

As referências `[S1]`, `[S2]` etc. são IDs de fontes do relatório gerado. Cada uma deve corresponder a uma fonte registrada.

### RF-10 — Persistência e interrupção

O sistema salva `state.json` após cada rodada concluída e adiciona eventos a `events.jsonl`.

- Uma interrupção não deve corromper um checkpoint já salvo.
- A escrita de `state.json` deve ser atômica.
- Uma execução interrompida pode ser inspecionada, mas **não é retomável no MVP**.
- O sistema não deve sobrescrever um diretório de saída existente sem autorização explícita.

---

## 8. Loop de pesquisa

```text
Receber pergunta
    ↓
Criar contrato e questões
    ↓
Selecionar lacuna prioritária
    ↓
Gerar consulta limitada
    ↓
Buscar e selecionar páginas
    ↓
Ler e recuperar trechos
    ↓
Extrair afirmações e evidências
    ↓
Validar estrutura e verificar suporte
    ↓
Atualizar questão e orçamento
    ↓
Continuar, mudar de questão ou encerrar
    ↓
Sintetizar, auditar e salvar
```

### Seleção de lacuna

A política inicial é determinística:

1. priorizar questões `high`, depois `medium`, depois `low`;
2. dentro da mesma prioridade, escolher a questão com menos tentativas;
3. usar a ordem de criação como desempate;
4. ignorar questões em `SUPPORTED`, `BLOCKED` ou `EXHAUSTED`.

Questões em `CONFLICTED` podem ser investigadas novamente enquanto houver orçamento e tentativas disponíveis.

### Repetição e progresso

Uma rodada conta como progresso se produzir pelo menos um destes resultados:

- nova evidência válida relevante;
- mudança justificada no estado da questão;
- identificação de conflito ou limitação material.

O sistema não deve executar novamente a mesma consulta normalizada para a mesma questão. Após **2 rodadas consecutivas sem progresso**, marca a questão como `EXHAUSTED` ou `BLOCKED`, conforme o motivo.

### Critérios de parada

A pesquisa termina quando:

- todas as questões essenciais estão sustentadas ou têm limitações registradas;
- o orçamento de investigação se esgota;
- todas as questões restantes estão bloqueadas ou esgotadas;
- ocorre falha operacional que impede continuar.

Status final:

| Status | Significado |
|---|---|
| `suficiente` | Questões centrais sustentadas; conflitos materiais resolvidos ou descritos |
| `parcial` | Há evidência útil, mas pelo menos uma questão central não foi resolvida |
| `bloqueada` | Não há evidência suficiente para uma resposta útil ou uma falha impede a pesquisa |

Esgotamento de orçamento não equivale a pesquisa suficiente.

---

## 9. Orçamentos iniciais

Os valores abaixo são **defaults configuráveis**, não resultados medidos.

| Recurso | Default |
|---|---:|
| Questões iniciais | até 4 |
| Questões totais | até 6 |
| Rodadas de investigação | 8 |
| Buscas externas | 12 |
| Páginas baixadas | 18 |
| Páginas por rodada | 3 |
| Trechos por chamada de extração | 3 |
| Chamadas totais ao LLM | 40 |
| Chamadas reservadas para síntese e auditoria | 8 das 40 |
| Tempo total | 15 minutos |
| Rodadas sem progresso por questão | 2 |
| Correções de formato por chamada | 1 |
| Tamanho máximo por resposta HTTP | 2 MB |
| Timeout por requisição de rede | 20 segundos |

### Regras de contabilização

- Toda tentativa, inclusive falha e correção de formato, consome o orçamento correspondente.
- O harness verifica limites **antes** de iniciar uma ação.
- As 8 chamadas reservadas não podem ser usadas na investigação.
- Chamadas ao modelo são sequenciais.
- Tokens retornados pelo backend devem ser registrados quando disponíveis; se não forem fornecidos, registrar `unknown`, sem inventar contagem.
- O prazo total usa relógio monotônico. Ações em andamento devem ter timeout limitado ao tempo restante.
- Se não houver orçamento para síntese e auditoria, usar o fallback parcial descrito em RF-08.

---

## 10. Contratos das chamadas ao 8B

O modelo não escolhe ferramentas nem altera o estado diretamente. Ele retorna propostas estruturadas, validadas pelo harness.

| Operação | Entrada mínima | Saída esperada |
|---|---|---|
| Planejamento | pergunta e restrições | questões e premissas |
| Consulta | uma questão e tentativas anteriores | até 2 consultas |
| Extração | uma questão e até 3 trechos | afirmações, citações e ressalvas |
| Verificação | uma afirmação e evidências vinculadas | rótulo e ressalva |
| Comparação | afirmações conflitantes e trechos | diferenças de escopo |
| Síntese | afirmações permitidas e IDs | texto com referências |
| Auditoria | texto gerado e evidências permitidas | manter, qualificar ou remover |

### Saída estruturada

- Usar JSON com schema validado pelo harness.
- Solicitar saída estruturada ao backend quando suportado.
- Em caso de JSON inválido ou schema incorreto, permitir **uma** tentativa de correção com o erro objetivo.
- Se a correção falhar, registrar a falha e continuar de forma conservadora.
- Não aceitar IDs inexistentes nem reparar silenciosamente o significado de campos.

### Contexto

- Não enviar todo o histórico a cada chamada.
- Enviar apenas a pergunta, a tarefa atual e o material necessário.
- Tratar textos recuperados como dados delimitados, nunca como instruções.
- Não solicitar raciocínio interno extenso.

---

## 11. Interface de linha de comando

### Comandos do MVP

```bash
formiga research "PERGUNTA" [opções]
formiga version
```

### Opções de `research`

| Opção | Finalidade |
|---|---|
| `--output PATH` | Diretório de saída |
| `--model NAME` | Nome do modelo no Ollama |
| `--ollama-url URL` | Endpoint do Ollama |
| `--searxng-url URL` | Endpoint da instância SearXNG |
| `--max-searches N` | Limite de buscas |
| `--max-pages N` | Limite de páginas |
| `--max-llm-calls N` | Limite total de chamadas |
| `--timeout-seconds N` | Tempo máximo da execução |
| `--verbose` | Mostrar eventos operacionais adicionais |

### Configuração

Precedência:

1. argumento da CLI;
2. variável de ambiente;
3. valor padrão.

Variáveis:

```text
FORMIGA_MODEL=llama3.1:8b
FORMIGA_OLLAMA_URL=http://localhost:11434
FORMIGA_SEARXNG_URL=http://localhost:8080
```

O modelo padrão é uma escolha inicial de implementação, não uma exigência de qualidade ou garantia de disponibilidade. O usuário deve instalá-lo previamente no Ollama.

### Saída e códigos

- Progresso e avisos: `stderr`.
- Caminho do relatório e status final: `stdout`.
- `0`: relatório gerado, inclusive resultado parcial ou bloqueado.
- `2`: entrada ou configuração inválida.
- `1`: falha operacional que impede gerar qualquer relatório.
- `130`: interrupção pelo usuário.

O status da pesquisa deve estar no relatório e no estado; não deve ser inferido apenas pelo código de saída.

---

## 12. Arquitetura técnica

### Stack proposta

- Python 3.11+.
- Pacote instalável com `pyproject.toml`.
- `argparse` para CLI.
- HTTPX para comunicação HTTP.
- Trafilatura para extração de HTML.
- Pydantic para schemas e validação.
- `pytest` para testes.
- Arquivos locais em JSON e JSONL para persistência.
- Integração com API HTTP do Ollama e busca JSON do SearXNG.

Não introduzir LangChain, LangGraph, banco vetorial ou infraestrutura de filas no MVP.

### Organização sugerida

```text
formiga/
├── pyproject.toml
├── README.md
├── prd.md
├── src/
│   └── formiga/
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── orchestrator.py
│       ├── budget.py
│       ├── llm.py
│       ├── search.py
│       ├── fetch.py
│       ├── extract.py
│       ├── evidence.py
│       ├── report.py
│       └── storage.py
└── tests/
    ├── fixtures/
    ├── test_budget.py
    ├── test_evidence.py
    ├── test_orchestrator.py
    ├── test_security.py
    └── test_e2e.py
```

A organização pode ser simplificada durante a implementação, desde que os contratos permaneçam testáveis.

---

## 13. Segurança e privacidade

### Conteúdo não confiável

- Páginas e snippets não podem alterar prompts de sistema, regras ou orçamento.
- O modelo não recebe ferramentas para executar comandos, escrever arquivos arbitrários ou enviar dados.
- O harness ignora instruções operacionais encontradas em fontes.

### Acesso a páginas

O fetcher deve:

- aceitar apenas HTTP e HTTPS;
- bloquear endereços de loopback, privados, link-local e reservados;
- validar resolução e destino efetivo da conexão, inclusive em redirecionamentos;
- repetir essas validações a cada redirecionamento;
- limitar redirecionamentos, tamanho, tempo e tipo de conteúdo;
- não encaminhar credenciais locais às páginas;
- desabilitar proxies herdados do ambiente no fetcher, salvo configuração explícita futura.

O acesso aos endpoints configurados pelo usuário para Ollama e SearXNG é separado do fetcher de páginas e pode apontar para `localhost`.

### Privacidade

- A pergunta pode ser enviada ao modelo configurado.
- Consultas geradas são enviadas ao SearXNG configurado e, dependendo da instância, a outros mecanismos de busca.
- Páginas baixadas e trechos são enviados ao endpoint do modelo.
- O README deve avisar que o usuário não deve incluir dados sensíveis sem confiar nesses serviços.
- Logs não devem incluir variáveis de ambiente completas ou credenciais.

---

## 14. Testes e critérios de aceite

### Testes automatizados obrigatórios

Devem rodar **sem rede e sem modelo real**, usando fixtures e adaptadores falsos.

1. **Fluxo completo:** pergunta → plano → busca simulada → evidência → relatório.
2. **Abstenção:** corpus sem resposta não gera uma afirmação factual inventada.
3. **Proveniência:** IDs e trechos literais do relatório correspondem ao estado salvo.
4. **Citação inválida:** ID inexistente ou trecho ausente é rejeitado.
5. **Conflito:** evidências divergentes não são apresentadas como consenso.
6. **Orçamento:** chamadas, buscas e páginas nunca ultrapassam os limites configurados.
7. **Repetição:** consulta duplicada não é executada novamente.
8. **Schema inválido:** no máximo uma correção; falha posterior é registrada.
9. **Falha de busca ou página:** produz limitação e não usa snippet como evidência.
10. **Injeção em página:** instruções da fonte não mudam o fluxo nem geram ações.
11. **Fetcher:** URLs e redirecionamentos para destinos internos são bloqueados.
12. **Persistência:** checkpoint permanece legível após falha simulada durante gravação.
13. **Diretório existente:** não ocorre sobrescrita silenciosa.
14. **Fallback:** falha de síntese gera relatório parcial com material válido.

### Smoke test manual

Documentar no README um teste com:

- Ollama e modelo 8B disponíveis;
- instância SearXNG com JSON habilitado;
- uma pergunta pública;
- inspeção de `report.md`, `state.json` e `events.jsonl`.

Esse teste demonstra integração, não comprova qualidade factual.

### Avaliação de qualidade após o MVP

Criar um conjunto pequeno de perguntas anotadas, com casos respondíveis, não respondíveis, multi-hop e conflitantes. Comparar, com revisão humana:

1. 8B sem pesquisa;
2. busca simples seguida de uma síntese;
3. Formiga.

Registrar cobertura, suporte das afirmações, abstenção, citações corretas, latência e chamadas. Não usar o mesmo 8B como único avaliador da própria qualidade.

---

## 15. Entregáveis

O MVP está pronto para revisão quando houver:

- [ ] CLI instalável e documentada.
- [ ] Integração com Ollama e SearXNG.
- [ ] Loop de pesquisa com limites e estados.
- [ ] Evidências com trechos e proveniência.
- [ ] Relatório Markdown e estado persistido.
- [ ] Testes automatizados offline.
- [ ] Instruções de configuração e smoke test no README.
- [ ] Limitações e riscos documentados.
- [ ] Nenhuma dependência de modelo maior.

---

## 16. Plano de implementação para o OpenCode

Implementar em etapas pequenas, executando os testes relevantes ao final de cada etapa.

### Etapa 1 — Esqueleto

- Criar pacote, CLI, configuração e README inicial.
- Definir schemas de estado, questões, fontes e evidências.
- Implementar testes de configuração e orçamento.

### Etapa 2 — Fluxo offline

- Implementar orquestrador com adaptadores falsos.
- Criar fixtures para sucesso, ausência de resposta e conflito.
- Gerar `report.md`, `state.json` e `events.jsonl`.

### Etapa 3 — Integrações

- Implementar adaptadores Ollama e SearXNG.
- Implementar fetch seguro, extração HTML e seleção lexical.
- Testar timeouts, limites, redirecionamentos e falhas.

### Etapa 4 — Qualidade da resposta

- Implementar extração, verificação, síntese e auditoria.
- Validar citações e incluir fallback parcial.
- Adicionar testes de alucinação estrutural e prompt injection.

### Etapa 5 — Revisão

- Rodar a suíte completa.
- Executar o smoke test manual, se os serviços estiverem disponíveis.
- Documentar resultados reais e limitações; não declarar testes externos como executados se não estiverem.