# D4.8 — Baseline experimental de dense retrieval sobre P1/S1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo e hipótese

As fases D4.3 a D4.7 esgotaram, uma a uma, as explicações lexicais para as
falhas de recuperação de P1: a política de correspondência (D4.3), os
diacríticos (D4.4), o orçamento de candidatos (D4.5), os sinais de ranking
(D4.6) e a ponderação desses sinais (D4.7). A D4.7 concluiu que **nenhuma
reponderação melhora a configuração de produção**, e a D4.5 tinha já mostrado
que a maioria das falhas ocorre antes do ranking, na elegibilidade.

Esta fase testa a hipótese que restou:

> A recuperação semântica acrescenta capacidade de recuperação que o ajuste do
> mecanismo lexical demonstrou não conseguir acrescentar?

A resposta pode ser não, e o desenho tem de a admitir. Nada foi alterado em
produção: `app.retrieval.dependencies.get_retriever` continua a devolver o
retriever lexical, e há teste que o fixa.

**Não** foi implementada arquitetura híbrida, RRF, reranking semântico,
cross-encoder, reescrita de consultas nem qualquer combinação das duas
condições. A comparação C0 × C1 tinha de acontecer primeiro.

## 2. Contexto experimental

| Item | Valor |
| --- | --- |
| `origin/main` | `47c1e9cfb8e759c7ff612cf7865126a9cb81939c` (merge do Pull Request #55, D4.7) |
| Branch de trabalho | `analysis/d4-8-dense-baseline`, criada a partir de `origin/main` |
| `snapshot_id` | `a94f9402…baf4c1` — verificado antes de indexar e antes de medir |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| `ground_truth_digest` | `ada6b388…8586e` — o **repooled** da D4.6 |
| Baseline D4.2 | `result_digest` `b00ca87b…cc7fb4` — ranking de C0 reproduzido **exatamente** |
| Controlo D4.7 | `result_digest` `42000554…c8b11` — métricas de C0 reproduzidas **exatamente** |
| Índice vetorial | `index_digest` `451d9f2f…d9370c`, 1834 vetores |
| `result_digest` do D4.8 | `98f521cdbc7e1082dcc5430cd549393eda36e545e3cc7ea512b0958c64a2c783` |
| Lista de repooling | `result_digest` `e71c7a90…2ede0d`, 31 pedidos |

Três execuções sobre o índice persistido produziram *payloads* idênticos exceto
`executed_at`, incluindo o `index_digest` e a lista de repooling.

Constantes: corpus, snapshot, perguntas, `top_k`, `official_only`, idioma,
data de referência, `RetrievalEligibility`, extração, OCR, segmentação, FTS,
ranking lexical, pesos e orçamento de candidatos.

### 2.1 Guardas, por ordem de execução

1. **Integridade dos artefactos consumidos.** O ficheiro do D4.2 e o do D4.7 têm
   de coincidir com o seu próprio `result_digest`. Reproduzir os números não
   substitui esta verificação: eles são recalculados a partir da base e
   continuariam a coincidir com um digest adulterado.
2. **Protocolo de métricas** — as constantes declaradas têm de ser as
   implementadas.
3. **Identidade do conjunto de perguntas** — tem de ser o repooled do D4.6, e o
   mesmo que o D4.7 declara ter consumido. O digest esperado está **no código**:
   lê-lo do próprio ficheiro em uso verificaria apenas que ele é consistente
   consigo mesmo.
4. **Snapshot** — o corpus reconstruído tem de continuar a ser S1.
5. **Homogeneidade e cobertura do índice vetorial** — o índice tem de ser
   homogéneo para a identidade declarada, e todos os segmentos admissíveis têm
   de ter vetor **dessa** identidade. Um segmento por embeber é invisível para
   C1, e a sua ausência do resultado seria indistinguível de uma falha semântica
   do modelo; um vetor obsoleto seria pior, porque conta como coberto. Ver
   §3.3.1.
6. **Replicação de C0** — em duas frentes, porque medem coisas diferentes: o
   **ranking posicional** tem de ser o do D4.2 (o sistema não mudou), e as
   **métricas** sob o conjunto repooled têm de ser as da célula de controlo
   `A0`/`current_quota` do D4.7 (o protocolo foi aplicado da mesma maneira).

Se qualquer uma falhar, nada é escrito.

## 3. Configuração densa

### 3.1 Modelo de embeddings

| Item | Valor |
| --- | --- |
| Fornecedor | OpenAI |
| Modelo | `text-embedding-3-small` |
| Dimensão | 1536 (nativa; sem parâmetro `dimensions`) |
| Normalização aplicada pela aplicação | nenhuma |
| Métrica | cosseno |
| `configuration_version` | `openai_embeddings_v1` |
| Texto embebido | `DocumentChunk.content` |

**Justificação da escolha, e o que ela não é.** O SDK da OpenAI já é dependência
declarada do backend, pelo que a condição C1 não exigiu infraestrutura nova
nenhuma; a família `text-embedding-3` foi publicada com melhoria explícita em
recuperação multilingue, o que a torna adequada a um corpus em português
europeu; e a dimensão nativa cabe numa coluna `vector` sem redução. A
alternativa — um modelo local — exigiria acrescentar `torch` e
`sentence-transformers` ao `requirements.txt` que a CI instala, o que é uma
alteração de peso desproporcionado para uma experiência cuja conclusão pode ser
negativa.

Esta fase **não** é um benchmark de modelos de embeddings: um único modelo foi
escolhido e documentado, e nenhuma afirmação aqui depende de ele ser o melhor
disponível. Uma comparação entre modelos é trabalho separado, e a tabela
`chunk_embeddings` já a suporta sem migration (ver §3.3).

Declarar `normalization = "none"` é literal: o vetor é persistido tal como
chegou. O fornecedor devolve vetores de norma ≈ 1, mas a aplicação não
normaliza, e a similaridade do cosseno é invariante à escala — declarar
`l2_unit` seria uma afirmação falsa sobre o que está guardado.

### 3.2 O texto que cada condição vê

C0 pesquisa sobre `normalized_content` e recebe a pergunta normalizada
(`normalize_text`), como em produção e como no D4.2. C1 foi indexada sobre
`content` — a forma original, com acentuação, maiúsculas e pontuação — e recebe
a pergunta original.

A assimetria é deliberada e está registada no artefacto
(`query_preprocessing`). A normalização existe para servir o índice FTS: remove
acentos e caixa porque o *stemmer* e a comparação de termos beneficiam disso.
Um modelo de embeddings é treinado sobre texto natural, e alimentá-lo com texto
normalizado degradaria deliberadamente a condição a medir. Cada condição é
avaliada como seria efetivamente executada; as duas partem da mesma string do
ground truth.

### 3.3 Armazenamento

Tabela nova `chunk_embeddings`, com chave primária composta
`(chunk_id, provider, model)`.<sup>[correção D4.8.1](#correções-posteriores)</sup>
Nenhuma coluna de `document_chunks` foi criada, alterada ou removida;
`search_vector` e o seu índice GIN ficaram como estavam, e há teste de migration
que o verifica no `upgrade`, no `downgrade` e no `upgrade` seguinte.

`embedded_content_sha256` regista o SHA-256 do texto efetivamente enviado ao
modelo, **recalculado no momento do envio** e não copiado de
`DocumentChunk.content_sha256`. As duas definições coincidem, e é justamente por
isso que copiar seria um erro discreto: a coluna passaria a descrever o que se
supõe ter sido enviado em vez do que foi. É o que permite reconhecer um vetor
obsoleto — se o chunk for reprocessado, os dois valores divergem.

**Sem índice ANN (HNSW/IVFFlat), por decisão explícita.** Com 1834 vetores a
pesquisa exata é barata, e um índice aproximado tornaria o resultado dependente
dos seus parâmetros de recall — exatamente o que uma experiência comparativa não
pode ter.

### 3.3.1 A identidade é guardada e imposta inteira

`EmbeddingIdentity` declara `provider`, `model` e `configuration_version`, e a
tabela guarda os três. `(chunk_id, provider, model)` é a chave primária;
`configuration_version` fica fora dela de propósito, porque mudar a configuração
**invalida** o vetor anterior em vez de coexistir com ele.

A consequência é que a leitura tem de filtrar pelos três, e não só pelo nome do
modelo. Existe uma definição única desse filtro —
`ChunkEmbedding.matches_identity` — usada pela recuperação, pela contagem de
cobertura e pelo digest do índice. Três implementações paralelas do mesmo filtro
é precisamente a forma de uma delas ficar a filtrar por menos campos do que a
identidade declara.

Duas guardas separadas:

- **cobertura** — todo o segmento admissível tem de ter vetor dessa identidade;
- **homogeneidade** — nenhuma linha do `(provider, model)` declarado pode ter
  outra `configuration_version`, e nenhuma pode descrever conteúdo que o chunk
  já não tem.

Não são redundantes, mas também não o são pela razão que se poderia supor. Como
a cobertura filtra pela identidade **completa**, uma reindexação interrompida a
meio já lhe aparece como cobertura parcial — não passa despercebida. O que a
homogeneidade acrescenta é de duas ordens:

- **diagnóstico**, na configuração divergente. A cobertura diria «1830 de 1834
  segmentos embebidos», que se lê como *falta indexar*; a homogeneidade diz que
  os vetores existem e são de outra configuração, e nomeia-a. São problemas
  diferentes, com correções diferentes. Corre também antes de qualquer pesquisa,
  e não por pergunta;
- **deteção**, no conteúdo obsoleto. Aqui só ela apanha: um vetor obsoleto
  satisfaz a identidade e conta como coberto — para a cobertura, o segmento está
  indexado.

O SHA do conteúdo é **recalculado** a partir do `content` atual, e não comparado
com o `content_sha256` persistido. A diferença é o caso que interessa: se o
conteúdo mudar sem que o hash do chunk seja atualizado, os dois valores
obsoletos coincidem entre si e uma comparação entre persistidos passaria sobre
um vetor que descreve texto que já não existe. Há teste que constrói exatamente
esse estado e afirma, antes de verificar, que os dois valores persistidos
concordam.

Uma versão anterior desta fase declarava a identidade em três campos e impunha
um. A base local estava consistente e as métricas não mudaram, mas a garantia de
reprodutibilidade não existia. O índice foi reconstruído sob o esquema corrigido
— daí `index_digest` e `result_digest` diferirem dos de qualquer execução
anterior a esta correção.

### 3.4 A política de admissibilidade é reutilizada, não reimplementada

`RetrievalEligibility`, de `app.documents.retrievability`, aplicada no
PostgreSQL: C1–C4 e C6–C11 como predicados do `WHERE`, C5 pela subquery
canónica. **Similaridade vetorial nunca contorna admissibilidade** — o filtro
está na mesma consulta, não numa verificação posterior sobre vizinhos já
escolhidos. Um teste fixa a propriedade pela via forte: o conjunto que o
retriever denso consegue devolver coincide, chunk a chunk, com o que
`select_eligible_chunk_ids` seleciona, com o segmento inadmissível colocado
deliberadamente como o **mais próximo** da pergunta.

O que **não** é reutilizado é a elegibilidade **lexical**
(`app.retrieval.eligibility`), e a razão não é economia: ela é definida sobre
cobertura de termos da pergunta, e uma estratégia densa não tem termos. Aplicar
«pelo menos metade dos termos correspondidos» a um vizinho vetorial não seria
ser conservador — seria medir uma coisa com o instrumento de outra.

### 3.5 Semântica do score

`ScoreKind.DENSE_SIMILARITY`, família nova. A `version` transporta a pipeline e
a identidade do modelo, porque trocar de modelo produz números incomparáveis com
os anteriores sem mais nada mudar. `comparable_across_queries` é `False`: a
similaridade depende de onde a **pergunta** cai no espaço de embeddings, e
nenhuma calibração foi feita.

O score **não** é chamado *confidence* em lado nenhum, e não é comparável com
o score lexical. Um 0,62 de um lado não significa o mesmo que um 0,62 do outro.

### 3.6 Ausência de limiar — uma diferença de primeira ordem

C1 não aplica limiar nenhum. `settings.retrieval_min_relevance_score` é um piso
sobre o score composto lexical em [0, 1]; aplicá-lo à similaridade do cosseno
seria tratar duas escalas incomparáveis como se fossem uma.

A consequência é estrutural: **C1 não tem etapa capaz de devolver vazio**. Nas
catorze perguntas devolveu 70 de 70 resultados possíveis; C0 devolveu 23, e
devolveu **zero** em seis perguntas. O princípio constitucional de que *ausência
de resultados é uma resposta legítima* pressupõe um mecanismo que saiba
recusar — C0 tem-no, C1 não.

A afirmação é sobre o **mecanismo**, e é tudo o que os dados sustentam. Se a
abstenção de C0 estava certa, ou se os resultados que C1 devolveu nesses casos
são irrelevantes, exigiria julgá-los; a maioria está entre os 31 por julgar
(§6).

Não se acrescentou um limiar para corrigir isto: qual seria o seu valor é uma
pergunta empírica que esta fase não mediu, e um número escolhido à mão pareceria
medição sem o ser. Fica declarado como limitação e está fixado por teste.

## 4. Resultados

Doze perguntas medidas (Q013 não tem evidência no corpus; Q014 está excluída por
ambiguidade temporal). Macro-média.

| Métrica | C0 lexical | C1 denso (provisório) |
| --- | ---: | ---: |
| Recall@1 | 0,2500 | **0,5000** |
| Recall@3 | 0,4167 | **0,7917** |
| Recall@5 | 0,4583 | **0,8750** |
| MRR | 0,4167 | **0,7111** |
| nDCG@1 | 0,3333 | **0,6111** |
| nDCG@3 | 0,3637 | **0,7030** |
| nDCG@5 | 0,3867 | **0,7354** |

C0 reproduz o controlo `A0`/`current_quota` do D4.7 em todos os valores, e o seu
ranking posicional é o do D4.2 pergunta a pergunta.

**As métricas de C1 são provisórias** — ver §6. Foram **substituídas** pelas da
[D4.8.1](d4-8-1-lexical-dense-repooling.md) depois do repooling; ver
[Correções posteriores](#correções-posteriores).

### 4.1 Por pergunta

| Pergunta | R@5 C0 | R@5 C1 | RR C0 | RR C1 | nDCG@5 C0 | nDCG@5 C1 | devolvidos C0 | não julgados C1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Q001 | 0,500 | 1,000 | 0,500 | 1,000 | 0,351 | 0,914 | 4 | 0 |
| Q002 | 1,000 | 1,000 | 0,500 | 1,000 | 0,521 | 0,826 | 2 | 2 |
| Q003 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | 0,945 | 1 | 1 |
| Q004 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 3 | 0 |
| Q005 | 1,000 | 1,000 | 1,000 | 0,333 | 0,890 | 0,686 | 5 | 2 |
| Q006 | 0,000 | 1,000 | 0,000 | 0,200 | 0,000 | 0,493 | 0 | 3 |
| Q007 | 0,000 | 1,000 | 0,000 | 0,500 | 0,000 | 0,631 | 0 | 4 |
| Q008 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | 1,000 | 0 | 4 |
| Q009 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | 0,821 | 0 | 2 |
| Q010 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1 | 4 |
| Q011 | 1,000 | **0,500** | 1,000 | **0,500** | 0,877 | **0,387** | 4 | 1 |
| Q012 | 0,000 | 0,000 | 0,000 | 0,000 | 0,000 | 0,121 | 0 | 1 |
| Q013 | *(não medida — sem evidência)* | | | | | | 0 | 5 |
| Q014 | *(não medida — excluída)* | | | | | | 3 | 2 |

### 4.2 Destino dos alvos de grau 2

Dezassete alvos de grau 2 no conjunto repooled.

| Destino | N | Casos |
| --- | ---: | --- |
| Recuperados por **ambas** | 8 | Q001/002-14, Q002/002-24, Q004/002-19, Q004/002-57, Q005/004-175, Q010/005-397, Q011/003-72, Q014/002-24 |
| **Só por C1 (denso)** | 6 | Q001/002-16, Q003/002-44, Q006/004-184, Q007/007-160, Q008/007-161, Q009/007-251 |
| **Só por C0 (lexical)** | 1 | Q011/003-37 |
| Por nenhuma | 2 | Q012/002-78, Q014/003-25 |

## 5. Recuperações exclusivas, e o que as explica

### 5.1 Exclusivas do denso — as falhas semânticas da D4.2

O estado corrente registava **cinco falhas semânticas por resolver**: Q003,
Q006, Q007, Q009 e Q012. C1 recupera o alvo em **quatro das cinco**; a quinta
(Q012) continua por resolver em ambas as condições.

«Recupera» é aqui Recall@5, e a margem não é a mesma nas quatro: em Q003 e Q009
o alvo aparece na posição 1, em Q007 na 2, mas em **Q006 aparece na posição 5**
— dentro do corte por um lugar, com RR de 0,200. Contá-la como resolvida é
correto sob a métrica e frágil na prática.

Em três delas — Q006, Q007 e Q009 — C0 não devolveu resultado nenhum: oito
candidatos avaliados em cada uma, **todos** excluídos por
`insufficient_coverage` ou `no_content_match`. Em Q003 devolveu um resultado
irrelevante, com cinco dos seis candidatos excluídos pelos mesmos motivos.

O que as quatro têm em comum é decisivo: **nenhum candidato foi excluído pelo
limiar**, em nenhuma delas. A falha ocorre na elegibilidade, **antes** do
ranking — é o diagnóstico da D4.5, e é a razão aritmética pela qual nenhuma
reponderação da D4.7 lhe podia tocar.

Q008 merece nota própria: é a pergunta do **BUG-D4.2-01**, cuja causa a D4.4
estabeleceu ao nível do termo (`stem('prorrogacao') = 'prorrogaca'` contra
`stem('prorrogação') = 'prorrog'`). C1 recupera o alvo na posição 1. Isto **não
corrige o bug** — o bug é do caminho lexical e continua lá, por decisão de
âmbito — mas mostra que uma estratégia que não passa pelo *stemmer* não é
afetada por ele.

Por tipo de dificuldade, contando alvos de grau 2 recuperados:

| Tipo | Perguntas | Alvos | C0 | C1 |
| --- | ---: | ---: | ---: | ---: |
| `rule_in_specific_section` | 5 | 5 | 1 | **5** |
| `paraphrase` | 5 | 5 | 1 | **4** |
| `synonym` | 2 | 2 | 1 | **2** |
| `date_deadline` | 7 | 11 | 7 | **9** |
| `table_information` | 6 | 8 | 5 | **7** |
| `acronym` | 2 | 3 | 3 | 3 |
| `similar_documents` | 5 | 8 | 6 | 6 |
| `cross_document_reference` | 1 | 1 | 0 | 0 |
| `cross_year_disambiguation` | 1 | 2 | **2** | 1 |

O ganho concentra-se onde a pergunta usa vocabulário diferente do documento —
paráfrase, sinónimo, regra escondida numa secção específica. Não há ganho onde a
correspondência já era literal (`acronym`), e há **perda** onde a
desambiguação depende de um literal.

### 5.2 Exclusiva do lexical — Q011, e porquê

Q011: *«Quando foi o primeiro dia de aulas do segundo semestre em 2023/2024?»*.
O corpus contém dois calendários académicos simultaneamente elegíveis
(P1-DOC-003 = 2023/2024, P1-DOC-002 = 2025/2026).

```
C0   1. P1-DOC-003/37   0,4295  grau 2      ← calendário correto
     2. P1-DOC-003/21   0,3295  grau 0
     3. P1-DOC-003/38   0,3209  grau 0
     4. P1-DOC-003/72   0,3100  grau 2      ← calendário correto

C1   1. P1-DOC-002/16   0,7414  grau 0      ← calendário ERRADO
     2. P1-DOC-003/72   0,7083  grau 2
     3. P1-DOC-002/56   0,6850  não julgado ← calendário errado
     4. P1-DOC-002/66   0,6783  grau 0      ← calendário errado
     5. P1-DOC-002/58   0,6613  grau 0      ← calendário errado
```

C0 devolveu **quatro resultados, todos do calendário certo**. C1 devolveu
**quatro dos cinco do calendário errado**, e colocou um deles em primeiro lugar.

O mecanismo é legível: «primeiro dia de aulas do segundo semestre» é
semanticamente quase idêntico nos dois calendários, e o literal `2023/2024`
— o único elemento que os distingue — quase não move o vetor da pergunta. O
que para o lexical é um token discriminante é, para o modelo denso, uma
diferença de superfície entre dois textos que dizem a mesma coisa.

Este é o caso onde a recuperação lexical não é substituível: **desambiguação
por literal entre documentos temporalmente concorrentes**. Q014, a pergunta
temporalmente ambígua excluída das métricas, mostra o mesmo padrão de forma mais
branda — ambas as condições recuperam 002/24 e nenhuma recupera 003/25.

### 5.3 Ranking, não só recuperação — Q005

Em Q005 as duas condições recuperam o alvo, mas C1 coloca-o em terceiro,
atrás de dois segmentos de grau 1 (contexto verdadeiro que não responde
sozinho). RR cai de 1,000 para 0,333 e nDCG@5 de 0,890 para 0,686. Recuperar
não é ordenar bem, e a média agregada esconde este tipo de troca.

### 5.4 Q013 — a pergunta sem resposta no corpus

Q013 está anotada com `no_relevant_evidence`, pelo que **nenhum** segmento do
corpus responde à pergunta. É a única pergunta nessa condição.

O que é observável: **C0 devolve zero resultados e C1 devolve cinco.** É uma
diferença de comportamento, medida, e é toda a afirmação que os dados sustentam.

O que **não** é observável, e por isso não é afirmado: se esses cinco segmentos
são irrelevantes. Estão entre os 31 por julgar. Que a pergunta não tenha
evidência **relevante** anotada não determina o grau de segmentos que ninguém
avaliou — a rubrica tem um grau 1 para contexto verdadeiro que não responde
sozinho, e nada permite dizer, sem julgar, em que grau caem estes cinco. Uma
versão anterior deste relatório afirmava que não tinham relação com a pergunta;
era uma inspeção informal apresentada como resultado, e foi removida.

Uma observação quantitativa, com a ressalva que se segue: as similaridades de
Q013 (0,4718 no topo, 0,4582 no quinto) são **as mais baixas de todas as
catorze perguntas**, e ficam abaixo do mínimo dos topos das restantes (0,6466).
A separação é visível — e é uma separação entre **distribuições de
similaridade**, não entre relevâncias, que continuam por julgar.

**A ressalva é decisiva e não deve ser lida ao contrário:** há **uma** pergunta
nesta classe. Uma amostra de um não fundamenta um limiar, e propor um valor
concreto a partir destes números seria ajustar um parâmetro ao ground truth —
precisamente o que a D4.7 se proibiu de fazer com os pesos. O que se regista é
que a questão é **empiricamente investigável**, não que esteja respondida.

## 6. Resultados não julgados e repooling

| Item | Valor |
| --- | --- |
| Resultados no top 5 sem julgamento | **31** |
| Origem | **31 de C1**, 0 de C0 |
| Perguntas afetadas | 12 de 14 (todas exceto Q001 e Q004) |
| Classificação | `REPOOLING_REQUIRED` |

Que todos os 31 venham de C1 não é um acaso: o ground truth foi construído por
inspeção dirigida a partir de execuções **lexicais** (D4.1–D4.6), pelo que C0
não podia devolver nada que ele não tivesse visto. O próprio `metric_protocol`
antecipou esta fase:

> «Antes de comparar lexical com denso ou hibrido, repoolar o conjunto com os
> resultados de ambos e reanotar.»

Sob a convenção `ASSUMED_IRRELEVANT`, cada um destes 31 conta grau 0 — não
porque tenha sido julgado irrelevante, mas porque nunca foi julgado. A
comparação **penaliza a condição nova por ser nova**.

A lista explícita dos pares pergunta/segmento a julgar está em
[`docs/evaluation/dense-repooling-requests-p1-s1.json`](../evaluation/dense-repooling-requests-p1-s1.json),
ancorada em `corpus_item_id` + `chunk_index`, sem texto documental. O ground
truth **não foi alterado** nesta fase.

### 6.1 O que o repooling pode e não pode mudar

Esta distinção é o centro da leitura dos resultados.

**Não pode mudar:** os seis alvos de grau 2 que só C1 recuperou, e o alvo que só
C0 recuperou. Esses julgamentos já existem no conjunto repooled da D4.6, foram
atribuídos contra o documento e a pergunta, e não dependem de nada que o
repooling venha a acrescentar. A **complementaridade** está estabelecida sobre
evidência já julgada.

**Pode mudar:** a magnitude da vantagem de C1. As 31 posições por julgar afetam
o nDCG (que perderia e ganharia ao mesmo tempo, porque o IDCG é calculado sobre
os julgamentos da própria pergunta) e afetariam o Recall se algum dos 31 for
relevante — nesse caso sobe o numerador e também o denominador. O sentido é
indeterminado, como o protocolo declara.

Por isso: **nenhum vencedor é declarado**, e os números de C1 na §4 aparecem
marcados como provisórios.

## 7. Complementaridade

Sobreposição entre as duas condições: **12 de 81** itens da união. Sete das
catorze perguntas têm sobreposição **zero** — as duas condições devolvem
conjuntos disjuntos.

A sobreposição baixa, por si só, não demonstra nada: duas condições podem não se
sobrepor e falhar ambas, que é o que acontece em Q012. O que sustenta a
complementaridade é a evidência julgada:

1. **C1 recupera seis alvos de grau 2 que C0 nunca devolveu**, quatro deles em
   perguntas onde C0 não devolveu nada, com causa identificada (elegibilidade
   lexical) e classe identificada (paráfrase, sinónimo, regra em secção).
2. **C0 recupera um alvo que C1 não devolve**, com mecanismo explicado e classe
   identificada (desambiguação por literal entre documentos concorrentes). E
   nesse caso C1 não apenas falha: das cinco posições que devolveu, **quatro
   estão julgadas e três dessas são grau 0 do calendário errado** — incluindo a
   primeira. A degradação está julgada, não inferida.
3. Em Q005, C0 ordena melhor a mesma evidência que ambas recuperam.

Os três pontos assentam em julgamentos que já existem e que o repooling não vai
alterar.

Há uma quarta diferença, **de natureza distinta e por isso listada à parte**:
C0 devolve zero resultados em seis perguntas e C1 nunca devolve zero. É uma
assimetria de mecanismo — só uma das condições tem uma etapa capaz de rejeitar
tudo — e a capacidade de abstenção é constitucionalmente necessária ao projeto.
Mas dizer que a abstenção de C0 está **certa** em cada um desses casos exigiria
julgar o que C1 devolveu, e 31 desses resultados estão por julgar. A assimetria é
observável; a sua avaliação não é, ainda.

As duas condições falham em sítios diferentes, por razões diferentes e
identificáveis. Isso é complementaridade — não «recuperam resultados
diferentes».

**Veredito: SIM**, com a ressalva de que a *magnitude* fica por confirmar até ao
repooling.

## 8. Limitações

1. **Julgamentos incompletos.** 31 resultados por julgar, todos de C1. As
   métricas de C1 são provisórias. O ground truth continua
   `DIRECTED_JUDGMENT_INCOMPLETE`.
2. **Amostra pequena.** Doze perguntas medidas, um corpus, uma instituição, um
   anotador único sem adjudicação. Uma diferença de uma pergunta desloca a
   macro-média em ~0,083.
3. **C1 devolve sempre `top_k`.** Parte da vantagem em Recall é estrutural e não
   semântica: C0 devolveu 23 resultados de 70 possíveis, C1 devolveu 70. Não é
   toda — em Q011 C1 devolveu cinco e perdeu na mesma, e em Q012 devolveu cinco
   sem recuperar o alvo julgado — mas é uma parte, e não é separável com este
   desenho.
4. **Um só modelo de embeddings.** Nada aqui depende de ele ser o melhor
   disponível, e nada aqui o compara com outro.
5. **Dependência de um serviço externo no retrieval.** C1 exige uma chamada de
   rede por pergunta para embeber a consulta, e a indexação transmitiu o texto
   dos segmentos ao fornecedor. É o mesmo fluxo de dados que a geração de
   respostas já faz com as evidências selecionadas, mas é uma diferença real
   face a C0, que corre inteiramente local.
6. **O fornecedor não é determinístico — medido, não presumido.** Ver §8.1.
7. **Uma única pergunta sem resposta no corpus** (§5.4). Não fundamenta limiar
   nenhum, e a relevância do que C1 devolveu nessa pergunta continua por julgar.
8. **Sem índice ANN.** A pesquisa exata é adequada a 1834 vetores e não diz nada
   sobre o comportamento a escalas onde um índice aproximado seja necessário.

### 8.1 Deriva do fornecedor, medida

Este ponto estava declarado como incerteza e passou a medição. O comando de
indexação foi corrido com `--reembed`, que reenvia ao fornecedor **o mesmo texto,
com o mesmo modelo e a mesma configuração**, e a avaliação foi repetida sobre o
índice resultante:

| Observação | Resultado |
| --- | --- |
| `index_digest` | **mudou** |
| Scores alterados | **19 de 70** |
| Maior diferença absoluta de similaridade | **3,59 × 10⁻⁴** |
| Ordens de ranking alteradas | **0** |
| Métricas por pergunta | **idênticas** |
| Lista de repooling | **idêntica** |

Os embeddings **não** são reprodutíveis bit a bit, e a magnitude da deriva é da
ordem de 10⁻⁴ na similaridade do cosseno — pequena o suficiente para não inverter
nenhum par no top 5 deste corpus, mas não nula.

Duas consequências, e a segunda é a que importa:

- a reprodutibilidade desta experiência assenta no **índice persistido**, não em
  o fornecedor ser determinístico. Não reembeber por omissão é, por isso, um
  requisito de correção e não uma otimização;
- a estabilidade das ordens observada aqui é uma **propriedade deste corpus e
  destas catorze perguntas**, não uma garantia. Num par cuja diferença de
  similaridade seja inferior a 10⁻⁴, uma reindexação pode trocar posições — e o
  `index_digest` é o que torna essa troca detetável em vez de silenciosa.

## 9. Conclusão

> **C — lexical e denso apresentam complementaridade suficiente para justificar
> uma experiência híbrida.**

Fundamento, e não a literatura: as duas condições recuperam evidência **já
julgada** que a outra não recupera, em classes identificadas e com mecanismo
explicado em ambos os sentidos. A escolha entre elas seria uma troca, não uma
melhoria.

A conclusão assenta apenas em julgamentos existentes. A assimetria de abstenção
(§7) aponta no mesmo sentido, mas **não** é usada como fundamento: avaliá-la
exigiria julgar o que C1 devolveu onde C0 se absteve.

As alternativas foram consideradas e rejeitadas com razão declarada:

- **A** (denso não acrescenta capacidade suficiente) — contradita por seis alvos
  de grau 2 recuperados e por quatro das cinco falhas semânticas resolvidas.
- **B** (vantagens sem complementaridade clara) — contradita pela **Q011**, cujos
  dois alvos estão julgados: C0 recupera ambos e C1 perde um, enchendo quatro das
  cinco posições com o calendário do ano errado. C0 não é dominado, e há uma
  classe de perguntas onde C1 é mensuravelmente pior.
- **D** (inconclusivo, corrigir outra limitação primeiro) — a limitação real
  (julgamentos incompletos) é conhecida, quantificada e **não afeta** a
  conclusão de complementaridade, que assenta em evidência já julgada. Afeta a
  magnitude, e é por isso que a magnitude não é declarada.

## 10. Próximo passo

**D4.9 — experiência de Hybrid Retrieval lexical + denso.** Não foi
implementada, e não deve ser iniciada antes de:

1. **Repooling dos 31 pares** listados em
   `docs/evaluation/dense-repooling-requests-p1-s1.json`, com reanotação sob a
   mesma rubrica e anotador. Só então a comparação final C0 × C1 é definitiva.
2. Só depois, o desenho de D4.9 — que terá de resolver explicitamente a
   incomparabilidade entre `LEXICAL_RELEVANCE` e `DENSE_SIMILARITY`. Fundir dois
   scores de famílias diferentes exige uma transformação declarada; uma
   combinação linear direta seria somar quantidades que o próprio `ScoreKind`
   existe para impedir que se confundam.

Duas questões ficam registadas, **não** para esta fase e **não** decididas:

- se a condição densa deve ter um critério de não-devolução, e qual (§5.4);
- se a correção do BUG-D4.2-01 continua a justificar-se caso a estratégia
  adotada deixe de passar pelo *stemmer* (§5.1). Continua por corrigir e por
  desenhar.

## 11. O que esta fase não fez

Não implementou `HybridRetriever`, RRF, combinação lexical + denso, reranking
semântico, cross-encoder, reescrita ou multiplicação de consultas, GraphRAG,
Agentic RAG, *fine-tuning*, `DecisionPolicy` nem *confidence score*. Não alterou
o retrieval, o ranking, os pesos, os limiares, a elegibilidade, o planeamento de
consultas, o orçamento de candidatos, o FTS, a normalização, a API, o answering
nem o frontend. Não corrigiu o BUG-D4.1-01 nem o BUG-D4.2-01. Não alterou o
ground truth nem os artefactos das fases D4.2–D4.7.

## Correções posteriores

Esta secção é aditiva. O corpo do relatório **não** foi reescrito: é um
documento histórico e regista o que foi observado e decidido no momento. O que
segue nomeia o que ficou errado ou superado, e onde vive a versão válida.

### Erro factual corrigido (D4.8.1)

A §3.3 descrevia a chave primária de `chunk_embeddings` como
`(chunk_id, model)`. É **`(chunk_id, provider, model)`**, como a §3.3.1 do
próprio relatório já dizia, como o modelo declara e como a migration
`c4f7ab19d3e5` cria. A frase da §3.3 foi corrigida; o resto do relatório estava
certo. A implementação nunca esteve em causa — a divergência era entre duas
frases do mesmo documento.

### Métricas de C1 substituídas (D4.8.1)

A coluna «C1 denso (provisório)» da §4 e as colunas de C1 da §4.1 mediam contra
um conjunto em que 31 resultados do top 5 nunca tinham sido julgados, e a §6
declarava-as provisórias por isso. Esses 31 pares foram julgados na
[D4.8.1](d4-8-1-lexical-dense-repooling.md), e **as métricas definitivas de C1
são as de lá**, não as daqui. As de C0 não mudaram.

O sentido da correção é o que a §6.1 dizia ser indeterminado: as métricas de C1
**subiram**. O `result_digest` `98f521cd…a2c783` continua a descrever esta
execução, e a execução em si — os rankings — está reproduzida exatamente pela
D4.8.1.

### Conclusão revista (D4.8.1)

A §9 concluiu **C** (complementaridade suficiente para justificar uma
experiência híbrida) e a §10 recomendou a D4.9. Com os 31 julgamentos feitos, a
D4.8.1 concluiu **D**: C1 aumenta o recall de forma inequívoca, mas não tem
etapa capaz de recusar, e a evidência que faltava para avaliar essa assimetria —
os resultados que C1 devolveu em Q013 — está agora julgada. A recomendação
passou a ser um estudo de admissibilidade densa **antes** do híbrido. O
fundamento está em [`d4-8-1-lexical-dense-repooling.md`](d4-8-1-lexical-dense-repooling.md).
