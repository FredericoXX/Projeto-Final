# D4.2 — Baseline lexical real sobre o Pilot Corpus P1 e o Snapshot S1

Relatório de fase. Documento **histórico**: regista a medição e a análise no
momento em que foram feitas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo

Medir, pela primeira vez, a recuperação real sobre documentação institucional
real:

```
Pilot Corpus P1  +  Evaluation Snapshot S1  +  Retrieval Ground Truth
        +
retrieval lexical atual, inalterado
        ↓
Recall@k · MRR · nDCG@k  →  análise de tipos de falha
```

Esta fase **mede**. Não melhora, não afina e não decide arquitetura. Nenhum
parâmetro de ranking, limiar, planeamento de consulta, segmentação, extração,
OCR, `top_k` ou estratégia foi alterado. O defeito **BUG-D4.1-01**, identificado
em D4.1, **não** foi corrigido: a baseline mede o sistema com ele.

## 2. Configuração experimental

| Item | Valor |
| --- | --- |
| `origin/main` verificada | `d3055d7d7c4d456e1014861ac4a819921f3ab09c` (merge do Pull Request #49) |
| Branch de trabalho | `feat/d4-2-lexical-baseline`, criada a partir de `origin/main` |
| Corpus | P1 — 6 documentos, 6 versões, 1834 segmentos elegíveis |
| `snapshot_id` | `a94f940229152a3b61860b370df8cb3ea8fe1a0e7236d65e86fe4b5118baf4c1` |
| `corpus_digest` | `e8a0f08b5ecf37821244e62c266a48b1d64c928cabb75e0e23e08f9c895a447e` |
| `reference_date` | `2026-08-15` |
| `strategy` / `pipeline_version` | `lexical` / `lexical_pipeline_v1` |
| `scoring_version` | `lexical_composite_v1` |
| `language` / `fts_config` | `pt` / `portuguese` |
| `top_k` / `official_only` | `5` / `true` |
| `min_relevance_score` / `candidate_limit` | `0.05` / `25` |

### 2.1 O snapshot é condição de execução

O *runner* **reconstrói** o snapshot com o builder real antes de medir e compara
`snapshot_id` e `corpus_digest` com os declarados no ficheiro de anotações. Se
divergirem, nada é escrito e o processo termina com código 3. Medir contra um
corpus que já não é aquele contra o qual as anotações foram feitas produziria
números que pareceriam comparáveis e não seriam — e criar um S2 em silêncio seria
a pior forma de o descobrir.

Verificação nesta execução: **coincidem**. S1 continua a ser o contexto
experimental em vigor.

O protocolo de métricas também é verificado e não presumido: os valores de
`metric_protocol` no ficheiro de anotações têm de coincidir com as constantes de
`app.evaluation.retrieval_metrics`. Se divergirem, código 4.

## 3. Implementação

Duas peças, nenhuma delas exposta por HTTP, sem tabela nova e sem migration:

```
app/evaluation/retrieval_metrics.py     métricas puras (sem SQLAlchemy, sem Settings)
scripts/evaluate_retrieval_baseline.py  execução contra a base + artefacto
```

`retrieval_metrics.py` **não** é reexportado por `app/evaluation/__init__.py`,
pela mesma razão que `results.py` e `snapshot.py` não o são: a garantia de que
importar `app.evaluation.assets` não carrega `sqlalchemy` não deve depender de
disciplina.

A pergunta é normalizada com `normalize_text` e passada a
`PostgresLexicalRetriever.search` exatamente como
`app.services.retrieval_service` o faz. A `reference_date` é a de S1 e não a data
corrente: o serviço usa `datetime.now(UTC).date()`, o que seria irreprodutível.

**58 testes novos**, sobre dados **sintéticos**, em três ficheiros:

| Ficheiro | N | Cobre |
| --- | --- | --- |
| `tests/test_retrieval_metrics.py` | 30 | aritmética de Recall@k, MRR e nDCG@k, e as constantes do protocolo |
| `tests/test_retrieval_baseline_runner.py` | 16 | protocolo declarado, índice do binding, agregação macro e digest sem carimbo temporal |
| `tests/test_retrieval_baseline_diagnostics.py` | 12 | contrafactual de elegibilidade, destino do alvo nos quatro estados, e recusa por divergência de snapshot |

O terceiro ficheiro existe por uma razão específica: fixa as duas guardas
introduzidas depois de dois erros causais reais cometidos nesta fase — aproximar
a elegibilidade por *stemming* (que fazia `residencia` parecer casar
`residencias`) e classificar como "nunca foi candidato" um segmento que o `top_k`
podia ter truncado. Sem teste, ambas voltariam a degradar-se em silêncio.

Nenhum documento institucional real, excerto ou identificador de P1 entrou na
suite.

## 4. Perguntas avaliadas

Das 14 perguntas do *ground truth*:

| Grupo | N | Tratamento |
| --- | --- | --- |
| Medidas | **12** | entram em Recall, MRR e nDCG |
| `no_relevant_evidence` (Q013) | 1 | métricas indefinidas; observada separadamente |
| `excluded_from_metrics` (Q014) | 1 | ambiguidade temporal declarada; observada separadamente |

Nenhuma pergunta e nenhum julgamento foram alterados. O *ground truth* usado é
exatamente o integrado pelo Pull Request #49.

## 5. Métricas

Protocolo fixado em D4.1, aplicado sem alteração: relevância binária no **grau
2** para Recall e MRR; ganhos nDCG **0 / 1 / 3**; segmentos não julgados contam
como grau 0; agregação **macro** (cada pergunta pesa o mesmo).

| Métrica | Valor |
| --- | --- |
| Recall@1 | **0,2083** |
| Recall@3 | **0,4167** |
| Recall@5 | **0,4583** |
| MRR | **0,3750** |
| nDCG@1 | **0,2500** |
| nDCG@3 | **0,3323** |
| nDCG@5 | **0,3630** |

O *reciprocal rank* é **truncado** pela lista devolvida: se o primeiro relevante
estivesse na posição 7 de uma lista de 5, o valor é 0 e não 1/7. Pedir mais
resultados do que a configuração real devolve mediria um sistema diferente.

### 5.1 Reprodutibilidade

Quatro execuções sobre S1 inalterado. As duas últimas, já com o artefacto na sua
forma final, produziram `result_digest`
`b00ca87b01f47a1aa618c775354940f8b4d9d45903c01ae999efd4e9a0cc7fb4` e *payloads*
idênticos campo a campo, excluindo apenas `executed_at`. O digest é calculado
sobre o *payload* **sem** o carimbo temporal, precisamente para que duas
execuções idênticas não sejam indistinguíveis de duas execuções divergentes.

O determinismo não é acidental: `_ranking_key` impõe uma ordem total com
desempate explícito até `chunk_id`, e a consulta de candidatos ordena por
`(score, document_id, chunk_index, chunk_id)`.

## 6. Resultados por pergunta

`R@5` = Recall@5, `RR` = reciprocal rank, `nD@5` = nDCG@5. "Devolvidas" é o
número de evidências que o sistema apresentou.

| ID | Dificuldade | Devolvidas | R@5 | RR | nD@5 | Destino do alvo |
| --- | --- | --- | --- | --- | --- | --- |
| Q001 | data, tabela | 4 | 0,50 | 0,50 | 0,39 | 1 devolvido, 1 nunca candidato |
| Q002 | data, tabela | 2 | 1,00 | 0,50 | 0,63 | devolvido (posição 2) |
| Q003 | paráfrase, data | 1 | **0,00** | 0,00 | 0,00 | nunca candidato |
| Q004 | acrónimo | 3 | 1,00 | 0,50 | 0,63 | devolvido (posição 2) |
| Q005 | sinónimo, regra | 5 | 1,00 | 1,00 | 0,83 | devolvido (posição 1) |
| Q006 | regra numérica | **0** | **0,00** | 0,00 | 0,00 | nunca candidato |
| Q007 | paráfrase, regra | **0** | **0,00** | 0,00 | 0,00 | candidato **excluído**, cobertura 0,250 |
| Q008 | regra numérica | **0** | **0,00** | 0,00 | 0,00 | candidato **excluído**, cobertura 0,400 |
| Q009 | paráfrase, secção | **0** | **0,00** | 0,00 | 0,00 | nunca candidato |
| Q010 | acrónimo, tabela | 1 | 1,00 | 1,00 | 1,00 | devolvido (posição 1) |
| Q011 | desambiguação de ano | 4 | 1,00 | 1,00 | 0,88 | ambos devolvidos |
| Q012 | referência entre documentos | **0** | **0,00** | 0,00 | 0,00 | nunca candidato |

**Cinco perguntas devolveram lista vazia.** Seis das doze têm Recall@5 = 0. O
sistema não errou a ordenação nestas: não apresentou nada.

### 6.1 O que o Recall sozinho esconde

Um zero tem pelo menos duas causas distintas, e a métrica confunde-as. O
artefacto regista, por isso, o **destino** de cada segmento de grau 2 — um facto
observável, não uma interpretação:

| Destino | N | Significado |
| --- | --- | --- |
| `RETURNED` | 7 | apareceu na lista |
| `CANDIDATE_EXCLUDED` | 2 | o retriever viu-o e rejeitou-o na elegibilidade lexical |
| `NEVER_A_CANDIDATE` | 5 | nunca entrou no conjunto de candidatos |

Para os cinco `NEVER_A_CANDIDATE` foi calculado o **contrafactual**: teriam
passado a elegibilidade caso tivessem chegado a candidatos? O cálculo usa
`compute_content_match` e `decide_eligibility` — as **funções reais**, não uma
aproximação — e está registado no artefacto, por pergunta:

| Pergunta | Termos | Casados | Cobertura | Teria sido elegível? |
| --- | --- | --- | --- | --- |
| Q001 | 6 | 2 | 0,333 | não |
| Q003 | 9 | 3 | 0,333 | não |
| Q006 | 7 | 1 | 0,143 | não |
| Q009 | 4 | 1 | 0,250 | não |
| Q012 | 7 | 1 | 0,143 | não |

**Nenhum** dos cinco teria passado. Não existe, nesta baseline, uma única falha
atribuível a privação do conjunto de candidatos: todos os alvos não avaliados
seriam rejeitados na elegibilidade de qualquer forma.

### 6.2 A correspondência da elegibilidade é exata, não lematizada

Uma primeira versão desta análise calculou o contrafactual com
`to_tsvector`/`plainto_tsquery` e concluiu que Q009 era privação do conjunto de
candidatos. **Estava errado**, e a razão é uma assimetria do próprio pipeline que
importa registar:

| Etapa | Correspondência |
| --- | --- |
| Geração de candidatos | Full-Text Search sobre `search_vector` — **com *stemming*** |
| Cobertura da elegibilidade | `term in content_set` — **forma canónica exata** |

Um segmento pode, portanto, ser recuperado pelo FTS e depois rejeitado porque a
forma de superfície difere. É exatamente o caso de Q009: a pergunta traz
`residencia`, o segmento diz `residencias`, e o FTS conflaria as duas — a
elegibilidade não. A cobertura real é 0,250 e não 0,500.

Aproximar a segunda etapa pela primeira **sobrestima** sistematicamente a
correspondência. O contrafactual passou a ser calculado pelo runner com as
funções reais, e o artefacto guarda o resultado, para que a afirmação seja
verificável em vez de reconstruída à mão.

## 7. Casos sem métrica

### Q013 — `no_relevant_evidence = true`

Não entra em Recall, MRR nem nDCG: as três são indefinidas sem conjunto
relevante. Observado:

| Facto | Valor |
| --- | --- |
| Evidências devolvidas | **0** |
| Candidatos avaliados | 8 |
| Sobreviventes antes do corte | 0 |

O sistema não apresentou evidência para uma pergunta cuja resposta não está no
corpus. Isto é o comportamento observado e **nada mais**: não é `ABSTAIN`, não é
`NOT_ANSWERABLE` e não é `ESCALATE`. Esses são conceitos de política, dependem de
O1–O7 e continuam por decidir. Note-se ainda que o mesmo comportamento — lista
vazia — ocorre em cinco perguntas cuja evidência **existe** no corpus; a lista
vazia, por si só, não distingue "não há resposta" de "não a encontrei".

### Q014 — `excluded_from_metrics = true`

Ambiguidade temporal declarada. Devolveu 3 evidências; a primeira é o segmento de
grau 2 da interpretação 2025/2026 (score 0,5607), e o segmento de grau 2 da
interpretação 2023/2024 foi **candidato excluído** por cobertura 0,400. A
exclusão das métricas mantém-se: escolher qual das duas conta exigiria a
convenção institucional de vigência, que continua desconhecida.

## 8. Tipos de falha

Classificação das seis perguntas com Recall@5 = 0, mais a falha parcial de Q001.
Cada uma com o mecanismo observado, não inferido.

| Tipo | N | Perguntas | Observação |
| --- | --- | --- | --- |
| `LEXICAL_MISMATCH` | **6** | Q003, Q006, Q007, Q008, Q009, Q012 | cobertura por **forma exata** abaixo de 0,5 |
| `CHUNKING_DEGRADATION` | **0** | — | ver §8.1: nenhum caso sobrevive à verificação |
| `EVIDENCE_NOT_RETRIEVED` (privação de candidatos) | **0** | — | ver §6.1: nenhum alvo não avaliado seria elegível |
| `TEMPORAL_DISTRACTOR` | **0** | — | ver §8.5 |
| `RELEVANT_EVIDENCE_LOW_RANK` | **0** | — | nenhum alvo foi devolvido em má posição; ou aparece cedo, ou não aparece |
| `OCR_DEGRADATION` | **0** | — | o documento com OCR (P1-DOC-002) é o que sustenta as perguntas mais bem-sucedidas |
| Falha parcial | 1 | Q001 | evidência duplicada: um dos dois segmentos de grau 2 foi devolvido |

**As seis falhas têm o mesmo mecanismo.** Não é ordenação, não é geração de
candidatos e não é — de forma demonstrável — fragmentação: é o limiar de
cobertura de 0,5 aplicado sobre correspondência de **forma canónica exata**.

O que varia entre elas é a natureza da divergência de forma:

| Sub-causa | Perguntas | Exemplo |
| --- | --- | --- |
| Morfologia (singular/plural, nominalização) | Q008, Q009 | `residencia` / `residencias`; `prorrogacao` / `prorrogar` |
| Sinonímia institucional | Q012, Q007 | *entrega dos diplomas* / *outorga de grau* |
| Formulação numérica | Q006 | *percentagem mínima* / `75%` |
| Comprimento da pergunta eleva o mínimo exigido | Q003 | 9 termos exigem 5 correspondências |

A repartição importa para o passo seguinte: **apenas a primeira linha** — duas
perguntas, Q008 e Q009 — é divergência de flexão que normalização morfológica
resolveria. A sinonímia institucional, a formulação numérica e o efeito do
comprimento da pergunta **não** são resolvidos por normalização, e cada uma
exigiria um trabalho diferente.

### 8.1 Q006 e a fragmentação: uma hipótese que não sobreviveu

A regra que responde à pergunta **está** partida a meio da frase entre dois
segmentos consecutivos de P1-DOC-004:

- segmento 183 termina em `...com componente pratica laboratorial a frequencia desta`;
- segmento 184 começa em `pratica e obrigatoria em 75%...`.

Uma redação anterior deste relatório atribuiu a separação ao preenchimento de
layout consumir o orçamento de 1200 caracteres, e declarou Q006 como impacto
**direto** de BUG-D4.1-01. **Duas verificações desmentiram-no.**

**Primeira — o orçamento não foi excedido.** Os *spans* brutos são 83 e 993
caracteres; somados, 1076, abaixo dos 1200. A separação ocorreu porque
`_units_are_compatible` recusa juntar unidades de **estrutura diferente**, e 183
é `list_item` enquanto 184 é `paragraph`. É uma fronteira estrutural, não um
orçamento esgotado.

**Segunda — mesmo unidos, falhariam.** Concatenando o texto normalizado dos dois
segmentos e passando-o por `compute_content_match` e `decide_eligibility`:

| Sujeito | Casados | Cobertura | Elegível |
| --- | --- | --- | --- |
| segmento 183 isolado | 3 / 7 | 0,429 | não |
| segmento 184 isolado | 1 / 7 | 0,143 | não |
| **183 + 184 combinados** | **3 / 7** | **0,429** | **não** |

A união não acrescenta nada: o 184 só contribui `pratica`, que o 183 já tinha, e
os termos `percentagem`, `minima`, `exigida` e `presencas` não existem no texto
sob forma exata — o documento escreve `75%` e `presenca`.

Conclusão: **`CHUNKING_DEGRADATION` não se sustenta como causa de Q006.** A causa
é a mesma das restantes: cobertura exata abaixo do limiar. A fragmentação é real e
observável, mas não é o que faz esta pergunta falhar.

Note-se que BUG-D4.1-01 **está** presente no segmento 184 — 993 caracteres brutos
para 163 de texto útil, 83 % de preenchimento. O defeito existe; o que não se
confirma é que seja a causa desta falha.

### 8.2 `LEXICAL_MISMATCH` — Q003, Q007, Q012

Distância de vocabulário entre linguagem de atendimento e linguagem normativa:

- **Q012** é o caso extremo: a pergunta diz *entrega dos diplomas*, o corpus diz
  *outorga de grau*. O segmento-alvo tem 57 caracteres e casa **um** dos sete
  termos (`cerimonia`), cobertura 0,143;
- **Q007** pergunta *durante quantos anos posso continuar alojado*; o documento
  responde com *renovável até ao máximo de quatro anos letivos*. O segmento foi
  candidato e caiu com cobertura 0,250;
- **Q003** tem nove termos informativos, o que exige cinco correspondências; o
  alvo casa três.

### 8.3 Divergência morfológica — Q008 e Q009

As duas falhas com a causa mais estreita, e as mais informativas para o passo
seguinte, porque a divergência é de **forma** e não de sentido:

- **Q009**: a pergunta traz `residencia`; o segmento-alvo escreve `residencias`.
  Casa apenas `candidato`, cobertura 0,250;
- **Q008**: a pergunta traz `prorrogacao`; o segmento escreve `prorrogar`. Casa
  `alojamento` e `antecedencia`, cobertura 0,400, quando eram exigidos 3 de 5.

Nos dois casos o sentido está presente no segmento e a resposta é a correta. O
que falha é a comparação de superfície descrita em §6.2.

**Observação separada sobre o FTS.** A geração de candidatos usa o *stemmer*
português, e aí existe um defeito distinto, verificado diretamente:

```
to_tsvector('portuguese', 'prorrogação') -> 'prorrog'
to_tsvector('portuguese', 'prorrogar')   -> 'prorrog'     ← conflaem
to_tsvector('portuguese', 'prorrogacao') -> 'prorrogaca'  ← não conflaem
```

O texto é normalizado **sem acentos** antes de chegar ao FTS, o que retira ao
*stemmer* o acento de que a regra `-ção` depende. Registado como **BUG-D4.2-01**,
severidade MEDIUM, **não corrigido**.

**O seu impacto nesta baseline não está demonstrado.** O segmento de Q008 foi
recuperado como candidato apesar disso, e caiu depois na cobertura exata, que não
usa *stemming* nenhum. O defeito é real na etapa de geração; não é o que fez esta
pergunta falhar.

### 8.4 O orçamento de candidatos é subutilizado, e isso não explica nenhuma falha

Observação estrutural, quantificada sobre as 14 perguntas e agora registada no
artefacto:

| Variante | Candidatos devolvidos |
| --- | --- |
| `exact` | **0 em 14 perguntas** |
| `reduced_and` | **0 em 14 perguntas** |
| `canonical_relaxed_and` | 3, só em Q014 (planeada em 4 perguntas) |
| `reduced_or` | a única que produz candidatos com regularidade |

O orçamento global é repartido pelas variantes **a priori** e a quota não usada
não é redistribuída. Consequência: orçamento total 350, candidatos efetivamente
avaliados **104** — **29,7 %** de utilização. O sistema avalia 6 a 8 candidatos
quando podia avaliar 25.

**Nenhuma das seis falhas é atribuível a isto.** O contrafactual de §6.1 mostra
que os cinco alvos não avaliados seriam rejeitados na elegibilidade mesmo que o
orçamento os tivesse alcançado. A subutilização é um facto do sistema com efeito
**não observado** nesta amostra — fica registada como tal, e não como causa.

### 8.5 O distractor temporal não se materializou

**Nenhum** dos nove distractores anotados a grau 0 foi recuperado, em nenhuma
pergunta. A contaminação entre anos letivos, que motivou boa parte do trabalho de
anotação em D4.1, **não ocorreu** nesta baseline.

Não se deve ler isto como desambiguação temporal bem-sucedida. O sistema não
distingue anos: recupera tão pouco que os distractores ficam invisíveis pela mesma
razão que a evidência correta fica. O trabalho de anotação continua a ser
necessário — passa a ser testável quando a cobertura de recuperação subir.

### 8.6 Ruído nas posições ocupadas

Das 20 posições devolvidas nas 12 perguntas medidas, **12 (60 %)** são segmentos
**não julgados**, que contam como grau 0 pela convenção `ASSUMED_IRRELEVANT`. Isto
não prova que sejam irrelevantes — prova que o conjunto de julgamentos é
incompleto, e é a razão pela qual o enviesamento de Recall e nDCG é
indeterminado (D4.1 §19.2).

## 9. BUG-D4.1-01: impacto observado

**Impacto na baseline: INCONCLUSIVO. Não corrigido: SIM.**

O defeito **existe** e é observável no corpus — o segmento 184 de P1-DOC-004 tem
993 caracteres brutos para 163 de texto útil, 83 % de preenchimento. O que não se
sustenta é atribuir-lhe qualquer das falhas medidas:

| Hipótese inicial | Estado após verificação |
| --- | --- |
| Q006 falha porque o preenchimento partiu a frase | **refutada** — o *span* combinado (1076) cabe no orçamento (1200); a separação é estrutural, e mesmo unidos os segmentos não passam a elegibilidade (§8.1) |
| As variantes conjuntivas não produzem candidatos porque os segmentos são pequenos | **plausível, não testada** — e sem efeito observado, porque nenhum alvo não avaliado seria elegível (§8.4) |

Manter "impacto SIM" com base num mecanismo plausível seria confundir a existência
do defeito com a demonstração do seu efeito. O contrafactual que decidiria a
questão — resegmentar sem preenchimento e voltar a medir — exige alterar o
pipeline, que é precisamente o que esta fase não faz. Fica como pergunta em
aberto, e é uma das razões para o passo seguinte.

## 10. Limitações

Nenhuma destas é contornável com os dados desta fase, e todas afetam a leitura
dos números:

- **Corpus piloto pequeno.** Seis documentos, todos do Conselho da Universidade.
  Não cobre editais, guias de serviços nem páginas institucionais.
- **Perguntas construídas.** `constructed_from_public_documents`. **Não são
  perguntas reais de estudantes** e não representam a distribuição real de
  pedidos, que pertence à categoria B (estado UNKNOWN).
- **Anotador único.** `SINGLE_ANNOTATOR_PILOT`, sem medida de concordância.
- **Conjunto de julgamentos incompleto.** `DIRECTED_JUDGMENT_INCOMPLETE`.
  Precision@k e MRR são pessimistas por construção; **Recall@k e nDCG@k têm
  enviesamento indeterminado**. Nenhuma métrica é comparável entre sistemas sem
  *repooling*.
- **Amostra de 12 perguntas medidas.** Cada pergunta vale 1/12 ≈ 8,3 pontos
  percentuais do Recall macro. Não são apresentados intervalos de confiança
  porque a amostra não os suporta.
- **BUG-D4.1-01 presente**, por decisão de âmbito.
- **Reprodutibilidade local.** S1 é reproduzível na instalação onde foi
  produzido.

## 11. Interpretação

Estes números **não** são o desempenho do assistente na Uni-CV, e nada neste
relatório deve ser citado como tal. São uma **baseline diagnóstica e formativa**:
o seu valor está em localizar falhas, não em estimar qualidade.

O que a medição estabelece com segurança:

1. existe agora um ponto de referência reprodutível — `result_digest`
   `b00ca87b…7fb4` contra S1 — contra o qual qualquer alteração futura pode ser
   comparada em vez de presumida;
2. o modo de falha dominante **não é ordenação**. Em nenhuma pergunta o alvo foi
   devolvido em má posição: ou aparece cedo, ou não aparece. Sete alvos foram
   devolvidos, dois foram vistos e rejeitados, cinco nunca foram avaliados;
3. as seis falhas têm **um único mecanismo** — cobertura por forma canónica
   exata abaixo de 0,5 —, e não os três que uma primeira leitura sugeriu.
   Fragmentação de segmentos e privação do conjunto de candidatos foram ambas
   testadas e **refutadas** como causa;
4. dentro desse mecanismo, **duas das seis falhas são puramente morfológicas**
   (`residencia`/`residencias`, `prorrogacao`/`prorrogar`): o sentido está no
   segmento, e o que falha é a comparação de superfície;
5. o comportamento perante uma pergunta sem resposta no corpus (Q013) é
   indistinguível do comportamento perante cinco perguntas cuja resposta existe.
   Isto é observação, não veredicto de política.

Uma nota metodológica sobre o próprio protocolo: tornar as perguntas
*well-posed* em D4.1, acrescentando o ano letivo, **aumentou** o número de termos
informativos e, com ele, o número de correspondências exigidas pelo limiar de
cobertura. Em Q012 nenhum dos dois tokens de ano aparece no segmento-alvo. A
decisão continua correta — sem o ano a relevância era indeterminável — mas o seu
custo métrico é real e fica declarado.

**Nenhuma decisão entre lexical e denso/híbrido foi tomada.** Nada nestes
resultados a autoriza. Que seis falhas sejam `LEXICAL_MISMATCH` parece, à
primeira vista, um argumento para *embeddings* — mas duas delas são divergências
de **flexão** que qualquer normalização morfológica resolveria, e o custo dessa
correção não se compara com o de mudar de estratégia de recuperação. Medir uma
alternativa antes de esgotar as correções baratas atribuiria à estratégia um
ganho que pertencia à normalização.

## 12. Próximo passo recomendado

**B — investigar o defeito concreto encontrado: a assimetria de correspondência
entre geração de candidatos e elegibilidade.**

Esta recomendação **mudou** face à primeira redação, que propunha A (corrigir
BUG-D4.1-01 e produzir S2). A mudança decorre das duas verificações que
refutaram a atribuição de falhas à fragmentação: com Q006 explicada pela
cobertura exata e não pelo orçamento de segmentação, deixa de haver evidência de
que corrigir BUG-D4.1-01 melhore alguma das falhas medidas.

O que a evidência sustenta:

- **6 de 6 falhas** passam pelo mesmo ponto — a cobertura por forma canónica
  exata contra um limiar de 0,5;
- **2 de 6** são divergências puramente morfológicas, e o FTS que gera os
  candidatos **já** as conflaí. A elegibilidade desfaz o que a geração fez;
- BUG-D4.2-01 mostra que mesmo o *stemming* da geração está degradado pela
  remoção de acentos.

Isto é um defeito concreto, localizado e testável, e não uma decisão
arquitetural. Investigá-lo **não** é implementá-lo: a questão de desenho — se a
cobertura deve comparar formas canónicas, lemas, ou ambos com pesos distintos —
não é decidida aqui.

**A continua necessário, mas mais tarde.** BUG-D4.1-01 é um defeito real e por
corrigir; o que esta baseline mostra é que corrigi-lo primeiro não é justificado
pelos dados. Quando for corrigido, as consequências mantêm-se:

- a segmentação muda, logo mudam `chunk_digest` e **`corpus_digest`** → **novo
  snapshot S2**;
- as âncoras `corpus_item_id` + `chunk_index` do *ground truth* deixam de ser
  válidas e as anotações têm de ser **revistas**, nos termos de §15.7 do
  relatório do D4.1;
- `LEXICAL_PIPELINE_VERSION` **não** sobe por essa correção: cobre apenas etapas
  de `app/retrieval/`, e extração e segmentação vivem em `app/services/`.

Qualquer alteração à elegibilidade ou ao *stemming*, essa, **sobe**
`LEXICAL_PIPELINE_VERSION` e produz novo `snapshot_id` com o mesmo
`corpus_digest` — que é exatamente o par que o desenho do snapshot tornou
observável, e a comparação mais limpa disponível: mesmo corpus, recuperação
diferente.

**O próximo passo não foi iniciado.** Esta fase termina aqui.
