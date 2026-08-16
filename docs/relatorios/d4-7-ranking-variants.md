# D4.7 — Ablação e reponderação controlada do ranking lexical sobre P1/S1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo e hipótese

A D4.6 concluiu que os sinais atuais discriminam na maioria dos casos
observáveis, e classificou seis pares (alvo, concorrente) como **A — a
ponderação pode estar errada**. Esta fase testa se isso é verdade:

> Alterações controladas nos pesos do ranking lexical conseguem melhorar a
> ordenação da evidência relevante sem introduzir regressões relevantes?

Nada foi alterado em produção. Cada variante é um vetor de pesos escrito à mão a
partir de uma hipótese nomeada. **Não houve otimização, pesquisa em grelha nem
ajuste por tentativa e erro**: com doze perguntas medidas, procurar pesos
produziria sobreajustamento e não conhecimento.

## 2. Contexto experimental

| Item | Valor |
| --- | --- |
| `origin/main` | `1a62016ff2d0f2fecc4be7710d4ca81f6c44f303` (merge do Pull Request #54, D4.6) |
| Branch de trabalho | `analysis/d4-7-ranking-variants`, criada a partir de `origin/main` |
| `snapshot_id` | `a94f9402…baf4c1` — verificado antes de medir |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| `ground_truth_digest` | `ada6b388…8586e` — o **repooled** da D4.6, verificado como pré-condição |
| Diagnóstico D4.6 | `result_digest` `b10e940c…bf13f` — células reproduzidas **exatamente** |
| `result_digest` do D4.7 | `420005541b58033bc6efd4cef2da254dc720b39e06d8fe30eb97fad2640c8b11` |

Três execuções produziram *payloads* idênticos exceto `executed_at`.

Constantes: corpus, snapshot, perguntas, *query planning*, elegibilidade, FTS,
orçamento de candidatos, `top_k`, extração, OCR e segmentação. O conjunto de
candidatos é recolhido **uma vez** por pergunta e por política e reutilizado por
todas as variantes — se cada uma recolhesse o seu, uma diferença poderia vir da
base de dados e não dos pesos.

O artefacto do D4.6 é verificado contra o seu próprio `result_digest` antes de
qualquer medição. Reproduzir as células não substitui essa verificação: elas são
recalculadas a partir da base e continuariam a coincidir mesmo com o digest
adulterado, e o D4.7 acabaria a declarar uma ligação a um digest que não descreve
o conteúdo consumido. Verificado por execução: com o digest adulterado o comando
recusa com código 4 e **nada** é escrito.

### 2.1 Porque é que as variantes são renormalizadas

`app.retrieval.reranking` **exige** que os pesos somem 1,0 e levanta erro se não
somarem: um vetor que não some 1,0 não é uma configuração de produção possível, e
testá-lo mediria algo que nunca poderia ser adotado.

Há uma segunda razão, decisiva para a validade. O limiar mínimo de relevância é
**absoluto**. Zerar um peso sem renormalizar encolheria todos os scores e poderia
empurrar candidatos para baixo do limiar — a variante passaria a alterar **quem é
devolvido** e não apenas a ordem, e o efeito medido seria uma mistura de
ordenação com corte.

Verificado: em todas as catorze células, **zero** candidatos ficaram abaixo do
limiar, e o conjunto elegível é idêntico entre variantes. As variantes reordenam
e mais nada.

A contrapartida tem de ser declarada: renormalizar faz uma ablação responder a
*"que peso relativo deve este sinal ter face aos restantes?"* e não a *"o que
acontece se este termo desaparecer sem mais nada mudar?"*. É a pergunta certa
para quem quer decidir uma configuração, e é a única que a produção aceitaria.

## 3. Variantes testadas

| Variante | Alteração | Hipótese |
| --- | --- | --- |
| **A0** | pesos de produção | Controlo. Tem de reproduzir a D4.6 por inteiro. |
| **A1** | `structure_table_row` → 0 | O bónus está disponível a **um** dos seis documentos (D4.6 §5.2): mede extração, não pertinência. Removido, a falha entre documentos de Q011 deve desaparecer. |
| **A2** | `structure_table_row` 0,06 → 0,01 | Se o sinal tiver valor legítimo em documentos bem extraídos, reduzi-lo preserva-o e deixa de decidir comparações entre documentos. |
| **A3** | `section_overlap` → 0 | A secção premeia cabeçalhos que contêm o ano por acidente de titulação (D4.6 §5.3). |
| **B1** | `title_overlap` 0,07 → 0,14 | É o único sinal ao nível do **documento**, e a D4.6 mostrou que sozinho inverteria a falha entre documentos de Q011. |
| **B2** | `proximity` 0,14 → 0,07 | A proximidade recompensa densidade lexical, e um cabeçalho é maximamente denso sem responder a nada (D4.6 §5.1). |
| **B3** | A1 + B1 | As duas alterações mais justificadas atacam modos de falha diferentes. Compõem-se ou interferem? |

Duas políticas de orçamento: **`current_quota`** — o painel que decide, porque é
o de produção — e `redistribute_unused`, secundário, porque a D4.5 concluiu que é
o ranking que torna inseguro ampliar o orçamento e esta é a fase que pode
responder se isso muda.

## 4. Métricas

### 4.1 Painel primário — orçamento de produção

| Variante | R@1 | R@3 | R@5 | MRR | nDCG@1 | nDCG@3 | nDCG@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A0** | 0,2500 | 0,4167 | 0,4583 | 0,4167 | 0,3333 | 0,3637 | 0,3867 |
| A1 | 0,2500 | 0,4167 | 0,4583 | 0,4167 | 0,3333 | 0,3637 | 0,3867 |
| A2 | 0,2500 | 0,4167 | 0,4583 | 0,4167 | 0,3333 | 0,3637 | 0,3867 |
| **A3** | 0,2500 | **0,4583** | 0,4583 | 0,4167 | 0,3333 | **0,3892** | **0,3902** |
| B1 | 0,2500 | 0,4167 | 0,4583 | 0,4167 | 0,3333 | 0,3637 | 0,3867 |
| B2 | 0,2500 | 0,4167 | 0,4583 | 0,4167 | 0,3333 | 0,3637 | 0,3867 |
| B3 | 0,2500 | 0,4167 | 0,4583 | 0,4167 | 0,3333 | 0,3637 | 0,3867 |

**Cinco das seis variantes são bit a bit idênticas à baseline.** É o resultado
central da fase, e é negativo.

A sexta, A3, move uma coisa: o segundo alvo de Q011 sobe da posição 4 para a 3 —
dentro do top 5 nos dois casos, pelo que Recall@5 e MRR não mexem e o ganho é
`+0,0035` de nDCG@5.

### 4.2 Painel secundário — orçamento ampliado

| Variante | R@1 | R@3 | R@5 | MRR | nDCG@1 | nDCG@5 | Comparável? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A0** | 0,2083 | 0,2917 | 0,3750 | 0,3125 | 0,3333 | 0,3701 | sim |
| A1 | **0,2500** | 0,2917 | 0,3750 | **0,3542** | **0,4167** | **0,3890** | sim |
| A2 | **0,2500** | 0,2917 | 0,3750 | **0,3542** | **0,4167** | **0,3890** | sim |
| A3 | 0,2083 | 0,2917 | 0,3750 | 0,3125 | 0,3333 | 0,3701 | **não — repooling** |
| B1 | 0,2083 | 0,2917 | 0,3750 | 0,3125 | 0,3333 | 0,3701 | sim |
| B2 | 0,2083 | 0,2917 | **0,4167** | **0,3292** | 0,3333 | **0,3881** | sim |
| **B3** | **0,2500** | 0,2917 | **0,4167** | **0,3542** | **0,4167** | **0,4088** | sim |

Aqui **há** movimento, e no sentido previsto. Nenhuma variante regride em
pergunta nenhuma, em nenhum dos dois painéis.

## 5. Melhorias e regressões, por pergunta

| Painel | Variante | Pergunta | Alvo | Antes → depois | Efeito |
| --- | --- | --- | --- | --- | --- |
| produção | A3 | Q011 | DOC-003 / 72 | rank 4 → **3** | nDCG@5 0,877 → 0,920 |
| produção | A3 | Q001 | — | reordena dois grau 0 | sem efeito métrico |
| ampliado | A1, A2 | Q011 | DOC-003 / 37 | rank 2 → **1** | RR 0,50 → **1,00**; nDCG@5 0,387 → 0,613 |
| ampliado | A1, A2 | Q002 | — | reordena dois grau 0 | sem efeito métrico |
| ampliado | B2 | Q001 | DOC-002 / 14 | rank 7 → **5** | R@5 0,00 → **0,50**; nDCG@5 0,185 → 0,401 |
| ampliado | B3 | Q011 | DOC-003 / 37 e / 72 | rank 2 → **1** e 8 → **5** | R@5 0,50 → **1,00**; nDCG@5 0,387 → 0,850 |

**Regressões: nenhuma.** Em nenhuma variante, em nenhum painel, em nenhuma
pergunta.

### 5.1 Porque é que o painel de produção não se move

É a observação mais informativa da fase, e qualifica a D4.6.

A falha entre documentos de Q011 — o caso mais forte do diagnóstico, em que um
segmento do calendário do ano errado ultrapassava a evidência correta —
**não existe sob o orçamento de produção**. Com a quota atual, o conjunto de
candidatos de Q011 tem seis segmentos, **todos do P1-DOC-003**, o documento
certo. O concorrente P1-DOC-002 / 58 só entra quando o orçamento é ampliado.

Daí que A1, cuja justificação era precisamente essa falha, não tenha nada para
corrigir em produção: remove um sinal que, ali, não está a decidir nada.

O mesmo vale para B2. A falha de densidade lexical de Q001 — cabeçalhos a vencer
o conteúdo — manifesta-se com o alvo na posição **7** sob o orçamento ampliado; em
produção o alvo está na posição **2**, atrás de um único concorrente, e reduzir a
proximidade a metade não chega para o inverter.

Fica assim estabelecido: **os modos de falha que a D4.6 diagnosticou são, em
larga medida, propriedades do conjunto ampliado, não do sistema em produção.**

### 5.2 Porque é que B1 sozinho não faz nada

A D4.6 mostrou que `title_overlap` sozinho inverteria a falha entre documentos de
Q011. Reforçá-lo não inverteu nada.

A razão é a renormalização, e é instrutiva: o peso extra dado ao título tem de
sair de algum lado, e sai proporcionalmente de todos os outros — incluindo de
`coverage`, que **também** favorecia o alvo naquele par (D4.6 §5.2: `+0,0500`). O
ganho num sinal é pago com a perda noutro que apontava no mesmo sentido, e o
saldo é nulo.

É por isso que B3 funciona onde B1 falha: removido o bónus estrutural, o peso
libertado financia o reforço do título **sem** ter de o tirar à cobertura.
As duas alterações compõem-se porque uma paga a outra.

### 5.3 O caso B da D4.6 continua por resolver

A D4.6 classificou o alvo **Q011 / P1-DOC-003 / 72** como caso **B**: dominado em
**todos** os sinais pelo concorrente P1-DOC-003 / 21, pelo que nenhuma
reponderação com pesos não negativos o pode colocar à frente.

Sob B3, esse alvo entra no top 5 (posição 5) e o Recall@5 de Q011 passa de 0,50 a
1,00. **Isto não resolve o caso B, e seria um erro apresentá-lo como tal.**

O ranking de B3 para Q011 é:

```
1  DOC-003/37 (grau 2)   2  DOC-002/58 (grau 0)   3  DOC-003/21 (grau 0)
4  DOC-003/38 (grau 0)   5  DOC-003/72 (grau 2)
```

O alvo 72 continua **abaixo** do 21 que o domina. Entrou no top 5 porque outros
concorrentes — segmentos do P1-DOC-002 — foram empurrados para baixo, e não
porque tenha passado à frente de quem o vence. A dominância mantém-se intacta em
todas as sete variantes, nos dois painéis, como a aritmética exigia.

**O caso B permanece insolúvel por reponderação, e confirma-se como candidato a
sinal novo.**

## 6. Resultados não julgados

| | |
| --- | --- |
| Variantes com resultados por julgar | **1** (A3, apenas no painel ampliado) |
| Quantidade | 1 segmento — P1-DOC-002 / 4, posição 5 de Q001 |
| Perguntas | Q001 |
| Repooling necessário | **SIM**, para essa variante e só para ela |

A3 remove `section_overlap` e, no conjunto ampliado, promove ao top 5 um segmento
que a D4.6 não anotou. O protocolo pontua não julgado como grau 0, o que aqui
seria uma armadilha: A3 seria penalizada por trazer à superfície algo que ninguém
avaliou. A célula está marcada `REPOOLING_REQUIRED` e **o *ground truth* não foi
alterado**.

As restantes seis variantes não introduzem resultados por julgar em nenhum
painel: os seus deltas são comparáveis sem reservas.

## 7. Limitações

- **Amostra minúscula.** Doze perguntas medidas; uma pergunta vale 0,083 de
  Recall@5. Nenhuma diferença é estatisticamente sustentada, e a maior variação
  observada corresponde a uma única pergunta a mudar de posição.
- **Renormalização.** As ablações medem peso **relativo**, não remoção pura
  (§2.1). É a única leitura que a produção aceitaria, mas é uma leitura.
- **Sete vetores escritos à mão.** Não há garantia de que não exista uma
  ponderação melhor; há a garantia de que não se procurou nenhuma. Uma variante
  acrescentada depois de ver os resultados seria procura de pesos disfarçada de
  hipótese, e por isso não foi acrescentada — nem sequer a combinação A1 + B2,
  que a aritmética de Q001 sugere.
- **O painel secundário não é produção.** Todos os ganhos de B3 e B2 vivem numa
  política de orçamento que a D4.5 recomendou **não** adotar.
- **Julgamentos incompletos por construção.** O repooling da D4.6 cobre os
  resultados devolvidos pelas condições daquela fase; qualquer variante que mova
  segmentos novos para o top 5 volta a precisar de anotação — foi o que
  aconteceu com A3.
- **BUG-D4.1-01 e BUG-D4.2-01 continuam presentes**, e o primeiro é a causa da
  assimetria estrutural que A1 e A2 contornam sem corrigir.

## 8. Conclusão científica

> **A — nenhuma variante deve avançar.**

O argumento, em quatro passos:

1. **Sob o orçamento de produção, seis das sete variantes não mudam nada.** Cinco
   são bit a bit idênticas à baseline; A3 move um alvo de grau 2 da posição 4
   para a 3 numa pergunta, o que vale `+0,0035` de nDCG@5 e nem toca em Recall@5
   ou MRR. Recomendar uma alteração de pesos com esta evidência, sobre doze
   perguntas, seria sobreajustamento por definição.
2. **Os ganhos reais existem, mas fora de produção.** B3 melhora Q011 de forma
   substancial e sem regressões — R@5 0,50 → 1,00, nDCG@5 0,387 → 0,850 —, e B2
   recupera Q001. Ambos só sob o orçamento ampliado, que a D4.5 recomendou não
   adotar. Um ganho condicionado a uma alteração que já foi desaconselhada não é
   um ganho disponível.
3. **A D4.6 sobrestimou o alcance do diagnóstico, e esta fase corrige-o.** Os
   modos de falha diagnosticados são em larga medida propriedades do conjunto
   ampliado. Em produção, o concorrente que motivava A1 nem sequer é candidato.
4. **O caso B continua insolúvel por reponderação**, como a aritmética previa, e
   a sua aparente melhoria sob B3 é deslocação de terceiros e não inversão do par
   que o domina.

Há um resultado positivo que importa registar sem o transformar em recomendação:
**B3 é a primeira configuração em que o orçamento ampliado deixa de ser
claramente pior.** Contra a produção atual, `redistribute_unused` + B3 perde em
Recall@5 (0,4167 contra 0,4583) e em MRR (0,3542 contra 0,4167) mas **ganha** em
nDCG@5 (0,4088 contra 0,3867). É uma combinação de dois mecanismos e esta fase
não a testou como proposta; é uma pista para quem retomar o assunto.

## 9. Próximo passo recomendado

**Preparar o experimento comparativo entre recuperação lexical e denso/híbrido,
sobre P1/S1.**

A justificação é o esgotamento, documentado e por medição, das alavancas locais:

| Alavanca | Fase | Resultado |
| --- | --- | --- |
| Correspondência morfológica | D4.3 | resolve pouco; o resto é semântico |
| Diacríticos | D4.4 | defeito confirmado, uma pergunta, correção por desenhar |
| Orçamento de candidatos | D4.5 | restrição real, não é a alavanca |
| Qualidade dos julgamentos | D4.6 | corrigida onde afetava a comparação |
| **Pesos do ranking** | **D4.7** | **sem ganho em produção** |

O que resta por recuperar — Q003, Q006, Q007, Q009, Q012 — foi classificado pela
D4.3 §6.3 como **semântico**: formulação numérica, regra expressa por renovação,
sinonímia institucional. Nenhum desses alvos chega sequer ao ranking, pelo que
nenhum peso os pode alcançar. É exatamente a classe de falha que uma abordagem
semântica existe para atacar, e é a pergunta que o projeto tem por responder.

Três pré-condições que a fase seguinte deve declarar à partida, e que decorrem
desta série:

1. **Repooling é obrigatório antes de comparar.** Uma arquitetura nova traz
   resultados que ninguém anotou; a D4.6 mostrou que 84 % de uma regressão
   medida podia ser incompletude da anotação. O `ground_truth_digest` existe para
   tornar essa necessidade visível.
2. **BUG-D4.2-01 fica declarado como confundidor.** Está confirmado e por
   corrigir; penaliza o lado lexical da comparação, e omiti-lo creditaria à
   arquitetura nova um ganho que é a correção de um defeito conhecido.
3. **A assimetria de extração (BUG-D4.1-01) também.** A D4.6 mostrou que
   corrompe um sinal de ranking; a D4.7 mostrou que removê-lo não custa nada em
   produção. Corrigi-la muda o `corpus_digest` e exige um snapshot novo, pelo que
   pertence a uma fase própria — mas tem de constar das limitações da comparação.

**Não foi iniciada.** Esta fase termina aqui.
