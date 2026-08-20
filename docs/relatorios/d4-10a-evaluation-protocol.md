# D4.10a — Pré-registo da avaliação independente e ampliada de retrieval

Relatório de fase. Documento **histórico**: regista o desenho no momento em que
foi fixado. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

**Esta fase não executou a experiência.** Não gerou embeddings, não correu
retrieval, não construiu pool, não observou rankings, não julgou relevância, não
calculou métricas e não tomou decisão nenhuma.

## 1. Motivação

A [D4.9](d4-9-hybrid-rrf-p1-s1.md) concluiu **D** — a fusão por RRF é promissora
e a amostra não sustenta promoção. Mas o problema da D4.9 não foi só o tamanho da
amostra: foi que a **regra de decisão e o resultado nasceram no mesmo commit**.
Não havia como provar que o critério precedeu a medição, e o instrumento que ele
usava — um `MATERIAL_DELTA = 0,02` — violava a instrução explícita da própria
fase.

A correção não é escrever ressalvas melhores. É separar o desenho da execução no
histórico do projeto, que é o que esta fase faz.

## 2. O problema da amostra da D4.9

| | |
| --- | --- |
| perguntas medidas | 12 |
| em que C0 devolveu zero (fusão = identidade) | 5 |
| em que a fusão podia agir | 7 |
| que mudaram face a C1 | 4 (2 melhores, 2 piores) |

O resultado agregado era o líquido de quatro perguntas. Qualquer conclusão sobre
o híbrido assentava nisso.

## 3. Pergunta de investigação

> Num conjunto independente de cenários e perguntas não utilizado nas fases
> D4.2–D4.9, a fusão lexical+densa por RRF preserva ou melhora a qualidade de
> recuperação face ao Dense Retrieval isolado?

Secundárias: o benefício da D4.9 aparece em cenários novos? Há novos casos em que
o lexical recupera evidência que o denso perde? C2 preserva a vantagem semântica
de C1? Com que frequência a fusão melhora, mantém ou degrada perguntas? A
sensibilidade a empates de Q003 repete-se? Como se comportam as três condições
em perguntas sem evidência, **sem** política de admissão?

## 4. Condições congeladas

| | |
| --- | --- |
| **C0** | lexical, `lexical_composite_v1`, `top_k` 5 — como a D4.8.1 mediu |
| **C1** | denso, `text-embedding-3-small`, 1536, cosseno, `index_digest` `451d9f2f…d9370c`, `top_k` 5 |
| **C2** | RRF, `k_rrf` 60, `source_depth` 5, `final_top_k` 5, aritmética racional exata, desempate da D4.9 |

Nada disto muda. O corpus, o snapshot, o chunking, o OCR, a elegibilidade, o
ranking lexical, o modelo de embeddings, o índice e o *ground truth* histórico
ficam como estão. A D4.10 mede **generalização sobre perguntas novas**; alterar
uma condição ao mesmo tempo tornaria o resultado inatribuível.

O desempate fica congelado **mesmo sabendo que custou uma pergunta na D4.9**. A
sensibilidade observada em Q003 é uma hipótese a observar nesta fase, não uma
autorização para corrigir o algoritmo dentro do mesmo teste.

Também não entra política de admissão. A D4.8.2 está fechada; `hybrid + admission`
só faz sentido como experiência separada, e só se a D4.10 justificar continuar
com C2.

## 5. Independência do painel

Os identificadores das duas fases anteriores foram enumerados e os seus tópicos
excluídos do desenho:

- **Q001–Q014** (D4.1–D4.9): calendário 2025/26, anulação e renovação de
  matrícula, UCT, diplomas, presenças, residências (duração, prorrogação,
  candidatura), CESP, portal;
- **DA001–DA049** (D4.8.2): outorga (convidados, confirmação, traje,
  requisitos), propinas (liquidação antecipada, matrícula), residências
  (pagamentos, horários, vistorias, caução), exame de recurso, reclamação de
  nota, prémio de mérito, biblioteca, cantina, Erasmus, ECTS, seguro,
  estacionamento, dívida pessoal.

Os identificadores novos usam o prefixo **`DX`**, distinto de `Q` e `DA`, para
que a reutilização seja visível à vista desarmada. Há teste que verifica
sobreposição zero de identificadores **e** de texto normalizado.

Um cenário foi marcado **`HUMAN_REVIEW_REQUIRED`**: `SC-N04` (datas de aulas de
2026/2027, ausentes do corpus) pertence à mesma família semântica de DA036/DA037
(datas de aulas de 2024/2025). O ano é outro e a direção temporal é outra, mas a
independência não é óbvia e não a declaro por decreto.

## 6. Desenho por cenários

O painel é construído por **famílias semânticas**, não por perguntas soltas.
Perguntas do mesmo `scenario_id` são formulações da mesma intenção, e é o cenário
— não a pergunta — que a análise de incerteza reamostra.

```
cenários   32        perguntas   50
ANSWERABLE 42        NO_EVIDENCE  8
perguntas por cenário: 1 a 2
```

Tipos representados:

| Tipo | Cenários |
| --- | ---: |
| `numeric_fee_deadline` | 9 |
| `procedural` | 7 |
| `plausible_absent` | 4 |
| `exact_institutional_terms` | 3 |
| `semantic_interpretation` | 3 |
| `semantic_reformulation` | 3 |
| `strong_lexical_cue` | 2 |
| `near_miss_negative` | 1 |

## 7. Cobertura documental

| Documento | Cenários | Perguntas | Tipos semânticos |
| --- | ---: | ---: | --- |
| P1-DOC-002 — Calendário 2025/2026 | 5 | 8 | `numeric_fee_deadline` 5, `procedural` 3 |
| P1-DOC-003 — Calendário 2023/2024 | 3 | 4 | `numeric_fee_deadline` 4 |
| P1-DOC-004 — Regulamento Geral de Graduação | 9 | 15 | `procedural` 5, `exact_institutional_terms` 4, `semantic_interpretation` 3, `semantic_reformulation` 2, `strong_lexical_cue` 1 |
| P1-DOC-005 — Propinas e Emolumentos | 5 | 8 | `numeric_fee_deadline` 4, `procedural` 3, `semantic_reformulation` 1 |
| P1-DOC-006 — Outorga de Grau | 1 | 1 | `semantic_reformulation` 1 |
| P1-DOC-007 — Residências Universitárias | 4 | 6 | `exact_institutional_terms` 2, `strong_lexical_cue` 2, `numeric_fee_deadline` 1, `semantic_interpretation` 1 |
| _(sem documento alvo — NO_EVIDENCE)_ | 5 | 8 | `plausible_absent` 6, `near_miss_negative` 2 |

As três colunas andam juntas de propósito. Uma contagem sozinha não distingue
cobertura de repetição: cinco perguntas sobre o mesmo documento, todas do mesmo
tipo, não testam o que cinco perguntas repartidas por termos exatos, paráfrase e
formulação indireta testam — e é precisamente essa repartição que separa o que
o retrieval lexical apanha do que só a via densa apanha. A distribuição está no
artefacto (`document_distribution`), não apenas nesta tabela.

As oito NO_EVIDENCE aparecem sob uma chave explícita (`NO_TARGET_DOCUMENT`) em
vez de serem omitidas: assim a distribuição soma 50 e não esconde um sexto do
painel.

**Os seis documentos utilizáveis estão cobertos.** P1-DOC-001 (Estatuto do
Estudante) fica de fora porque **não está no corpus indexado**: o upload falhou
com `413 payload_too_large` e nenhuma versão foi criada. É um facto registado no
*binding* de S1, não uma escolha desta fase.

P1-DOC-006 tem apenas um cenário porque a D4.8.2 já esgotou a maior parte do que
esse regulamento cobre.

## 8. Validação ANSWERABLE / NO_EVIDENCE — e o que falta

Cada rótulo foi trabalhado contra o corpus **real**: os 1834 chunks indexados de
P1, lidos por busca normalizada (sem acentos, sem caixa, sem espaços — vários
documentos vieram de OCR com caracteres espaçados, e um `grep` literal não
provaria nada).

- cada **ANSWERABLE** traz a âncora `(corpus_item_id, chunk_index)` onde a
  evidência foi localizada, mais uma justificação curta. **48 âncoras, todas
  verificadas contra o corpus indexado**;
- cada **NO_EVIDENCE** traz os termos procurados e o resultado da procura,
  incluindo as ocorrências vizinhas que **não** respondem.

**E é aqui que esta fase não fecha.** Os §13 e §14 do enunciado exigem validação
**humana**, e uma máquina pode localizar evidência e registar onde a localizou —
não pode assinar por um humano. Por isso todas as 50 perguntas estão em
`MACHINE_PROPOSED_PENDING_HUMAN_REVIEW` ou `HUMAN_REVIEW_REQUIRED`,
`annotator` é `null`, e `human_review.freeze_ready` é **`false`**.

Há uma guarda no código que recusa `HUMAN_CONFIRMED` sem `annotator` nomeado.

### 8.1 Correção após auditoria — a validação também é selada

O `question_set_digest` **não cobre** o `review_status`: se cobrisse, a revisão
humana invalidaria o conjunto que ela própria valida, e ninguém a faria.
Confirmar uma validação não altera nenhuma pergunta, e há teste que o fixa.

A primeira versão desta fase parou aí, e isso era um buraco. Uma auditoria
independente demonstrou-o empiricamente: confirmando `DX001` com um anotador
numa variante e `DX002` com outro anotador noutra, ambas passavam
`verify_question_set` e produziam **exatamente** os mesmos `question_set_digest`,
`scenario_digest` e `protocol_digest`. Ou seja, depois das cinquenta
confirmações seria possível reescrever quem validou, qual pergunta foi validada
e que evidência ficou registada sem invalidar coisa nenhuma — a validação humana
ficava ao lado da selagem em vez de dentro dela.

O argumento que fiz para deixar a revisão fora do digest estava certo quanto ao
`question_set_digest` e errado quanto à conclusão: dizia porque é que **aquele**
digest não devia cobrir a revisão, e daí não se segue que **nenhum** deva.

A correção mantém o digest do conteúdo estável e acrescenta um segundo:

| Digest | Cobre | Muda quando |
| --- | --- | --- |
| `question_set_digest` | identificador, cenário, texto, idioma, intenção, documento alvo | uma pergunta é editada, acrescentada, removida ou muda de cenário |
| `scenario_digest` | metadados do cenário — tipo, tópico, documento alvo, intenção, contagem — e as perguntas que o compõem | um cenário é redefinido ou recomposto |
| `human_review_digest` | por pergunta: estado de revisão e o bloco de validação **inteiro** — anotador, método, estado, racional, âncoras ou termos procurados | qualquer coisa no registo da validação muda |

Os três entram no `protocol_digest` e os três são precondição da D4.10b. As duas
perguntas — «as perguntas são as mesmas?» e «a validação é a mesma?» — passam a
ter respostas separadas, que é o que permite confirmar uma validação sem
invalidar o painel **e**, ao mesmo tempo, impedir que a validação seja reescrita
sem rasto.

O `human_review_digest` cobre o bloco de validação por inteiro, e não uma lista
escolhida de campos: um campo acrescentado ao bloco é uma mudança no registo da
validação e deve mudar o digest.

Consequência prática: quando a revisão humana for feita, o `human_review_digest`
muda — e portanto o `protocol_digest` também. É o efeito pretendido. A selagem
que vale é a que existir **depois** da revisão, e o comando de carimbo
(`stamp_d4_10_question_set`) e o de selagem (`seal_d4_10_protocol`) são
separados precisamente para que a selagem possa **verificar** a identidade em
vez de a recalcular e concordar sempre consigo própria.

### 8.2 Os metadados dos cenários também contam

O `scenario_digest` passou a cobrir tipo, tópico, documento alvo e intenção de
cada cenário, e não apenas o agrupamento. Reetiquetar um cenário de
`exact_institutional_terms` para `paraphrase_natural` não toca em nenhuma
pergunta, preserva identificadores e contagens — e mudaria por completo a
leitura dos resultados por tipo semântico. Sem metadados no digest, essa
redefinição passava despercebida.

Pela mesma razão, cada pergunta repete os metadados do seu cenário e essa
repetição é **verificada**: repetição não verificada é repetição que acaba por
divergir, e uma pergunta que se declarasse de outro documento alvo deixaria a
análise por cenário a medir uma coisa e a leitura por documento a medir outra.

## 9. Prevenção de leakage

O que esta fase impede, e como:

| Risco | Barreira |
| --- | --- |
| escolher perguntas depois de ver rankings | nenhum retrieval foi executado; o comando de selagem não importa retrievers, embeddings nem a fusão — verificado por AST |
| mover uma paráfrase entre cenários | muda `question_set_digest` **e** `scenario_digest` |
| editar uma pergunta ou trocar um rótulo | muda `question_set_digest` |
| redefinir o tipo ou o tópico de um cenário | muda `scenario_digest` |
| reescrever quem validou, o quê ou com que evidência | muda `human_review_digest` |
| carimbar uma identidade que não corresponda ao conteúdo | a selagem recusa (`verify_declared_identity`) |
| uma pergunta contradizer os metadados do seu cenário | `verify_question_set` recusa |
| alterar C2, a métrica ou o bootstrap | muda `protocol_digest` |
| o protocolo transportar resultados | lista de campos proibidos, verificada recursivamente |
| reutilizar uma pergunta histórica | prefixo `DX` + teste de sobreposição de IDs e de texto |

## 10. Métricas

Herdadas do protocolo do D4.1, sem redefinição: cortes 1/3/5, relevância binária
no grau 2, ganhos nDCG `{0:0, 1:1, 2:3}`, não julgado = grau 0.

**Métrica primária: `nDCG@5`.** A fusão altera sobretudo a **ordem**; o Recall
com limiar binário é cego a reordenações dentro do top 5.

**Comparação principal: C2 contra C1.** «C2 > C0» seria satisfeito por qualquer
fusão que preservasse a ordem densa e não informaria nada.

Secundárias: Recall@1/3/5, MRR, nDCG@1/3, taxa de perguntas resolvidas,
distribuição de graus, delta por pergunta, contagens melhorou/igual/piorou,
alvos exclusivos de cada condição preservados por C2.

Nas perguntas **NO_EVIDENCE** não se calcula Recall, MRR nem nDCG — não há alvo,
as métricas não estão definidas. Reporta-se contagem devolvida por condição,
graus 0 e 1 e ruído por pergunta. Sem limiar, sem admissão.

Sobre empates, a fase **observa sem alterar**: quantos ocorreram, quantos
chegaram ao desempate por identidade, quantos mudaram o grau da primeira posição
e em quantos o desempate favoreceu relevante ou irrelevante.

## 11. Análise por cenário

Perguntas do mesmo cenário são paráfrases e **não** são observações
independentes. Os resultados serão agregados por pergunta **e** por cenário, e a
incerteza reamostra cenários.

## 12. Bootstrap

```
unidade      scenario_id
réplicas     10000
intervalo    95%
seed         20260819
```

Intervalos para Δ nDCG@5 (C2−C1) e, como secundários, Δ MRR, Δ Recall@5 e Δ taxa
de perguntas resolvidas. Proibido: usar o bootstrap para escolher configuração,
ou alterar a seed depois de observar resultados.

## 13. Decisão pré-registada

**Não existe limiar de «ganho material».** A D4.9 criou um contra a instrução da
fase e teve de o remover; aqui a magnitude é reportada como estimativa,
intervalo, casos e cenários.

- **A — EVIDENCE_FOR_HYBRID:** Δ nDCG@5 positivo **e** o intervalo de 95%
  agrupado por cenário não inclui zero **e** Recall@5 de C2 não inferior ao de C1
  **e** taxa de perguntas resolvidas de C2 não inferior à de C1. Significa
  evidência no painel independente — **não** significa produção.
- **B — EVIDENCE_FOR_DENSE:** o intervalo fica integralmente abaixo de zero, ou
  há degradação consistente das secundárias essenciais. A causa tem de ser
  documentada.
- **C — INCONCLUSIVE:** o intervalo inclui zero, os resultados são mistos, o
  ganho não é robusto entre cenários, ou a amostra continua insuficiente. **É um
  resultado válido** e não autoriza novo tuning sobre o mesmo conjunto.

Note-se a diferença face à D4.9: `A` depende de o intervalo **não incluir zero** —
uma afirmação sobre sinal e incerteza — e não de a magnitude ultrapassar um
número escolhido por quem mede.

## 14. Pooling futuro

`pool(pergunta) = top5(C0) ∪ top5(C1)`. C2 deriva dessa união e não pode
introduzir elementos novos — guarda que já existe desde a D4.9.

Todo o elemento do pool tem de ser julgado antes de qualquer métrica final. Se
`unjudged_in_top_k > 0` numa pergunta, **essa pergunta não entra nas métricas**
até o julgamento estar completo. Não se assume zero.

Os graus 0/1/2 **não existem nesta fase** e há teste que o verifica: só podem ser
atribuídos depois de haver rankings para julgar.

## 15. Congelamento dos embeddings

Pré-registado para a D4.10b: os vetores das perguntas são gerados **uma vez** e
congelados antes de qualquer medição, cada um com `question_id`,
`content_sha256`, `provider`, `model`, `dimension`, `normalization`,
`similarity_metric`, `configuration_version`, `vector_digest` e o vetor. Depois
do congelamento, a D4.10b não volta a consultar o fornecedor.

A razão é medida, não teórica: a D4.8 observou deriva do fornecedor na ordem de
1e-4 na similaridade **para o mesmo texto**. Nenhum vetor foi gerado nesta fase.

## 16. Limitações

1. **A validação humana não está feita.** 50 perguntas pendentes, `annotator`
   nulo, `freeze_ready` falso. O que existe é uma proposta auditável.
2. **Continua a ser um corpus, um snapshot, um anotador, um modelo.** O painel é
   maior; a generalização institucional não é demonstrada por isto.
3. **P1-DOC-001 está fora do corpus indexado** e nenhuma pergunta o cobre.
4. **P1-DOC-006 tem um só cenário**, porque a D4.8.2 esgotou o regulamento.
5. **Quantas perguntas permitem à fusão agir é desconhecido** e será um
   **resultado** da D4.10b, não um critério de seleção. Nenhuma pergunta será
   removida por C0 devolver vazio.
6. **50 perguntas em 32 cenários é uma decisão de desenho**, justificada por
   cobertura documental e diversidade semântica — **não** um cálculo de poder
   estatístico. O bootstrap reamostra 32 unidades, e isso é pouco.
7. **SC-N04 tem proximidade semântica declarada** com DA036/DA037.
8. O painel foi desenhado por leitura do corpus indexado, não do PDF original:
   herda o que o OCR e o chunking produziram.

## 17. Critérios para desbloquear a D4.10b

A D4.10b só pode começar quando:

1. cada pergunta tiver `review_status = HUMAN_CONFIRMED` com `annotator`
   nomeado, ou for removida do conjunto **antes** de qualquer execução;
2. `human_review.freeze_ready` for `true`;
3. o conjunto for **recarimbado** — o `human_review_digest` muda com a revisão —
   e o protocolo reselado, com o `protocol_digest` final versionado;
4. a selagem estiver **num commit anterior** ao da execução — é isso que dá à
   ordem temporal uma prova que a D4.9 não tinha.

A D4.10b receberá `protocol_digest`, `question_set_digest`, `scenario_digest` e
`human_review_digest` e recusará correr se algum divergir.

## 18. Estado

```
protocol_digest      6b066812d5c4ab7e8dc5d5095daad409549f6c0d71585bd782f25512d66e9b2a
question_set_digest  666ddb6f41e805f24dd885ef709527ad21ef11144c89638ac4488b126a77d093
scenario_digest      1900150ef10729f85fee2d863fab612f0eb4cbc8ee8226257cb5d3efa686bb29
human_review_digest  dccdb73a5722b0ed1513b67afd9eeca16be95b1d03dcddf02c5613735cbf3845
freeze_ready         false  (50 validações por confirmar)
```

O `question_set_digest` é o mesmo de antes da correção da §8.1 — o conteúdo das
perguntas não mudou, e é isso que ele cobre. O `scenario_digest` mudou porque
passou a cobrir os metadados dos cenários, e o `protocol_digest` mudou por
consequência.

Estes digests **não são finais**: o `human_review_digest` mudará com a revisão
humana, e com ele o `protocol_digest`. A selagem que a D4.10b terá de citar é a
que existir depois disso.

## 19. Reprodução

```bash
cd backend

python -m scripts.stamp_d4_10_question_set \
    --question-set ../docs/evaluation/d4-10-question-set-v1.json

python -m scripts.seal_d4_10_protocol \
    --question-set ../docs/evaluation/d4-10-question-set-v1.json \
    --snapshot ../storage/pilot-corpus/evaluation-snapshot-S1.json \
    --output ../docs/evaluation/d4-10-protocol-v1.json --overwrite
```

Para verificar sem escrever — é o que interessa a quem audita:

```bash
python -m scripts.stamp_d4_10_question_set \
    --question-set ../docs/evaluation/d4-10-question-set-v1.json --check
```

Não é preciso base de dados, chave de API nem rede.
