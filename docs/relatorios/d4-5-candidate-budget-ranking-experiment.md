# D4.5 — Experimento controlado do orçamento de candidatos e do ranking sobre P1/S1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo

O D4.3 (§4) mostrou que o orçamento de candidatos é repartido em quotas fixas
antes de qualquer consulta, que a quota não utilizada não é redistribuída, e que
uma consulta disjuntiva com 240 correspondências pode ficar com quota 6. Mostrou
também que **remover o limite piora tudo**. A questão ficou em aberto.

Esta fase responde:

> Existe uma política de distribuição do orçamento de candidatos que aumenta a
> probabilidade de a evidência relevante chegar ao ranking sem degradar o top 5?

E responde a uma pergunta prévia que o D4.2 não conseguia colocar: quando um alvo
não é recuperado, **onde é que ele parou**?

Nenhuma alteração de produção foi feita. Nenhuma política é recomendada para
implementação.

## 2. Baseline e estado Git

| Item | Valor |
| --- | --- |
| `origin/main` | `b42f9ede32ab906a33cc4c675af948a939d59a1d` (merge do Pull Request #52, D4.4) |
| Branch de trabalho | `analysis/d4-5-candidate-budget`, criada a partir de `origin/main` |
| `snapshot_id` | `a94f9402…baf4c1` — verificado antes de medir, inalterado |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| `ground_truth_digest` | `1f05f49a…8ea2` — o conjunto histórico, inalterado |
| Baseline D4.2 | `result_digest` `b00ca87b…7fb4` **reproduzido exatamente** |
| `result_digest` do D4.5 | `3c6eed912f424e613e9993503fa6b1ceae102d9c7d16db1462a3d56818b9633c` |

O *working tree* tem **6 ficheiros: 1 modificado + 5 novos**. O único modificado é
[`docs/ai/02-current-state.md`](../ai/02-current-state.md), a atualização de
estado que a fase exige. Corpus, *ground truth*, retrieval de produção e
artefactos do D4.2/D4.3/D4.4 não foram tocados.

## 3. Desenho

### 3.1 As três políticas de orçamento

O orçamento global é `min(100, max(20, top_k × 5)) = 25`.

| Condição | Política |
| --- | --- |
| **A** `current_quota` | produção: `distribute_quotas(25, n)` calculado **antes** de qualquer consulta; cada variante recebe `LIMIT quota`; a quota não usada perde-se |
| **B** `redistribute_unused` | o **mesmo** teto de 25, em cascata: a quota de cada variante é a fórmula de produção aplicada ao que **sobra** |
| **C** `global_limited_pool` | variantes **sem** teto individual; a união é ordenada globalmente e truncada em 25 antes da elegibilidade |

B não é orçamento novo. É a mesma fórmula de produção aplicada ao remanescente, e
a soma das linhas devolvidas continua limitada a 25 — propriedade fixada por
teste. Se B ganhasse por gastar mais, a comparação com A não seria justa.

A condição `unbounded` do D4.3 **não** foi usada: introduzi-la aqui misturaria
dois fatores.

### 3.2 A ordenação de C não usa o score

`ts_rank_cd` é calculado contra a `tsquery` **daquela** variante. Duas variantes
são duas consultas diferentes e os seus scores não são grandezas comparáveis — é
a mesma razão pela qual `ScoreSemantics` declara `comparable_across_queries=False`
e pela qual produção nunca funde variantes por score.

C ordena primeiro por **prioridade de estratégia** — o critério que produção já
usa implicitamente ao repartir a quota por `STRATEGY_PRIORITY` — e só compara
scores **dentro** da mesma estratégia. Os desempates finais (documento, segmento,
identificador) existem para que a ordem seja total: sem eles, o resultado
dependeria da ordem em que a base devolvesse as linhas.

### 3.3 Dois painéis, e o segundo é secundário

O painel que decide é `exact_canonical`, a correspondência de produção.
`stem_normalized` corre as mesmas três políticas e responde **apenas** à pergunta
que o D4.3 deixou aberta — se a quota estava a impedir uma política de
correspondência alternativa de alcançar um alvo, chega redistribuir o orçamento
para a desbloquear? É diagnóstico. **Nenhuma conclusão sobre a quota de produção
se apoia nele.**

### 3.4 Separar candidate recall de ranking

O D4.2 classificava o destino de um alvo a partir do *trace*, e não conseguia
distinguir "nunca foi candidato" de "sobreviveu e ficou abaixo do corte" — daí o
`NOT_RETURNED_INDETERMINATE`. Aqui o conjunto de candidatos é conhecido por
inteiro e a lista ordenada é guardada **antes** do corte, pelo que o destino é
uma observação:

| Destino | Significado |
| --- | --- |
| `NEVER_A_CANDIDATE` | o alvo não entrou no conjunto de candidatos |
| `CANDIDATE_EXCLUDED` | entrou e a elegibilidade (ou o limiar) rejeitou-o |
| `RANKED_OUTSIDE_TOP_K` | sobreviveu, foi pontuado, e ficou fora do top 5 |
| `RETURNED` | está no top 5 |

Só o primeiro é um problema de **orçamento**; só o terceiro é um problema de
**ranking**. `candidate_recall` — a fração de alvos que chegaram a ser avaliados —
é acrescentada, nunca substitui as métricas do D4.2.

### 3.5 Validação e reprodutibilidade

A célula A × `exact_canonical` **tem** de reproduzir o artefacto do D4.2 por
inteiro, e nada é escrito se não reproduzir. Reproduziu.

Três execuções sobre S1 inalterado produziram *payloads* idênticos exceto
`executed_at`, com `result_digest` `3c6eed91…633c`.

## 4. Onde estão realmente os alvos

Antes das métricas, o facto que organiza a fase: a que distância do corte está
cada alvo.

O runner executa, uma vez por pergunta, cada variante do plano **sem teto** e
regista a posição de cada segmento de grau 2 na ordenação por `ts_rank_cd`. Os
dados vivem no artefacto, em `target_candidate_positions`, e o resumo recontável
em `target_position_summary` — a tabela abaixo é reconstruída deles, não contada
à mão. O bloco está no topo do artefacto, e não dentro de uma célula, porque
**não depende da política de orçamento**: é uma propriedade do corpus, da
consulta e da ordenação FTS.

`best_strategy` é a variante de **maior prioridade** que encontra o alvo, e a
quota indicada é a que essa variante recebe sob a política A. A alcançabilidade,
essa, é avaliada sobre **todas** as variantes: basta que uma o traga dentro da
sua quota.

| Pergunta | Alvo | Variante | Posição / total | Quota (A) | Alcançável? |
| --- | --- | --- | --- | --- | --- |
| Q010 | P1-DOC-005 / 397 | `reduced_or` | 1 / 93 | 8 | sim |
| Q011 | P1-DOC-003 / 72 | `reduced_or` | 1 / 119 | 6 | sim |
| Q005 | P1-DOC-004 / 175 | `reduced_or` | 2 / 62 | 8 | sim |
| Q007 | P1-DOC-007 / 160 | `reduced_or` | 2 / 245 | 8 | sim |
| Q014 | P1-DOC-002 / 24 | `canonical_relaxed_and` | 2 / 3 | 6 | sim |
| Q004 | P1-DOC-002 / 19 | `reduced_or` | 3 / 171 | 8 | sim |
| Q008 | P1-DOC-007 / 161 | `reduced_or` | 3 / 64 | 8 | sim |
| Q011 | P1-DOC-003 / 37 | `reduced_or` | 3 / 119 | 6 | sim |
| Q001 | P1-DOC-002 / 14 | `reduced_or` | 4 / 143 | 8 | sim |
| Q002 | P1-DOC-002 / 24 | `reduced_or` | 4 / 238 | 6 | sim |
| Q014 | P1-DOC-003 / 25 | `reduced_or` | 5 / 147 | 6 | sim |
| **Q006** | P1-DOC-004 / 184 | `reduced_or` | **9 / 62** | 8 | **não** |
| **Q003** | P1-DOC-002 / 44 | `reduced_or` | **10 / 240** | 6 | **não** |
| **Q001** | P1-DOC-002 / 16 | `reduced_or` | **13 / 143** | 8 | **não** |
| **Q009** | P1-DOC-007 / 251 | `reduced_or` | **13 / 87** | 8 | **não** |
| **Q012** | P1-DOC-002 / 78 | `reduced_or` | **99 / 170** | 8 | **não** |

São **os dezasseis** segmentos de grau 2 do *ground truth*, incluindo os dois de
Q014, que está excluída das métricas mas continua a ter alvos no corpus. Um teste
verifica que o conjunto registado coincide exatamente com os julgamentos de grau
2 do ficheiro de anotações, para que a tabela não possa voltar a ficar incompleta.

### 4.1 A previsão coincide com a observação

A coluna *Alcançável?* é uma **previsão**: um alvo entra no conjunto de
candidatos de `current_quota` se e só se alguma variante o traz dentro da sua
quota. São cinco os previstos inalcançáveis, e a execução observa exatamente
cinco `NEVER_A_CANDIDATE`, nos mesmos cinco segmentos.

O runner verifica essa coincidência e **recusa escrever** se ela falhar. Sem
isso, a tabela seria uma segunda medição não verificada ao lado da primeira, em
vez de a explicar.

### 4.2 Duas leituras, e as duas importam

1. **A quota está a cortar mesmo em cima dos alvos.** Quinze dos dezasseis estão
   nos **13 primeiros** da sua consulta; a quota efetiva é 6 ou 8. Quatro ficam
   de fora por uma diferença de uma a sete posições. Não é uma margem
   confortável — é um corte que passa no meio da distribuição.
2. **Q012 é outra coisa.** O seu alvo está na posição **99 de 170**. Nenhum
   orçamento defensável lá chega, e o D4.3 §6.3 já o classificara como falha
   semântica (*entrega dos diplomas* contra *outorga de grau*). Não é um problema
   de orçamento e não deve ser contado como tal.

## 5. Métricas

Protocolo do D4.1, sem alteração. Macro-média sobre as 12 perguntas medidas.

### 5.1 Painel primário — correspondência de produção

| Condição | R@1 | R@3 | R@5 | MRR | nDCG@1 | nDCG@3 | nDCG@5 | **candidate recall** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A** `current_quota` | 0,2083 | 0,4167 | **0,4583** | **0,3750** | 0,2500 | 0,3323 | **0,3630** | 0,6250 |
| **B** `redistribute_unused` | 0,1667 | 0,2917 | 0,3750 | 0,2569 | 0,1667 | 0,2178 | 0,2623 | **0,9167** |
| **C** `global_limited_pool` | 0,1667 | 0,2917 | 0,3750 | 0,2569 | 0,1667 | 0,2178 | 0,2623 | **0,9167** |

Delta A → B (idêntico para A → C):

| R@1 | R@3 | R@5 | MRR | nDCG@1 | nDCG@3 | nDCG@5 | candidate recall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| −0,0417 | −0,1250 | **−0,0833** | **−0,1181** | −0,0833 | −0,1146 | **−0,1007** | **+0,2917** |

**Todas as métricas de recuperação descem e a cobertura do conjunto de candidatos
sobe.** É o resultado central da fase, e as duas metades explicam-se na §6.

### 5.2 Painel secundário — diagnóstico

| Condição | R@3 | R@5 | MRR | nDCG@5 | candidate recall |
| --- | --- | --- | --- | --- | --- |
| A\* `stem_normalized` + `current_quota` | 0,4167 | 0,4583 | **0,3750** | 0,3749 | 0,6250 |
| B\* `stem_normalized` + `redistribute_unused` | **0,4583** | 0,4583 | 0,2917 | 0,3074 | **0,9167** |
| C\* `stem_normalized` + `global_limited_pool` | **0,4583** | 0,4583 | 0,2917 | 0,3074 | **0,9167** |

**Q009 é recuperada**, em posição 3. É a confirmação direta da hipótese do D4.3
§4: a quota estava mesmo a impedir uma política de correspondência alternativa de
alcançar aquele alvo. Mas mesmo aqui o Recall@5 fica igual — o ganho de Q009 é
exatamente anulado pelas perdas — e o MRR **desce** 0,0833.

## 6. Destino dos alvos

Dezasseis segmentos de grau 2, por condição:

| Condição | RETURNED | RANKED_OUTSIDE_TOP_K | CANDIDATE_EXCLUDED | NEVER_A_CANDIDATE |
| --- | --- | --- | --- | --- |
| A | **8** | 0 | 3 | 5 |
| B / C | 6 | **2** | 7 | **1** |
| A\* | **9** | 0 | 2 | 5 |
| B\* / C\* | 8 | **2** | 5 | **1** |

### 6.1 A metade boa: o orçamento é mesmo uma restrição

`NEVER_A_CANDIDATE` cai de **5 para 1**. Os quatro alvos que passam a ser
avaliados são exatamente os das posições 9, 10, 13 e 13 da §4. O único que
sobra é o de Q012, na posição 99.

Isto refuta, com observação direta, qualquer leitura de que a quota atual não
restringe nada: restringe, e restringe onde dói.

### 6.2 A metade má: nenhum deles sobrevive

Sob correspondência de produção, os quatro alvos recém-admitidos são **todos**
rejeitados pela elegibilidade:

| Pergunta | Alvo | A | B |
| --- | --- | --- | --- |
| Q001 | P1-DOC-002 / 16 | `NEVER_A_CANDIDATE` | `CANDIDATE_EXCLUDED` |
| Q003 | P1-DOC-002 / 44 | `NEVER_A_CANDIDATE` | `CANDIDATE_EXCLUDED` |
| Q006 | P1-DOC-004 / 184 | `NEVER_A_CANDIDATE` | `CANDIDATE_EXCLUDED` |
| Q009 | P1-DOC-007 / 251 | `NEVER_A_CANDIDATE` | `CANDIDATE_EXCLUDED` |

Zero recuperações. O motivo é sempre `insufficient_coverage` — a cobertura por
formas canónicas exatas, que o D4.3 já caracterizara. **O orçamento converte
"nunca avaliado" em "avaliado e rejeitado", e mais nada.**

### 6.3 E o ranking piora

Dois alvos que estavam no top 5 saem dele:

| Pergunta | Alvo | Posição em A | Posição em B |
| --- | --- | --- | --- |
| Q001 | P1-DOC-002 / 14 | **2** | **7** |
| Q011 | P1-DOC-003 / 72 | **4** | **8** |

E outros três descem sem sair: Q002 / 24 de 2 para 4, Q004 / 19 de 2 para 3,
Q011 / 37 de 1 para 2.

Quem os ultrapassa, em Q011:

```
A:  1 P1-DOC-003/37 (grau 2)   2 P1-DOC-003/21   3 P1-DOC-003/38   4 P1-DOC-003/72 (grau 2)
B:  1 P1-DOC-002/58   2 P1-DOC-003/37 (grau 2)   3 P1-DOC-002/66   4 P1-DOC-002/16   5 P1-DOC-002/38
```

**Quatro das cinco posições passam a ser ocupadas por P1-DOC-002**, que o *ground
truth* de Q011 declara com `document_level_relevance` **0** — é o calendário do
ano errado, o distractor que a pergunta foi construída para ter. O alvo de grau 2
cai para a posição 8. Não é uma lacuna de anotação: é o ranking a promover um
documento declarado irrelevante acima da evidência.

Em Q001 o mecanismo é diferente e igualmente revelador: os cinco resultados que
passam a ocupar o top 5 vêm **todos do mesmo documento do alvo**, P1-DOC-002, e
nenhum está julgado. Aqui o ranking não consegue discriminar **dentro** do
documento certo.

Nos dois casos o efeito é o mesmo: com mais candidatos, a ordenação escolhe pior.

## 7. Q009 em detalhe

O caso que o D4.3 identificou como demonstração da interação quota × elegibilidade.

| Condição | Candidatos | Linhas lidas | Quota `reduced_or` | Destino do alvo |
| --- | --- | --- | --- | --- |
| A | 8 | 8 | **8** | `NEVER_A_CANDIDATE` |
| B | 25 | 25 | **25** | `CANDIDATE_EXCLUDED` |
| C | 25 | 87 | sem teto | `CANDIDATE_EXCLUDED` |
| A\* | 8 | 8 | **8** | `NEVER_A_CANDIDATE` |
| **B\*** | 25 | 25 | **25** | **`RETURNED` (posição 3)** |
| **C\*** | 25 | 87 | sem teto | **`RETURNED` (posição 3)** |

O mecanismo, verificado:

- as duas variantes conjuntivas devolvem **0** linhas e, em A, as suas quotas
  (9 e 8) **perdem-se**; a disjuntiva fica com 8 para 87 correspondências;
- o alvo P1-DOC-007 / 251 está na posição **13** dessas 87 — cinco posições
  abaixo do corte;
- em B, as quotas não usadas caem em cascata e a disjuntiva recebe 25; o alvo
  entra no conjunto;
- sob correspondência de produção é então rejeitado por `insufficient_coverage`
  (`residencia` contra `residencias`, o caso do D4.2);
- sob `stem_normalized` sobrevive e é ordenado em **3.º**, com `R@5 = 1,00` e
  `RR = 0,333`.

Q009 precisa das **duas** alterações. Nem o orçamento sozinho nem a
correspondência sozinha a recuperam — o D4.3 já o tinha visto com o conjunto
ilimitado, e o D4.5 mostra que **25 candidatos bastam**: não é preciso remover o
limite, basta não o desperdiçar.

## 8. B e C produzem o mesmo resultado, a custos muito diferentes

| Condição | Linhas lidas da base | Candidatos avaliados |
| --- | --- | --- |
| A | 107 | 104 |
| B | **350** | 347 |
| C | **2105** | 350 |

Comparados registo a registo, **B e C devolvem exatamente os mesmos resultados,
os mesmos rankings, as mesmas métricas e os mesmos destinos em todas as 14
perguntas.** A única diferença em todo o artefacto é a contagem de candidatos
*excluídos* em Q014 (18 contra 21), porque C avaliou três candidatos a mais.

A razão é estrutural: as duas políticas só divergem quando uma variante de
prioridade superior devolve linhas, e neste corpus isso acontece **numa única
pergunta** — Q014, onde `canonical_relaxed_and` devolve 3. Nas outras treze, B dá
à disjuntiva o orçamento inteiro e lê as 25 primeiras linhas pela mesma ordem em
que C leria tudo para depois ficar com as 25 primeiras.

C lê **6 vezes mais linhas** para chegar ao mesmo sítio; em Q013 lê 261 para usar
25. Se alguma vez se decidisse alargar o conjunto de candidatos, C não teria
justificação sobre B neste corpus.

## 9. Ruído e regressões

| Condição | Devolvidos | Não julgados | Distractores grau 0 |
| --- | --- | --- | --- |
| A | 23 | 14 | **0** |
| B / C | 33 | 26 | **0** |
| A\* | 28 | 16 | 1 |
| B\* / C\* | 40 | 29 | 1 |

- **Perguntas com regressão métrica (painel primário):** Q001, Q002, Q004, Q011.
  São quatro das seis que o enunciado (§8) pedia para vigiar. Q005 e Q010
  mantêm-se intactas.
- **Distractores julgados: nenhum**, em nenhuma condição do painel primário. O
  distractor único que aparece no painel secundário (P1-DOC-002 / 89, em Q003) é
  o já documentado no D4.3 §7.1, e é custo da radicalização, não do orçamento.
- **Não julgados: 14 → 26.** É aqui que está o deslocamento. Sob
  `DIRECTED_JUDGMENT_INCOMPLETE` um resultado não julgado **não é** prova de
  irrelevância, e não deve ser lido como tal — com uma exceção declarada: em
  Q011, quatro dos deslocadores pertencem a um documento com
  `document_level_relevance` 0, e aí a irrelevância **está** anotada.
- **Q013 — a pergunta sem evidência — devolve zero resultados nas seis
  condições**, incluindo em C, onde 261 linhas foram lidas e 25 candidatos
  avaliados. Nenhuma política produziu evidência espúria. É o resultado mais
  tranquilizador da fase, e mantém-se um facto sobre o corpus, não um desfecho de
  política.
- **Q014**, excluída das métricas, é observável: no painel secundário passa a
  devolver as **duas** respostas corretas e incompatíveis (P1-DOC-002 / 24 e
  P1-DOC-003 / 25). Uma recuperação melhor torna a ambiguidade temporal mais
  visível, não menos — como no D4.4 §8.4.

## 10. Limitações

- **Amostra minúscula.** 12 perguntas medidas; uma pergunta vale 0,083 de
  Recall@5. Nenhuma diferença é estatisticamente sustentada.
- **Julgamentos incompletos.** A maioria dos resultados devolvidos não tem
  julgamento e conta como grau 0. O deslocamento observado na §6.3 é medido
  contra esse conjunto incompleto; só em Q011 há anotação ao nível do documento
  que o corrobore.
- **Uma única topologia de plano.** Neste corpus, as variantes conjuntivas
  devolvem zero em 13 das 14 perguntas. Um corpus onde elas contribuíssem faria
  B e C divergir, e a conclusão da §8 não se transporta.
- **`candidate_recall` mede alcance, não utilidade.** Um alvo que entra no
  conjunto e é rejeitado conta na cobertura e não conta em métrica nenhuma. É
  precisamente por isso que a fase reporta as duas.
- **BUG-D4.1-01 e BUG-D4.2-01 continuam presentes** e afetam todas as condições
  por igual. Nenhum foi corrigido, por decisão explícita do enunciado.
- **Os pesos do ranking não foram tocados.** A fase demonstra que o ranking é o
  bloqueio; **não** demonstra qual alteração o resolveria.

## 11. Conclusão

Das quatro conclusões que o enunciado admitia, a que os dados sustentam é a
**opção C** — *o problema está principalmente no ranking e exige investigação
própria* —, e é preciso dizer com precisão **em que sentido**.

O que a execução demonstra é isto:

> **O ranking torna inseguro ampliar o orçamento, e explica todas as regressões
> medidas.** Não que seja o principal bloqueio de todas as falhas.

A distinção não é retórica. A mesma execução mostra **dois bloqueios distintos**,
com remédios diferentes:

- **elegibilidade** — os quatro alvos que a redistribuição passa a admitir são
  todos rejeitados por `insufficient_coverage`. É o bloqueio já caracterizado
  pelo D4.3, e o orçamento não lhe toca;
- **ranking** — dois alvos que já sobreviviam saem do top 5 e outros três descem.
  É o bloqueio **novo**, e é ele que produz o saldo negativo.

Chamar ao ranking "o principal bloqueio" sem esta separação atribuir-lhe-ia as
seis falhas do D4.2, quando ele só responde por duas regressões e pela
impossibilidade de usar o orçamento como alavanca.

O argumento, em quatro passos que a mesma execução fornece:

1. **A quota é uma restrição real.** Quinze dos dezasseis alvos estão nos 13
   primeiros da sua consulta e a quota efetiva é 6 ou 8. Redistribuir o orçamento
   não usado eleva o `candidate_recall` de 0,6250 para 0,9167 e reduz os alvos
   nunca avaliados de 5 para 1. Quem afirmasse que a quota não restringe nada
   estaria a contradizer uma observação direta.
2. **Mas o orçamento não é a alavanca.** Sob correspondência de produção, os
   quatro alvos recém-admitidos são rejeitados pela elegibilidade, todos. O ganho
   de cobertura converte-se em zero ganho de métrica.
3. **E o custo aparece no ranking.** Com um conjunto maior, dois alvos que
   estavam no top 5 saem dele e outros três descem. Em Q011, quatro das cinco
   posições passam a ser ocupadas por um documento declarado irrelevante para
   aquela pergunta. O saldo é −0,0833 de Recall@5 e −0,1181 de MRR.
4. **O bloqueio muda de sítio, não desaparece.** A restrição deixa de ser
   "o alvo nunca é avaliado" e passa a ser "o alvo é avaliado e perde" — nuns
   casos na elegibilidade, noutros na ordenação. São duas etapas, e a fase não
   as funde: quatro alvos morrem na primeira, dois na segunda.

Consequência operacional imediata: **a quota atual deve ficar como está.** Não
porque esteja bem dimensionada — não está —, mas porque alargá-la sem antes
corrigir a discriminação a jusante troca uma falha silenciosa por uma regressão
medida.

Duas observações que não cabem na escolha única e que importa registar:

- **A opção D seria falsa.** O orçamento *é* uma alavanca — é condição
  **necessária** da única recuperação observada (Q009 em B\*), e o D4.5 mostra
  que bastam 25 candidatos, sem remover o limite. Não é condição **suficiente**.
- **`global_limited_pool` não tem justificação sobre `redistribute_unused`**
  neste corpus: mesmo resultado, seis vezes o custo de leitura (§8).

## 12. Próxima fase recomendada

**Investigação dirigida ao ranking, com o conjunto de candidatos fixo.**

O que a torna a próxima fase certa é o que a §6.3 mostra: com 25 candidatos, o
ranking coloca acima da evidência julgada segmentos de um documento que a
anotação declara irrelevante. Isso é mensurável sem tocar no orçamento, sem tocar
na elegibilidade e sem tocar no corpus — basta fixar a condição B e variar o que
se estuda.

**O que essa fase resolve, e o que não resolve.** Resolve as regressões de Q001 e
Q011 e a discriminação sobre o conjunto ampliado — ou seja, responde à pergunta
"é seguro alargar o orçamento?". **Não testa a recuperação dos quatro alvos
barrados pela elegibilidade** (Q001 / 16, Q003 / 44, Q006 / 184, Q009 / 251):
esses nunca chegam ao ranking, e nenhum peso os traz de volta. Ficam a depender
da correspondência lexical, que é matéria do D4.3 e do D4.4 e continua em aberto.
Declarar isto à partida evita que a fase seguinte seja avaliada por um resultado
que não pode produzir.

Antes de qualquer *tuning* de pesos, a fase deve responder a duas perguntas de
diagnóstico, por esta ordem:

1. **Que sinal falta?** Os deslocadores de Q011 vêm de um documento declarado
   irrelevante; os de Q001 vêm do documento certo. São dois modos de falha
   diferentes, e confundi-los levaria a ajustar o peso errado.
2. **Os julgamentos suportam a medição?** Vinte e seis dos trinta e três
   resultados de B não estão julgados. Medir uma alteração de ranking contra um
   conjunto assim mediria sobretudo a incompletude. Um *repooling* dirigido aos
   resultados que as condições B/C introduzem é provavelmente pré-requisito, e
   isso **altera o `ground_truth_digest`** — que existe precisamente para tornar
   essa mudança visível.

**Não foi iniciada.** Esta fase termina aqui.
