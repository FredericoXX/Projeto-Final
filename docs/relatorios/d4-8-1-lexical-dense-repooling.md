# D4.8.1 — Repooling e comparação definitiva C0 lexical × C1 denso sobre P1/S1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo

A [D4.8](d4-8-dense-baseline-p1-s1.md) mediu duas condições — C0 lexical e C1
denso — contra um *ground truth* construído por inspeção dirigida a partir de
execuções **lexicais** (D4.1–D4.6). Trinta e um resultados do top 5, **todos de
C1**, nunca tinham sido vistos por um anotador. Sob a convenção
`ASSUMED_IRRELEVANT` cada um contava grau 0 — não por ter sido julgado
irrelevante, mas por nunca ter sido julgado. A comparação penalizava a condição
nova por ser nova, e a D4.8 declarou as métricas de C1 **provisórias** e
recusou-se a declarar vencedor.

Esta fase faz duas coisas, e só estas:

**A.** julga os 31 pares, sem rever nada do que já estava julgado;
**B.** volta a medir as **mesmas** execuções contra o conjunto completo.

Não foi implementado `HybridRetriever`, RRF, fusão de scores, reranking
semântico, cross-encoder, limiar denso, modelo de embeddings novo, reescrita de
consultas, GraphRAG nem Agentic RAG. Não foi alterado o retrieval de produção, o
*answering*, o OCR, a segmentação nem o Momento 5.
`app.retrieval.dependencies.get_retriever` continua a devolver o retriever
lexical, e há teste que o fixa.

## 2. Contexto experimental

| Item | Valor |
| --- | --- |
| `origin/main` | `22b59fc4d2f3ddf7d1e79231d5c3b1fff5971f8d` (merge do Pull Request #56, D4.8) |
| Branch de trabalho | `analysis/d4-8-dense-baseline`, `HEAD` em `b0ab6db0d4ef69fa1751b2daf41b25e8158af018` — já integrado na `main` pelo Pull Request #56, pelo que o conteúdo versionado de partida é o da `main` |
| `snapshot_id` | `a94f9402…baf4c1` — inalterado |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| `ground_truth_digest` **antes** | `ada6b38886a06910e425e4be164099a3a63320050890253404064e3fde88586e` |
| `ground_truth_digest` **depois** | `bbaea746a1cd58d0392a213fd8fd1c282239ad8d299afb9d78d13728051b1301` |
| Baseline D4.2 | `result_digest` `b00ca87b…cc7fb4` — ranking de C0 reproduzido **exatamente** |
| Experimento D4.8 | `result_digest` `98f521cd…a2c783` — rankings de C0 **e** C1 reproduzidos **exatamente** |
| Lista de repooling | `result_digest` `e71c7a90…2ede0d`, 31 pedidos, todos tratados |
| Índice vetorial | `index_digest` `451d9f2f…d9370c`, 1834 vetores — **o mesmo** que a D4.8 mediu |
| `result_digest` do D4.8.1 | `b708a70ed922c2937903033b1a3847457dffa3d682934d8e2e6b73e525f7a003` — idêntico nas três execuções |

Constantes: corpus, snapshot, perguntas, `top_k` = 5, `official_only`, idioma,
data de referência, `RetrievalEligibility`, extração, OCR, segmentação, FTS,
ranking lexical, pesos, orçamento de candidatos, modelo de embeddings, índice
vetorial. **A única coisa que mudou foram os julgamentos.**

### 2.1 Guardas, por ordem de execução

Implementadas em
[`scripts/evaluate_lexical_dense_comparison.py`](../../backend/scripts/evaluate_lexical_dense_comparison.py).
Se qualquer uma falhar, **nada é escrito**.

1. **Integridade dos artefactos consumidos** — o D4.2, o D4.8 e a lista de
   pedidos de repooling têm de coincidir com o seu próprio `result_digest`. A
   lista de pedidos é verificada porque, sem isso, o âmbito do repooling seria
   um ficheiro editável à mão: quem acrescentasse um julgamento poderia
   acrescentar o pedido a seguir.
2. **Protocolo de métricas** — as constantes declaradas têm de ser as
   implementadas.
3. **Controlo do repooling** — §4.
4. **Snapshot** — o corpus reconstruído tem de continuar a ser S1.
5. **Índice vetorial** — homogéneo, completo, e com o `index_digest` que a D4.8
   declara. Esta última parte é nova e é a garantia de que **C1 não mudou**: o
   digest cobre o conteúdo binário de cada vetor, e a D4.8 (§8.1) mediu que
   reembeber o *mesmo* texto pelo *mesmo* modelo produz vetores diferentes. Sem
   esta guarda, uma reindexação silenciosa apareceria como efeito do repooling.
6. **Replicação dos rankings** — C0 tem de reproduzir o ranking posicional do
   D4.2 **e** o do D4.8; C1 tem de reproduzir o do D4.8. É a guarda central: se
   um ranking mudasse, a diferença de métricas deixaria de ser atribuível ao
   repooling, e as duas causas seriam indistinguíveis no agregado.
7. **Comparabilidade** — a união dos dois top 5 tem de estar inteiramente
   julgada, e a classificação tem de ser `COMPARABLE`.

As métricas do controlo D4.7 **não** são comparadas, e isso é deliberado: foram
medidas contra o conjunto anterior, e é precisamente o denominador do Recall que
o repooling alterou em Q006 e Q007 (§4.3). Comparar contra elas faria falhar uma
execução correta.

## 3. Os 31 julgamentos

Cada par foi julgado contra o **documento** e a **pergunta**, nunca contra a
posição, o score ou a condição que o devolveu. Anotador único, sem adjudicação,
como nos conjuntos anteriores. A escala é a mesma do D4.1:

| Grau | Significado |
| --- | --- |
| 0 | irrelevante, **incluindo** distractor: mesmo assunto, ano/público/procedimento errado |
| 1 | parcialmente útil: contexto relevante mas insuficiente sozinho |
| 2 | evidência diretamente relevante para responder ao pedido |

### 3.1 O que foi acrescentado

| Grau | Novos julgamentos |
| --- | ---: |
| 0 — irrelevante | **26** |
| 1 — contexto útil, insuficiente | **3** |
| 2 — diretamente relevante | **2** |
| **Total** | **31**, em 12 perguntas |

Os 31 correspondem, um a um, aos 31 pedidos da D4.8. Nenhum julgamento foi
acrescentado fora dessa lista, e nenhum pedido ficou por tratar — verificado, não
declarado (§4).

### 3.2 A regra de grau 1 que este repooling seguiu

Os julgamentos anteriores dão grau 1 a duas coisas: cabeçalhos de secção que
**localizam** a resposta sem a dar, e regras que **condicionam** a resposta sem a
enunciar. Esta fase seguiu a mesma regra e explicitou-a, porque três dos casos
novos ficaram na fronteira:

> **Grau 1** — o segmento localiza a resposta (cabeçalho ou início da própria
> regra) **ou** enuncia um limite ou condição do mesmo instituto que a pergunta
> interroga, sem dar o facto pedido **e sem oferecer um valor rival** que possa
> ser lido como resposta.
> **Grau 0** — tudo o resto, incluindo o distractor que oferece um valor rival do
> tipo pedido.

A cláusula do valor rival é a que decide os casos difíceis, e é a que a rubrica
já usava ao classificar como grau 0 um segmento cuja recuperação «produziria uma
resposta confiante e errada» (Q011/`P1-DOC-002/58`).

### 3.3 Os dois graus 2 novos

**Q006 / `P1-DOC-004/60`** — *«Qual é a percentagem mínima de presenças exigida
na componente prática laboratorial?»*. O segmento é o fim da definição de
*Frequência Mínima*: «não podendo ser inferior a 50% nas aulas teóricas e **75%
nas aulas práticas**». É a regra geral e não a regra específica da componente
laboratorial — essa vive no `P1-DOC-004/184`, já julgada grau 2 — mas indica a
**mesma percentagem** e responde diretamente ao pedido. Quem lesse só este
segmento responderia certo.

Para a Q005 (*«A presença nas aulas práticas é obrigatória?»*) este mesmo
segmento já estava julgado **grau 1**, com a nota «acrescenta o valor sem
responder à pergunta binária». Os dois julgamentos são consistentes: o segmento
dá um valor, e a Q006 é a pergunta que pede um valor.

**Q007 / `P1-DOC-007/152`** — *«Durante quantos anos posso continuar alojado numa
residência da universidade?»*. «Cada estudante poderá renovar o alojamento até ao
limite máximo de **4 anos consecutivos**, salvo exceções devidamente
fundamentadas.» É a mesma regra que o `P1-DOC-007/160` (já grau 2) enuncia
noutro artigo, com o mesmo limite.

### 3.4 Os três graus 1 novos

| Pergunta | Segmento | Porquê 1 e não 2, e porquê 1 e não 0 |
| --- | --- | --- |
| Q006 | `P1-DOC-004/183` | Início da frase da regra da componente prática laboratorial; a percentagem vive no segmento seguinte. Localiza a regra e nomeia a componente sem dar o valor. |
| Q007 | `P1-DOC-007/161` | Continuação do mesmo artigo: mecanismo de prorrogação do período de alojamento. Contexto relevante para continuar alojado, sem indicar duração — e sem oferecer duração rival. |
| Q008 | `P1-DOC-007/152` | Limite de 4 anos consecutivos de renovação: condiciona a possibilidade de prorrogar sem indicar antecedência, e não oferece prazo rival. |

### 3.5 O caso que a regra do valor rival decidiu

**Q008 / `P1-DOC-007/160` — grau 0.** É a parte anterior do **mesmo artigo** cujo
número 6 (`P1-DOC-007/161`) responde à pergunta, e contém **dois prazos
próprios**: trinta dias de antecedência para a saída, e um mês antes do termo do
ano letivo para a renovação das vagas. Nenhum deles é a antecedência da
prorrogação. Recuperado no topo, produziria uma resposta confiante e errada — é
o padrão que a rubrica classifica como distractor.

A assimetria com o Q007/`P1-DOC-007/161` (grau 1) é deliberada e tem uma razão
declarada: o 161 não carrega duração nenhuma que possa passar por resposta à
Q007, e o 160 carrega prazos que passam por resposta à Q008.

### 3.6 Q013 — os cinco resultados julgados

Os cinco segmentos que C1 devolveu na única pergunta sem evidência no corpus
receberam **grau 0, todos**: uma alínea sobre fotografias tipo passe do boletim
de matrícula, a perda de validade do cartão de estudante, e três fragmentos sobre
propinas e reingresso. Nenhum tem relação com credenciais de acesso ao portal.

O julgamento **confirma** a anotação `no_relevant_evidence` em vez de a
contradizer, e é o facto que a D4.8 não podia afirmar (§7).

## 4. Controlo do repooling

Seis condições, todas verificadas por código antes de qualquer medição
(`verify_repooling` e `verify_requests_satisfied`, em
[`app/evaluation/repooling.py`](../../backend/app/evaluation/repooling.py)):

| Condição | Resultado |
| --- | --- |
| Nenhum julgamento anterior foi removido | **0 removidos** |
| Nenhum julgamento anterior foi alterado | **0 revistos** |
| Nenhuma pergunta foi modificada | verificado campo a campo |
| Exatamente os pedidos esperados foram tratados | **31 de 31**, nenhum a mais |
| Nenhum resultado C0/C1 do top 5 fica por julgar | **`COMPARABLE`**, 0 por julgar |
| Identidade P1/S1 mantida | `corpus_id`, `snapshot_id`, `corpus_digest` iguais |

A regra que o código impõe é a mesma desde a D4.6, e não é negociável:

> **acrescentar julgamentos é legítimo; rever os existentes não é.**

O que `verify_requests_satisfied` acrescenta a `verify_repooling` é o **âmbito**.
A primeira prova que o conjunto novo estende o antigo; não prova que o estenda
pela razão declarada. Um repooling que acrescentasse julgamentos escolhidos por
outro critério passaria na primeira e produziria uma comparação diferente da que
o artefacto de pedidos descreve.

O que o código **não** prova é que os graus estejam certos. Isso é juízo do
anotador, e dizer o contrário seria vender uma garantia que o código não dá.

### 4.1 O que o repooling não podia mudar, e não mudou

`document_level_relevance` recebeu quatro entradas novas, todas de **grau 0**, e
apenas para documentos que passaram a ter julgamento e ainda não constavam da
lista (Q009/`P1-DOC-005`, Q010/`P1-DOC-004`, Q013/`P1-DOC-004` e
Q013/`P1-DOC-005`). É a manutenção de uma invariante do ficheiro — todo documento
julgado aparece na lista — e não uma revisão: nenhuma entrada existente foi
alterada, e o campo não entra no `ground_truth_digest` nem em métrica nenhuma.
Está fixado por teste.

### 4.2 Cobertura, antes e depois

| Condição | Resultados devolvidos | Julgados antes | Julgados depois |
| --- | ---: | ---: | ---: |
| C0 lexical | 23 | 23 | **23** |
| C1 denso | 70 | 39 | **70** |

Que os 31 viessem todos de C1 não é acaso: o *ground truth* foi construído a
partir de execuções lexicais, pelo que C0 não podia devolver nada que ele não
tivesse visto.

### 4.3 Os denominadores que mudaram

Acrescentar um grau 2 muda o denominador do Recall da pergunta, e com ele o
Recall medido em **todas** as condições. Aconteceu em duas:

| Pergunta | Alvos antes | Alvos depois |
| --- | ---: | ---: |
| Q006 | 1 | **2** |
| Q007 | 1 | **2** |

Sem esta lista, uma variação de Recall entre as duas versões seria
indistinguível de uma variação de comportamento do sistema.

## 5. Métricas definitivas

Doze perguntas medidas. Q013 está fora por não ter evidência no corpus e Q014 por
ambiguidade temporal (§8). Macro-média: cada pergunta pesa o mesmo.

| Métrica | C0 lexical | C1 denso | Delta (C1 − C0) |
| --- | ---: | ---: | ---: |
| Recall@1 | 0,2500 | **0,5833** | +0,3333 |
| Recall@3 | 0,4167 | **0,8333** | +0,4167 |
| Recall@5 | 0,4583 | **0,8750** | +0,4167 |
| MRR | 0,4167 | **0,8194** | +0,4028 |
| nDCG@1 | 0,3333 | **0,7778** | +0,4444 |
| nDCG@3 | 0,3637 | **0,7677** | +0,4040 |
| nDCG@5 | 0,3867 | **0,7987** | +0,4120 |

**Estas substituem as da D4.8.** As de C1 lá eram provisórias por construção.

### 5.1 O que o repooling mudou, e em que direção

O agregado de **C0 não mudou em nenhuma casa decimal**, e isso é uma
consequência aritmética e não uma coincidência: os 31 julgamentos eram todos de
resultados que C0 nunca devolveu, e as duas perguntas cujo denominador subiu
(Q006 e Q007) eram perguntas em que C0 devolveu **zero** resultados — 0/1 e 0/2
são ambos 0.

O de C1 **subiu**. A D4.8 (§6.1) declarara o sentido indeterminado, e era; a
medição resolveu-o:

| Métrica C1 | D4.8 (provisória) | D4.8.1 (definitiva) | Delta |
| --- | ---: | ---: | ---: |
| Recall@1 | 0,5000 | 0,5833 | +0,0833 |
| Recall@3 | 0,7917 | 0,8333 | +0,0417 |
| Recall@5 | 0,8750 | 0,8750 | 0,0000 |
| MRR | 0,7111 | 0,8194 | +0,1083 |
| nDCG@1 | 0,6111 | 0,7778 | +0,1667 |
| nDCG@3 | 0,7030 | 0,7677 | +0,0647 |
| nDCG@5 | 0,7354 | 0,7987 | +0,0633 |

A subida concentra-se em duas perguntas, e por uma razão nítida: os dois graus 2
novos estavam ambos na **posição 1** de C1.

| Pergunta | RR antes | RR depois | nDCG@5 antes | nDCG@5 depois |
| --- | ---: | ---: | ---: | ---: |
| Q006 | 0,200 | **1,000** | 0,493 | **0,897** |
| Q007 | 0,500 | **1,000** | 0,631 | **0,987** |

As dez restantes não mudaram em nenhuma métrica: os 29 julgamentos restantes
foram 26 graus 0 e 3 graus 1, e nenhum deles desloca o primeiro acerto.

### 5.2 Por pergunta

| Pergunta | Alvos | R@1 C0 | R@1 C1 | R@3 C0 | R@3 C1 | R@5 C0 | R@5 C1 | RR C0 | RR C1 | nDCG@5 C0 | nDCG@5 C1 | devolvidos C0 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Q001 | 2 | 0,000 | 0,500 | 0,500 | 1,000 | 0,500 | 1,000 | 0,500 | **1,000** | 0,351 | **0,914** | 4 |
| Q002 | 1 | 0,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 0,500 | **1,000** | 0,521 | **0,826** | 2 |
| Q003 | 1 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | **1,000** | 0,000 | **0,945** | 1 |
| Q004 | 2 | 0,500 | 0,500 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 3 |
| Q005 | 1 | 1,000 | 0,000 | 1,000 | 1,000 | 1,000 | 1,000 | **1,000** | 0,333 | **0,890** | 0,686 | 5 |
| Q006 | 2 | 0,000 | 0,500 | 0,000 | 0,500 | 0,000 | 1,000 | 0,000 | **1,000** | 0,000 | **0,897** | 0 |
| Q007 | 2 | 0,000 | 0,500 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | **1,000** | 0,000 | **0,987** | 0 |
| Q008 | 1 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | **1,000** | 0,000 | **1,000** | 0 |
| Q009 | 1 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | 1,000 | 0,000 | **1,000** | 0,000 | **0,821** | 0 |
| Q010 | 1 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1 |
| Q011 | 2 | 0,500 | 0,000 | 0,500 | 0,500 | **1,000** | 0,500 | **1,000** | 0,500 | **0,877** | 0,387 | 4 |
| Q012 | 1 | 0,000 | 0,000 | 0,000 | 0,000 | 0,000 | 0,000 | 0,000 | 0,000 | 0,000 | 0,121 | 0 |
| Q013 | — | *(sem evidência no corpus — §7)* | | | | | | | | | | 0 |
| Q014 | 2 | *(excluída por ambiguidade temporal — §8)* | | | | | | | | | | 3 |

## 6. Complementaridade

A distinção que dá sentido à resposta, e que o artefacto separa por construção:

- **complementaridade real** — um alvo de grau 2 que entra no top 5 de *uma* das
  condições e não da outra;
- **diferença de ranking** — um alvo de grau 2 que entra no top 5 das *duas*, em
  posições diferentes. Ambas encontram a mesma evidência; uma ordena-a melhor.
  Isto **não** é complementaridade, e contá-lo como tal inflacionaria o
  argumento a favor de uma arquitetura híbrida.

### 6.1 Destino dos alvos de grau 2

Dezanove alvos de grau 2 nas catorze perguntas (dezassete antes, mais os dois
novos).

| Destino | N | Casos |
| --- | ---: | --- |
| Recuperados por **ambas** | 8 | Q001/`002-14`, Q002/`002-24`, Q004/`002-19`, Q004/`002-57`, Q005/`004-175`, Q010/`005-397`, Q011/`003-72`, Q014/`002-24` |
| **Só por C1 (denso)** | 8 | Q001/`002-16`, Q003/`002-44`, Q006/`004-60`, Q006/`004-184`, Q007/`007-152`, Q007/`007-160`, Q008/`007-161`, Q009/`007-251` |
| **Só por C0 (lexical)** | 1 | Q011/`003-37` |
| Por nenhuma | 2 | Q012/`002-78`, Q014/`003-25` |

Dos oito comuns, **seis** estão em posições diferentes nas duas condições. São
diferenças de ranking, não complementaridade, e não sustentam nenhum argumento
de cobertura: Q001/`002-14`, Q002/`002-24`, Q004/`002-19`, Q004/`002-57`,
Q005/`004-175`, Q011/`003-72`.

### 6.2 Perguntas resolvidas por cada condição

«Resolvida» é ter pelo menos um alvo de grau 2 no top 5 — o mesmo critério que dá
`reciprocal_rank > 0`. Sobre as doze medidas:

| Classe | N | Perguntas |
| --- | ---: | --- |
| Resolvidas por **ambas** | 6 | Q001, Q002, Q004, Q005, Q010, Q011 |
| Resolvidas **só por C1** | 5 | Q003, Q006, Q007, Q008, Q009 |
| Resolvidas **só por C0** | **0** | — |
| Falhadas por ambas | 1 | Q012 |

**Nenhuma pergunta é resolvida apenas por C0.** É a diferença mais importante
face à leitura da D4.8, e não decorre dos julgamentos novos: decorre de os contar
ao nível da pergunta em vez de ao nível do alvo.

Por nDCG@5 — a única métrica do protocolo sensível ao mesmo tempo à recuperação e
à ordenação — C0 é favorecida em **duas** perguntas (Q005, Q011) e C1 em **oito**
(Q001, Q002, Q003, Q006, Q007, Q008, Q009, Q012).

### 6.3 A única evidência exclusiva de C0, e o que a explica

**Q011**: *«Quando foi o primeiro dia de aulas do segundo semestre em
2023/2024?»*. O corpus contém dois calendários simultaneamente elegíveis
(`P1-DOC-003` = 2023/2024, `P1-DOC-002` = 2025/2026).

```
C0   1. P1-DOC-003/37   0,4295  grau 2      ← calendário correto
     2. P1-DOC-003/21   0,3295  grau 0
     3. P1-DOC-003/38   0,3209  grau 0
     4. P1-DOC-003/72   0,3100  grau 2      ← calendário correto

C1   1. P1-DOC-002/16   0,7414  grau 0      ← calendário ERRADO
     2. P1-DOC-003/72   0,7083  grau 2
     3. P1-DOC-002/56   0,6850  grau 0      ← calendário errado
     4. P1-DOC-002/66   0,6783  grau 0      ← calendário errado
     5. P1-DOC-002/58   0,6613  grau 0      ← calendário errado
```

C0 devolveu quatro resultados, **todos do calendário certo**. C1 devolveu
**quatro dos cinco do calendário errado**, e colocou um deles em primeiro lugar.
Depois do repooling as cinco posições de C1 estão julgadas, e a degradação está
medida e não inferida.

O mecanismo é legível: «primeiro dia de aulas do segundo semestre» é
semanticamente quase idêntico nos dois calendários, e o literal `2023/2024` — o
único elemento que os distingue — quase não move o vetor da pergunta. O que para
o lexical é um *token* discriminante é, para o modelo denso, uma diferença de
superfície entre dois textos que dizem a mesma coisa.

Esta é a única classe onde a recuperação lexical não é substituível:
**desambiguação por literal entre documentos temporalmente concorrentes.** É
também a única pergunta dessa classe no conjunto, o que é uma limitação e não uma
demonstração.

### 6.4 Ranking, não recuperação — Q005

Em Q005 as duas condições recuperam o alvo, mas C1 coloca-o em terceiro, atrás de
dois segmentos de grau 1 (contexto verdadeiro que não responde sozinho). RR cai
de 1,000 para 0,333 e nDCG@5 de 0,890 para 0,686. Recuperar não é ordenar bem, e
a média agregada esconde este tipo de troca.

### 6.5 Por tipo de dificuldade

Descritivo. A amostra por célula é de um dígito e nenhuma célula estabelece
causa.

| Tipo | Perguntas | Alvos | C0 | C1 |
| --- | ---: | ---: | ---: | ---: |
| `rule_in_specific_section` | 5 | 7 | 1 | **7** |
| `paraphrase` | 5 | 6 | 1 | **5** |
| `synonym` | 2 | 3 | 1 | **3** |
| `date_deadline` | 7 | 11 | 7 | **9** |
| `table_information` | 6 | 8 | 5 | **7** |
| `lexically_close` | 2 | 3 | 2 | **3** |
| `acronym` | 2 | 3 | 3 | 3 |
| `similar_documents` | 5 | 8 | 6 | 6 |
| `cross_document_reference` | 1 | 1 | 0 | 0 |
| `cross_year_disambiguation` | 1 | 2 | **2** | 1 |
| `temporal_ambiguity` | 1 | 2 | 1 | 1 |

O ganho concentra-se onde a pergunta usa vocabulário diferente do documento. Não
há ganho onde a correspondência já era literal (`acronym`), e há **perda** onde a
desambiguação depende de um literal.

## 7. Q013 — a pergunta sem evidência no corpus

Q013 (*«Perdi a palavra-passe do portal do estudante. Como a recupero?»*) está
anotada com `no_relevant_evidence`: nenhum segmento do corpus responde. É a única
pergunta nessa condição, e o `metric_protocol` exclui-a de Recall, MRR e nDCG
porque as três são indefinidas sem alvo. Essa exclusão foi mantida.

O que se regista, agora com os cinco resultados julgados:

| Observação | Valor |
| --- | --- |
| Resultados devolvidos por C0 | **0** |
| Resultados devolvidos por C1 | **5** |
| Graus dos cinco resultados de C1 | **0, 0, 0, 0, 0** |
| Resultados relevantes encontrados (grau 2) | **NÃO** |
| Resultados parcialmente úteis (grau 1) | **NÃO** |
| Similaridade do 1.º de C1 | 0,4718 |
| Similaridade do 5.º de C1 | 0,4582 |
| Menor similaridade de topo nas outras 13 perguntas | 0,6466 |
| Maior similaridade de topo nas outras 13 perguntas | 0,8334 |

Duas afirmações, e a diferença entre elas importa.

**A primeira é sobre a operação e está estabelecida:** a abstenção de C0 nesta
pergunta estava **certa**, e os cinco resultados de C1 são falsos positivos —
julgados, não presumidos. É o facto que a D4.8 não podia afirmar, e é o que torna
a assimetria de mecanismo avaliável em vez de apenas observável.

**A segunda é sobre limiares e não está estabelecida:** as similaridades de Q013
ficam integralmente abaixo do mínimo dos topos das restantes treze perguntas, e a
separação é visível. **Há uma pergunta nesta classe.** Uma amostra de um não
fundamenta limiar nenhum, e propor um valor concreto a partir destes números
seria ajustar um parâmetro ao *ground truth* — precisamente o que a D4.7 se
proibiu de fazer com os pesos. **Nenhum limiar denso foi criado nesta fase**, e a
ausência de limiar em C1 continua fixada por teste.

### 7.1 A abstenção de C0 nas outras cinco perguntas

C0 devolveu zero resultados em seis perguntas. Com o repooling é possível dizer,
pela primeira vez, se cada abstenção estava certa:

| Pergunta | C1 devolveu | Existia evidência? | Veredicto sobre a abstenção de C0 |
| --- | ---: | --- | --- |
| Q006 | 5 (2 de grau 2) | sim, e C1 encontrou-a | **errada** |
| Q007 | 5 (2 de grau 2) | sim, e C1 encontrou-a | **errada** |
| Q008 | 5 (1 de grau 2) | sim, e C1 encontrou-a | **errada** |
| Q009 | 5 (1 de grau 2) | sim, e C1 encontrou-a | **errada** |
| Q012 | 5 (0 de grau 2) | sim, e nenhuma a encontrou | **errada** |
| Q013 | 5 (0 de grau 2) | não | **certa** |

**Uma em seis.** Nas trinta posições que C1 devolveu onde C0 se absteve há 6
graus 2, 7 graus 1 e 17 graus 0.

Isto corta nos dois sentidos e é registado assim de propósito: a capacidade de
abstenção de C0 é constitucionalmente necessária, mas o seu **exercício
concreto** neste corpus falhou em cinco dos seis casos. Nenhum argumento desta
fase se apoia na qualidade da abstenção de C0.

## 8. Q014 — a exclusão foi mantida

Q014 (*«Até quando posso pedir a anulação da matrícula do primeiro semestre?»*)
continua `excluded_from_metrics=true`. A razão registada no *ground truth* não
mudou: a pergunta não fixa ano letivo, o corpus tem dois calendários
simultaneamente elegíveis, nenhum tem vigência declarada, e existem por isso duas
respostas corretas e incompatíveis sem ordenação defensável entre elas. Incluir a
pergunta exigiria escolher um ano **sem fundamento institucional**.

Nenhuma interpretação temporal foi inventada. Os dois resultados de Q014 por
julgar receberam grau 0 sob **ambas** as interpretações, e nenhum julgamento
anterior foi tocado — os dois graus 2 incompatíveis (`002-24` e `003-25`)
continuam ambos lá.

A exclusão deixa de se justificar quando a convenção de vigência (dependência de
categoria B, estado `UNKNOWN`) for conhecida. Não é trabalho desta fase.

O que é observável, e não entra em métrica nenhuma: as duas condições recuperam
`002-24` na posição 1 e nenhuma recupera `003-25`. C1 devolve mais três
resultados, todos grau 0.

## 9. Comportamento do denso

### 9.1 Ruído no top 5

| Condição | Resultados devolvidos | Grau 0 | Grau 1 | Grau 2 | Fração de grau 0 |
| --- | ---: | ---: | ---: | ---: | ---: |
| C0 lexical | 23 de 70 possíveis | 12 | 2 | 9 | 52,2 % |
| C1 denso | **70** de 70 | 43 | 11 | 16 | **61,4 %** |

A leitura tem de ser feita com as duas colunas ao mesmo tempo. C1 devolve mais do
triplo dos resultados e uma fração maior deles é irrelevante — em números
absolutos, 43 falsos positivos contra 12. Mas devolve também 16 graus 2 contra 9,
e o nDCG@5, que penaliza ruído dentro do top 5, dá-lhe 0,799 contra 0,387. A
troca não é «C1 é ruidoso»; é **C1 compra recall com precisão por resultado
devolvido**.

### 9.2 A assimetria de abstenção é de mecanismo

C1 devolveu **70 de 70** resultados possíveis. Não é uma propriedade do corpus: é
estrutural. C1 não tem elegibilidade de conteúdo e não tem limiar, pelo que
qualquer pergunta cujo corpus admissível tenha pelo menos `top_k` segmentos
embebidos recebe `top_k` vizinhos, por mais distante que o mais próximo esteja.
**C1 não tem etapa capaz de devolver vazio.**

O princípio constitucional de que *ausência de resultados é uma resposta
legítima* pressupõe um mecanismo que saiba recusar. C0 tem-no; C1 não tem
nenhum.

### 9.3 Datas, anos e termos exatos

Onde a resposta é uma data e o ano está fixado na pergunta e é único no corpus,
as duas condições recuperam (`date_deadline`: 7 alvos para C0, 9 para C1). Onde
dois documentos dizem a mesma coisa para anos diferentes, o literal do ano é o
único sinal discriminante — e é aí que C1 falha (§6.3) e C0 não.

### 9.4 Paráfrase e baixa sobreposição lexical

É onde o ganho de C1 se concentra: `paraphrase` 1 → 5, `rule_in_specific_section`
1 → 7, `synonym` 1 → 3. Em quatro das cinco perguntas que a D4.8 chamava «falhas
semânticas por resolver» (Q003, Q006, Q007, Q009), C0 devolveu zero ou um
resultado irrelevante, **sem nenhum candidato excluído pelo limiar** — a falha
ocorre na elegibilidade, antes do ranking, que é o diagnóstico da D4.5 e a razão
aritmética pela qual nenhuma reponderação da D4.7 lhe podia tocar.

Q008 merece nota própria: é a pergunta do **BUG-D4.2-01**, cuja causa a D4.4
estabeleceu ao nível do termo (`stem('prorrogacao')` ≠ `stem('prorrogação')`). C1
recupera o alvo na posição 1. Isto **não corrige o bug** — o bug é do caminho
lexical e continua lá — mas mostra que uma estratégia que não passa pelo *stemmer*
não é afetada por ele.

### 9.5 O que não é afirmado

Nada aqui atribui causalidade a partir das contagens por tipo de dificuldade: as
células têm um dígito, os tipos não são exclusivos entre si e uma pergunta conta
em vários. As contagens descrevem onde as diferenças caem; os mecanismos
afirmados (§6.3, §9.4) estão ancorados em rankings concretos e em diagnósticos de
fases anteriores, não nas contagens.

## 10. Reprodutibilidade

A comparação foi executada **três vezes** sobre o índice persistido, com a versão
final do comando. Resultado:

| Observação | Resultado |
| --- | --- |
| Rankings (âncora e posição) | **idênticos** nas três |
| Graus | **idênticos** |
| Métricas, por pergunta e agregadas | **idênticas** |
| Complementaridade e classificação das perguntas | **idênticas** |
| `index_digest` | **idêntico**, e igual ao da D4.8 |
| **`result_digest`** | **idêntico** — `b708a70e…7a003` |
| `execution_digest` | **dois valores** nas três execuções |

O gate de reprodutibilidade — mesmos rankings, mesmas métricas, mesmo
`result_digest` — está satisfeito.

### 10.1 Porque é que o artefacto tem dois digests

O fornecedor de embeddings não é bit a bit determinístico. A D4.8 mediu-o (§8.1)
ao reembeber o **índice**; aqui manifesta-se no *embedding da pergunta*, que C1
calcula a cada execução. Nas três execuções, **5 das 70 similaridades de C1
diferiram**, todas na Q014, com desvio máximo de **1,78 × 10⁻³** — e **nenhuma
ordem, grau ou métrica mudou**.

Um digest calculado sobre o *payload* inteiro seria, por isso, instável entre
execuções. Havia três saídas, e duas são inaceitáveis: arredondar mais o score
esconderia a deriva, e retirá-lo do artefacto perderia informação que a análise
de Q013 usa. A terceira é a implementada — **o digest canónico descreve o
resultado, não a execução**:

| Digest | Âmbito | Comportamento |
| --- | --- | --- |
| **`result_digest`** | `provider_independent_fields` | **Tem** de ser idêntico entre execuções sobre o mesmo índice e o mesmo *ground truth*. É o digest canónico do artefacto, e é o que uma fase seguinte cita para dizer «medi contra este resultado». |
| `execution_digest` | `full_payload` | Muda com a deriva do fornecedor, e é isso que o torna útil: é o que deteta que os vetores não são os mesmos. A deriva fica preservada e visível. |

A projeção do `result_digest` retira **apenas** a similaridade bruta de C1 — nos
rankings e no bloco da Q013 — e os campos que descrevem a execução. Mantém o
score de **C0**, porque o ranking lexical corre inteiramente local e é
determinístico, pelo que uma alteração nele é sinal e não ruído; e mantém a
posição, o grau e todas as métricas de C1, que é sobre o que a comparação se
pronuncia. Há testes que verificam que o `result_digest` absorve uma deriva de
similaridade, **não** absorve uma troca de posição e **não** absorve uma
alteração do score lexical.

Consequência para quem consumir este artefacto: com dois digests ele **não** é
verificável pela guarda genérica de digest único (`verify_baseline_integrity`),
que assume a convenção de um só. A definição a usar é
`app.evaluation.lexical_dense_comparison.artefact_digests`, que é a mesma que os
produziu.

## 11. Limitações

1. **Amostra pequena.** Doze perguntas medidas, um corpus, uma instituição, um
   anotador único sem adjudicação. Uma diferença de uma pergunta desloca a
   macro-média em ~0,083. Todos os deltas da §5 são de 3 a 5 perguntas de
   magnitude.
2. **Uma pergunta por classe crítica.** Uma pergunta sem evidência no corpus
   (Q013), uma de desambiguação entre anos (Q011), uma temporalmente ambígua
   (Q014). As três conclusões mais fortes desta fase apoiam-se, cada uma, numa
   única pergunta.
3. **O conjunto continua incompleto por construção.** O repooling elimina a
   incompletude **na união dos dois top 5**, não no corpus:
   `DIRECTED_JUDGMENT_INCOMPLETE` mantém-se. Um segmento relevante que nenhuma
   das duas condições devolveu continua por julgar, e continuaria a contar 0.
4. **C1 devolve sempre `top_k`.** Parte da vantagem em Recall é estrutural e não
   semântica, e não é separável com este desenho.
5. **Um só modelo de embeddings.** Nada aqui depende de ele ser o melhor
   disponível, e nada aqui o compara com outro.
6. **O fornecedor não é determinístico** (§10). A reprodutibilidade assenta no
   índice persistido, não no fornecedor, e o `result_digest` é estável por ser
   definido sobre o resultado e não sobre a execução. A estabilidade das ordens
   sob uma deriva de 10⁻³ é uma propriedade **deste** corpus e destas catorze
   perguntas, não uma garantia: num par cuja diferença de similaridade seja
   dessa ordem, uma execução pode trocar posições — e é o `execution_digest`
   que torna a deriva detetável em vez de silenciosa.
7. **Dependência de rede no retrieval.** C1 exige uma chamada por pergunta para
   embeber a consulta; C0 corre inteiramente local.
8. **Sem índice ANN.** A pesquisa exata é adequada a 1834 vetores e não diz nada
   sobre o comportamento a escalas onde um índice aproximado seja necessário.

## 12. Decisão

> **D — C1 aumenta o recall de forma inequívoca, mas introduz ruído e não tem
> critério de admissibilidade, o que exige primeiro um estudo de
> limiar/admissibilidade densa.**

O fundamento, e o que o distingue da conclusão da D4.8:

1. **C1 domina todas as métricas do protocolo**, por margens de +0,33 a +0,44, e
   resolve cinco perguntas que C0 não resolve. Depois do repooling a vantagem é
   maior, não menor.
2. **Nenhuma pergunta é resolvida apenas por C0.** A complementaridade em
   direção a C0 reduz-se a **um alvo** (Q011/`003-37`) e a uma vantagem de
   ordenação em duas perguntas. É real e tem mecanismo identificado, mas é
   estreita e assenta numa única pergunta da sua classe.
3. **A incapacidade de recusar de C1 deixou de ser hipotética.** Na única
   pergunta sem resposta no corpus, C1 devolveu cinco segmentos, **todos
   julgados grau 0**, onde C0 devolveu zero. Era exatamente o que a D4.8 não
   podia afirmar, e é o facto novo desta fase.
4. **Uma fusão herdaria o defeito.** Qualquer combinação — RRF incluída — sobre
   uma condição que devolve sempre `top_k` devolve sempre resultados. Desenhar o
   híbrido antes de decidir o critério de não-devolução densa fixaria essa
   propriedade na arquitetura, contra o princípio constitucional de que *ausência
   de resultados é uma resposta legítima*.

As alternativas foram consideradas e rejeitadas com razão declarada:

- **A** (C1 sem vantagem suficiente) — contradita por oito alvos de grau 2
  exclusivos e cinco perguntas resolvidas só por C1.
- **B** (C1 supera e C0 não acrescenta complementaridade relevante) — contradita
  pela Q011, cujos dois alvos estão julgados: C0 recupera ambos e C1 perde um,
  enchendo quatro das cinco posições com o calendário do ano errado. C0 não é
  dominado, e há uma classe de perguntas onde C1 é mensuravelmente pior.
- **C** (complementaridade suficiente para justificar o híbrido) — foi a
  conclusão da D4.8 e **é revista aqui**. A complementaridade continua a existir,
  mas é agora quase inteiramente unidireccional, e o obstáculo que os
  julgamentos novos revelaram — C1 não sabe recusar, e produz cinco falsos
  positivos onde tem de recusar — é anterior à fusão e não é resolvido por ela.
- **E** (amostra insuficiente para decidir) — a amostra é pequena e está
  declarada como limitação, mas a decisão D não depende de uma diferença de
  magnitude: depende de C1 não ter mecanismo de recusa, que é uma propriedade
  estrutural e não uma medição.

## 13. Próximo passo

**D4.9 — estudo de admissibilidade e limiar da condição densa.** Não foi
iniciado, não foi desenhado e nada dele foi implementado. As perguntas que terá
de responder, e que esta fase deliberadamente não respondeu:

1. **Existe critério de não-devolução defensável para C1?** Um limiar sobre a
   similaridade do cosseno é a hipótese óbvia e não é a única — cobertura de
   termos sobre o vizinho, margem entre o 1.º e o `k`-ésimo, ou calibração por
   pergunta são alternativas com desenhos diferentes.
2. **Com que dados se fixaria?** Uma pergunta sem evidência não chega. O
   conjunto P1 precisaria de mais perguntas dessa classe, e construí-las é
   trabalho de anotação, não de código.
3. **Só depois, o híbrido.** O desenho de uma fusão terá ainda de resolver
   explicitamente a incomparabilidade entre `LEXICAL_RELEVANCE` e
   `DENSE_SIMILARITY`: fundir dois scores de famílias diferentes exige uma
   transformação declarada, e uma combinação linear direta seria somar
   quantidades que o próprio `ScoreKind` existe para impedir que se confundam.
   O RRF evita a fusão de scores, mas não o problema da §12.4.

Duas questões ficam registadas, **não** para esta fase e **não** decididas:

- se a correção do BUG-D4.2-01 continua a justificar-se caso a estratégia
  adotada deixe de passar pelo *stemmer* (§9.4). Continua por corrigir e por
  desenhar;
- se a exclusão da Q014 pode ser levantada, o que depende da convenção
  institucional de vigência e não de trabalho de retrieval (§8).

## 14. O que esta fase não fez

Não implementou `HybridRetriever`, RRF, fusão de scores, reranking semântico,
cross-encoder, limiar denso, admissibilidade densa, modelo de embeddings novo,
reescrita ou multiplicação de consultas, GraphRAG, Agentic RAG, *fine-tuning*,
`DecisionPolicy` nem *confidence score*. Não alterou o retrieval de produção, o
ranking, os pesos, os limiares, a elegibilidade, o planeamento de consultas, o
orçamento de candidatos, o FTS, a normalização, o índice vetorial, a API, o
*answering* nem o *frontend*. Não corrigiu o BUG-D4.1-01 nem o BUG-D4.2-01. Não
alterou o Pilot Corpus P1, o Evaluation Snapshot S1, o Momento 5, nem qualquer
julgamento das fases D4.1–D4.8. Não reindexou nem reembebeu.
