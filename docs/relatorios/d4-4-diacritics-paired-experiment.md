# D4.4 — Condição pareada com diacríticos sobre P1/S1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo

O D4.3 terminou com uma dívida explícita (§6.2): a variante que preserva acentos
não podia ser avaliada, porque as perguntas do *ground truth* histórico foram
escritas sem diacríticos e a projeção ficava assimétrica. BUG-D4.2-01 ficou, por
isso, **por testar**.

Esta fase paga essa dívida isolando **uma** variável:

> Preservar os diacríticos na pergunta melhora a correspondência do *stemmer*
> português e a recuperação da evidência relevante?

E responde a uma segunda pergunta, que o D4.3 §8 identificou como pré-requisito:
**como identificar deterministicamente a versão das perguntas** com que um
resultado foi medido.

Nenhuma alteração de produção foi feita. Nenhuma variante foi adotada.

## 2. Baseline e estado Git

| Item | Valor |
| --- | --- |
| `origin/main` | `5514d8ba076a43ac7de951dfcddc081428459937` (merge do Pull Request #51, D4.3) |
| Branch de trabalho | `analysis/d4-4-diacritics-paired`, criada a partir de `origin/main` |
| `snapshot_id` | `a94f9402…baf4c1` — verificado antes de medir, inalterado |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| Baseline D4.2 | `result_digest` `b00ca87b…7fb4` **reproduzido exatamente** |
| Experimento D4.3 | `result_digest` `9a86a154…e165b6` — as três células `production_quota` **reproduzidas exatamente** |

O corpus, o retrieval de produção e o *ground truth* histórico não foram tocados.
O *working tree* tem **8 ficheiros: 1 modificado + 7 novos**. O único modificado
é [`docs/ai/02-current-state.md`](../ai/02-current-state.md), a atualização de
estado que a fase exige; **nenhum ficheiro de produção, artefacto do D4.2/D4.3 ou
pergunta histórica foi alterado**.

## 3. Identidade do *ground truth*

### 3.1 O problema que resolve

O D4.3 registou o buraco sem o fechar: o `snapshot_id` deriva de
`schema_version + institution_id + reference_date + corpus_digest + retrieval` —
**não** do conjunto de perguntas. Com duas versões das perguntas em circulação, a
afirmação "estes resultados foram medidos com estas perguntas" deixa de poder ser
convenção.

`app/evaluation/ground_truth_identity.py` — módulo **puro**, não reexportado por
`__init__.py` — calcula um `ground_truth_digest` sobre uma representação
canónica, com `canonical_json` (a serialização única do projeto) e SHA-256.
`hash()` do Python nunca é usado: é aleatorizado por processo e não é identidade
nenhuma entre execuções.

| Conjunto | `ground_truth_digest` |
| --- | --- |
| Histórico (`retrieval-ground-truth-p1-seed.json`) | `1f05f49ae8f596175b6943734c3778d73280e6a2f89da7886db08434e6db8ea2` |
| Pareado (`retrieval-ground-truth-p1-diacritics.json`) | `8abe153628ea07207e8f7ddf9651a80d759d9006f9acb2542dedede83c34f51d` |

### 3.2 O que o digest cobre, e o que **não** cobre

O digest responde a uma única pergunta: *duas execuções sobre estes dois
ficheiros produziriam os mesmos números, dado o mesmo corpus e a mesma
configuração de recuperação?* Daí o âmbito declarado
`measurement_relevant_fields`: entram exatamente os campos que a medição **lê**.

| Entra | Fica de fora |
| --- | --- |
| `schema_version`, `contract`, `corpus_id` | `notes`, `scope_note`, justificações em prosa |
| `question_id`, `question`, `language` | `difficulty_types`, `question_origin`, `annotation` |
| `no_relevant_evidence`, `excluded_from_metrics` | `exclusion_reason` (texto), `temporal_scope` |
| `evidence_judgments` (item, segmento, grau) | `note` de cada julgamento, `document_level_relevance` |
| `metric_protocol` operativo (5 campos) | `snapshot_id`, `corpus_digest`, `reference_date` |

Duas consequências a declarar sem rodeios:

1. **Isto não é um hash do ficheiro.** Reescrever uma nota ou reetiquetar uma
   dificuldade **não** muda o digest. É deliberado: um digest que mudasse por
   razões que não afetam a comparabilidade avisaria de incomparabilidade onde
   ela não existe, que é o oposto do que serve. Quem quiser integridade ao nível
   do ficheiro precisa de outro hash, com outro nome.
2. **O estado do corpus fica de fora, para desacoplar as duas identidades.**
   `snapshot_id`, `corpus_digest` e `reference_date` descrevem o corpus, não as
   perguntas. Incluí-los **não** criaria colisões — as perguntas participam no
   hash, e conjuntos diferentes teriam digests diferentes de qualquer forma —
   mas ligaria a identidade das perguntas a um estado que muda por razões
   alheias a elas: reprocessar o corpus ou mudar a data de referência passaria a
   reemitir o digest do *ground truth*, e deixaria de ser possível dizer "esta
   versão das perguntas" independentemente do snapshot contra o qual foi medida.
   `corpus_id` **entra**, por ser o rótulo estável da população anotada e não um
   estado: perguntas dirigidas a outra população são outro conjunto.

O digest é invariante à ordem das perguntas e à ordem dos julgamentos, porque
nenhuma das duas muda número nenhum: as métricas indexam julgamentos por
`(documento, segmento)` e a agregação é uma macro-média. Um ficheiro malformado
levanta erro em vez de produzir um digest plausível.

**Não** foi criada tabela, migration nem endpoint.

## 4. A condição pareada

### 4.1 O que foi criado, e o que não foi tocado

O conjunto histórico é **imutável** e não foi alterado. `retrieval-ground-truth-p1-diacritics.json`
é um conjunto **novo**, com as mesmas 14 perguntas e os mesmos 32 julgamentos,
diferindo apenas nos diacríticos linguisticamente corretos.

Os identificadores são **derivados, não atribuídos**: `Q008` → `Q008-diacritics`,
com `paired_question_id` a nomear explicitamente o original. Identificadores
iguais nos dois ficheiros tornariam ambíguo qualquer artefacto que os juntasse, e
nada o detetaria.

### 4.2 A prova de que é um par

A verificação central é uma igualdade exata de cadeias:

```
strip_diacritics(pergunta_pareada) == pergunta_original
```

Como o conjunto histórico não tem **um único** diacrítico — verificado, e fixado
por teste —, isto diz que o par é o original com marcas combinantes acrescentadas
e nada mais: nem uma palavra trocada, nem uma vírgula, nem uma maiúscula. É
deliberadamente mais estrito do que `normalize_text`, que também descarta
maiúsculas e espaçamento e portanto deixaria essas duas alterações passar.

Verifica-se ainda a igualdade de `evidence_judgments`, `temporal_scope`,
`language`, `no_relevant_evidence`, `excluded_from_metrics`, `exclusion_reason`,
`difficulty_types` e `document_level_relevance` — campos que o **digest** ignora
por não entrarem em métrica nenhuma. A assimetria é intencional: o digest
pergunta *"mediria o mesmo?"*, o pareamento pergunta *"é a mesma pergunta com os
acentos restituídos?"*.

Cada pergunta declara a lista `diacritics_restored`, verificada como **sólida e
completa**: cada par declarado é mesmo uma restituição e ocorre nos dois textos,
e nenhuma palavra acentuada do texto pareado fica por declarar. Sem a segunda
metade, a lista seria documentação que se pode esquecer de atualizar.

**O que a verificação não prova**: que os acentos restituídos sejam os
linguisticamente corretos. `mátricula` passaria. Isso é juízo humano do anotador,
e dizer o contrário seria vender uma garantia que o código não dá.

### 4.3 Resultado do pareamento

**Nenhuma pergunta exigiu reformulação.** As 14 foram admitidas.

| | Perguntas |
| --- | --- |
| Com diacríticos restituídos (11) | Q001, Q002, Q003, Q004, Q005, Q006, Q007, Q008, Q009, Q012, Q014 |
| Sem diacríticos a restituir (3) | Q010, Q011, Q013 |

As três últimas já estavam ortograficamente corretas sem acento. **Não são um
resíduo: são os controlos nulos internos do experimento.** O seu texto é byte a
byte igual nas duas condições, pelo que têm de medir exatamente o mesmo — e o
comando recusa escrever se não medirem.

Um caso merece nota. Q003 e Q004 restituem `e` → `é`. Sem acento, a forma coincide
com a conjunção; a restituição resolve uma ambiguidade real da escrita sem
diacríticos, e não apenas uma marca ortográfica.

## 5. Desenho

Um fator, dois níveis, três variantes de correspondência:

| | **ORIGINAL** | **DIACRÍTICOS** |
| --- | --- | --- |
| `exact_canonical` (produção) | **A1** | **A2** |
| `stem_normalized` | **B1** | **B2** |
| `stem_accented` | **C1** | **C2** |

Condição de conjunto de candidatos: **apenas `production_quota`**. A condição
`unbounded` do D4.3 não foi usada — introduzi-la aqui misturaria dois fatores e
esta fase existe para isolar um.

### 5.1 Porque é que o fator fica isolado

A consulta enviada ao PostgreSQL é construída por `normalize_text`, que **remove**
diacríticos. As duas condições produzem, por isso, a mesma `tsquery`, o mesmo
conjunto de candidatos e os mesmos `query_terms`. Verificado no artefacto: as
seis células avaliam **104 candidatos**, os mesmos.

O que muda é só o texto de que a variante `stem_accented` lê a acentuação do lado
da pergunta. Corpus, snapshot, quotas, elegibilidade, ranking, limiar, `top_k` e
julgamentos são idênticos. A atribuição de causa é direta, não inferida.

Daí decorre uma **previsão verificável antes de medir**: `exact_canonical` e
`stem_normalized` nunca leem o texto acentuado da pergunta, pelo que A1 ≡ A2 e
B1 ≡ B2 têm de sair idênticas. Saíram — ver §6.

### 5.2 Guardas

Nada é escrito se alguma falhar:

1. o pareamento é válido (§4.2);
2. os dois conjuntos têm `ground_truth_digest` **diferentes** — sem isso não há
   par para medir;
3. **A1 reproduz a baseline do D4.2 por inteiro** — conjunto de perguntas,
   ranking posicional, Recall, MRR, nDCG, contagens e agregados; e o artefacto do
   D4.2 coincide com o seu próprio `result_digest`;
4. **A1, B1 e C1 reproduzem as três células `production_quota` do D4.3**, o que
   verifica *mecanicamente* — e não por afirmação — que o D4.4 não deslocou o
   D4.3;
5. **os controlos nulos medem idêntico** nas duas condições, em todas as
   variantes.

O código de execução — recolha de candidatos, ordenação, avaliação por célula e
as guardas 3 e 4 — vem por **importação** de `scripts/evaluate_retrieval_experiment.py`,
que não foi tocado. Copiá-lo faria as duas experiências divergirem em silêncio e o
D4.4 deixaria de medir o mesmo sistema que o D4.3 mediu.

### 5.3 Reprodutibilidade

Duas execuções sobre S1 inalterado produziram o mesmo `result_digest` —
`1dd1615cb86849d77c5c7ed0d70fef548f0f56ed499cc0c4f58543113989330a` — e *payloads*
idênticos exceto `executed_at`. Os dois `ground_truth_digest` são igualmente
estáveis entre execuções.

## 6. Métricas

Protocolo do D4.1, sem alteração: `k` primário 5, relevância binária a grau 2,
ganhos nDCG 0/1/3, não julgados como grau 0, macro-média sobre as 12 perguntas
medidas.

| Célula | R@1 | R@3 | R@5 | MRR | nDCG@1 | nDCG@3 | nDCG@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A1** (baseline) | 0,2083 | 0,4167 | 0,4583 | 0,3750 | 0,2500 | 0,3323 | 0,3630 |
| **A2** | 0,2083 | 0,4167 | 0,4583 | 0,3750 | 0,2500 | 0,3323 | 0,3630 |
| **B1** | 0,2083 | 0,4167 | 0,4583 | 0,3750 | 0,2500 | 0,3451 | 0,3749 |
| **B2** | 0,2083 | 0,4167 | 0,4583 | 0,3750 | 0,2500 | 0,3451 | 0,3749 |
| C1 | 0,1250 | 0,2500 | 0,2917 | 0,2500 | 0,1667 | 0,2192 | 0,2412 |
| **C2** | **0,2917** | **0,5000** | **0,5417** | **0,4583** | **0,3333** | **0,4284** | **0,4582** |

Deltas por par:

| Par | R@5 antes | R@5 depois | Δ R@5 | Δ MRR | Δ nDCG@5 |
| --- | --- | --- | --- | --- | --- |
| A1 → A2 | 0,4583 | 0,4583 | **0,0000** | **0,0000** | **0,0000** |
| B1 → B2 | 0,4583 | 0,4583 | **0,0000** | **0,0000** | **0,0000** |
| C1 → C2 | 0,2917 | 0,5417 | **+0,2500** | **+0,2083** | **+0,2170** |

Três leituras, por ordem de importância:

1. **A previsão da §5.1 confirma-se: A e B são insensíveis aos diacríticos.** As
   células são idênticas, não "quase". É o resultado que valida o desenho — se
   diferissem, o fator não estaria isolado e nenhum outro delta seria
   interpretável.
2. **Só C reage, e reage muito.** Todas as sete métricas sobem, nenhuma desce.
3. **C2 é a única célula, em todo o D4.2/D4.3/D4.4, que supera a baseline de
   produção**: +0,0833 de Recall@5, +0,0833 de MRR e +0,0952 de nDCG@5 face a A1.

## 7. Resultados por pergunta

`R@5` nas seis células:

| Pergunta | A1 | A2 | B1 | B2 | C1 | C2 |
| --- | --- | --- | --- | --- | --- | --- |
| Q001 | 0,50 | 0,50 | 0,50 | 0,50 | 0,50 | 0,50 |
| **Q002** | 1,00 | 1,00 | 1,00 | 1,00 | **0,00** | **1,00** |
| Q003 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |
| Q004 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 |
| **Q005** | 1,00 | 1,00 | 1,00 | 1,00 | **0,00** | **1,00** |
| Q006 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |
| Q007 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |
| **Q008** | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | **1,00** |
| Q009 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |
| Q010 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 |
| Q011 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 |
| Q012 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |
| Q013 | — | — | — | — | — | — |
| Q014 | — | — | — | — | — | — |

### 7.1 Duas reparações e **um** ganho

C1 → C2 melhora três perguntas: **Q002, Q005 e Q008**. Zero regressões. Mas as
três não são a mesma coisa, e confundi-las inflacionaria o resultado:

- **Q002 e Q005 são reparações.** Ambas valiam 1,00 na baseline e caíram para
  0,00 em C1, pela assimetria que o D4.3 §6.2 diagnosticou. C2 devolve-as ao
  nível que já tinham. **Não são ganho face a produção.**
- **Q008 é o único ganho real.** Nenhuma das cinco outras células a recupera —
  nem a baseline, nem a radicalização sobre formas sem acentos, nem C1.

A verificação decisiva: **C2 difere de B2 em exatamente uma pergunta, Q008.**
Comparadas registo a registo, as duas células são iguais em tudo o resto —
ranking, contagens, métricas. Restituir diacríticos na pergunta compra, sobre a
melhor política sem acentos, uma coisa e uma só.

### 7.2 Q008: o mecanismo, verificado e não presumido

*"Com que antecedência tenho de pedir a prorrogação do alojamento?"* — 5 termos
informativos, e `required_matches(5) = 3`, com cobertura mínima 0,5.

Os radicais, obtidos de `ts_lexize('portuguese_stem', …)` — o *stemmer* que o
próprio índice FTS usa:

```
stem(prorrogacao) = prorrogaca      stem(prorrogação) = prorrog
stem(prorrogar)   = prorrog         stem(antecedencia) = antecedenc
                                    stem(antecedência) = antecedent
```

O segmento-alvo, P1-DOC-007 / 161, usa o **verbo** `prorrogar` e a forma
acentuada `antecedência`. Aplicando a elegibilidade de produção:

| Célula | Termos correspondidos | Cobertura | Elegível |
| --- | --- | --- | --- |
| A (exata) | `alojamento`, `antecedencia` | 0,40 | não |
| B (radical sem acentos) | `alojamento`, `antecedencia` | 0,40 | não |
| C1 (conteúdo acentuado, pergunta não) | `alojamento` | 0,20 | não |
| **C2** | `alojamento`, `antecedencia`, `prorrogacao` | **0,60** | **sim** |

Duas coisas ficam visíveis de uma vez:

- **a assimetria de C1 é observável ao nível do termo.** `antecedencia` →
  `antecedenc` deixa de casar com `antecedência` → `antecedent`, e C1 fica
  **abaixo** da baseline — 1 termo em vez de 2. Não é ruído: é a assimetria a
  destruir uma correspondência que a igualdade exata tinha;
- **o ganho de C2 é atribuível a um único termo.** Face a A e B, o que C2
  acrescenta é `prorrogação` → `prorrog` a casar com `prorrogar` → `prorrog`.
  `antecedência` volta a casar, mas já casava por igualdade exata em A e B, pelo
  que não contribui com nada de novo.

O termo que faz a diferença é exatamente aquele que o D4.2 identificou ao
descrever BUG-D4.2-01. O alvo entra em **posição 1**, com grau 2: `R@5 = 1,00`,
`RR = 1,00`, `nDCG@5 = 1,00`.

O D4.3 §6.1 tinha declarado que a previsão do D4.2 sobre Q008 "não se
confirmou". Estava certo **sobre as condições que mediu** — a forma acentuada não
existe no corpus e nenhuma das seis células a podia produzir. O que faltava era
a única fonte possível dessa forma: **a pergunta**.

### 7.3 As cinco falhas que nada move

Q003, Q006, Q007, Q009 e Q012 continuam a 0,00 nas seis células. O D4.3 §6.3 já
as classificara como semânticas — formulação numérica, regra expressa por
renovação, sinonímia institucional — e nada nesta fase o contraria. **Os
diacríticos não são a explicação de nenhuma delas.**

## 8. Ruído e regressões

### 8.1 Agregado

| Célula | Devolvidos | Não julgados | Distractores grau 0 | Candidatos |
| --- | --- | --- | --- | --- |
| A1 / A2 | 23 | 14 | 0 | 104 |
| B1 / B2 | 28 | 16 | 1 | 104 |
| C1 | 16 | 9 | 1 | 104 |
| **C2** | **29** | **16** | **1** | 104 |

**C2 devolve exatamente mais um resultado do que B2, e esse resultado é o alvo de
Q008.** Zero resultados não julgados novos, zero distractores novos. O ganho não
é comprado com ruído.

### 8.2 Distractores de grau 0

Um único distractor julgado é recuperado: **P1-DOC-002 / 89** em Q003 — a
renovação de matrículas do 1.º semestre do ano letivo *seguinte*, acima de
qualquer alvo. Aparece em **B1, B2, C1 e C2**, e não em A. **É um custo da
radicalização, já documentado no D4.3 §7.1, e não um custo dos diacríticos.**

C1 devolve menos do que a baseline (16 contra 23), o que confirma que a
assimetria perde correspondências em vez de relaxar.

### 8.3 Q013 — a pergunta sem evidência

**Devolve zero resultados nas seis células**, com os mesmos 8 candidatos
avaliados. É também um dos três controlos nulos, pelo que o seu texto é idêntico
nas duas condições; a comparação que interessa é entre variantes, e nem a mais
permissiva devolve nada.

Continua a ser um **facto sobre o corpus**, não um desfecho de política: nada
aqui afirma `ABSTAIN` nem `NOT_ANSWERABLE`.

### 8.4 Q014 — a pergunta temporalmente ambígua

Excluída das métricas, mas observável. Em A1 devolvia um resultado; em C2 devolve
quatro, entre os quais **as duas respostas corretas e incompatíveis** —
P1-DOC-002 / 24 e P1-DOC-003 / 25, ambas grau 2. É a ilustração mais nítida do
problema que o D4.1 documentou: o corpus tem dois calendários simultaneamente
elegíveis e nenhum tem vigência declarada. Uma correspondência melhor torna a
ambiguidade **mais** visível, não menos.

## 9. BUG-D4.2-01 — classificação

> **CONFIRMADO.**

O enunciado exige que a confirmação venha da condição pareada e não da mera
diferença técnica do *stemmer*. Vem:

1. **A diferença é atribuível aos diacríticos por construção.** Corpus, snapshot,
   `tsquery`, conjunto de candidatos, elegibilidade, ranking, limiar e julgamentos
   são idênticos entre as duas condições. Só a acentuação da pergunta difere.
2. **O desenho tem controlos que passaram.** As variantes que não leem o texto
   acentuado (A, B) saíram **idênticas**; as três perguntas sem acentos a
   restituir mediram **idêntico**; as células da condição original reproduziram o
   D4.2 e o D4.3 por inteiro.
3. **O efeito é positivo, dirigido e sem regressão.** Uma pergunta recuperada,
   nenhuma perdida, um resultado adicional devolvido — que é o alvo —, nenhum
   distractor novo.
4. **O mecanismo foi verificado ao nível do termo**, com o *stemmer* real, e
   coincide exatamente com o descrito pelo D4.2: `prorrogacao` → `prorrogaca`
   quebra a regra `-ção` que `prorrogação` → `prorrog` satisfaz.

O que a confirmação **não** autoriza a concluir está na §10.

## 10. Limitações

- **Uma pergunta em doze.** O efeito confirmado tem magnitude 1/12 = 0,0833 de
  Recall@5. É uma amostra minúscula e nada aqui é estatisticamente sustentado.
  Confirmar que um mecanismo **existe** não é medir a sua **incidência**.
- **A correção de produção não está determinada por este experimento, e isto é a
  ressalva mais importante da fase.** C2 varia a projeção do lado da **pergunta**,
  offline. Produção recebe o que o utilizador escreveu: se o utilizador escrever
  sem acentos, nenhuma alteração ao lado documental recupera Q008, porque o
  lexema da consulta continua a ser `prorrogaca`. O D4.4 demonstra o **defeito**;
  **não** demonstra que exista uma alteração implementável que o corrija sem
  contrapartidas.
- **Qual das duas formas representa o utilizador real continua UNKNOWN.** É uma
  dependência de categoria B, que o D4.1 §17 declarou desconhecida. O D4.4 mede
  as duas sem precisar de responder — mas o desenho de uma correção **precisa**,
  e assumir a resposta seria inventar o tipo de facto institucional que a
  categoria B proíbe assumir.
- **A condição pareada não é o *ground truth* histórico.** O D4.2 e o D4.3
  continuam associados ao conjunto sem diacríticos, agora com digest
  `1f05f49a…8ea2`. O pareado é uma condição experimental adicional, não uma
  substituição.
- **A prova de pareamento é ortográfica, não linguística.** Garante que só
  mudaram marcas combinantes; não garante que sejam as corretas. Anotador único,
  sem adjudicação.
- **Conjunto de julgamentos incompleto** (`DIRECTED_JUDGMENT_INCOMPLETE`): a
  maioria dos resultados devolvidos não tem julgamento e conta como grau 0. As
  células partilham o enviesamento; os valores absolutos não são estimativas não
  enviesadas.
- **BUG-D4.1-01 continua presente** e afeta todas as células por igual.
- **A quota de candidatos continua por estudar** e continua a truncar uma consulta
  com 240 correspondências em 6 (D4.3 §4).

## 11. Conclusão

1. **BUG-D4.2-01 tem impacto real e mensurável.** Uma pergunta que nenhuma outra
   condição recupera é recuperada em posição 1, por um mecanismo verificado ao
   nível do termo, sem regressão e sem ruído adicional.
2. **O efeito é específico, não geral.** Restituir diacríticos não move as cinco
   falhas semânticas e não altera nada nas variantes que não leem acentuação.
   Sobre a melhor política sem acentos, compra exatamente uma pergunta.
3. **A remoção de diacríticos antes do *stemming* é, ela própria, uma fonte de
   erro nos dois sentidos.** C1 mostra que a assimetria **destrói**
   correspondências que a igualdade exata tinha. Não é só uma oportunidade
   perdida: mal aplicada, é uma regressão.
4. **A identidade do *ground truth* deixou de ser convenção.** Cada resultado
   pode agora declarar sobre que versão das perguntas foi medido, com um digest
   determinístico e de âmbito explícito.

Nenhuma variante é recomendada para implementação nesta fase.

## 12. Próxima fase recomendada

**B — investigar a repartição do orçamento de candidatos e o ranking.**

Porque não **A** (implementar já uma correção lexical de produção), apesar da
confirmação: o D4.4 identifica o defeito, **não** uma correção. A alteração que
produziu o ganho não é implementável tal como foi medida — produção não pode
acentuar a pergunta de quem escreve sem acentos. Uma correção real teria de
escolher entre indexar texto acentuado, alterar a cadeia de dicionários ou
tratar as duas formas em paralelo; cada opção mexe no conjunto de candidatos de
**todas** as consultas, obriga a subir `LEXICAL_PIPELINE_VERSION` e arrisca
perder a insensibilidade a acentos de que a baseline hoje depende — `matricula`
encontra `matrícula` precisamente porque ambos os lados são desacentuados.
Nenhuma dessas opções foi medida. Implementar agora seria trocar um defeito
conhecido por um risco desconhecido.

Porque não **C** (preparar lexical contra denso/híbrido): continua prematuro,
pelo mesmo argumento do D4.3 §10. Restam dois defeitos concretos na etapa
lexical — a quota e, agora, um BUG-D4.2-01 confirmado mas por corrigir. Comparar
uma arquitetura nova contra uma baseline com defeitos conhecidos atribuiria à
arquitetura ganhos que eram apenas a correção do que já se sabe estar mal.

A fase B deve, por esta ordem:

1. **Estudar a quota junto com o ranking.** A quota impede uma política
   alternativa de alcançar alvos (Q009: 87 correspondências, quota 8), mas a sua
   remoção isolada piora tudo (D4.3 §5). É uma interação e tem de ser medida como
   tal.
2. **Desenhar e medir uma correção candidata para BUG-D4.2-01**, com as
   contrapartidas explícitas acima, antes de qualquer implementação — e, se a
   decisão depender de saber como os utilizadores escrevem, registá-lo como o que
   é: uma dependência de categoria B por resolver.

**Não foi iniciada.** Esta fase termina aqui.
