# D4.10a — Pré-registo da avaliação independente e ampliada de retrieval

Relatório de fase. Documento **histórico**: regista o desenho no momento em que
foi fixado. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

**Esta fase não executou a experiência.** Não gerou embeddings, não correu
retrieval, não construiu pool, não observou rankings, não julgou relevância, não
calculou métricas e não tomou decisão nenhuma.

## 0. Adenda corretiva — o que mudou depois do Pull Request #60

O Pull Request #60 foi aberto como *draft*, dizia no título e no primeiro
parágrafo do corpo **«validação humana pendente, NÃO fazer merge»**, declarava
`human_confirmed: 0`, `pending_human_review: 50` e `freeze_ready: false` — e foi
integrado na `main` (`bc703e1`) à mesma.

Isso não se esconde nem se aproveita. O que está na `main` é **infraestrutura de
pré-registo e um painel proposto**, não um pré-registo congelado. A separação
temporal que esta fase existe para criar continua por cumprir, e cumpre-se com
uma selagem futura: revisão humana feita, `protocol_status = SEALED`, num commit
anterior ao do primeiro embedding.

Uma auditoria subsequente encontrou quatro problemas concretos, todos corrigidos
neste trabalho:

| Problema | Onde ficou | Correção |
| --- | --- | --- |
| `HUMAN_CONFIRMED` verificava só o `review_status` e um anotador; o bloco de validação podia continuar «pendente» | §8.3 | os campos têm de concordar, nos dois sentidos, e a confirmação exige nome, método, justificação e evidência |
| `freeze_ready` contava apenas `review_status` | §8.3 | conta confirmações coerentes, e exige também a revisão de independência dos cenários |
| `seal` produzia um protocolo com `freeze_ready=false` | §8.5 | recusa (código 5, sem escrever); o artefacto provisório pede-se por `--draft` |
| bootstrap e regra A/B/C subespecificados | §12, §13 | estimador, PRNG, método do intervalo e quantil congelados em código; `B`/`C` sem termos interpretativos |
| independência semântica sem revisão estruturada | §8.4 | bloco por cenário, nos 32, coberto pelo `human_review_digest` |

Uma segunda auditoria, sobre a própria correção, encontrou mais três — todos
casos em que a garantia existia num caminho e não noutro:

| Problema | Onde ficou | Correção |
| --- | --- | --- |
| `human_review_summary` contava um cenário como revisto pelo rótulo do estado, e `build_protocol` confiava no chamador: um cenário `INDEPENDENT` sem anotador dava `freeze_ready` verdadeiro e `SEALED`, apesar de `verify_question_set` o recusar | §8.3, §8.6 | o resumo passa pela mesma verificação que a guarda, e `build_protocol` valida internamente |
| `historical_refs: ["Q999"]` era aceite — a guarda verificava o formato, não a existência | §8.4 | o manifesto enumera os 63 identificadores reais e a referência é validada contra eles |
| «apenas ANSWERABLE» era uma frase no protocolo; o bootstrap recebia um mapa já agrupado e não distinguia intenções | §12 | a seleção passa por `eligible_scenario_deltas`, que **recusa** uma NO_EVIDENCE em vez de a ignorar |

O padrão é o mesmo nos três: uma invariante verdadeira no percurso habitual e
falsa noutro. Não basta que o CLI valide antes de construir — a garantia tem de
estar onde a decisão é tomada.

**A D4.10b continua bloqueada.** Não foi executada, não foi implementada, e as
suas precondições passaram a incluir `protocol_status = SEALED`.

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

**E isto não chega.** Sobreposição zero de identificadores e de texto normalizado
é o que o código prova sozinho — não é independência semântica. Duas formulações
sem uma palavra em comum podem testar exatamente o mesmo requisito já medido, e
nenhuma verificação automática distingue isso. Marcar apenas `SC-N04` seria
tratar como excecional o que é a regra: **todos os 32 cenários** carecem de
decisão humana. Ver §8.4.

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

### 8.3 O que «confirmado» passou a significar

A guarda anterior lia o `review_status` e, quando este dizia `HUMAN_CONFIRMED`,
exigia que existisse um `annotator`. Bastava então isto para uma pergunta contar
como validada:

```
review_status     = HUMAN_CONFIRMED
annotator         = "Carlos"
validation_status = MACHINE_LOCATED_PENDING_HUMAN_CONFIRMATION
```

O campo que descreve o trabalho de validação continuava a dizer «pendente»
enquanto o resumo a contava como feita. Dois campos que descrevem o mesmo facto
não podem discordar — e a incoerência inversa, com o bloco confirmado e a
pergunta por rever, é igualmente inaceitável.

Uma confirmação afirma três coisas ao mesmo tempo: que um humano decidiu, quem
foi, e sobre que material. Passam a ser exigidas as três:

```
review_status               == HUMAN_CONFIRMED
validation.validation_status == HUMAN_CONFIRMED
annotator                   não vazio
validation_method           presente
rationale (ou search_result) não vazio
located_evidence (ou terms_searched) não vazio
```

Enquanto pendente, o `validation_status` tem de ser o estado pendente próprio do
seu bloco — uma ANSWERABLE não pode dizer que «procurou e não encontrou».

E o `freeze_ready` deixou de ser uma contagem de `review_status`: conta
confirmações **coerentes** e exige, além delas, a revisão de independência de
todos os cenários. Há teste que confirma que uma pergunta incoerente é vista pelo
resumo como não confirmada, mesmo aparecendo em `by_status` como
`HUMAN_CONFIRMED`.

**O resumo usa a guarda, não uma segunda leitura.** `question_is_confirmed` e
`scenario_review_is_final` chamam a mesma verificação que levanta `ProtocolError`
e devolvem falso quando ela recusa. A primeira versão desta correção tinha duas
leituras — a guarda exigia tudo, o resumo verificava um subconjunto — e uma
auditoria mostrou o resultado: um cenário `INDEPENDENT` sem anotador era recusado
por `verify_question_set` **e** contado como revisto pelo resumo, com
`freeze_ready` verdadeiro. Duas implementações da mesma pergunta acabam sempre
por divergir; a correção foi deixar de haver duas.

### 8.4 Independência semântica: uma decisão por cenário, todas humanas

Cada um dos 32 cenários passou a ter um bloco `historical_overlap_review`, em
`PENDING_HUMAN_REVIEW`:

| Estado final | Significado | Exige |
| --- | --- | --- |
| `INDEPENDENT` | não testa o mesmo facto/intenção já medido | `annotator` |
| `RELATED_BUT_DISTINCT` | há relação temática, mas o facto testado é distinto | `historical_refs`, `rationale`, `annotator` |
| `EXCLUDE` | reutiliza material histórico de forma que compromete a independência | `historical_refs`, `rationale`, `annotator` |

Não é preciso concluir que nenhum cenário tem relação temática com o material
anterior — estão todos no mesmo domínio institucional. O que interessa é
confirmar que **não são a mesma intenção ou o mesmo requisito factual** já
avaliado sob outra formulação.

Um cenário `EXCLUDE` **bloqueia o congelamento enquanto estiver no conjunto**:
sai, ele e todas as suas perguntas, antes de qualquer embedding — nunca depois de
se ver o que produziu. Removê-lo depois seria escolher a amostra em função do
resultado.

As referências têm de **existir**. Validar apenas o padrão `Q###`/`DA###`
aceitava `Q999` e `DA999`, que têm o formato certo e não correspondem a pergunta
nenhuma — e uma justificação que aponta para o nada não sustenta uma decisão. O
manifesto passou a enumerar os **63** identificadores reais (Q001–Q014 e
DA001–DA049), derivados dos dois artefactos históricos, e a guarda valida contra
essa lista. Há teste que confirma que a lista declarada é exatamente a que os
artefactos contêm — caso contrário estaríamos a validar contra uma ficção.

Esta revisão entra no `human_review_digest` e **não** no `scenario_digest`. Se
entrasse no `scenario_digest`, rever a independência invalidaria os cenários
revistos: a mesma armadilha que o `question_set_digest` evita ao não cobrir o
`review_status`.

Para tornar a revisão praticável há uma folha de trabalho gerada por
`scripts/build_d4_10_review_workbook.py`, com o texto de cada pergunta, a
evidência registada e — por cenário — as históricas mais parecidas. **Gerar a
folha não é tê-la preenchido**, e o comando não escreve no conjunto de perguntas.

A folha mostra também onde o seu próprio auxílio falha. Em `SC-N04`, as duas
históricas que este projeto já identificou como a preocupação real — DA036 e
DA037 — ficam em **sexto lugar e abaixo** por sobreposição de palavras, atrás de
`Q001`, `DA013`, `DA014`, `DA015` e `Q012`, todas menos aparentadas. O parentesco
que interessa — perguntar por datas de aulas de um ano que o corpus não cobre —
não está nas palavras. Por isso o que o registo já cita aparece sempre, marcado,
à margem da ordenação; e por isso a decisão é humana.

### 8.5 `DRAFT` e `SEALED`

O comando chamava-se `seal` e aceitava selar um conjunto com cinquenta validações
por fazer, limitando-se a registar no artefacto que havia pendências. Isso não é
selar: é produzir um ficheiro com ar de definitivo.

Agora `seal_d4_10_protocol` **recusa** enquanto `freeze_ready` for falso — sai
com código 5, distinto do código de guarda violada, e não escreve nada. Quem
quiser o artefacto provisório pede-o pelo nome:

```bash
python -m scripts.seal_d4_10_protocol ... --draft
```

`--draft` autoriza produzir com revisão pendente; **não escolhe o estado**. O
`protocol_status` é derivado da revisão real, e por isso um conjunto totalmente
revisto sela como `SEALED` mesmo que a opção seja passada. Só `SEALED` satisfaz
as precondições da D4.10b.

O artefacto atualmente versionado é, e declara-se, `DRAFT`.

### 8.6 A validação não depende de por onde se entra

`build_protocol` assumia que o chamador já tinha validado o conjunto — o que era
verdade no CLI e falso para qualquer outro uso. Quem chamasse a função
diretamente obtinha `protocol_status = SEALED` a partir de um conjunto que
`verify_question_set` recusa.

Agora `build_protocol` valida internamente. É trabalho repetido no percurso
normal, e é o preço de a invariante ser da função e não do percurso.

## 9. Prevenção de leakage

O que esta fase impede, e como:

| Risco | Barreira |
| --- | --- |
| escolher perguntas depois de ver rankings | nenhum retrieval foi executado; o comando de selagem não importa retrievers, embeddings nem a fusão — verificado por AST |
| mover uma paráfrase entre cenários | muda `question_set_digest` **e** `scenario_digest` |
| editar uma pergunta ou trocar um rótulo | muda `question_set_digest` |
| redefinir o tipo ou o tópico de um cenário | muda `scenario_digest` |
| reescrever quem validou, o quê ou com que evidência | muda `human_review_digest` |
| reescrever uma decisão de independência | muda `human_review_digest` |
| marcar uma pergunta como confirmada deixando a validação pendente | `verify_question_set` recusa, nos dois sentidos |
| selar antes de a revisão humana estar feita | `seal_d4_10_protocol` sai com código 5 e não escreve |
| um protocolo `DRAFT` autorizar a D4.10b | `protocol_status = SEALED` é precondição declarada |
| escolher o método do intervalo depois de ver os dados | congelado em código, com testes |
| escolher o ramo A/B/C interpretativamente | a regra é total; `C` é o caso por omissão |
| justificar independência com uma pergunta que não existe | referências validadas contra os 63 identificadores reais |
| uma NO_EVIDENCE entrar no bootstrap | `eligible_scenario_deltas` recusa |
| construir um protocolo sem passar pela validação | `build_protocol` valida internamente |
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

Fixar unidade, réplicas, intervalo e seed **não determina um resultado**. A
primeira versão desta secção parava aí, e uma auditoria mostrou o que ficava em
aberto: se o intervalo é *percentile*, *basic* ou BCa; se cada pergunta pesa um
ou cada cenário pesa um; como entra um cenário sorteado duas vezes; que perguntas
participam; como se calcula a taxa de perguntas resolvidas. Duas implementações
razoáveis dariam intervalos diferentes — e a decisão A/B/C depende do intervalo.
Deixar isso por decidir era guardar para depois da medição uma escolha que a
muda.

Está tudo congelado, e em código:

```
unidade            scenario_id
elegíveis          apenas perguntas ANSWERABLE
estimador          macro-média por cenário
réplicas           10000
seed               20260819
PRNG               random.Random(seed).choices
intervalo          percentile, 95%
quantis            2,5% e 97,5%
método do quantil  linear (Hyndman-Fan tipo 7)
implementação      app/evaluation/d4_10_statistics.py
```

**O estimador, por extenso.** Para cada pergunta ANSWERABLE, `delta =
métrica(C2) − métrica(C1)`. Para cada cenário, a média aritmética dos deltas das
suas perguntas. O estimador é a média aritmética desses valores por cenário.
Cada cenário pesa **um**: um cenário com duas paráfrases não vale duas
observações, pela mesma razão que a unidade de reamostragem é o cenário.

**A réplica, por extenso.** Ordenar os `scenario_id` elegíveis
lexicograficamente — sem ordem fixa, a mesma seed daria sequências diferentes
conforme a ordem de iteração do mapa. Sortear N identificadores **com
reposição**, sendo N o número de cenários elegíveis; cada ocorrência contribui
com a média do seu cenário; a estatística da réplica é a média aritmética dos N
valores. As perguntas nunca são reamostradas individualmente.

**Perguntas NO_EVIDENCE não entram** em nenhum bootstrap de retrieval: sem alvo
relevante, nDCG, Recall e MRR não estão definidos. São analisadas à parte por
`returned_count`, graus 0 e 1 devolvidos e ruído por pergunta. Nenhuma política
de admissão entra nesta fase.

Isto era uma frase no protocolo e passou a ser uma função. O bootstrap recebe um
mapa já agrupado por cenário e não tem como saber que intenções lhe deram origem:
uma NO_EVIDENCE que entrasse por engano ficava invisível, e o número que saísse
daí não significaria nada. A seleção passa por `eligible_scenario_deltas`, que
**recusa** — não ignora. Ignorar em silêncio esconderia o erro de quem chama; e
há teste que passa uma NO_EVIDENCE e exige a recusa.

**Taxa de perguntas resolvidas:** por pergunta, 1 se existir pelo menos um
resultado de grau 2 no top-5, 0 caso contrário; agregada por cenário e depois
entre cenários, como as restantes.

O bloco que o protocolo transporta é **gerado pelo módulo que implementa o
cálculo**, e não escrito à mão ao lado dele: descrição e código não podem
divergir sem que um teste o note. A D4.10b não implementa estatística nenhuma —
chama isto.

A macro-média convencional **por pergunta** pode ser reportada para comparação
descritiva com as fases anteriores. A inferência primária é a macro-média por
cenário definida aqui.

## 13. Decisão pré-registada

**Não existe limiar de «ganho material».** A D4.9 criou um contra a instrução da
fase e teve de o remover; aqui a magnitude é reportada como estimativa,
intervalo, casos e cenários.

A regra é **total e determinística**:

```
A — EVIDENCE_FOR_HYBRID
    CI95_lower(Δ nDCG@5) > 0
    E Recall@5(C2) >= Recall@5(C1)
    E solved_question_rate(C2) >= solved_question_rate(C1)

B — EVIDENCE_FOR_DENSE
    CI95_upper(Δ nDCG@5) < 0

C — INCONCLUSIVE
    todos os restantes casos
```

Todas as quantidades são macro-médias por cenário. `A` significa evidência no
painel independente — **não** significa produção. `C` **é um resultado válido** e
não autoriza novo tuning sobre o mesmo conjunto.

**O que saiu, e porquê.** A versão anterior punha em `B` «degradação consistente
das secundárias essenciais que torne a fusão injustificável» e em `C` «resultados
mistos» e «ganho não robusto». São conceitos com sentido — mas como *critério de
classificação* devolvem ao analista a escolha do ramo depois de ver os números,
que é precisamente o que esta fase existe para impedir. Continuam a existir na
discussão; deixaram de existir no algoritmo.

**As secundárias não reclassificam.** MRR, Recall@1/@3, nDCG@1/@3, distribuição
de graus e regressões por pergunta são reportadas e discutidas, e não mudam o
ramo.

Dois pontos que a regra fixa e que valem a pena dizer: os limites são
**estritos** — um intervalo que toca exatamente zero é `C`, não `A` nem `B` — e a
regra é invariante à escala: multiplicar todos os efeitos por qualquer fator
positivo não muda a decisão. É essa propriedade, e não a redação, que o teste
verifica; se algum dia reaparecer um limiar de magnitude, ela quebra.

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

1. **A validação humana não está feita.** 50 perguntas e 32 cenários pendentes,
   `annotator` nulo, `freeze_ready` falso, protocolo em `DRAFT`. O que existe é
   uma proposta auditável — e está na `main`, o que não a torna outra coisa.
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

1. cada pergunta tiver `review_status` **e** `validation_status` em
   `HUMAN_CONFIRMED`, com `annotator` nomeado — ou for removida do conjunto
   **antes** de qualquer execução;
2. cada um dos 32 cenários tiver decisão final de independência, assinada, e
   nenhum cenário `EXCLUDE` permanecer no conjunto;
3. `human_review.freeze_ready` for `true`;
4. o conjunto for **recarimbado** — o `human_review_digest` muda com a revisão —
   e o protocolo reselado **sem** `--draft`, ficando em `protocol_status =
   SEALED`, com o `protocol_digest` final versionado;
5. a selagem estiver **num commit anterior** ao da execução — é isso que dá à
   ordem temporal uma prova que a D4.9 não tinha.

A D4.10b receberá `protocol_status`, `protocol_digest`, `question_set_digest`,
`scenario_digest` e `human_review_digest`, e recusará correr se algum divergir ou
se o estado não for `SEALED`. O runner não existe e não foi implementado nesta
fase; a precondição está formalizada no protocolo e coberta por testes.

## 18. Estado

```
protocol_status      DRAFT
protocol_digest      73522360acfe00e5d965f92b81eaee6e10e15333cd6ab12cbf587b9b44590fab
question_set_digest  666ddb6f41e805f24dd885ef709527ad21ef11144c89638ac4488b126a77d093
scenario_digest      1900150ef10729f85fee2d863fab612f0eb4cbc8ee8226257cb5d3efa686bb29
human_review_digest  0fbc06e5bf916c294aa8d5996b2b6c74013ea224b7924f1cd838a6a076c0f670
freeze_ready         false
human_confirmed      0 de 50
cenários por rever   32 de 32
```

O `question_set_digest` e o `scenario_digest` **não mudaram** com esta correção:
o conteúdo das perguntas e os metadados dos cenários são exatamente os mesmos. O
`human_review_digest` mudou, porque passou a cobrir a revisão de independência; e
o `protocol_digest` mudou por consequência, e também porque o protocolo passou a
transportar o estado, o bootstrap especificado e a regra determinística.

Estes digests **são provisórios**. Mudarão outra vez com a revisão humana, e é
essa segunda selagem — `SEALED` — que a D4.10b terá de citar.

## 19. Reprodução

```bash
cd backend

# 1. folha para a revisão humana (não decide nada)
python -m scripts.build_d4_10_review_workbook \
    --question-set ../docs/evaluation/d4-10-question-set-v1.json \
    --historical \
        ../docs/evaluation/retrieval-ground-truth-p1-lexical-dense-repooled.json \
        ../docs/evaluation/dense-admission-dataset-v1.json \
    --output ../docs/evaluation/d4-10-human-review-workbook.md

# 2. carimbo da identidade declarada
python -m scripts.stamp_d4_10_question_set \
    --question-set ../docs/evaluation/d4-10-question-set-v1.json

# 3. protocolo. Sem --draft isto recusa enquanto a revisão estiver pendente.
python -m scripts.seal_d4_10_protocol \
    --question-set ../docs/evaluation/d4-10-question-set-v1.json \
    --snapshot ../storage/pilot-corpus/evaluation-snapshot-S1.json \
    --output ../docs/evaluation/d4-10-protocol-v1.json --overwrite --draft
```

Para verificar sem escrever — é o que interessa a quem audita:

```bash
python -m scripts.stamp_d4_10_question_set \
    --question-set ../docs/evaluation/d4-10-question-set-v1.json --check
```

Não é preciso base de dados, chave de API nem rede.

## 20. O que continua por fazer

**A revisão humana.** 50 perguntas e 32 cenários. Nada nela foi fabricado: não há
uma única confirmação, nenhum `annotator` preenchido e nenhuma decisão de
independência tomada — e há teste que o verifica sobre o artefacto versionado.

Depois dela: recarimbar, reselar em `SEALED`, versionar essa selagem num commit
próprio, e só então a D4.10b — congelar os embeddings das perguntas, executar C0
e C1 e construir o pool para julgamento, ainda sem calcular a comparação final.
