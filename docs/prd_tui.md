# Especificação pós-MVP — TUI do Formiga

## 1. Visão

A TUI do Formiga será uma interface de terminal **simples, linear e orientada à pesquisa**.

A inspiração é a experiência minimalista de agentes de terminal como o Pi: conteúdo legível, progresso apresentado em sequência e uma área de entrada fixa e discreta. O Formiga não precisa imitar exatamente a interface ou os atalhos do Pi.

A interface deve transmitir uma ideia:

> O usuário faz uma pergunta, acompanha a pesquisa e pode inspecionar o resultado sem precisar entender a implementação.

A TUI será uma camada sobre o mesmo motor usado pela CLI. Ela não terá um agente próprio nem regras diferentes de pesquisa.

---

## 2. Objetivos

A TUI deve permitir:

1. Iniciar uma pesquisa digitando uma pergunta.
2. Acompanhar o progresso em tempo real.
3. Ver rapidamente questões, fontes e orçamento.
4. Inspecionar evidências e limitações.
5. Interromper uma pesquisa de forma segura.
6. Consultar o relatório final.
7. Navegar pelos principais comandos usando uma **barra de menu**.
8. Retornar à experiência de terminal sem um fluxo complexo de configuração.

### Não objetivos

A primeira versão da TUI não deve incluir:

- múltiplos painéis permanentes;
- dashboard de métricas;
- gráficos;
- animações elaboradas;
- múltiplas pesquisas simultâneas;
- edição manual de evidências;
- navegador web embutido;
- gerenciamento ou download de modelos;
- retomada de pesquisas interrompidas;
- histórico compartilhado entre máquinas;
- configuração de todos os parâmetros por interface.

---

## 3. Princípios de interface

### 3.1 Uma tela, uma tarefa

A tela principal deve ser suficiente para iniciar e acompanhar uma pesquisa. Informações secundárias aparecem em uma área de detalhes, aberta apenas quando solicitada.

### 3.2 Pouco ruído

Mostrar acontecimentos úteis, não cada detalhe técnico.

**Bom:**

```text
Buscando documentação oficial sobre filtros por metadados.
```

**Evitar na visualização padrão:**

```text
GET https://... status=200 bytes=32817 duration=0.42
```

Detalhes técnicos ficam disponíveis na inspeção ou nos arquivos de eventos.

### 3.3 Estado explícito

A interface deve distinguir claramente:

- pesquisando;
- pesquisa suficiente;
- pesquisa parcial;
- pesquisa bloqueada;
- pesquisa interrompida;
- falha operacional.

### 3.4 Sem falsa precisão

Não mostrar uma barra de progresso percentual para a pesquisa. O número de questões resolvidas não é uma medida confiável de conclusão.

Uma barra é apropriada para **orçamento consumido**, pois esse valor é conhecido.

### 3.5 Discreta e acessível

A interface deve funcionar sem cores e não depender exclusivamente delas para transmitir estados.

---

## 4. Estrutura da tela

A tela principal tem quatro regiões:

1. **Cabeçalho:** nome, modelo e estado.
2. **Área de atividade:** pergunta, plano e eventos da pesquisa.
3. **Barra de menu:** ações disponíveis.
4. **Barra de entrada:** pergunta ou comando.

### Estado inicial

```text
 formiga                                      modelo: llama3.1:8b
 pesquisa profunda, passo a passo
────────────────────────────────────────────────────────────────

 Faça uma pergunta para começar.

 A pesquisa usa o modelo e o provedor de busca configurados.
 Consultas serão enviadas ao provedor de busca.

────────────────────────────────────────────────────────────────
 Menu  Ctrl+P     Ajuda  F1     Sair  Ctrl+Q
────────────────────────────────────────────────────────────────
 ❯ _
```

### Durante uma pesquisa

```text
 formiga                                      pesquisando
 modelo: llama3.1:8b                          02:14
────────────────────────────────────────────────────────────────

 Você
 Quais são os trade-offs entre busca lexical e busca híbrida?

 Plano
 ● 1. Identificar os mecanismos de cada abordagem
 ◐ 2. Comparar requisitos e custos operacionais
 ○ 3. Identificar situações em que cada abordagem falha

 Atividade
 14:02  Pesquisando a documentação sobre busca lexical.
 14:02  Fonte encontrada: documentação do Elasticsearch.
 14:03  Evidência registrada para a questão 1.
 14:04  Comparando requisitos de indexação.

 Orçamento
 Buscas     ████░░░░░░  5/12
 Páginas    ██░░░░░░░░  4/18
 LLM        ███░░░░░░░  12/40

────────────────────────────────────────────────────────────────
 Menu Ctrl+P  Questões F2  Fontes F3  Estado F4  Parar Esc
────────────────────────────────────────────────────────────────
 Pesquisa em andamento
```

Os símbolos são acompanhados de texto nas visualizações de detalhes. Se o terminal não suportar bem Unicode, a interface deve oferecer equivalentes ASCII.

### Após a pesquisa

```text
 formiga                                      pesquisa parcial
 modelo: llama3.1:8b                          duração: 06:18
────────────────────────────────────────────────────────────────

 Resultado

 A busca lexical é uma base operacional mais simples quando
 correspondência de termos é suficiente. A busca híbrida pode
 recuperar resultados semanticamente relacionados, mas adiciona
 componentes e custos que dependem da implementação. [S1] [S2]

 Limitação: não foram encontradas medições comparáveis para o
 corpus e o hardware do usuário.

 Relatório salvo em:
 ./pesquisa-formiga/report.md

────────────────────────────────────────────────────────────────
 Menu Ctrl+P  Relatório F5  Fontes F3  Nova pesquisa Ctrl+N
────────────────────────────────────────────────────────────────
 ❯ _
```

O texto acima é ilustrativo, não o resultado de uma pesquisa executada.

---

## 5. Barra de menu

A barra de menu fica acima da entrada e mostra os atalhos mais importantes para o estado atual.

### 5.1 Conteúdo contextual

**Sem pesquisa ativa:**

```text
 Menu Ctrl+P  Ajuda F1  Abrir relatório F5  Sair Ctrl+Q
```

**Pesquisando:**

```text
 Menu Ctrl+P  Questões F2  Fontes F3  Estado F4  Parar Esc
```

**Pesquisa finalizada:**

```text
 Menu Ctrl+P  Relatório F5  Fontes F3  Nova pesquisa Ctrl+N
```

### 5.2 Menu expandido

`Ctrl+P` abre um menu compacto sobre a área de atividade:

```text
 Comandos
────────────────────────────────────
 > Nova pesquisa              Ctrl+N
   Ver questões                   F2
   Ver fontes                     F3
   Ver estado e orçamento         F4
   Abrir relatório                F5
   Mostrar ajuda                  F1
   Sair                       Ctrl+Q
────────────────────────────────────
 ↑↓ navegar   Enter selecionar   Esc fechar
```

Regras:

- `↑` e `↓` navegam.
- `Enter` executa a ação.
- `Esc` fecha o menu.
- Ações indisponíveis aparecem desabilitadas ou são omitidas.
- Em terminais estreitos, a barra mostra apenas `Menu Ctrl+P` e o estado; os demais comandos continuam no menu expandido.
- Atalhos de função devem ter alternativas no menu, pois alguns terminais os interceptam.

### 5.3 Barra versus comandos de texto

O menu é a principal forma de descoberta. Comandos iniciados por `/` são atalhos opcionais:

| Comando | Ação |
|---|---|
| `/help` | Abrir ajuda |
| `/questions` | Mostrar questões |
| `/sources` | Mostrar fontes |
| `/status` | Mostrar estado e orçamento |
| `/report` | Abrir relatório |
| `/new` | Preparar nova pesquisa |
| `/quit` | Sair |

Um texto que começa com `/` e não corresponde a um comando conhecido deve produzir uma mensagem curta, sem iniciar uma pesquisa acidentalmente.

---

## 6. Barra de entrada

### 6.1 Comportamento

A entrada recebe a próxima pergunta ou um comando:

```text
 ❯ _
```

- `Enter`: envia a pergunta ou executa o comando.
- `Ctrl+J`: adiciona uma quebra de linha.
- `↑` e `↓`: navegam pelo histórico de entradas quando o cursor estiver, respectivamente, na primeira ou última linha.
- A entrada cresce até um limite visual de **4 linhas**; depois, rola internamente.
- Perguntas vazias não são enviadas.
- Espaços nas extremidades podem ser removidos, preservando o texto interno.

A entrada deve aceitar perguntas em português e outros idiomas, incluindo caracteres Unicode.

### 6.2 Durante a pesquisa

O campo de pergunta fica desabilitado enquanto uma pesquisa está ativa. A barra exibe:

```text
 Pesquisa em andamento — pressione Esc para interromper
```

O usuário ainda pode abrir o menu e consultar questões, fontes e estado.

Essa decisão evita sugerir que o MVP suporta conversação contínua ou alterações no plano enquanto o motor está executando.

### 6.3 Nova pesquisa

Após o encerramento:

- o campo volta a ficar disponível;
- `Ctrl+N` prepara uma nova pesquisa;
- a interface pede confirmação antes de limpar a visualização atual;
- os arquivos da pesquisa anterior permanecem no disco;
- uma nova execução recebe um novo diretório de saída.

---

## 7. Fluxos principais

## 7.1 Iniciar pesquisa

1. O usuário abre a TUI:

   ```bash
   formiga tui
   ```

2. Digita uma pergunta.
3. Pressiona `Enter`.
4. A TUI verifica configuração mínima.
5. Exibe o diretório de saída escolhido.
6. Inicia a pesquisa pelo mesmo motor da CLI.
7. Exibe plano e eventos à medida que são confirmados pelo harness.

Se o usuário executar:

```bash
formiga tui "Quais são os trade-offs entre busca lexical e híbrida?"
```

a pergunta deve aparecer na entrada para revisão. A pesquisa só começa após `Enter`.

Isso evita enviar consultas externas sem uma ação explícita do usuário.

---

## 7.2 Acompanhar pesquisa

A área central mostra:

- pergunta original;
- plano e estado das questões;
- eventos relevantes em ordem cronológica;
- resumo de orçamento.

### Estados das questões

| Símbolo | Estado | Descrição na interface |
|---|---|---|
| `○` | `OPEN` | Ainda não investigada |
| `◌` | `SEARCHING` | Em investigação |
| `◐` | `PARTIAL` | Evidência parcial |
| `●` | `SUPPORTED` | Sustentada para o escopo |
| `!` | `CONFLICTED` | Conflito identificado |
| `×` | `BLOCKED` | Bloqueada |
| `–` | `EXHAUSTED` | Tentativas esgotadas |

A legenda completa fica disponível na tela de questões e na ajuda.

### Eventos visíveis

Exemplos:

```text
14:02  Plano criado com 3 questões.
14:03  Buscando a documentação oficial.
14:03  2 páginas selecionadas para leitura.
14:04  Evidência registrada para a questão 1.
14:05  Fontes divergem sobre as condições de teste.
14:06  Questão 2 encerrada com limitação de acesso.
14:08  Preparando relatório.
```

A interface não deve mostrar:

- raciocínio interno do modelo;
- prompts completos por padrão;
- grandes blocos de HTML;
- mensagens repetidas a cada token recebido.

---

## 7.3 Inspecionar questões

`F2` abre uma visualização temporária:

```text
 Questões                                              Esc voltar
────────────────────────────────────────────────────────────────

 1. Identificar os mecanismos de cada abordagem
    Estado: sustentada
    Evidências: E1, E2
    Tentativas: 2

 2. Comparar requisitos e custos operacionais
    Estado: parcial
    Evidências: E3
    Limitação: custos dependem do ambiente e não foram medidos.

 3. Identificar situações em que cada abordagem falha
    Estado: aberta
    Evidências: nenhuma

────────────────────────────────────────────────────────────────
 ↑↓ navegar   Enter detalhes   Esc voltar
```

Ao selecionar uma questão:

```text
 Questão 2                                             Esc voltar
────────────────────────────────────────────────────────────────

 Pergunta
 Comparar requisitos e custos operacionais.

 Critério de suficiência
 Identificar componentes adicionais e limitações das fontes.

 Estado
 Parcial

 Evidências
 E3 — Documentação de indexação [S2]

 Limitação
 Não foram encontradas medições para o hardware do usuário.

────────────────────────────────────────────────────────────────
 Enter ver evidência   Esc voltar
```

---

## 7.4 Inspecionar fontes

`F3` mostra uma lista:

```text
 Fontes                                                Esc voltar
────────────────────────────────────────────────────────────────

 > [S1] Documentação de busca lexical
        example.org/docs/search
        Extração: concluída · Evidências: 2

   [S2] Documentação de busca híbrida
        example.org/docs/hybrid
        Extração: concluída · Evidências: 1

   [S3] Comparação de desempenho
        example.org/blog/benchmark
        Extração: falhou

────────────────────────────────────────────────────────────────
 ↑↓ navegar   Enter detalhes   Esc voltar
```

Detalhes de uma fonte:

```text
 Fonte S1                                              Esc voltar
────────────────────────────────────────────────────────────────

 Título: Documentação de busca lexical
 URL: https://example.org/docs/search
 Acesso: 2026-04-20 14:03
 Publicação: desconhecida
 Extração: concluída
 Evidências: E1, E2

 Evidência E1
 “Trecho literal armazenado a partir da página.”

 Localizador: seção “Search”, trecho 3

────────────────────────────────────────────────────────────────
 ↑↓ navegar   Esc voltar
```

A TUI deve exibir a URL registrada, mas **não abrir automaticamente** páginas no navegador. Uma ação explícita para copiar ou abrir URLs pode ser considerada em uma versão posterior.

---

## 7.5 Inspecionar estado e orçamento

`F4` mostra dados objetivos:

```text
 Estado da pesquisa                                    Esc voltar
────────────────────────────────────────────────────────────────

 Status: pesquisando
 Duração: 02:14
 Modelo: llama3.1:8b

 Orçamento
 Buscas             5 / 12
 Páginas            4 / 18
 Chamadas ao LLM   12 / 40
 Rodadas            3 / 8

 Questões
 Sustentadas: 1
 Parciais: 1
 Abertas: 1

 Diretório
 ./pesquisa-formiga

────────────────────────────────────────────────────────────────
 Esc voltar
```

As contagens devem vir do estado do harness. A TUI não deve calcular um orçamento alternativo.

---

## 7.6 Interromper pesquisa

Durante uma pesquisa, `Esc` abre uma confirmação:

```text
 Interromper pesquisa?

 O Formiga tentará concluir a ação atual dentro do timeout,
 salvar o estado disponível e gerar um relatório parcial
 quando possível.

 [Continuar pesquisa]   [Interromper]
```

Regras:

1. A opção padrão é **Continuar pesquisa**.
2. Se o usuário confirmar, a TUI envia um pedido de cancelamento ao motor.
3. A interface mostra `Interrompendo...` até o motor confirmar o encerramento.
4. O motor salva o estado disponível e tenta gerar um relatório parcial apenas se isso for compatível com o orçamento e o estado da execução.
5. A TUI informa claramente se um relatório foi ou não gerado.
6. O estado visual final é `interrompida`; não deve ser apresentado como pesquisa suficiente.

**Dependência técnica:** o MVP precisa expor cancelamento cooperativo para que esse comportamento seja implementado. A TUI não deve simular uma interrupção enquanto o trabalho continua em segundo plano.

---

## 7.7 Ler o relatório

`F5` abre uma visualização somente leitura de `report.md`:

```text
 Relatório                                             Esc voltar
────────────────────────────────────────────────────────────────

 # Pesquisa: busca lexical e busca híbrida

 ## Resposta

 ...

────────────────────────────────────────────────────────────────
 ↑↓ rolar   PgUp/PgDn página   Esc voltar
```

Requisitos:

- suportar rolagem;
- renderizar o Markdown de forma simples, sem exigir recursos gráficos;
- preservar texto e referências;
- mostrar o caminho do arquivo;
- se o arquivo ainda não existir, informar que o relatório está indisponível.

A TUI não precisa permitir edição do relatório.

---

## 8. Estados e transições

```text
INICIAL
  │
  ├── pergunta enviada ──→ PREPARANDO
  │                            │
  │                            ├── configuração válida ──→ PESQUISANDO
  │                            └── erro ────────────────→ ERRO
  │
PESQUISANDO
  ├── conclusão ──────────→ SUFICIENTE | PARCIAL | BLOQUEADA
  ├── cancelar ───────────→ INTERROMPENDO ──→ INTERROMPIDA
  └── falha ──────────────→ ERRO

SUFICIENTE | PARCIAL | BLOQUEADA | INTERROMPIDA | ERRO
  └── nova pesquisa ──────→ INICIAL
```

Abrir questões, fontes ou relatório não altera o estado da pesquisa; apenas muda a visualização.

---

## 9. Tratamento de erros

Os erros devem ser curtos e indicar uma ação possível.

### Ollama indisponível

```text
 Não foi possível conectar ao Ollama.

 Endpoint: http://localhost:11434
 Verifique se o servidor está em execução e tente novamente.
```

### Modelo indisponível

```text
 O modelo configurado não está disponível no Ollama.

 Modelo: llama3.1:8b
 Verifique o nome do modelo e sua instalação.
```

### SearXNG indisponível

```text
 Não foi possível consultar o SearXNG.

 A pesquisa pode continuar apenas se o motor tiver fontes
 disponíveis; caso contrário, será encerrada como bloqueada.
```

A interface não deve prometer continuação se o motor não tiver suporte para isso.

### Falha durante a pesquisa

```text
 A pesquisa foi encerrada por uma falha operacional.

 Estado salvo: ./pesquisa-formiga/state.json
 Relatório parcial: não disponível

 Consulte events.jsonl para detalhes.
```

Não exibir stack traces na tela principal. Detalhes técnicos podem ser registrados nos eventos, sem credenciais.

---

## 10. Aparência

### 10.1 Cores

Paleta discreta:

| Elemento | Estilo sugerido |
|---|---|
| Nome do Formiga | negrito |
| Texto principal | cor padrão do terminal |
| Metadados | discreto |
| Pesquisa em andamento | azul ou ciano |
| Sucesso | verde |
| Parcial ou conflito | amarelo |
| Erro ou bloqueio | vermelho |
| Seleção do menu | inversão ou destaque |

As cores são sugestões, não requisito funcional. Se `NO_COLOR` estiver definido, usar apenas texto, símbolos e contraste do terminal.

### 10.2 Animação

No máximo um indicador simples durante operações longas:

```text
 ⠋ Lendo fonte S2...
```

A animação:

- pode ser desativada;
- não substitui o texto do estado;
- deve parar quando a operação termina;
- não deve impedir leitura ou navegação.

### 10.3 Largura e altura

- Alvo principal: terminal com pelo menos **80 colunas × 24 linhas**.
- Em tamanhos menores, reduzir textos e ocultar atalhos secundários.
- Abaixo de **40 colunas ou 12 linhas**, exibir aviso de tamanho insuficiente, preservando a pesquisa em andamento.
- Ao redimensionar, recalcular layout sem reiniciar a pesquisa.

---

## 11. Arquitetura

```text
┌────────────────────────────────────────────┐
│ TUI                                        │
│                                            │
│ Tela principal                             │
│ Menu e entrada                             │
│ Visualizações de questões, fontes e estado │
│ Leitor de relatório                        │
└─────────────────────┬──────────────────────┘
                      │
                 comandos / eventos
                      │
┌─────────────────────▼──────────────────────┐
│ Serviço de pesquisa                        │
│                                            │
│ start(question, config)                    │
│ request_cancel()                           │
│ get_state()                                │
│ subscribe_events()                         │
└─────────────────────┬──────────────────────┘
                      │
┌─────────────────────▼──────────────────────┐
│ Motor Formiga existente                    │
│                                            │
│ Orquestrador · orçamento · busca · LLM      │
│ Evidências · persistência · relatório      │
└────────────────────────────────────────────┘
```

### Regras de separação

- A TUI **não** decide se uma questão está sustentada.
- A TUI **não** altera evidências ou estados diretamente.
- A TUI **não** chama o LLM ou o SearXNG por conta própria.
- A CLI e a TUI usam os mesmos schemas, limites e mecanismos de persistência.
- Eventos recebidos pela TUI devem representar ações ou mudanças efetivamente registradas pelo motor.
- A interface deve permanecer responsiva durante chamadas de rede e ao modelo.

### Integração assíncrona

A implementação deve usar um mecanismo adequado de tarefas em segundo plano ou processo separado, com comunicação de eventos segura. A escolha depende da implementação do motor:

- não bloquear o loop da interface;
- não atualizar componentes de UI diretamente de threads não autorizadas pela biblioteca;
- tratar cancelamento como solicitação cooperativa;
- garantir que falhas do worker sejam comunicadas à interface.

---

## 12. Tecnologia sugerida

**Sugestão inicial:** Python com [Textual](https://textual.textualize.io/).

Motivos:

- suporte a teclado e redimensionamento;
- componentes básicos de entrada, listas e rolagem;
- suporte a testes de interface;
- permite uma aparência discreta sem construir um framework de TUI do zero.

Textual é uma proposta, não um requisito absoluto. Antes da implementação, validar que a biblioteca escolhida permite o fluxo de eventos e o comportamento de terminal desejados.

A TUI deve usar poucos componentes e evitar criar uma aplicação visualmente pesada apenas porque a biblioteca permite.

### Estrutura sugerida

```text
src/formiga/
├── tui/
│   ├── app.py          # aplicação e atalhos globais
│   ├── screens.py      # telas de detalhes
│   ├── widgets.py      # barra de menu, entrada e atividade
│   └── controller.py   # ponte com o serviço de pesquisa
├── service.py          # interface compartilhada de execução
└── ...
```

---

## 13. Comandos e configuração

### Inicialização

```bash
formiga tui
```

### Com pergunta pré-preenchida

```bash
formiga tui "Compare busca lexical e busca híbrida"
```

### Com diretório de saída e modelo

```bash
formiga tui \
  --output-dir ./pesquisas \
  --model llama3.1:8b
```

A TUI deve respeitar a mesma precedência de configuração da CLI:

1. argumentos;
2. variáveis de ambiente;
3. padrões.

### Diretórios de saída

Para evitar sobrescrita, cada pesquisa iniciada pela TUI cria um subdiretório exclusivo dentro de `--output-dir`, por exemplo:

```text
pesquisas/
└── 2026-04-20_140200_a1b2/
    ├── report.md
    ├── state.json
    └── events.jsonl
```

O sufixo deve evitar colisões. O caminho final deve ser exibido na interface antes do início.

---

## 14. Critérios de aceite

### Interface

- [ ] `formiga tui` abre a tela inicial.
- [ ] Uma pergunta pode ser digitada e enviada.
- [ ] Uma pergunta passada por argumento aparece para revisão.
- [ ] A barra de menu muda conforme o estado.
- [ ] `Ctrl+P` abre o menu; `Esc` fecha.
- [ ] As telas de questões, fontes, estado e relatório podem ser abertas e fechadas.
- [ ] A interface funciona sem cores.
- [ ] Redimensionar o terminal não interrompe a pesquisa.

### Pesquisa

- [ ] A TUI usa o mesmo motor e orçamento da CLI.
- [ ] O usuário acompanha eventos reais da execução.
- [ ] Não há duas pesquisas simultâneas na mesma TUI.
- [ ] O orçamento exibido corresponde ao estado do harness.
- [ ] O status final corresponde ao resultado real.
- [ ] Cancelamento só é confirmado após o motor parar.
- [ ] Uma pesquisa interrompida não é mostrada como concluída com sucesso.
- [ ] A interface informa quando não foi possível gerar relatório parcial.

### Segurança e dados

- [ ] A TUI avisa que consultas serão enviadas ao provedor configurado.
- [ ] URLs não são abertas automaticamente.
- [ ] Credenciais não aparecem na tela nem nos eventos.
- [ ] Uma nova pesquisa não sobrescreve resultados anteriores.
- [ ] A TUI não apresenta texto de fontes como instruções do sistema.

### Testes

- [ ] Testes de navegação usam um motor falso, sem rede e sem LLM real.
- [ ] Testes cobrem pesquisa concluída, parcial, bloqueada, erro e cancelamento.
- [ ] Testes verificam menu contextual, entrada, redimensionamento e estados.
- [ ] Há um smoke test manual documentado com Ollama e SearXNG.

---

## 15. Ordem sugerida de implementação

1. **Serviço compartilhado:** expor início, estado, eventos e cancelamento cooperativo no motor.
2. **Tela principal:** cabeçalho, atividade, menu e entrada.
3. **Pesquisa em segundo plano:** manter a interface responsiva.
4. **Visualizações:** questões, fontes, estado e relatório.
5. **Cancelamento e erros:** confirmação, persistência e estado final.
6. **Acessibilidade e terminais pequenos:** sem cor, alternativas de teclado e redimensionamento.
7. **Testes e documentação:** fixtures, testes de TUI e smoke test.

### Regra de escopo

A primeira versão deve ser considerada completa quando permitir **iniciar, acompanhar, inspecionar e interromper uma pesquisa**. Recursos adicionais só entram se resolverem uma necessidade observada no uso.