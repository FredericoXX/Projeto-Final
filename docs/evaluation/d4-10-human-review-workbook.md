# D4.10a — folha de revisão humana

**Este documento não é prova de revisão.** É o material para a fazer.
Enquanto as decisões abaixo não forem tomadas por uma pessoa e escritas
no conjunto de perguntas, o protocolo permanece `DRAFT` e a D4.10b está
bloqueada.

Nada aqui foi decidido por máquina. O que a máquina fez foi localizar
evidência, registar onde a localizou e — para a independência — listar as
perguntas históricas com mais palavras em comum. Semelhança de palavras
não é semelhança de intenção: duas formulações sem uma palavra comum
podem testar o mesmo requisito, e duas quase iguais podem testar factos
diferentes. Por isso a lista é um ponto de partida, não uma resposta.

Há prova concreta disso neste mesmo documento. Em `SC-N04`, as duas
perguntas históricas que a nota do conjunto já identifica como a
preocupação real — `DA036` e `DA037` — ficam em **sexto lugar e abaixo**
por palavras em comum, atrás de cinco perguntas menos aparentadas. O
parentesco que interessa (perguntar por datas de aulas de um ano que o
corpus não cobre) não está nas palavras. Por isso o que o registo já
assinalou aparece sempre, marcado com ⚑, à margem da ordenação.

## Como preencher

**Por cenário** — decidir o estado de independência face a Q001–Q014 e
DA001–DA049:

| Estado | Quando |
| --- | --- |
| `INDEPENDENT` | não testa o mesmo facto/intenção já medido |
| `RELATED_BUT_DISTINCT` | há relação temática, mas o facto testado é distinto — exige `historical_refs` e `rationale` |
| `EXCLUDE` | reutiliza material histórico de forma que compromete a independência — exige `historical_refs` e `rationale` |

Qualquer decisão final exige `annotator` com nome real. Um cenário
`EXCLUDE` tem de sair do conjunto — ele e todas as suas perguntas —
**antes** de qualquer embedding ou ranking.

**Por pergunta** — `CONFIRM`, `EDIT` ou `EXCLUDE`. Confirmar significa
pôr `review_status` e `validation_status` em `HUMAN_CONFIRMED` e assinar
com o nome real; os dois campos têm de concordar, e há guarda que recusa
se não concordarem.

Cenários a rever: **32**. Perguntas a rever: **50**.

## SC-A01 — escala_classificacao

- tipo: `exact_institutional_terms`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.12 | `DA025` | Qual e o contacto dos Servicos Academicos da Uni-CV? |
| 0.12 | `DA030` | Qual e o horario de funcionamento da biblioteca da Uni-CV? |
| 0.12 | `DA039` | Quantos valores preciso para entrar em Medicina na Uni-CV? |
| 0.12 | `DA040` | Como funciona o programa Erasmus na Uni-CV? |
| 0.12 | `DA041` | Como me candidato a uma bolsa Erasmus na Uni-CV? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX001 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Em que escala sao expressas as classificacoes na Uni-CV?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#333`
- justificação registada: Artigo sobre nota/classificacao: escala numerica de 0 a 20 valores.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX002 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> As notas vao de zero a quanto?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#333`
- justificação registada: Artigo sobre nota/classificacao: escala numerica de 0 a 20 valores.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A02 — nota_minima_aprovacao

- tipo: `exact_institutional_terms`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.20 | `DA038` | Qual e a nota minima de entrada no curso de Medicina da Uni-CV? |
| 0.20 | `DA046` | Quantos creditos ECTS vale cada unidade curricular? |
| 0.11 | `DA024` | Qual e o prazo para reclamar da nota de um exame? |
| 0.10 | `DA034` | Qual e a percentagem minima de presencas exigida nos seminarios? |
| 0.08 | `DA012` | Qual e o numero maximo de estudantes numa aula teorico-pratica? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX003 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e a nota minima para ser aprovado numa unidade curricular?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#335`, `P1-DOC-004#452`
- justificação registada: Aprovacao exige classificacao final igual ou superior a 10 valores.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX004 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> A partir de que classificacao se considera aprovado?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#335`, `P1-DOC-004#452`
- justificação registada: Aprovacao exige classificacao final igual ou superior a 10 valores.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A03 — provas_avaliacao_continua

- tipo: `semantic_reformulation`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.17 | `DA012` | Qual e o numero maximo de estudantes numa aula teorico-pratica? |
| 0.17 | `DA046` | Quantos creditos ECTS vale cada unidade curricular? |
| 0.11 | `DA049` | Qual e o meu numero de estudante? |
| 0.08 | `DA004` | Que desconto tenho se pagar a propina anual toda de uma vez? |
| 0.08 | `DA026` | Quanto custa por mes um quarto individual numa residencia da Uni-CV? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX005 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quantos momentos de avaliacao tem de haver por semestre numa unidade curricular?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#348`
- justificação registada: Minimo de duas provas por semestre; quatro nas unidades anuais.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX006 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Numa cadeira anual, qual e o numero minimo de provas de avaliacao?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#348`
- justificação registada: Minimo de duas provas por semestre; quatro nas unidades anuais.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A04 — propina_prestacoes

- tipo: `procedural`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-005`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.25 | `DA004` | Que desconto tenho se pagar a propina anual toda de uma vez? |
| 0.18 | `DA015` | Quando e a pausa de Natal no ano letivo 2025/2026? |
| 0.18 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |
| 0.17 | `DA012` | Qual e o numero maximo de estudantes numa aula teorico-pratica? |
| 0.17 | `DA037` | Qual foi a data de inicio do ano letivo 2024/2025? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX007 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Posso pagar a propina em prestacoes?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-005#72`
- justificação registada: Pagamento em prestacoes de igual montante, maximo de doze por ano letivo.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX008 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e o numero maximo de prestacoes da propina num ano letivo?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-005#72`
- justificação registada: Pagamento em prestacoes de igual montante, maximo de doze por ano letivo.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A05 — multa_prestacoes

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-005`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.18 | `DA004` | Que desconto tenho se pagar a propina anual toda de uma vez? |
| 0.17 | `DA011` | Quanto tempo se espera pelo docente antes de a aula nao ter lugar? |
| 0.11 | `DA007` | Que juros se pagam por atraso no pagamento do alojamento? |
| 0.11 | `DA044` | O seguro escolar esta incluido na propina? |
| 0.10 | `DA005` | A liquidacao antecipada da propina da direito a alguma reducao? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX009 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Que multa se paga por prestacoes de propina em atraso?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-005#78`
- justificação registada: Multa de 10% do valor das prestacoes em divida.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX010 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e a penalizacao por nao pagar uma prestacao da propina a tempo?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-005#78`
- justificação registada: Multa de 10% do valor das prestacoes em divida.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A06 — reducao_protocolo

- tipo: `semantic_reformulation`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-005`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.18 | `DA005` | A liquidacao antecipada da propina da direito a alguma reducao? |
| 0.10 | `DA025` | Qual e o contacto dos Servicos Academicos da Uni-CV? |
| 0.10 | `DA030` | Qual e o horario de funcionamento da biblioteca da Uni-CV? |
| 0.10 | `DA039` | Quantos valores preciso para entrar em Medicina na Uni-CV? |
| 0.10 | `DA040` | Como funciona o programa Erasmus na Uni-CV? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX011 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Que reducao de propina existe para candidatos abrangidos por protocolos com a Uni-CV?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-005#224`
- justificação registada: Reducao de propina ate 50% ao abrigo de protocolos institucionais.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A07 — propina_tfc

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-005`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.11 | `DA042` | Ha estacionamento gratuito no campus para estudantes? |
| 0.10 | `DA028` | Qual e o valor em escudos do premio de merito da Uni-CV? |
| 0.10 | `DA044` | O seguro escolar esta incluido na propina? |
| 0.09 | `DA005` | A liquidacao antecipada da propina da direito a alguma reducao? |
| 0.09 | `DA027` | Qual e o valor da renda mensal de um quarto duplo na residencia? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX012 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quanto pago de propina se so me falta o trabalho de fim de curso?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-005#351`
- justificação registada: Propina para quem so tem o trabalho de fim de curso por realizar: 27.000$00.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX013 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e o valor da propina para estudantes a quem falta apenas o TFC?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-005#351`
- justificação registada: Propina para quem so tem o trabalho de fim de curso por realizar: 27.000$00.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A08 — epoca_especial_inscricao_2526

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-002`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.40 | `DA015` | Quando e a pausa de Natal no ano letivo 2025/2026? |
| 0.40 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |
| 0.36 | `Q012` | Quando e a cerimonia de entrega dos diplomas no ano letivo 2025/2026? |
| 0.33 | `DA013` | Quando comecam as aulas do segundo semestre do ano letivo 2025/2026? |
| 0.33 | `Q004` | Quando e publicada a lista de inscritos em UCT no ano letivo 2025/2026? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX014 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quando me inscrevo nos exames da epoca especial em 2025/2026?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-002#28`
- justificação registada: Inscricao em exames da epoca especial: 03 a 09 de novembro de 2025.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX015 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e o prazo de inscricao para a epoca especial do ano letivo 2025/2026?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-002#28`
- justificação registada: Inscricao em exames da epoca especial: 03 a 09 de novembro de 2025.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A09 — epoca_especial_realizacao_2526

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-002`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.18 | `DA015` | Quando e a pausa de Natal no ano letivo 2025/2026? |
| 0.18 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |
| 0.17 | `DA014` | Qual e a data do primeiro dia de aulas do 2.o semestre em 2025/2026? |
| 0.17 | `Q012` | Quando e a cerimonia de entrega dos diplomas no ano letivo 2025/2026? |
| 0.15 | `DA013` | Quando comecam as aulas do segundo semestre do ano letivo 2025/2026? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX016 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Em que datas se realizam os exames da epoca especial em 2025/2026?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-002#30`
- justificação registada: Realizacao dos exames da epoca especial: 01 a 12 de dezembro de 2025.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A10 — regime_avaliacao_2526

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-002`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.36 | `DA015` | Quando e a pausa de Natal no ano letivo 2025/2026? |
| 0.36 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |
| 0.33 | `DA037` | Qual foi a data de inicio do ano letivo 2024/2025? |
| 0.33 | `Q012` | Quando e a cerimonia de entrega dos diplomas no ano letivo 2025/2026? |
| 0.31 | `DA013` | Quando comecam as aulas do segundo semestre do ano letivo 2025/2026? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX017 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Ate quando posso mudar de regime de avaliacao em 2025/2026?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-002#21`
- justificação registada: Mudanca do regime de avaliacao: ate 7 de novembro de 2025.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX018 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e a data limite para alterar o regime de avaliacao no ano letivo 2025/2026?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-002#21`
- justificação registada: Mudanca do regime de avaliacao: ate 7 de novembro de 2025.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A11 — reingresso_prazos_2627

- tipo: `procedural`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-002`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.30 | `DA015` | Quando e a pausa de Natal no ano letivo 2025/2026? |
| 0.30 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |
| 0.27 | `Q012` | Quando e a cerimonia de entrega dos diplomas no ano letivo 2025/2026? |
| 0.25 | `DA013` | Quando comecam as aulas do segundo semestre do ano letivo 2025/2026? |
| 0.25 | `Q004` | Quando e publicada a lista de inscritos em UCT no ano letivo 2025/2026? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX019 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quando entrego o pedido de reingresso para o ano letivo 2026/2027?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-002#87`
- justificação registada: 1a fase de entrega dos pedidos de reingresso e mudanca de curso: 02 maio a 30 junho 2026.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX020 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e a primeira fase de entrega dos pedidos de mudanca de curso?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-002#87`
- justificação registada: 1a fase de entrega dos pedidos de reingresso e mudanca de curso: 02 maio a 30 junho 2026.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A12 — transferencias_2fase_2627

- tipo: `procedural`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-002`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.09 | `DA015` | Quando e a pausa de Natal no ano letivo 2025/2026? |
| 0.09 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |
| 0.08 | `DA014` | Qual e a data do primeiro dia de aulas do 2.o semestre em 2025/2026? |
| 0.08 | `Q012` | Quando e a cerimonia de entrega dos diplomas no ano letivo 2025/2026? |
| 0.08 | `DA013` | Quando comecam as aulas do segundo semestre do ano letivo 2025/2026? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX021 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e a segunda fase para pedidos de transferencia em 2026/2027?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-002#88`
- justificação registada: 2a fase de transferencias e mudancas horizontais: 01 a 30 de setembro de 2026.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A13 — segunda_chamada_2324

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-003`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.36 | `Q011` | Quando foi o primeiro dia de aulas do segundo semestre em 2023/2024? |
| 0.25 | `DA036` | Quando comecaram as aulas do primeiro semestre do ano letivo 2024/2025? |
| 0.18 | `DA037` | Qual foi a data de inicio do ano letivo 2024/2025? |
| 0.18 | `Q014` | Ate quando posso pedir a anulacao da matricula do primeiro semestre? |
| 0.17 | `DA014` | Qual e a data do primeiro dia de aulas do 2.o semestre em 2025/2026? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX022 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quando foram os exames de 2a chamada do primeiro semestre em 2023/2024?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-003#30`, `P1-DOC-003#31`
- justificação registada: 2023/2024: inscricao 05 a 16 fev 2024; realizacao 19 fev a 02 mar 2024.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX023 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual foi o prazo de inscricao para a 2a chamada em fevereiro de 2024?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-003#30`, `P1-DOC-003#31`
- justificação registada: 2023/2024: inscricao 05 a 16 fev 2024; realizacao 19 fev a 02 mar 2024.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A14 — melhoria_notas_2324

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-003`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.23 | `Q011` | Quando foi o primeiro dia de aulas do segundo semestre em 2023/2024? |
| 0.15 | `DA037` | Qual foi a data de inicio do ano letivo 2024/2025? |
| 0.09 | `DA024` | Qual e o prazo para reclamar da nota de um exame? |
| 0.08 | `DA038` | Qual e a nota minima de entrada no curso de Medicina da Uni-CV? |
| 0.07 | `DA036` | Quando comecaram as aulas do primeiro semestre do ano letivo 2024/2025? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX024 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quando foi possivel inscrever-se em melhoria de nota no final de 2023/2024?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-003#73`
- justificação registada: Inscricao em exames de melhoria de notas e recuperacao: 1 a 14 de agosto de 2024.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A15 — regime_avaliacao_2324

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-003`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.23 | `DA037` | Qual foi a data de inicio do ano letivo 2024/2025? |
| 0.21 | `DA036` | Quando comecaram as aulas do primeiro semestre do ano letivo 2024/2025? |
| 0.19 | `Q002` | Ate quando posso pedir a anulacao da matricula do primeiro semestre do ano letivo 2025/2026? |
| 0.15 | `DA015` | Quando e a pausa de Natal no ano letivo 2025/2026? |
| 0.15 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX025 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Ate quando se podia mudar o regime de avaliacao no ano letivo 2023/2024?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-003#23`
- justificação registada: Mudanca do regime de avaliacao em 2023/2024: ate 3 de novembro de 2023.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A16 — cartao_estudante_emissao

- tipo: `procedural`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.17 | `DA049` | Qual e o meu numero de estudante? |
| 0.12 | `DA025` | Qual e o contacto dos Servicos Academicos da Uni-CV? |
| 0.12 | `DA029` | Quanto dinheiro recebe um estudante premiado por merito? |
| 0.12 | `DA030` | Qual e o horario de funcionamento da biblioteca da Uni-CV? |
| 0.12 | `DA039` | Quantos valores preciso para entrar em Medicina na Uni-CV? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX026 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Que servico emite o cartao de estudante?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#284`
- justificação registada: A expedicao do cartao de estudante cabe a Direccao dos Servicos Academicos.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX027 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quem trata da emissao do cartao de estudante na Uni-CV?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#284`
- justificação registada: A expedicao do cartao de estudante cabe a Direccao dos Servicos Academicos.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A17 — documentos_emitidos

- tipo: `strong_lexical_cue`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.29 | `DA025` | Qual e o contacto dos Servicos Academicos da Uni-CV? |
| 0.14 | `DA016` | Em que dia se comemora o Dia da Universidade? |
| 0.12 | `DA031` | A que horas abre a biblioteca da universidade? |
| 0.12 | `DA032` | Quanto custa uma refeicao na cantina da universidade? |
| 0.11 | `Q008` | Com que antecedencia tenho de pedir a prorrogacao do alojamento? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX028 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Que documentos academicos posso pedir aos servicos da universidade?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#568`
- justificação registada: Lista de documentos emitidos: atestados e certidoes, cartao, declaracao de frequencia, historico escolar, certificado de conclusao.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A18 — limites_horario_plano

- tipo: `semantic_interpretation`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.20 | `DA021` | Em quantas unidades curriculares posso fazer exame de recurso? |
| 0.12 | `DA049` | Qual e o meu numero de estudante? |
| 0.10 | `DA029` | Quanto dinheiro recebe um estudante premiado por merito? |
| 0.09 | `DA031` | A que horas abre a biblioteca da universidade? |
| 0.09 | `Q005` | A presenca nas aulas praticas e obrigatoria? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX029 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quantas horas seguidas de aulas teoricas da mesma area posso ter?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#310`
- justificação registada: Plano com nao mais de seis unidades curriculares; nao mais de quatro horas letivas seguidas nas aulas teoricas da mesma area cientifica.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX030 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Ha um limite de unidades curriculares no plano proposto ao estudante?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#310`
- justificação registada: Plano com nao mais de seis unidades curriculares; nao mais de quatro horas letivas seguidas nas aulas teoricas da mesma area cientifica.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A19 — creditacao_uc

- tipo: `procedural`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.22 | `DA046` | Quantos creditos ECTS vale cada unidade curricular? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX031 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Que orgao decide a creditacao de uma unidade curricular?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#304`
- justificação registada: A coordenacao do curso propoe ao Conselho Cientifico a creditacao ou nao da unidade curricular.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A20 — cursos_ferias

- tipo: `semantic_interpretation`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.22 | `DA045` | A universidade tem seguro de acidentes pessoais para os estudantes? |
| 0.14 | `DA016` | Em que dia se comemora o Dia da Universidade? |
| 0.12 | `DA031` | A que horas abre a biblioteca da universidade? |
| 0.12 | `DA032` | Quanto custa uma refeicao na cantina da universidade? |
| 0.09 | `DA003` | Com que antecedencia tem de ser confirmada ao Gabinete do Reitor a cerimonia academica? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX032 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> A universidade tem cursos no periodo de ferias?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#534`, `P1-DOC-004#544`
- justificação registada: Existe um capitulo sobre cursos de ferias e o numero de vagas nesses periodos e fixado internamente.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A21 — comissao_residentes

- tipo: `exact_institutional_terms`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-007`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

_Nenhuma pergunta histórica com palavras de conteúdo em comum. Isto **não** é prova de independência._

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX033 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Os residentes podem eleger representantes?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-007#307`, `P1-DOC-007#369`
- justificação registada: Direito de eleger e ser eleito para a Comissao de Residentes.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX034 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> O que e a Comissao de Residentes?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-007#307`, `P1-DOC-007#369`
- justificação registada: Direito de eleger e ser eleito para a Comissao de Residentes.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A22 — visitas_quinzenais

- tipo: `numeric_fee_deadline`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-007`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.11 | `DA009` | Qual e o horario de recolha nas residencias universitarias? |
| 0.10 | `DA023` | Quais sao as condicoes para me candidatar a um premio de merito? |
| 0.10 | `DA047` | Quantos ECTS sao precisos para concluir a licenciatura? |
| 0.08 | `DA002` | Na outorga de grau, quantos acompanhantes sao permitidos a cada finalista? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX035 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Com que frequencia sao feitas as visitas de inspecao as residencias?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-007#111`
- justificação registada: Realizar visitas periodicas quinzenais as Residencias Estudantis para inspecao.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A23 — responsabilidade_quarto_partilhado

- tipo: `semantic_interpretation`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-007`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.09 | `DA027` | Qual e o valor da renda mensal de um quarto duplo na residencia? |
| 0.08 | `DA008` | A que horas tenho de deixar o quarto no dia em que termina o alojamento? |
| 0.08 | `DA017` | Quanto custa a matricula pela primeira vez num curso de graduacao? |
| 0.08 | `DA026` | Quanto custa por mes um quarto individual numa residencia da Uni-CV? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX036 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Se houver um estrago num quarto partilhado, quem paga?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-007#209`
- justificação registada: Nos quartos partilhados todos os ocupantes respondem pelos danos.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A24 — proibicoes_residencia

- tipo: `strong_lexical_cue`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-007`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.33 | `Q009` | Como me candidato a uma residencia universitaria? |
| 0.22 | `DA020` | Tenho de pagar caucao para entrar na residencia universitaria? |
| 0.18 | `DA006` | Ate que dia do mes tenho de pagar a mensalidade da residencia universitaria? |
| 0.12 | `DA033` | Qual e o preco do almoco na cantina estudantil? |
| 0.10 | `DA027` | Qual e o valor da renda mensal de um quarto duplo na residencia? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX037 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Posso ter um animal de estimacao na residencia universitaria?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-007#337`
- justificação registada: Proibicoes: animais domesticos, jogos de azar, fumar, consumir bebidas.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX038 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> E permitido fumar dentro da residencia estudantil?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-007#337`
- justificação registada: Proibicoes: animais domesticos, jogos de azar, fumar, consumir bebidas.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A25 — recurso_juri_prazo

- tipo: `procedural`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-004`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.11 | `DA024` | Qual e o prazo para reclamar da nota de um exame? |
| 0.10 | `Q008` | Com que antecedencia tenho de pedir a prorrogacao do alojamento? |
| 0.09 | `DA020` | Tenho de pagar caucao para entrar na residencia universitaria? |
| 0.09 | `DA021` | Em quantas unidades curriculares posso fazer exame de recurso? |
| 0.08 | `DA004` | Que desconto tenho se pagar a propina anual toda de uma vez? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX039 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Qual e o prazo para interpor recurso do resultado junto do juri?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#457`
- justificação registada: Recurso ao presidente do juri no prazo maximo de tres dias uteis apos a divulgacao do resultado.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX040 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quantos dias tenho para recorrer depois de sair o resultado?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-004#457`
- justificação registada: Recurso ao presidente do juri no prazo maximo de tres dias uteis apos a divulgacao do resultado.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A26 — reclamacao_listas_ordenacao

- tipo: `procedural`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-005`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.12 | `DA024` | Qual e o prazo para reclamar da nota de um exame? |
| 0.08 | `Q004` | Quando e publicada a lista de inscritos em UCT no ano letivo 2025/2026? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX042 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Como reclamo da lista definitiva de ordenacao e em que prazo?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-005#318`
- justificação registada: Reclamacao das listas definitivas de ordenacao, dirigida ao Reitor, no prazo de 5 dias uteis.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-A27 — outorga_tipos_cerimonia

- tipo: `semantic_reformulation`
- intenção: `ANSWERABLE`
- documento alvo: `P1-DOC-006`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.27 | `DA001` | Quantos convidados pode levar cada graduando a cerimonia academica de outorga de grau? |
| 0.27 | `DA019` | Posso participar na cerimonia de outorga de grau se ainda tiver uma cadeira por fazer? |
| 0.18 | `DA002` | Na outorga de grau, quantos acompanhantes sao permitidos a cada finalista? |
| 0.18 | `DA018` | Onde e que os finalistas compram o traje academico para a outorga de grau? |
| 0.11 | `DA025` | Qual e o contacto dos Servicos Academicos da Uni-CV? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX041 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Que tipos de cerimonia de outorga de grau existem na Uni-CV?

- proposta: **ANSWERABLE**
- evidência localizada: `P1-DOC-006#34`, `P1-DOC-006#36`
- justificação registada: A realizacao da outorga de grau reveste duas formas: cerimonia academica e cerimonia familiar.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-N01 — residencia_internet

- tipo: `plausible_absent`
- intenção: `NO_EVIDENCE`
- documento alvo: `—`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.40 | `DA009` | Qual e o horario de recolha nas residencias universitarias? |
| 0.11 | `DA025` | Qual e o contacto dos Servicos Academicos da Uni-CV? |
| 0.11 | `DA030` | Qual e o horario de funcionamento da biblioteca da Uni-CV? |
| 0.11 | `DA039` | Quantos valores preciso para entrar em Medicina na Uni-CV? |
| 0.11 | `DA040` | Como funciona o programa Erasmus na Uni-CV? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX043 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Ha wi-fi nos quartos das residencias universitarias?

- proposta: **NO_EVIDENCE**
- termos procurados: `wifi`, `wi fi`, `internet`
- resultado da procura: Zero ocorrencias de 'wifi'. 'internet' aparece duas vezes e nenhuma sobre acesso a rede nas residencias: P1-DOC-004#171 descreve ensino por mediacao tecnologica e P1-DOC-007#251 refere edital publicado na pagina oficial.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX044 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> As residencias da Uni-CV tem acesso a internet incluido?

- proposta: **NO_EVIDENCE**
- termos procurados: `wifi`, `wi fi`, `internet`
- resultado da procura: Zero ocorrencias de 'wifi'. 'internet' aparece duas vezes e nenhuma sobre acesso a rede nas residencias: P1-DOC-004#171 descreve ensino por mediacao tecnologica e P1-DOC-007#251 refere edital publicado na pagina oficial.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-N02 — residencia_lavandaria

- tipo: `plausible_absent`
- intenção: `NO_EVIDENCE`
- documento alvo: `—`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.25 | `DA045` | A universidade tem seguro de acidentes pessoais para os estudantes? |
| 0.14 | `DA009` | Qual e o horario de recolha nas residencias universitarias? |
| 0.14 | `DA042` | Ha estacionamento gratuito no campus para estudantes? |
| 0.10 | `DA003` | Com que antecedencia tem de ser confirmada ao Gabinete do Reitor a cerimonia academica? |
| 0.10 | `DA012` | Qual e o numero maximo de estudantes numa aula teorico-pratica? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX045 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> As residencias tem lavandaria para os estudantes?

- proposta: **NO_EVIDENCE**
- termos procurados: `lavandaria`, `lavanderia`, `maquina de lavar`
- resultado da procura: Zero ocorrencias em todo o corpus.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-N03 — residencias_numero_vagas

- tipo: `plausible_absent`
- intenção: `NO_EVIDENCE`
- documento alvo: `—`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.29 | `DA009` | Qual e o horario de recolha nas residencias universitarias? |
| 0.12 | `DA025` | Qual e o contacto dos Servicos Academicos da Uni-CV? |
| 0.12 | `DA030` | Qual e o horario de funcionamento da biblioteca da Uni-CV? |
| 0.12 | `DA039` | Quantos valores preciso para entrar em Medicina na Uni-CV? |
| 0.12 | `DA040` | Como funciona o programa Erasmus na Uni-CV? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX046 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quantas residencias universitarias tem a Uni-CV?

- proposta: **NO_EVIDENCE**
- termos procurados: `numero de vagas`, `quantas residencias`, `capacidade`
- resultado da procura: 'numero de vagas' ocorre uma vez e e sobre unidades curriculares em periodo de ferias (P1-DOC-004#544), nao sobre alojamento. O regulamento das residencias regula candidatura e ocupacao sem fixar quantas residencias ou camas existem.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX047 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> Quantas vagas de alojamento estao disponiveis por ano?

- proposta: **NO_EVIDENCE**
- termos procurados: `numero de vagas`, `quantas residencias`, `capacidade`
- resultado da procura: 'numero de vagas' ocorre uma vez e e sobre unidades curriculares em periodo de ferias (P1-DOC-004#544), nao sobre alojamento. O regulamento das residencias regula candidatura e ocupacao sem fixar quantas residencias ou camas existem.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-N04 — calendario_2627_aulas

- tipo: `near_miss_negative`
- intenção: `NO_EVIDENCE`
- documento alvo: `—`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.27 | `DA036` ⚑ | Quando comecaram as aulas do primeiro semestre do ano letivo 2024/2025? |
| 0.18 | `DA037` ⚑ | Qual foi a data de inicio do ano letivo 2024/2025? |
| 0.71 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |
| 0.56 | `DA013` | Quando comecam as aulas do segundo semestre do ano letivo 2025/2026? |
| 0.44 | `DA014` | Qual e a data do primeiro dia de aulas do 2.o semestre em 2025/2026? |
| 0.33 | `DA015` | Quando e a pausa de Natal no ano letivo 2025/2026? |
| 0.30 | `Q012` | Quando e a cerimonia de entrega dos diplomas no ano letivo 2025/2026? |

⚑ já citada na nota do conjunto; mostrada independentemente da ordenação.

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX048 — `HUMAN_REVIEW_REQUIRED`

> Quando comecam as aulas do ano letivo 2026/2027?

- proposta: **NO_EVIDENCE**
- termos procurados: `2026 2027`, `ano letivo 2026`
- resultado da procura: P1-DOC-002 tem a seccao 'MATRICULAS E INSCRICOES NO ANO LETIVO 2026/2027' (#86) com prazos de matricula, mas NAO tem datas de aulas, exames ou pausas de 2026/2027. E um near-miss: o ano aparece, o facto pedido nao.
- nota de sobreposição: Familia semantica proxima de DA036/DA037 (calendario 2024/2025, NO_EVIDENCE na D4.8.2): ambos perguntam por datas de aulas de um ano que o corpus nao cobre. O ano e outro e a direcao temporal e outra (futuro vs passado), mas a independencia nao e obvia.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

#### DX049 — `HUMAN_REVIEW_REQUIRED`

> Qual e a data de inicio do primeiro semestre de 2026/2027?

- proposta: **NO_EVIDENCE**
- termos procurados: `2026 2027`, `ano letivo 2026`
- resultado da procura: P1-DOC-002 tem a seccao 'MATRICULAS E INSCRICOES NO ANO LETIVO 2026/2027' (#86) com prazos de matricula, mas NAO tem datas de aulas, exames ou pausas de 2026/2027. E um near-miss: o ano aparece, o facto pedido nao.
- nota de sobreposição: Familia semantica proxima de DA036/DA037 (calendario 2024/2025, NO_EVIDENCE na D4.8.2): ambos perguntam por datas de aulas de um ano que o corpus nao cobre. O ano e outro e a direcao temporal e outra (futuro vs passado), mas a independencia nao e obvia.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## SC-N05 — greve_interrupcao

- tipo: `plausible_absent`
- intenção: `NO_EVIDENCE`
- documento alvo: `—`
- estado da revisão de independência: `PENDING_HUMAN_REVIEW`

### Semelhanças históricas a considerar

| Semelhança | Histórica | Texto |
| ---: | --- | --- |
| 0.14 | `Q005` | A presenca nas aulas praticas e obrigatoria? |
| 0.11 | `Q001` | Quando comecam as aulas do ano letivo 2025/2026? |
| 0.10 | `DA014` | Qual e a data do primeiro dia de aulas do 2.o semestre em 2025/2026? |
| 0.09 | `DA013` | Quando comecam as aulas do segundo semestre do ano letivo 2025/2026? |
| 0.09 | `DA036` | Quando comecaram as aulas do primeiro semestre do ano letivo 2024/2025? |

```
status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE
historical_refs: []
rationale:
annotator:
```

### Perguntas

#### DX050 — `MACHINE_PROPOSED_PENDING_HUMAN_REVIEW`

> O que acontece as aulas em caso de greve?

- proposta: **NO_EVIDENCE**
- termos procurados: `greve`, `paralisacao`
- resultado da procura: Zero ocorrencias em todo o corpus.

```
decisão:   CONFIRM | EDIT | EXCLUDE
annotator:
notas:
```

## Depois de preencher

1. aplicar as decisões ao conjunto de perguntas (`EDIT` e `EXCLUDE`
   **antes** de qualquer execução);
2. `python -m scripts.stamp_d4_10_question_set --question-set ...`;
3. `python -m scripts.seal_d4_10_protocol ...` — sem `--draft`, que só
   passa quando `freeze_ready` for verdadeiro;
4. versionar essa selagem num commit anterior a qualquer execução da
   D4.10b.
