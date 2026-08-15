# D4.3 — Experimento controlado da correspondência lexical sobre P1/S1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo

Responder, com evidência e sem alterar produção:

> Qual alteração mínima na política de correspondência lexical melhora a
> recuperação das evidências relevantes sem aumentar de forma injustificada a
> recuperação de evidências irrelevantes?

Isto é um **experimento**, não uma otimização. Nenhuma variante foi implementada
no retrieval, e a escolha não é feita pelo maior Recall.

## 2. Baseline e estado Git

| Item | Valor |
| --- | --- |
| `origin/main` | `a88f4aeb03b2577b8ecad26634b8cbbbc9656bf6` (merge do Pull Request #50, D4.2) |
| Branch de trabalho | `analysis/d4-3-lexical-eligibility`, criada a partir de `origin/main` |
| `snapshot_id` | `a94f9402…baf4c1` — verificado antes de medir |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| Baseline D4.2 | `result_digest` `b00ca87b…7fb4` **reproduzido exatamente** |

O corpus, o *ground truth* e o retrieval de produção não foram tocados.

## 3. Desenho

Duas dimensões, e a segunda não é decorativa.

### 3.1 Políticas de correspondência

| Variante | Descrição | Alteração de produção? |
| --- | --- | --- |
| **A** `exact_canonical` | igualdade entre formas canónicas exatas — comportamento atual | Não |
| **B** `stem_normalized` | igualdade entre **radicais** das formas **sem acentos** que o sistema já persiste | Não |
| **C** `stem_accented` | igualdade entre radicais das formas **com acentos**, lidas do texto original de **cada lado** | Não |

Os radicais vêm de `ts_lexize('portuguese_stem', …)` — o *stemmer* que o próprio
índice FTS usa. Uma segunda implementação em Python divergiria dele e mediria um
sistema que não existe.

A variante é uma **projeção do espaço de termos**: pergunta e conteúdo são
projetados para o mesmo espaço e a comparação continua a ser igualdade. Os dois
lados têm mapas **separados**, cada um construído a partir do seu próprio texto —
a acentuação da pergunta vem da pergunta, a do segmento vem daquele segmento.

Marcadores canónicos (`ord:`, `rng:`) não são projetados: radicalizá-los
destruiria a distinção entre "1.ª chamada" e "2.ª chamada". `exact_phrase` e
`ordered` são mantidos constantes, para que uma variante não ganhe por dois
mecanismos ao mesmo tempo.

### 3.2 Condições de conjunto de candidatos

| Condição | Descrição |
| --- | --- |
| **P0** `production_quota` | quotas de produção, exatamente como hoje |
| **P1** `unbounded` | as **mesmas** consultas, sem quota |

P1 **não é uma proposta de sistema.** Existe porque quatro dos seis alvos
falhados no D4.2 foram classificados `NEVER_A_CANDIDATE`, e um alvo que nunca é
avaliado não pode ser recuperado por alteração nenhuma à elegibilidade.

### 3.3 Validação embutida

A célula **A/P0 tem de reproduzir o D4.2 por inteiro**, e nada é escrito se não
reproduzir. A guarda compara o **conjunto** de perguntas — incluindo as que o
D4.2 guarda numa lista separada por não terem métrica —, o **ranking
posicional**, Recall, MRR e nDCG por pergunta, as contagens devolvidas e os
agregados; e verifica que o próprio artefacto do D4.2 coincide com o seu
`result_digest`, para não comparar contra um ficheiro editado à mão.

Reproduziu: `Recall@5 = 0,4583`, `MRR = 0,3750`, `nDCG@5 = 0,3630`.

Uma versão anterior desta guarda comparava apenas o Recall das perguntas que
ambos os lados tivessem medido, e o conjunto de comparação era derivado do que a
célula continha — **uma célula vazia passava**. A versão atual está fixada por
testes que reprovam célula vazia, pergunta a mais, pergunta a menos, ranking
alterado, MRR alterado, nDCG alterado, contagem alterada, agregado alterado e
artefacto adulterado.

### 3.4 Reprodutibilidade

Duas execuções sobre S1 inalterado produziram o mesmo `result_digest` —
`9a86a1540229d4fab18b6fbace66c3008ab35978ab7bfba376012eb577e165b6` — e *payloads*
idênticos exceto `executed_at`.

## 4. A quota de candidatos: uma interação, não uma refutação

O D4.2 concluiu (§8.4) que o orçamento de candidatos estava subutilizado e que
não explicava nenhuma falha. **Dentro da política de correspondência atual, essa
conclusão está correta**: os contrafactuais do próprio D4.2 mostram que os quatro
alvos `NEVER_A_CANDIDATE` seriam rejeitados pela cobertura exata mesmo que
tivessem sido avaliados. Uma redação anterior deste relatório afirmava que o D4.2
"errou"; era uma sobredeclaração e foi retirada.

O que este experimento acrescenta é diferente e mais específico: **a quota
impede que uma política de correspondência alternativa alcance alguns alvos**. É
uma interação entre as duas etapas, não a substituição de uma causa por outra.

O mecanismo, verificado diretamente:

- o orçamento **global** é 25 e é repartido em quotas por variante de consulta —
  para Q009, `9 / 8 / 8`;
- as duas variantes conjuntivas devolveram **0** linhas, e as suas quotas **não
  são redistribuídas**;
- a variante `reduced_or` ficou com quota 8 para **87 correspondências**.

O alvo de Q009 (P1-DOC-007, segmento 251) **casa a tsquery** mas fica abaixo do
corte de 8 na ordenação por `ts_rank_cd`. Com correspondência exata isso não teria
importância — seria rejeitado a seguir. Com correspondência por radical passaria a
ser elegível, e é a quota que o impede de lá chegar.

Correspondências da consulta disjuntiva, contadas na condição sem quota:

| Pergunta | Correspondências | Quota efetiva |
| --- | --- | --- |
| Q003 | 240 | 6 |
| Q006 | 62 | 8 |
| Q009 | 87 | 8 |
| Q012 | 170 | 8 |

## 5. Métricas

Protocolo do D4.1, sem alteração: `k` primário 5, relevância binária a grau 2,
ganhos nDCG 0/1/3, não julgados como grau 0, macro-média sobre as 12 perguntas
medidas.

| Célula | R@1 | R@3 | R@5 | MRR | nDCG@1 | nDCG@3 | nDCG@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A/P0** (baseline) | 0,2083 | 0,4167 | **0,4583** | **0,3750** | 0,2500 | 0,3323 | 0,3630 |
| **B/P0** | 0,2083 | 0,4167 | **0,4583** | **0,3750** | 0,2500 | **0,3451** | **0,3749** |
| C/P0 | 0,1250 | 0,2500 | 0,2917 | 0,2500 | 0,1667 | 0,2192 | 0,2412 |
| A/P1 | 0,1667 | 0,2083 | 0,3750 | 0,2458 | 0,1667 | 0,1761 | 0,2529 |
| B/P1 | 0,1667 | 0,3750 | 0,4583 | 0,2806 | 0,1667 | 0,2607 | 0,2979 |
| C/P1 | 0,0833 | 0,2083 | 0,2083 | 0,1667 | 0,0833 | 0,1681 | 0,1681 |

Leituras que importam mais do que qualquer linha isolada:

1. **Sob as condições de produção, a variante B não muda Recall nem MRR.** São
   idênticos à baseline até à quarta casa. Ganha 0,0119 de nDCG@5, por surgirem
   segmentos de grau 1 e um distractor.
2. **A variante C regride em todas as métricas**, e a §6.2 explica porquê — é
   uma limitação desta condição experimental, não um veredicto sobre a
   hipótese.
3. **Retirar a quota, sozinho, piora tudo.** A/P1 tem Recall@5 0,3750 contra
   0,4583 da baseline: mais candidatos competem e empurram alvos para fora do
   top 5. Q001 cai de 0,50 para 0,00 e Q011 de 1,00 para 0,50.
4. **Nenhuma célula supera a baseline em MRR.** A melhor é B/P0, que a iguala.

## 6. Resultados das falhas

`R@5` por pergunta. As seis obrigatórias mais as duas que regridem.

| Pergunta | A/P0 | B/P0 | C/P0 | A/P1 | B/P1 | C/P1 | Interpretação |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Q003** | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | nunca recuperada |
| **Q006** | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | nunca recuperada; nenhuma variante devolve nada |
| **Q007** | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | nunca recuperada |
| **Q008** | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | nunca recuperada — **contraria a previsão do D4.2** |
| **Q009** | 0,00 | 0,00 | 0,00 | 0,00 | **1,00** | 0,00 | **única recuperação do experimento**: radical + conjunto sem quota |
| **Q012** | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | nunca recuperada |
| Q001 | 0,50 | 0,50 | 0,50 | **0,00** | **0,00** | **0,00** | regressão causada por P1 |
| Q011 | 1,00 | 1,00 | 1,00 | **0,50** | **0,50** | **0,50** | regressão causada por P1 |
| Q002 | 1,00 | 1,00 | **0,00** | 1,00 | 1,00 | **0,00** | regressão causada por C (§6.2) |
| Q005 | 1,00 | 1,00 | **0,00** | 1,00 | 1,00 | **0,00** | regressão causada por C (§6.2) |

**Uma única pergunta foi recuperada em todo o experimento**, e só na célula
B/P1 — que combina uma alteração de correspondência com a remoção da quota, e que
mesmo assim tem MRR e nDCG@5 abaixo da baseline.

### 6.1 Q008: a previsão do D4.2 não se confirmou

O D4.2 classificou Q008 como divergência morfológica resolúvel (`prorrogacao` na
pergunta, `prorrogar` no segmento). **Não se resolveu em nenhuma célula.**

```
stem(prorrogacao) = prorrogaca      stem(prorrogar) = prorrog
stem(prorrogação) = prorrog         ← conflaem, mas...
```

…a forma acentuada `prorrogação` **não existe no corpus**: os documentos usam o
verbo, nunca o nome deverbal. Nem a projeção do conteúdo nem a da pergunta a
podem produzir.

### 6.2 A variante C não é avaliável com este *ground truth*

Este é o achado metodológico mais importante da fase, e invalida uma conclusão
que uma redação anterior deste relatório apresentava como confirmada.

**As perguntas do *ground truth* não têm diacríticos.** Verificado: **0 de 163**
*tokens* das catorze perguntas trazem qualquer acento — foram escritas em ASCII
no artefacto do D4.1.

A variante C lê a acentuação do texto original de cada lado. Como o lado da
pergunta não tem acentuação para ler, a projeção fica **assimétrica**: o conteúdo
é radicalizado sobre as formas acentuadas, a pergunta sobre as formas sem
acentos. E o *stemmer* português trata as duas de maneira diferente:

```
pergunta: cerimonia  -> cerimon
conteúdo: cerimónia  -> cerimón     ← deixam de casar
```

O resultado é que C **quebra correspondências que a baseline tinha** — Q002 e
Q005 caem de 1,00 para 0,00 — e a sua regressão global mede a assimetria, não a
hipótese.

Uma versão anterior deste experimento usava um **índice global de acentuação
construído sobre todo o corpus**, o que reacentuava os termos da pergunta com
informação do corpus e fazia um segmento herdar o acento de outro. Nessa versão C
parecia a melhor variante e recuperava Q003 e Q004. **Esses resultados eram
artefacto do índice e foram descartados.**

Consequência a declarar sem rodeios: **BUG-D4.2-01 não pode ser testado sobre
este *ground truth***. Testá-lo exige perguntas que preservem diacríticos, e
esta fase não pode alterar o *ground truth*.

**Isto não é um defeito do artefacto do D4.1.** A tentação de lhe chamar defeito
é forte e seria um erro: o D4.1 declara explicitamente (§17) que as perguntas são
**construídas** e que a tipologia real dos pedidos pertence à categoria B, cujo
estado é **UNKNOWN**. Não existe, portanto, evidência de que um estudante escreva
com diacríticos — escrever sem acentos é comum, e afirmar o contrário seria
inventar exatamente o tipo de facto institucional que a categoria B proíbe
assumir.

O que existe é uma **propriedade** do *ground truth* atual, com uma consequência
precisa: ele não suporta a variante C. E a forma correta de a estudar **não é
reescrever as perguntas** — isso destruiria a comparabilidade do D4.2 e do D4.3,
que estão ancorados a estas perguntas — mas acrescentar uma **variante acentuada
como versão nova e condição pareada**, medida lado a lado com a atual. O
emparelhamento isola o fator diacrítico, que é precisamente o que uma reescrita
em cima do original tornaria impossível medir.

### 6.3 Q006, Q007 e Q012: nem morfológicas nem de acentuação

Nenhuma variante as move, e nenhuma devolve resultados em P0:

- **Q006** — *percentagem mínima* contra `75%`: formulação numérica;
- **Q007** — duração do alojamento expressa por uma regra de renovação;
- **Q012** — *entrega dos diplomas* contra *outorga de grau*: sinonímia
  institucional.

`cerimonia`/`cerimónia` e `residencia`/`residencias` colapsam corretamente sob B,
pelo que Q012 **não** falha por morfologia. As três são semânticas.

## 7. Regressões e ruído

### 7.1 Distractores de grau 0

Um único distractor julgado é recuperado por qualquer variante com radicalização:
**P1-DOC-002, segmento 89**, em Q003 — a renovação de matrículas do *1.º semestre
do ano letivo seguinte*. Aparece **acima** de qualquer alvo. A radicalização
torna o segmento do ano errado tão correspondente quanto o do ano certo, e o
ranking não tem como os distinguir: o corpus não tem vigência declarada.

### 7.2 Ruído agregado

| Célula | Devolvidos | Não julgados | Distractores grau 0 | Candidatos avaliados |
| --- | --- | --- | --- | --- |
| A/P0 | 23 | 14 | 0 | 104 |
| B/P0 | 28 | 16 | 1 | 104 |
| C/P0 | 16 | 9 | 1 | 104 |
| A/P1 | 34 | 27 | 0 | 2102 |
| B/P1 | 41 | 30 | 1 | 2102 |
| C/P1 | 26 | 21 | 1 | 2102 |

B sob produção acrescenta 5 resultados, dos quais 2 não julgados e 1 distractor —
e não compra Recall nenhum. C devolve **menos** do que a baseline, o que confirma
que está a perder correspondências em vez de relaxar.

### 7.3 Q013 — a pergunta sem evidência

**Devolve zero resultados nas seis células**, incluindo em P1, onde 261
candidatos foram avaliados.

É o resultado mais tranquilizador do experimento: se as variantes fossem
relaxamento disfarçado, a pergunta cuja resposta não existe no corpus começaria a
devolver resultados plausíveis. Não começou, nem com um conjunto de candidatos 33
vezes maior.

Continua a ser um **facto sobre o corpus**, não um desfecho de política: nada
aqui afirma `ABSTAIN` nem `NOT_ANSWERABLE`.

### 7.4 Morfologia ou relaxamento?

- **É morfologia, não relaxamento.** A única recuperação — Q009 em B/P1 — é
  atribuível a um mecanismo identificado (`residencia`/`residencias`);
- nenhum limiar foi baixado, e a política de elegibilidade é a de produção;
- Q013 não passou a devolver nada em nenhuma célula;
- o crescimento de resultados não julgados sob produção é de 2 em 23;
- mas o único distractor julgado que aparece surge acima do alvo, o que é
  precisão perdida.

## 8. Limitações

- **Amostra minúscula.** 12 perguntas medidas; uma pergunta vale 0,083 de
  Recall@5. Nenhuma diferença é estatisticamente sustentada.
- **A variante C é inavaliável** com este *ground truth* (§6.2), e com ela
  BUG-D4.2-01.
- **Conjunto de julgamentos incompleto** (`DIRECTED_JUDGMENT_INCOMPLETE`): a
  maioria dos resultados devolvidos não tem julgamento e conta como grau 0. As
  células partilham o enviesamento, mas os valores absolutos não são estimativas
  não enviesadas.
- **P1 não é um sistema.** Remover a quota sem mais nada degrada o serviço.
- **BUG-D4.1-01 continua presente** e afeta todas as células por igual.
- **A versão das perguntas não é identificável.** O `snapshot_id` cobre corpus,
  instituição, data de referência e configuração de recuperação — **não** o
  conjunto de perguntas — e nenhum artefacto guarda um digest do *ground truth*.
  A afirmação "estes resultados foram medidos com estas perguntas" é hoje
  convencional, não verificável por identidade.
- **Uma única execução por célula**, determinística.

## 9. Conclusão

Das três conclusões possíveis que o enunciado admitia, os dados sustentam a
**opção B**:

> A normalização morfológica resolve apenas parte pequena das falhas e as
> restantes são predominantemente semânticas.

Com três precisões:

1. **Sob condições de produção, a normalização morfológica não resolve falha
   nenhuma.** Recall e MRR ficam exatamente iguais; ganha-se 0,012 de nDCG@5 e
   perde-se precisão no topo de uma pergunta. Não há aqui um caso para alterar a
   elegibilidade.
2. **A única recuperação do experimento exige duas alterações em simultâneo** —
   radicalização e remoção da quota — e mesmo assim fica abaixo da baseline em
   MRR e nDCG@5. É uma interação, não um efeito de uma das partes.
3. **BUG-D4.2-01 continua por testar.** O mecanismo do *stemmer* é verificável
   diretamente, mas o seu efeito na recuperação não é mensurável enquanto as
   perguntas do *ground truth* não preservarem diacríticos.

Nenhuma variante é recomendada para implementação.

## 10. Próxima fase recomendada

**B — investigação adicional sobre uma falha concreta.** Duas candidatas, por
esta ordem:

1. **Uma condição pareada com diacríticos.** O *ground truth* atual não os tem
   (§6.2) e por isso não suporta a variante C, que é a única forma de testar
   BUG-D4.2-01. O trabalho **não é reescrever as perguntas**: é acrescentar uma
   **versão acentuada**, medida lado a lado com a atual, mantendo esta como
   referência. Só o par permite atribuir a diferença ao diacrítico em vez de a
   uma reformulação; e reescrever o original quebraria a comparabilidade
   histórica, porque o D4.2 e o D4.3 foram medidos **com esta versão das
   perguntas**.

   Nota sobre o que o `snapshot_id` cobre, e não cobre: ele identifica corpus,
   instituição, data de referência e configuração de recuperação — **não** o
   conjunto de perguntas. Nenhum dos artefactos guarda hoje um digest do *ground
   truth*, pelo que a ligação entre resultados e versão das perguntas é
   convencional e não verificável por identidade. Introduzir um
   `ground_truth_digest` ou um `question_set_version` é trabalho que a condição
   pareada torna necessário, e pertence a essa fase.

   Fica também por decidir, e é decisão da categoria B, **qual das duas formas
   representa o utilizador real** — o par mede as duas sem precisar de responder
   a isso já.
2. **A repartição do orçamento de candidatos**, que trunca uma consulta com 240
   correspondências em 6 e impede qualquer política alternativa de alcançar o
   alvo — mas cuja remoção isolada piora o resultado, pelo que precisa de ser
   estudada junto com o ranking.

Porque não as outras opções:

- **A (implementar a correção lexical e criar `lexical_pipeline_v2`) não é
  sustentada.** Sob produção a alteração não compra Recall nem MRR e introduz um
  distractor em posição de topo.
- **C (preparar experimento lexical contra denso/híbrido) é prematura.** Restam
  uma limitação da condição experimental e dois defeitos concretos na etapa
  lexical; comparar uma arquitetura nova contra uma baseline assim atribuiria à
  arquitetura ganhos que eram apenas a correção do que já se sabe estar mal.

**Não foi iniciada.** Esta fase termina aqui.
