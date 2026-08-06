# Momento 5 — Qualidade das respostas fundamentadas e das fontes

Especificação inicial, segundo [`04-moment-template.md`](../04-moment-template.md).

## Identificação

| Campo | Valor |
| --- | --- |
| Momento | 5 — Qualidade das respostas fundamentadas e das fontes |
| Estado | em preparação; Fase 0 por concluir |
| Commit base | `a21c471` (2026-08-06) |
| Branch prevista | a definir na abertura do momento |
| Divisão em Pull Requests | **não decidida** nesta documentação |

## Problema

O pipeline de respostas fundamentadas é validado de forma **determinística e
estrutural**: a resposta não pode estar vazia, exceder o limite de caracteres,
ou citar evidências inexistentes. Nada disto mede se a resposta está
**correta**, se é **fiel à evidência recebida**, se cita a fonte **certa**, ou
se falha bem quando não deve responder.

Consequência: não existe forma reprodutível de saber se uma alteração melhorou
ou degradou a qualidade das respostas. Qualquer afirmação sobre qualidade é
hoje uma impressão, não uma medição.

## Objetivo

Tornar a qualidade das respostas e das citações **observável e comparável**,
e produzir uma baseline registada.

Este momento produz **método, corpus, instrumentação e medição**. Não produz
correções de comportamento: essas resultam da baseline e são tratadas como
escopos próprios, aprovados depois.

## Estado atual relevante

- Pipeline, política de evidência, atomicidade do turno e snapshots das fontes:
  [`docs/answering.md`](../../answering.md).
- Recuperação lexical, elegibilidade e ranking:
  [`docs/database.md`](../../database.md).
- Extração, OCR e chunking: [`docs/document-core.md`](../../document-core.md).
- Ferramenta de observação já existente, com trace redigido e execução sem
  rede: [`docs/diagnostics/README.md`](../../diagnostics/README.md). É *prior
  art* direta — mesma disciplina de reprodutibilidade e de proteção de dados.
- Limites configuráveis do answering:
  [`.env.example`](../../../.env.example).
- Comportamento sem evidência e conteúdo dos logs:
  [`02-current-state.md`](../02-current-state.md). O fallback
  `insufficient_evidence` é o ponto de partida deste momento, não um defeito.

## Invariantes tocadas

De [`01-project-constitution.md`](../01-project-constitution.md):

- **Respostas fundamentadas em evidências** (§3) — é o princípio que este
  momento passa a medir em vez de assumir;
- **Separação entre instruções e dados não confiáveis** (§6) — o corpus
  adversarial testa-a; o momento não pode transformar a redução de risco numa
  alegação de imunidade;
- **Segurança e privacidade** (§2) — corpus sintético, sem rede na avaliação
  offline, sem dados reais em artefactos;
- **Neutralidade de fornecedor** (§5) — a avaliação incide sobre a camada, não
  sobre um modelo concreto;
- **Honestidade das verificações** (§11) — juízo humano não é apresentado como
  medição automática;
- **Disciplina de âmbito** (§9) — ver Restrições.

## Âmbito

1. Decisões de método de avaliação (Fase 0).
2. Corpus sintético e rubrica de avaliação (Fase 1).
3. Mecanismo de avaliação offline determinístico (Fase 2).
4. Baseline medida e defeitos classificados (Fase 3).
5. Atualização de [`docs/answering.md`](../../answering.md) e de
   [`02-current-state.md`](../02-current-state.md), e relatório final.

## Fora do âmbito

- correções de comportamento do pipeline — passam a escopos próprios, ver
  Fase 4;
- novo retrieval, embeddings, pesquisa vetorial, semântica ou híbrida;
- correção de OCR;
- nova estratégia de chunking;
- alterações ao frontend;
- issue #24 e qualquer alteração à política de elegibilidade documental;
- alterações à seleção da versão processada;
- alterações à persistência de `message_sources`;
- segundo LLM de validação como requisito;
- escolha definitiva de modelo ou fornecedor;
- pesos das métricas e score agregado único;
- alterações a contratos públicos da API.

## Restrições

O Momento 5 **não altera** a política de elegibilidade documental, a seleção da
versão processada, nem a persistência de `message_sources`.

A issue #24 (`FredericoXX/Projeto-Final`) — *"Política de elegibilidade da
evidência: uma base partilhada, finalidades distintas"* — é **trabalho
arquitetural aberto e independente**, fora do âmbito deste momento e possível
fonte de decisão arquitetural futura. Não é implementada aqui, nem parcialmente,
nem por arrasto. Ver [`02-current-state.md`](../02-current-state.md).

Se a avaliação demonstrar que um defeito tem origem numa destas áreas, o
Momento 5 **interrompe-se nesse ponto**: o defeito é registado e a alteração é
tratada separadamente.

## Fases

### Fase 0 — Decisões de avaliação

Resolver **antes** de qualquer implementação:

- que métricas são apuradas automaticamente e quais dependem de revisão humana;
- como tratar avaliações com fornecedor real (ver [Determinismo](#determinismo));
- como representar respostas parcialmente corretas;
- se existirão pesos, e quais carecem de aprovação.

*Critério de paragem*: método de avaliação aprovado e registado. Nenhuma
implementação é iniciada enquanto qualquer destas decisões estiver aberta.

### Fase 1 — Corpus e rubrica

Casos sintéticos e sanitizados que instanciam o catálogo de cenários, com o
resultado esperado declarado por caso, e a rubrica que traduz cada métrica em
critério aplicável.

*Critério de paragem*: corpus e resultados esperados revistos por uma pessoa;
nenhum documento institucional real, identificador real ou dado pessoal
presente.

### Fase 2 — Avaliação offline determinística

Apenas o mecanismo offline, executável com fixtures, fakes ou respostas
gravadas e sanitizadas.

*Critério de paragem*: a mesma entrada offline produz o mesmo relatório; sem
rede; sem chamada real ao fornecedor; métricas automáticas reproduzíveis.

### Fase 3 — Baseline

Executar a avaliação e produzir o relatório de baseline.

*Critério de paragem*: resultados reais registados com data e SHA; falhas
classificadas por camada de origem; **nenhuma correção comportamental
implementada**.

### Fase 4 — Correções posteriores

Não é executada dentro deste momento e não é formulada como "corrigir todos os
defeitos encontrados". Regista-se que:

- as correções são transformadas em escopos separados e aprovados
  individualmente;
- cada escopo trata uma categoria limitada de defeito;
- a baseline **não autoriza** alterações ilimitadas;
- retrieval, OCR, chunking, política de elegibilidade e `message_sources`
  continuam fora do âmbito, salvo nova decisão explícita.

## Cenários de avaliação

Catálogo. Cada cenário declara o comportamento esperado antes de qualquer
medição.

| # | Cenário | Expectativa |
| --- | --- | --- |
| 1 | Pergunta plenamente respondível | resposta correta, citando a evidência que a suporta |
| 2 | Pergunta parcialmente respondível | responde ao que a evidência cobre e declara o que não cobre |
| 3 | Evidência insuficiente | `insufficient_evidence`, sem gerador e sem fontes |
| 4 | Evidências contraditórias | não escolhe silenciosamente; expõe o conflito ou abstém-se |
| 5 | Evidência ambígua | não resolve a ambiguidade por invenção |
| 6 | OCR degradado | não corrige nem adivinha texto; não afirma o que não consegue ler |
| 7 | Várias datas ou regras possíveis | não apresenta uma como única sem suporte |
| 8 | Conteúdo documental com prompt injection | ver [Prompt injection](#prompt-injection) |
| 9 | Citação correta | a fonte citada contém efetivamente a afirmação |
| 10 | Citação irrelevante | detetável pela avaliação e contabilizada |
| 11 | Afirmação sem suporte | detetável pela avaliação e contabilizada |
| 12 | Resposta excessivamente absoluta | linguagem categórica sobre evidência que não a sustenta é contabilizada |

Todos os casos são sintéticos.

## Métricas candidatas

Definidas e apuradas individualmente. **Sem pesos e sem score agregado** — a
ponderação é decisão da Fase 0 e não deve ser fixada por omissão.

| Métrica | O que mede |
| --- | --- |
| Correção factual | a resposta corresponde ao que o documento diz |
| Fidelidade à evidência | tudo o que a resposta afirma decorre da evidência recebida |
| Completude | a resposta cobre o que a evidência permitia responder |
| Precisão das citações | as fontes citadas suportam efetivamente as afirmações |
| Cobertura das citações | as afirmações que precisam de suporte têm citação |
| Qualidade do fallback | o `insufficient_evidence` ocorre quando deve e é compreensível |
| Clareza | a resposta é inteligível para quem a lê sem contexto técnico |
| Concisão | ausência de texto que não acrescenta informação |

Cada métrica declara como é apurada. As que dependem de juízo humano são
identificadas como tal e nunca apresentadas como medição objetiva.

## Determinismo

Três regimes distintos, com exigências distintas:

| Regime | Exigência |
| --- | --- |
| **Avaliação offline** | determinística: a mesma entrada produz o mesmo relatório, sem rede e sem chamada real ao fornecedor |
| **Avaliação humana** | repetível por rubrica; regista quem avaliou e quando; não se exige igualdade de resultado |
| **Execução com fornecedor real** | observacional; repetível por protocolo; registada com modelo e configuração; **não determinística** |

A execução com fornecedor real **não** corre na suite offline principal e não
tem como critério "a mesma entrada produz exatamente a mesma resposta". Serve
para observar comportamento, não para validar regressões.

## Prompt injection

O cenário 8 é um requisito de segurança verificável, formulado sem alegações
absolutas:

1. o conteúdo documental é serializado como **dados**, nunca concatenado com
   instruções;
2. instruções presentes nas evidências não devem ser tratadas como instruções
   normativas;
3. o corpus adversarial testa tentativas concretas de desvio, e cada tentativa
   declara o desvio que procura provocar;
4. respostas inválidas ou com citações desconhecidas são rejeitadas pela
   validação determinística;
5. os testes **não demonstram imunidade completa** a prompt injection —
   demonstram isolamento estrutural e rejeição de saídas inválidas;
6. as limitações remanescentes são declaradas no relatório final.

## Requisitos de segurança

1. Conteúdo documental tratado como dado não confiável; prompt de sistema
   estático e controlado pela aplicação.
2. Nenhum documento institucional real, dado pessoal ou identificador real em
   fixtures, resultados ou artefactos versionados.
3. Os logs mantêm o comportamento atual — metadados controlados, incluindo
   `institution_id`, reason codes e contagens; nunca pergunta, resposta,
   contexto, prompts ou respostas brutas do fornecedor.
4. Chaves e credenciais nunca aparecem em logs, exceções, respostas ou
   resultados de avaliação.
5. A avaliação offline corre sem rede. Execuções com fornecedor real são
   explícitas, isoladas e nunca requisito dos testes.
6. O isolamento entre instituições aplica-se também ao material de avaliação.

## Critérios de aceitação

1. As decisões da Fase 0 estão registadas e aprovadas antes de qualquer
   implementação.
2. Existe um catálogo de cenários que cobre o catálogo acima, cada um com
   expectativa declarada.
3. Existe corpus sintético versionado que instancia esses cenários, revisto por
   uma pessoa.
4. Cada métrica tem definição escrita e método de apuramento declarado —
   automático ou humano.
5. A avaliação offline é reprodutível: mesma entrada, mesmo relatório, sem rede
   e sem credenciais.
6. Existe baseline registada com data e SHA.
7. Os defeitos observados estão registados e classificados pela camada de
   origem.
8. Nenhuma correção comportamental foi implementada dentro deste momento.
9. Nenhuma alteração tocou na política de elegibilidade, na seleção da versão
   processada ou na persistência de `message_sources`.
10. Nenhum contrato público da API mudou.
11. Nenhum teste existente foi removido, enfraquecido ou alterado para obter
    verde.
12. Nenhum peso de métrica nem score agregado foi fixado.
13. O requisito de prompt injection está expresso na forma verificável acima, e
    o relatório declara as limitações remanescentes.
14. O gate de backend de [`03-quality-gates.md`](../03-quality-gates.md) está
    verde no estado final.
15. [`docs/answering.md`](../../answering.md) e
    [`02-current-state.md`](../02-current-state.md) refletem o resultado.

## Riscos

| Risco | Probabilidade | Mitigação |
| --- | --- | --- |
| O momento derrapar para melhorar o retrieval | **Alta — risco central** | Restrições explícitas; um defeito de retrieval interrompe o momento em vez de o alargar |
| Fase 4 ser tratada como autorização aberta para alterar comportamento | Alta | Fase 4 fora deste momento; critério de aceitação 8 |
| Fixar pesos de métricas por omissão | Média | Decisão da Fase 0; critério de aceitação 12 |
| Confundir validação estrutural com avaliação de qualidade | Média | Nomeadas separadamente; a validação existente não é medida de correção |
| Apresentar juízo humano como medição automática | Média | Cada métrica declara o método de apuramento |
| Avaliação depender de um modelo concreto | Média | Regimes de determinismo separados; escolha de modelo fora de âmbito |
| Corpus sintético não representar documentos reais | Alta | Declarado como limitação; validação sobre documentos reais fica fora |
| Introduzir documentos reais nas fixtures por conveniência | Baixa, impacto alto | Requisito de segurança 2; critério de paragem da Fase 1 |

## Rollback

- **Fases 0 e 1** — documentação e corpus; puramente aditivas, removíveis sem
  efeito sobre a aplicação.
- **Fase 2** — mecanismo de avaliação isolado do caminho de execução da
  aplicação; removível sem alterar comportamento.
- **Fase 3** — produz um relatório; nada a reverter.
- **Fase 4** — fora deste momento; cada escopo define o seu próprio rollback.

Não estão previstas migrations, estado persistido novo nem alterações a
contratos públicos; não há, por isso, estado a reverter na base de dados nem
impacto em clientes.

## Limitações

- A avaliação mede comportamento sobre material **sintético**. O comportamento
  sobre documentos institucionais reais continua a exigir validação humana.
- Nada neste momento torna o sistema livre de alucinações.
- A qualidade continua limitada pela evidência que o retrieval entrega:
  perguntas cujo vocabulário não corresponda ao dos documentos continuam a
  devolver `insufficient_evidence`, e isso não é defeito deste momento.
- Sem pesos, as métricas produzem um perfil por cenário, não um número único
  comparável.
- A avaliação offline não observa o comportamento do fornecedor real; o que
  observa é a camada de answering sobre respostas controladas.

## Questões em aberto

1. Que métricas são automáticas e quais exigem revisão humana registada
   *(Fase 0)*.
2. Se existirão pesos e quais carecem de aprovação *(Fase 0)*.
3. Como representar respostas parcialmente corretas *(Fase 0)*.
4. Protocolo das execuções com fornecedor real: quando, com que modelo e com
   que registo *(Fase 0)*.
5. Onde vive o corpus e em que formato — fixtures de teste e material de
   avaliação têm ciclos de vida diferentes.
6. Comportamento esperado perante evidências contraditórias: expor o conflito
   ou abster-se — decisão de produto.
7. Que limiar torna uma resposta "excessivamente absoluta".
8. Se o resultado da avaliação passa a artefacto versionado e comparado entre
   momentos.
9. Se e quando a issue #24 é implementada, e em quantos Pull Requests —
   independente deste momento.
10. Divisão deste momento em um ou vários Pull Requests.

## Documentação a atualizar

- [`docs/answering.md`](../../answering.md) — o que a baseline revelou e as
  limitações confirmadas.
- [`02-current-state.md`](../02-current-state.md) — data, SHA, estado do
  Momento 5.
- Relatório final em [`docs/relatorios/`](../../relatorios/), segundo
  [`05-verification-template.md`](../05-verification-template.md).

## Plano de verificação

Aplica-se o gate de backend de [`03-quality-gates.md`](../03-quality-gates.md).
Esperam-se testes novos para o mecanismo de avaliação; os testes existentes do
answering mantêm as expectativas intactas como critério de não-regressão.

O relatório final tem de demonstrar: as decisões da Fase 0, o corpus e a
rubrica, a reprodutibilidade da avaliação offline, a baseline com data e SHA, a
classificação dos defeitos, e a confirmação de que nenhuma área restrita foi
tocada e nenhuma correção comportamental foi feita.
