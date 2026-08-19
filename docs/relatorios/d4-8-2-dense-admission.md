# D4.8.2 — Calibração e avaliação held-out da admissão/abstenção densa sobre P1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo

A [D4.8.1](d4-8-1-lexical-dense-repooling.md) estabeleceu que a condição densa
recupera muito melhor do que a lexical e que **não tem etapa capaz de recusar**:
devolveu 70 de 70 resultados possíveis, 43 deles de grau 0, e cinco resultados
na única pergunta sem evidência no corpus, todos julgados irrelevantes. C0
abstinha-se seis vezes e acertava numa.

Esta fase **não procura o melhor limiar**. Procura responder a uma pergunta
diferente e mais difícil: uma regra de admissão escolhida **apenas em DEV**,
sob um critério fixado **antes** de se ver quem ganha, transporta-se para
cenários independentes? Um resultado negativo seria um resultado, e o protocolo
foi escrito para o poder registar sem o transformar noutra ronda de afinação.

Não foi implementado `HybridRetriever`, RRF, fusão de scores, reranking,
cross-encoder, modelo de embeddings novo, reescrita de consultas, GraphRAG nem
Agentic RAG. Não foi alterado o retrieval de produção, o *answering*, o OCR, a
segmentação nem o Momento 5. `app.retrieval.dependencies.get_retriever` continua
a devolver o retriever lexical. **D4.9 — Hybrid Retrieval permanece
bloqueada.**

## 2. Contexto experimental

| Item | Valor |
| --- | --- |
| `origin/main` | `7b85b5057507725acd572d9e801009fd16f9839c` (Pull Request #57, D4.8.1) |
| Branch de trabalho | `analysis/d4-8-2-dense-admission`, criada antes do futuro commit/PR |
| `snapshot_id` | `a94f9402…baf4c1` — inalterado |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| Índice vetorial | `index_digest` `451d9f2f…d9370c`, 1834 vetores — **o mesmo** que a D4.8 e a D4.8.1 mediram |
| Modelo | `openai:text-embedding-3-small`, 1536 dimensões, cosseno, `openai_embeddings_v1` |
| `frozen_vectors_digest` | `b7ee0ec7…7df48a` — 49 vetores de pergunta, congelados uma única vez |
| `protocol_digest` | `f0b21d4abe859760787f83ccf0aec8976a314eb0bb18bb1c54f76d65d5008e53` |
| `split_digest` | `72aa7295c1766ea2d7da07bf4674fc6bde272f9738badafa6c8f151c67d0d567` |
| `heldout_manifest_digest` | `479b8e59023d020158131ff5e2f94a1190a68296f99904dbf8641ff5faa77b35` |
| `labels_digest` (selado) | `4e34bec17a348d9e4774bd598a82274d2a3201ac99436bd343dcd0f9e2eb60de` |
| Calibração `result_digest` | `2f4560532d4f3afbd77a8356e3275550782cec9807b0b1f2f459b7da65e49b71` |
| Held-out `result_digest` | `8369bf9aa56ffb9025a14fc101b1a60b60907e6e8a5d9fec636e958813900c6f` — métricas e decisões inalteradas; digest atualizado pelo vínculo metodológico completo |

O conjunto de perguntas da D4.8.1, o seu *ground truth* repooled e as 14
perguntas históricas **não foram tocados**. Este conjunto é complementar e novo.

## 3. D4.8.2a — o conjunto, o split e a selagem

### 3.1 Trinta cenários, 49 perguntas

| | ANSWERABLE | NO_EVIDENCE | Total |
| --- | --- | --- | --- |
| Cenários | 18 | 12 | 30 |
| Perguntas | 25 | 24 | 49 |
| DEV | 13 | 14 | 27 |
| HELD-OUT | 12 | 10 | 22 |

Um cenário é uma família semântica — um pedido e as suas paráfrases. A unidade
de separação é o **cenário**, nunca a pergunta: duas paráfrases do mesmo pedido
separadas pela fronteira tornariam o conjunto final parcialmente conhecido pela
calibração, e o resultado pareceria generalização sem o ser.

### 3.2 Como cada NO_EVIDENCE foi validado

A regra que o protocolo impõe é explícita: *nenhum retriever encontrou* **não**
significa *não existe no corpus*. Cada um dos 12 cenários NO_EVIDENCE foi
verificado contra o corpus **completo** — 1834 segmentos — por busca
normalizada seguida de leitura das ocorrências.

A normalização (sem acentos, sem caixa, sem espaço nenhum) não é zelo
excessivo: vários documentos vieram de OCR com caracteres espaçados
(`d o u t o r a m e n t o`), e um `grep` literal **não provaria ausência**
nesses ficheiros.

A validação apanhou três erros, e é o resultado mais importante desta
subfase. **Três candidatos iniciais a NO_EVIDENCE eram afinal respondíveis** e
foram reclassificados como ANSWERABLE:

| Pedido | Onde a resposta estava |
| --- | --- |
| Prazo para reclamar da nota de um exame | `P1-DOC-004/457`, artigo 49: três dias úteis |
| Contacto dos Serviços Académicos | `P1-DOC-003/35`, rodapé do calendário 2023/2024 |
| Requisitos do prémio de mérito | `P1-DOC-005/276`, média ≥ 16 valores |

Se estes três tivessem entrado como NO_EVIDENCE, cada abstenção correta sobre
eles teria sido contada como acerto quando era erro, e a taxa de abstenção
correta seria inflacionada por construção.

### 3.3 O NO_EVIDENCE mais contestável, registado como tal

O cenário SC-N05 — percentagem mínima de presenças nos **seminários** — é o
mais frágil do conjunto, e a objeção fica escrita no próprio artefacto em vez
de omitida. O corpus classifica os seminários como forma que as atividades
teóricas **e** teórico-práticas podem assumir (`P1-DOC-004/147`), e fixa 50%
para teóricas e 75% para teórico-práticas e laboratoriais. A inferência não
produz resposta determinada — daria 50% **ou** 75% consoante a forma que o
seminário assumisse — pelo que nenhum segmento responde ao pedido. Mantê-lo e
declarar a fragilidade é mais honesto do que retirá-lo depois de ver que a
política o admite.

### 3.4 Os 245 julgamentos

Cada uma das 49 perguntas foi executada na condição densa e os 5 resultados do
top 5 foram julgados na mesma rubrica de três graus da D4.1: 0 irrelevante
(inclui distractor), 1 contexto relevante mas insuficiente sozinho, 2 evidência
que responde.

| Grau | Segmentos |
| --- | --- |
| 0 | 170 |
| 1 | 59 |
| 2 | 29 |
| **Total recuperado** | **245** |

Às 245 juntam-se 13 âncoras **não recuperadas**, localizadas por leitura do
corpus e julgadas grau 2 — sem elas, o denominador do recall descreveria apenas
o que o retriever encontrou, que é a forma mais silenciosa de uma métrica se
elogiar a si própria. Total: 258 julgamentos.

Recall@5 da condição densa sobre as 25 perguntas ANSWERABLE, antes de qualquer
admissão: **0,60** (15 de 25 com pelo menos um grau 2 no top 5).

### 3.5 O split e a barreira

Split determinístico e **sem gerador aleatório**: dentro de cada estrato
(rótulo, dificuldade) os cenários são ordenados por identificador e atribuídos
alternadamente. Não há semente porque não há sorteio, e um sorteio com semente
seria menos verificável, não mais.

A promessa da fase — *a calibração não consegue carregar os rótulos do
HELD-OUT* — foi implementada como propriedade do programa e não como intenção
de quem o corre:

1. o dataset completo é dividido em dois ficheiros; a calibração lê
   [`dense-admission-dev-v1.json`](../evaluation/dense-admission-dev-v1.json),
   que **não contém uma única pergunta, rótulo, julgamento ou cenário selado**,
   nem as atribuições do split;
2. `scripts/calibrate_dense_admission.py` **não tem argumento `--dataset`**;
3. a única porta de entrada de dados,
   `load_calibration_questions`, verifica o contrato e o âmbito e levanta
   `LeakageError` — apontá-la ao dataset completo é um erro, não uma calibração
   sobre tudo;
4. a calibração não aceita o artefacto global de 49 vetores: lê exclusivamente
   [`dense-admission-dev-vectors-v1.json`](../evaluation/dense-admission-dev-vectors-v1.json),
   com os 27 vetores DEV, digest próprio e compromisso sobre a origem global;
   pedir o embedding de uma pergunta selada levanta `EmbeddingError`;
5. o manifesto público identifica as 22 perguntas seladas por identificador e
   cenário e **não revela nenhum rótulo** — leva o `labels_digest`, que é
   reconferido na D4.8.2c.

Testes automáticos fixam isto, incluindo um que lê o ficheiro DEV **como
texto** e verifica que nenhum dos 22 identificadores selados nem dos 14
cenários selados lá aparece.

### 3.6 Vetores congelados

Os 49 vetores de pergunta foram produzidos uma única vez e persistidos com a
identidade **completa** do modelo, o SHA-256 do texto embebido e o digest do
vetor. A razão é medida, não teórica: a D4.8 observou deriva de ~1e-4 na
similaridade ao reembeber o mesmo texto, e a D4.8.1 até 1,78e-3 no embedding da
pergunta. Uma regra de admissão compara similaridades com um limiar; sem
congelar, uma pergunta perto do limiar seria admitida numa execução e recusada
na seguinte.

O congelamento é feito do lado do **modelo** (`FrozenQuestionEmbeddings`
satisfaz o protocolo `EmbeddingModel`), pelo que `PostgresDenseRetriever` corre
sem uma linha alterada e a experiência mede o mesmo retriever que a D4.8.1
mediu.

Cada consumidor recalcula também o digest do conjunto que abre. Assim, alterar
um componente e recalcular apenas o `vector_digest` individual continua a
falhar contra o compromisso externo. Na avaliação final, o digest dos 49
vetores é confirmado contra o artefacto, o split e o protocolo **antes** de
selecionar os vetores HELD-OUT; em calibração, o mesmo vale para a projeção DEV.

## 4. O protocolo pré-registado

Fixado antes de a primeira política ser avaliada sobre qualquer split
([`dense-admission-protocol-v1.json`](../evaluation/dense-admission-protocol-v1.json)).

**Regras candidatas.** R0 admite sempre (controlo, sem parâmetros); R1 admite se
`top1 >= t`; R2 admite se `top1 >= t` **e** `top1 - top2 >= m`.

**Espaço de parâmetros.** `t ∈ {0,50; 0,55; 0,60; 0,65; 0,70}`,
`m ∈ {0,02; 0,05; 0,10}` — 21 políticas candidatas (1 + 5 + 15).

**Critério de seleção.** Elegível quem tiver `false_abstention_rate ≤ 0,20` em
DEV; entre as elegíveis, maximizar `correct_abstention_rate`; desempate por
menor `false_abstention_rate`, regra mais simples, menor `t`, menor `m`. Com 13
perguntas ANSWERABLE em DEV, o orçamento admite no máximo **duas** abstenções
falsas.

**Honestidade sobre a pré-registação.** O anotador viu as similaridades ao
julgar os segmentos — é inevitável, porque é a mesma pessoa que anota e conduz
a experiência. É por isso que a grelha é grosseira e está declarada: cinco
limiares espaçados de 0,05, sem ajuste fino e sem valores escolhidos por
proximidade a um caso concreto. O que a pré-registação garante não é
ignorância; é que **o critério de escolha não pode ser alterado depois de se ver
quem ganha**. O protocolo vincula `dataset_questions_digest`, `scenario_digest`,
`split_digest`, os digests das projeções DEV, `heldout_manifest_digest` e
`frozen_vectors_digest`; o `protocol_digest` é recalculado pela calibração antes
de o usar. O split recalcula o próprio digest a partir das atribuições, e o
held-out volta a reproduzir o algoritmo alternado a partir dos cenários.

## 5. D4.8.2b — calibração em DEV

Das 21 candidatas, **17 foram excluídas pelo orçamento** de abstenção falsa.
Todas as 15 variantes de R2 estão entre as excluídas: a margem `top1 - top2`
recusa perguntas respondíveis em massa (a melhor de todas custa 38% de
abstenções falsas). A hipótese de que uma pergunta sem resposta produz um topo
indistinto **não se confirmou** neste corpus.

Elegíveis, por ordem do critério pré-registado:

| Política | `correct_abstention_rate` | `false_abstention_rate` |
| --- | --- | --- |
| **R1, t = 0,60** | **0,7143** | **0,0769** |
| R1, t = 0,55 | 0,5000 | 0,0000 |
| R1, t = 0,50 | 0,2143 | 0,0000 |
| R0 (controlo) | 0,0000 | 0,0000 |

Política selecionada e **congelada**: `R1, min_top1 = 0,60`.

Métricas em DEV, contra o controlo:

| Métrica | R0 | R1 t=0,60 |
| --- | --- | --- |
| `coverage` | 1,0000 | 0,5926 |
| `coverage_answerable` | 1,0000 | 0,9231 |
| `risk` | 0,5185 | 0,2500 |
| `correct_abstention_rate` | 0,0000 | 0,7143 |
| `false_abstention_rate` | 0,0000 | 0,0769 |
| `answerable_with_relevant_preserved` | 0,6923 | 0,6923 |
| Recall@5 grau 2 (ANSWERABLE admitidas) | 0,6923 | 0,7500 |
| MRR (ANSWERABLE admitidas) | 0,5410 | 0,5861 |
| nDCG@5 (ANSWERABLE admitidas) | 0,6791 | 0,7128 |
| grau 0 devolvido por pergunta admitida | 3,56 | 3,13 |
| fração de grau 0 | 0,7111 | 0,6250 |

Os quatro erros em DEV são informativos. A única abstenção falsa foi DA007
(juros de mora do alojamento, `top1` = 0,5845) — e essa pergunta **não tinha
nenhum grau 2 no top 5**, pelo que a abstenção não perdeu evidência nenhuma;
`answerable_with_relevant_preserved` fica igual ao controlo. As quatro admissões
erradas incluem DA036 e DA037 (data de início do ano letivo **2024/2025**, que o
corpus não contém) com `top1` de **0,7412 e 0,7372** — os dois valores mais
altos de todo o DEV. São perguntas cuja resposta existe no corpus para *outros*
anos, e o texto quase idêntico produz similaridade altíssima. **Nenhum limiar
sobre `top1` as podia apanhar**: o limiar que as recusasse recusaria quase tudo.

## 6. D4.8.2c — avaliação única no HELD-OUT

A política congelada foi aplicada tal e qual. O comando não tem espaço de
parâmetros, não avalia candidatas e não tem critério de seleção — há teste que
lê o seu código-fonte e o confirma. Antes de medir, verificou-se que os 22
identificadores selados são exatamente os avaliados e que o `labels_digest`
recalculado coincide com o selado: nenhum rótulo mudou no intervalo.

| Métrica | R0 | R1 t=0,60 |
| --- | --- | --- |
| `coverage` | 1,0000 | 0,6818 |
| `coverage_answerable` | 1,0000 | 0,9167 |
| `risk` | 0,4545 | 0,2667 |
| `correct_abstention_rate` | 0,0000 | 0,6000 |
| `false_abstention_rate` | 0,0000 | 0,0833 |
| `answerable_with_relevant_preserved` | 0,5000 | 0,4167 |
| Recall@5 grau 2 (ANSWERABLE admitidas) | 0,5000 | 0,4545 |
| MRR (ANSWERABLE admitidas) | 0,3611 | 0,3636 |
| nDCG@5 (ANSWERABLE admitidas) | 0,5593 | 0,5475 |
| segmentos devolvidos | 110 | 75 |
| fração de grau 0 | 0,6727 | 0,5600 |
| fração de grau 1 | 0,2636 | 0,3600 |
| fração de grau 2 | 0,0636 | 0,0800 |
| grau 0 por pergunta admitida | 3,36 | 2,80 |

As três métricas de ranking são medidas **sobre denominadores diferentes**: R0
mede 12 perguntas ANSWERABLE, a política mede as 11 que admitiu. O delta não é,
por isso, uma comparação emparelhada — a pergunta que a política recusou (DA024)
sai do denominador e levava consigo um grau 2. É
`answerable_with_relevant_preserved`, medido sobre as 12, que regista essa
perda; `Recall@5` medido sobre as admitidas não a pode registar.

DEV contra HELD-OUT, para a mesma política:

| Métrica | DEV | HELD-OUT | Retenção |
| --- | --- | --- | --- |
| `correct_abstention_rate` | 0,7143 | 0,6000 | 0,84 |
| `false_abstention_rate` | 0,0769 | 0,0833 | — |
| `coverage` | 0,5926 | 0,6818 | — |
| `risk` | 0,2500 | 0,2667 | — |

### 6.1 O que custou

A abstenção falsa no HELD-OUT foi DA024 — prazo para reclamar da nota de um
exame, `top1` = 0,5841 — e desta vez **custou evidência real**: o top 5 continha
um grau 2 na terceira posição. É a razão de `answerable_with_relevant_preserved`
cair de 0,50 para 0,4167. Uma pergunta em doze passou a não receber resposta
quando a resposta estava a ser devolvida.

As quatro admissões erradas foram os cenários difíceis: valor do prémio de
mérito, presenças nos seminários e as duas do Erasmus. Em todas elas o corpus
tem material vizinho e nenhuma resposta.

## 7. Decisão

**A — a política generalizou.** Critério pré-registado, aplicado sem
interpretação: `false_abstention_rate` de 0,0833 dentro do orçamento de 0,20, e
`correct_abstention_rate` de 0,60 retendo **0,84** do valor medido em DEV, acima
do piso de retenção de 0,50 fixado antes de qualquer medição.

O que isto autoriza a dizer, e nada mais: **uma regra de limiar único sobre
`top1`, escolhida em 16 cenários, transportou-se para 14 cenários independentes
deste corpus, com este modelo e este índice.** Reduziu o risco de responder sem
evidência de 0,45 para 0,27 e o ruído de 3,36 para 2,80 segmentos irrelevantes
por pergunta admitida, ao preço de uma pergunta respondível em doze.

O que isto **não** autoriza a dizer: que 0,60 é um limiar válido noutro corpus,
noutro modelo ou noutro conjunto de perguntas. A similaridade do cosseno não é
confiança — `comparable_across_queries` é `False` para a condição densa, e
continua a ser depois desta fase. O valor 0,60 é uma propriedade desta
distribuição de perguntas contra este índice.

## 8. Reprodutibilidade

O comando do HELD-OUT correu **três** vezes. As três produziram `result_digest`,
`execution_digest` e decisões por pergunta idênticos. A calibração correu duas
vezes, com o mesmo resultado.

Que o `execution_digest` também seja estável é a confirmação de que os vetores
congelados removeram a deriva do fornecedor: na D4.8.1, com o embedding
calculado a cada execução, era precisamente esse digest que variava.

Os artefactos desta fase mantêm os dois digests introduzidos na correção da
D4.8.1: `result_digest` sobre as decisões e as métricas (âmbito
`decision_relevant_fields`) e `execution_digest` sobre o *payload* completo. Há
teste que perturba as similaridades em 1e-6 e verifica que o primeiro **não**
muda e o segundo muda; e outro que vira uma decisão e verifica que o primeiro
muda.

## 9. Limitações

1. **Escala.** 49 perguntas, 30 cenários, 22 no conjunto final. Uma abstenção
   falsa a mais no HELD-OUT levaria a taxa a 0,167 — ainda dentro do orçamento,
   mas o intervalo de confiança de uma proporção sobre 12 casos é largo. A
   decisão A é sobre a direção, não sobre o valor.
2. **Um anotador.** `SINGLE_ANNOTATOR_PILOT`, sem concordância inter-anotador.
   A fronteira entre grau 0 e grau 1 é a mais discutível, embora não afete o
   recall (limiar binário no grau 2).
3. **Um corpus, um modelo, um índice.** Nada aqui se transporta para outro
   corpus sem repetir a medição.
4. **O anotador viu as similaridades.** Declarado no protocolo. Mitigado pela
   grelha grosseira e pelo critério fixado antes, não eliminado.
5. **A pergunta cuja resposta existe para outro ano** é o modo de falha que esta
   política não cobre de todo, e o mais perigoso em produção: produz
   similaridade máxima e resposta errada. Nenhuma regra sobre `top1` a resolve.
6. **SC-N05** é um NO_EVIDENCE contestável, declarado na secção 3.3.

## 10. O que esta fase não fez

Não implementou retrieval híbrido, nem tocou no retrieval de produção, nem
introduziu a abstenção no `answering`. A política existe como artefacto medido,
não como comportamento do sistema. Levá-la a produção é uma decisão de produto
que esta fase não toma e para a qual deixa os números: um em doze pedidos
respondíveis deixaria de receber resposta.

Não foi feito commit, push nem Pull Request.

## 11. Reprodução

```bash
cd backend

# 1. selagem (D4.8.2a) - escreve o split e as projecoes DEV
python -m scripts.seal_dense_admission_split \
    --dataset ../docs/evaluation/dense-admission-dataset-v1.json \
    --frozen-vectors ../docs/evaluation/dense-admission-frozen-vectors-v1.json \
    --split-output ../docs/evaluation/dense-admission-split-v1.json \
    --dev-output ../docs/evaluation/dense-admission-dev-v1.json \
    --dev-vectors-output ../docs/evaluation/dense-admission-dev-vectors-v1.json \
    --overwrite

# 2. calibracao (D4.8.2b) - le apenas DEV
python -m scripts.calibrate_dense_admission \
    --protocol ../docs/evaluation/dense-admission-protocol-v1.json \
    --split ../docs/evaluation/dense-admission-split-v1.json \
    --dev ../docs/evaluation/dense-admission-dev-v1.json \
    --dev-vectors ../docs/evaluation/dense-admission-dev-vectors-v1.json \
    --binding ../storage/pilot-corpus/S1-identifier-binding.json \
    --output ../docs/evaluation/dense-admission-calibration-v1.json --overwrite

# 3. avaliacao final (D4.8.2c) - politica congelada, sem recalibracao
python -m scripts.evaluate_dense_admission_heldout \
    --protocol ../docs/evaluation/dense-admission-protocol-v1.json \
    --split ../docs/evaluation/dense-admission-split-v1.json \
    --dataset ../docs/evaluation/dense-admission-dataset-v1.json \
    --calibration ../docs/evaluation/dense-admission-calibration-v1.json \
    --frozen-vectors ../docs/evaluation/dense-admission-frozen-vectors-v1.json \
    --binding ../storage/pilot-corpus/S1-identifier-binding.json \
    --output ../docs/evaluation/dense-admission-heldout-v1.json --overwrite
```

O congelamento dos vetores (`scripts/freeze_dense_admission_vectors.py`) é o
único comando da fase que contacta o fornecedor e **não** deve voltar a correr:
correria com vetores novos e as decisões deixariam de ser as medidas.

## 12. Próximo passo

D4.9 — Hybrid Retrieval deixa de estar bloqueada pela D4.8.2. O que esta fase
lhe entrega é um conjunto anotado com perguntas sem resposta, um protocolo de
avaliação de abstenção e a medida de quanto custa recusar. O que **não** lhe
entrega é um limiar para usar: qualquer condição nova tem a sua própria
distribuição de scores e teria de repetir esta calibração.
