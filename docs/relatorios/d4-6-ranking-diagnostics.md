# D4.6 — Repooling dirigido e diagnóstico dos sinais de ranking sobre P1/S1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo

O D4.5 concluiu que o ranking torna inseguro ampliar o orçamento de candidatos, e
deixou uma ressalva que impedia agir sobre isso: **26 dos 33 resultados** da
condição ampliada não tinham julgamento. Medir uma alteração de ranking contra
esse conjunto mediria sobretudo a incompletude da anotação.

Esta fase faz as duas coisas por ordem:

**A.** reforça os julgamentos onde eles faltam — e só aí;
**B.** decompõe os sinais que decidem cada comparação, para responder a:

> Os sinais existentes no ranking lexical atual contêm informação suficiente para
> discriminar os candidatos relevantes dos candidatos que os ultrapassam?

Nenhum peso, limiar, fórmula, orçamento ou política de produção foi alterado.
**Isto é diagnóstico, não afinação.**

## 2. Baseline e estado Git

| Item | Valor |
| --- | --- |
| `origin/main` | `85c00550ffaa195b9b9adad3bbcec35c448d2774` (merge do Pull Request #53, D4.5) |
| Branch de trabalho | `analysis/d4-6-ranking-diagnostics`, criada a partir de `origin/main` |
| `snapshot_id` | `a94f9402…baf4c1` — verificado antes de medir, inalterado |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| Experimento D4.5 | `result_digest` `3c6eed91…633c` — células reproduzidas **exatamente** |
| `result_digest` do D4.6 | `b10e940c1164f2611a13a0c6194be267fb76c8d0fb4e015537e443b83d3bf13f` |

Três execuções sobre S1 inalterado produziram *payloads* idênticos exceto
`executed_at`.

## 3. Etapa A — repooling dirigido

### 3.1 O que foi anotado, e porquê exatamente isso

O conjunto a julgar é a **união dos resultados que entraram no top 5 de qualquer
uma das seis células do D4.5** — 47 pares (pergunta, segmento), dos quais 13 já
estavam julgados. Foram anotados os **34** restantes.

A união é deliberada e não é a leitura literal do enunciado. Anotar apenas os
resultados da condição ampliada daria a essa condição mais julgamentos do que à
baseline, e a comparação entre as duas passaria a medir também a diferença de
densidade da anotação. É o mesmo cuidado que o D4.4 teve com os controlos nulos:
o que se compara tem de ser simétrico.

O corpus **não** foi anotado por inteiro, e o conjunto continua
`DIRECTED_JUDGMENT_INCOMPLETE`: o repooling reduz a incompletude onde ela afeta a
comparação, não a elimina.

### 3.2 Identidade e regra de extensão

| | Valor |
| --- | --- |
| `ground_truth_digest` **antes** | `1f05f49ae8f596175b6943734c3778d73280e6a2f89da7886db08434e6db8ea2` |
| `ground_truth_digest` **depois** | `ada6b38886a06910e425e4be164099a3a63320050890253404064e3fde88586e` |

O conjunto histórico **não foi tocado**. O novo vive em
`retrieval-ground-truth-p1-repooled.json` e mantém os **mesmos**
`question_id` — ao contrário do conjunto pareado do D4.4, aqui as perguntas são
as mesmas letra a letra; o que muda é a densidade da anotação, e é o digest que
distingue as duas versões. É exatamente para isto que ele foi criado na D4.4.

A regra que o código impõe, e que não é negociável:

> **acrescentar julgamentos é legítimo; rever os existentes não é.**

Uma revisão silenciosa de um grau antigo tornaria a série D4.2–D4.5 incomparável
sem que nada o assinalasse, e faria a comparação "antes e depois do repooling"
medir a mudança de opinião do anotador em vez da incompletude.
`verify_repooling` recusa qualquer revisão ou remoção, e o campo `revisions` do
artefacto é vazio **por construção**, não por acaso.

O que o código **não** prova é que os graus novos estejam certos. Isso é juízo do
anotador — único, sem adjudicação, como no conjunto histórico.

### 3.3 O que foi acrescentado

| Grau | Novos julgamentos |
| --- | --- |
| 0 — irrelevante | **27** |
| 1 — contexto útil, insuficiente | **6** |
| 2 — diretamente relevante | **1** |
| **Total** | **34**, em 9 perguntas |

Cobertura dos resultados devolvidos, antes e depois:

| Condição | Antes | Depois |
| --- | --- | --- |
| `current_quota` | 9 / 23 julgados | **23 / 23** |
| `redistribute_unused` | 7 / 33 julgados | **33 / 33** |

**Nenhum resultado devolvido fica por julgar**, em nenhuma das duas condições. É
o pré-requisito que o D4.5 identificou, e está satisfeito.

Os seis graus 1 são todos do mesmo tipo — cabeçalhos de secção que **localizam** a
resposta sem a dar. Seguem a precedência que o D4.1 já fixara ao classificar o
cabeçalho do capítulo de candidaturas de Q009 como grau 1.

### 3.4 O único grau 2 novo, e o que ele desfaz

**Q004 / P1-DOC-002 / 57** — *"Publicação da lista de inscritos em UCT 2025-2026 |
Até 15 de março de 2026"*, na secção do 2.º semestre.

A pergunta — *"Quando é publicada a lista de inscritos em UCT no ano letivo
2025/2026?"* — **não fixa semestre**, e o calendário publica a lista duas vezes
nesse ano. A anotação original registou apenas a ocorrência do 1.º semestre. A
segunda é evidência igualmente direta, e faltava.

A consequência é a que dá sentido a toda a Etapa A: este segmento estava em
**posição 1 em todas as seis células** do D4.5. O que o D4.5 leu como "o alvo foi
empurrado de 2.º para 3.º" era, na verdade, **outra resposta correta à frente da
primeira**.

É a única pergunta cujo denominador do Recall mudou (1 → 2), e é por isso que os
resultados históricos continuam ligados ao digest antigo.

### 3.5 O que o repooling muda nas métricas

| Condição | *Ground truth* | R@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- |
| `current_quota` | histórico | 0,4583 | 0,3750 | 0,3630 |
| `current_quota` | **repooled** | 0,4583 | **0,4167** | **0,3867** |
| `redistribute_unused` | histórico | 0,3750 | 0,2569 | 0,2623 |
| `redistribute_unused` | **repooled** | 0,3750 | **0,3125** | **0,3701** |

E, sobretudo, o que muda na **regressão** que o D4.5 mediu:

| Δ (`current_quota` → `redistribute_unused`) | Histórico | Repooled |
| --- | --- | --- |
| Recall@5 | −0,0833 | −0,0833 |
| MRR | −0,1181 | −0,1042 |
| **nDCG@5** | **−0,1007** | **−0,0166** |

**Cerca de 84 % da regressão de nDCG@5 medida pelo D4.5 era artefacto de
resultados por julgar.** Sob anotação completa, a condição ampliada fica quase a
par da baseline nessa métrica. A perda de Recall@5 não se move — essa é real — e
a de MRR quase não se move.

Das quatro regressões que o D4.5 reportou:

| Pergunta | Sob o *ground truth* histórico | Sob o repooled |
| --- | --- | --- |
| **Q004** | RR 0,50 → 0,33 | **RR 1,00 → 1,00 — a regressão desaparece** |
| Q001 | R@5 0,50 → 0,00 | **mantém-se** (R@5 0,50 → 0,00) |
| Q002 | RR 0,50 → 0,25 | **mantém-se** |
| Q011 | R@5 1,00 → 0,50 | **mantém-se** |

Uma das quatro não era uma regressão. As outras três são.

## 4. Etapa B — os sinais que decidem

### 4.1 A base real, e só ela

`compute_score` é uma soma ponderada de **nove** termos. Estes, com os pesos do
código:

| Sinal | Peso |
| --- | --- |
| `coverage` | 0,40 |
| `exact_phrase` | 0,16 |
| `proximity` | 0,14 |
| `ordered` | 0,08 |
| `title_overlap` | 0,07 |
| `structure_table_row` | 0,06 |
| `section_overlap` | 0,05 |
| `fts_component` | 0,02 |
| `strategy_quality` | 0,02 |

`compactness` e `length_factor` **não** aparecem, e a omissão é deliberada: não
são parcelas do somatório. A primeira só condiciona o bónus estrutural; a segunda
multiplica `fts_norm` dentro de `fts_component`. Listá-las inventaria sinais que
o código não tem. Um teste verifica que a soma ponderada destes nove termos
reproduz `compute_score` exatamente.

### 4.2 O critério de classificação

Para cada par (alvo de grau 2, candidato acima dele) a decisão é aritmética. O
score é `Σ wᵢ · sᵢ` com todos os `wᵢ ≥ 0`, logo:

- **B — sinais insuficientes**: todos os sinais do alvo são `≤` aos do
  concorrente. Nenhuma reponderação com pesos não negativos inverte o par;
- **A — sinais discriminam**: algum sinal favorece o alvo, pelo que existe pelo
  menos uma reponderação que inverteria aquele par;
- **C — indeterminado**: o alvo não chegou ao ranking; não há par observável.

Acrescenta-se um segundo teste, mais exigente e **suficiente**: existe um sinal
que favorece o alvo contra **todos** os concorrentes ao mesmo tempo? Se existir,
uma única reponderação inverte o conjunto inteiro (basta concentrar o peso nele).
Se não existir, isso **não** prova que nenhuma ponderação sirva — só que nenhuma
de um único sinal serve. A resposta completa é um problema de viabilidade linear
que esta fase não resolve, porque resolvê-lo já seria procurar pesos.

Alcance a declarar: a dominância é sobre a **base linear existente**. Alterar como
um sinal é *calculado* não é uma reponderação — é um sinal novo, e sai
deliberadamente fora desta classificação.

### 4.3 Casos

Enumerados, não escolhidos: todo o alvo de grau 2 com alguém menos relevante
acima entra na tabela; os alvos que nunca chegam ao ranking entram como **C**.

| Condição | Pergunta | Alvo | Rank | Concorrentes | Diagnóstico | Inversão por um só sinal |
| --- | --- | --- | --- | --- | --- | --- |
| `current_quota` | Q001 | DOC-002 / 14 | 2 | 1 | **A** | `ordered`, `section_overlap` |
| `current_quota` | Q002 | DOC-002 / 24 | 2 | 1 | **A** | `section_overlap` |
| `current_quota` | Q011 | DOC-003 / 72 | 4 | 2 | **B** | — |
| `redistribute` | Q001 | DOC-002 / 14 | **7** | 6 | **A** | nenhum |
| `redistribute` | Q002 | DOC-002 / 24 | 4 | 3 | **A** | nenhum |
| `redistribute` | Q004 | DOC-002 / 19 | 3 | 1 | **A** | `fts_component` |
| `redistribute` | Q011 | DOC-003 / 37 | 2 | 1 | **A** | `coverage`, `section_overlap`, `title_overlap` |
| `redistribute` | Q011 | DOC-003 / 72 | **8** | 6 | **B** | — |

Mais **8 casos C** em cada condição: Q001/16, Q003/44, Q006/184, Q007/160,
Q008/161, Q009/251, Q012/78 e Q014/25. Nenhum é uma falha de ranking, e contá-los
como tal atribuiria ao ranking o que pertence às etapas anteriores — mas as
etapas anteriores são **duas**, e a repartição muda com a condição:

| Condição | `CANDIDATE_EXCLUDED` (elegibilidade) | `NEVER_A_CANDIDATE` (orçamento) |
| --- | --- | --- |
| `current_quota` | 3 | **5** |
| `redistribute_unused` | **7** | 1 |
| **Total dos 16 casos C** | **10** | **6** |

É a mesma migração que o D4.5 mediu: redistribuir o orçamento converte "nunca
avaliado" em "avaliado e rejeitado". Dizer que os 16 pertencem à elegibilidade
apagaria os seis que ainda pertencem ao orçamento.

## 5. Os modos de falha, separados

São **três**, e não um. Tratá-los com a mesma correção seria errado.

### 5.1 O cabeçalho vence o conteúdo — falha **dentro** do mesmo documento

**Q001**, alvo P1-DOC-002 / 14 (*"Início do ano letivo | 06 de outubro de 2025"*,
`table_row`), na posição **7** sob a condição ampliada. Acima dele, por esta
ordem:

| Rank | Segmento | Grau | Estrutura | Score |
| --- | --- | --- | --- | --- |
| 1 | DOC-002 / 12 | 1 | `heading` | 0,4830 |
| 2 | DOC-002 / 56 | 0 | `heading` | 0,4830 |
| 3 | DOC-002 / 10 | 0 | `heading` | 0,4643 |
| 4 | DOC-002 / 89 | 0 | `table_row` | 0,4143 |
| 5 | DOC-002 / 86 | 0 | `heading` | 0,3527 |
| — | **DOC-002 / 14** | **2** | `table_row` | **0,3387** |

Contra os três cabeçalhos, as contribuições ponderadas que decidem são
`coverage −0,0667`, `proximity −0,063` e `ordered −0,016`.

O mecanismo é nítido: um cabeçalho como *"1.º SEMESTRE DO ANO LETIVO 2025/2026"* é
composto **quase só** por termos da pergunta. Cobertura alta, correspondências
coladas, ordem perfeita. O alvo é uma linha de tabela com conteúdo a mais para
ser tão denso. **Os sinais recompensam densidade lexical, e um cabeçalho é
maximamente denso e não responde a nada.**

Note-se que o alvo **é** uma `table_row` e mesmo assim não recebe o bónus
estrutural: a sua cobertura (0,50) passa o mínimo, mas a compacidade (0,43) fica
abaixo do limiar de 0,50. O bónus vai, em vez disso, para DOC-002 / 89 — a
renovação de matrículas do **ano seguinte**.

Diagnóstico **A**: contra cada concorrente isoladamente há sinais que favorecem o
alvo (`fts_component`, `section_overlap`, `ordered`). Mas **nenhum sinal os bate
aos seis ao mesmo tempo** — é o caso mais fraco dos que recebem A.

### 5.2 O documento bem extraído vence o documento certo — falha **entre** documentos

**Q011**, alvo P1-DOC-003 / 37 na posição 2; à frente, P1-DOC-002 / 58 —
*"Primeiro dia de aulas do 2º semestre | 09 de março de 2026"*, mesmo evento,
mesmo semestre, **ano errado**.

Contribuições ponderadas do par:

| Sinal | Δ (alvo − concorrente) | Favorece |
| --- | --- | --- |
| `structure_table_row` | **−0,0600** | concorrente |
| `coverage` | **+0,0500** | alvo |
| `proximity` | −0,0175 | concorrente |
| `title_overlap` | +0,0175 | alvo |
| `ordered` | −0,0114 | concorrente |
| `fts_component` | −0,0071 | concorrente |
| `section_overlap` | +0,0063 | alvo |

O sinal que mais pesa contra o alvo é o **bónus estrutural**, e há um facto do
corpus que o torna decisivo. Contagem de segmentos por `structure_type`,
registada no artefacto em `document_structure_counts`:

| Documento | `table_row` | Restantes tipos |
| --- | --- | --- |
| **P1-DOC-002** (extração nativa) | **56** | 28 `paragraph`, 16 `heading`, 3 `list_block`, 3 `list_item`, 2 `fallback_fragment` |
| **P1-DOC-003** (documento OCR) | **0** | 30 `paragraph`, 23 `heading`, 13 `list_item`, 9 `fallback_fragment`, 1 `list_block` |
| P1-DOC-004 | 0 | 278 `paragraph`, 245 `list_item`, 50 `heading`, 16 `list_block` |
| P1-DOC-005 | 0 | 162 `paragraph`, 149 `heading`, 114 `list_item`, 51 `fallback_fragment`, 6 `list_block` |
| P1-DOC-006 | 0 | 60 `paragraph`, 46 `heading`, 43 `list_item`, 7 `list_block` |
| P1-DOC-007 | 0 | 161 `paragraph`, 141 `heading`, 98 `list_item`, 14 `list_block`, 9 `fallback_fragment` |

O achado é mais largo do que o par de Q011: **o bónus estrutural está disponível
a exatamente um dos seis documentos do corpus.** Cinco nunca o podem receber, por
muito pertinentes que sejam — e o P1-DOC-003, que detém a evidência correta de
Q011, é um deles. É a digitalização do calendário de 2023/2024, e o seu conteúdo
tabular aterra em `paragraph` e `fallback_fragment`.

O `structure_table_row` não está, aqui, a medir relevância: está a medir
**qualidade de extração**, e a favorecer sistematicamente o único documento
nativamente extraído. É a mesma família de defeito do BUG-D4.1-01, agora
observada a entrar no ranking como se fosse sinal de pertinência.

Diagnóstico **A**, e o mais forte de todos: `coverage`, `section_overlap` e
`title_overlap` favorecem o alvo, e **cada um deles sozinho** inverteria o par.

### 5.3 O alvo sem sinal nenhum a seu favor — o único **B**

**Q011**, alvo P1-DOC-003 / 72, contra P1-DOC-003 / 21 — **mesmo documento**:

```
favorecem o alvo       : (nenhum)
favorecem o concorrente: proximity, section_overlap, fts_component
```

O alvo é **dominado**: nenhuma reponderação com pesos não negativos o coloca à
frente. É o único caso B da fase, e aparece nas duas condições.

Há uma leitura mais específica. O segmento 72 vive na secção *"CANDIDATURAS A
CURSOS DE PÓS-GRADUAÇÃO"* e repete a data do 2.º semestre; o `section_overlap`
dá-lhe **zero**, enquanto o concorrente — um fragmento do 1.º semestre de
2023/2024 — recebe crédito por a sua secção conter *"2023/2024"*. O alvo é
relevante por uma razão que **nenhum dos nove sinais representa**: a sua secção
não fala do que ele contém.

## 6. Resposta à pergunta principal

> Os sinais existentes contêm informação suficiente para discriminar os
> candidatos relevantes dos que os ultrapassam?

**Parcialmente, e a repartição é assimétrica.**

| | Casos |
| --- | --- |
| **A** — sinais discriminam, ponderação sob suspeita | 6 (2 + 4) |
| **B** — sinais insuficientes | 2 (o mesmo alvo, nas duas condições) |
| **C** — não observável no ranking | 16 (8 + 8) — 10 barrados pela elegibilidade, 6 nunca candidatos |

Com três precisões que a tabela não mostra:

1. **A falha mais visível do D4.5 é do tipo A e é a mais tratável.** Q011
   cross-documento inverte-se por qualquer um de três sinais isolados.
2. **A falha mais teimosa também é do tipo A, mas fraca.** Q001 tem seis
   concorrentes e nenhum sinal os bate a todos; que exista uma ponderação única
   capaz de o resolver **não está estabelecido**.
3. **Dois dos nove sinais estão a medir outra coisa.** `structure_table_row` mede
   qualidade de extração entre documentos — está disponível a **um** dos seis —,
   e `section_overlap` premeia secções que contêm o ano por acidente de
   titulação. Reponderar não corrige um sinal que mede a coisa errada — muda
   quanto ele pesa.

## 7. Limitações

- **Amostra minúscula.** 12 perguntas medidas, 8 casos de ranking observáveis.
  Nada aqui é estatisticamente sustentado.
- **Anotador único, sem adjudicação.** O repooling herda a limitação do D4.1, e
  os 34 julgamentos novos foram feitos pelo mesmo autor das perguntas.
- **A completude é local.** Todos os resultados **devolvidos** estão julgados; o
  corpus continua por anotar, e o conjunto permanece
  `DIRECTED_JUDGMENT_INCOMPLETE`. Uma alteração de ranking que traga segmentos
  novos ao top 5 volta a precisar de repooling.
- **A não dominância é par a par.** Exceto onde há um sinal comum, A significa
  "cada par é invertível", não "existe uma ponderação que inverte o conjunto sem
  partir outras perguntas".
- **A classificação cobre reponderação, não redefinição de sinais.** Um sinal
  calculado de outra maneira — com consciência de ano, por exemplo — é matéria
  fora deste diagnóstico.
- **BUG-D4.1-01 e BUG-D4.2-01 continuam presentes**, e o primeiro tem agora um
  efeito de ranking documentado (§5.2).

## 8. Conclusão

1. **O repooling era mesmo pré-requisito, e mudou o quadro.** Uma das quatro
   regressões do D4.5 não existia, e 84 % da regressão de nDCG@5 era incompletude
   da anotação. Otimizar pesos antes disto teria perseguido um alvo falso.
2. **Os sinais atuais discriminam na maioria dos casos observáveis** — 6 de 8 —,
   e num deles a inversão é demonstrável por qualquer de três sinais isolados.
3. **Mas há um caso em que não discriminam de todo**, e dois dos nove sinais estão
   a medir propriedades que não são relevância: estrutura como *proxy* de
   qualidade de extração — disponível a um dos seis documentos —, secção como
   *proxy* de ano.
4. **O ranking não é um problema único.** São três modos — densidade lexical,
   assimetria de extração entre documentos, e ausência de sinal — com remédios
   diferentes.

Nenhum peso foi alterado, e nenhuma alteração de ranking é recomendada para
implementação nesta fase.

## 9. Próxima fase recomendada

**A — experimento controlado de variantes/pesos de ranking**, sobre o *ground
truth* repooled e com o orçamento fixo.

É a fase certa agora, e não antes, por três razões que esta fase estabeleceu: os
julgamentos cobrem 100 % dos resultados devolvidos; seis dos oito casos
observáveis são reponderáveis; e existe um caso — Q011 cross-documento — em que a
inversão é demonstrável por sinais isolados, o que dá ao experimento uma hipótese
falsificável em vez de uma busca.

Duas condições que a fase seguinte deve respeitar, e que decorrem da §6:

1. **Tratar `structure_table_row` como suspeito, não como sinal a afinar.** Ele
   é inacessível a **cinco dos seis** documentos do corpus (§5.2). Baixar-lhe o
   peso é reponderação legítima; mantê-lo como está e afinar à volta seria afinar
   contra um artefacto de extração.
2. **Voltar a fazer repooling depois.** Qualquer reponderação que traga segmentos
   novos ao top 5 reintroduz resultados por julgar, e o `ground_truth_digest`
   existe para tornar essa necessidade visível em vez de tácita.

O caso **B** — Q011 / 72 — não é matéria de reponderação e fica registado como
candidato a sinal novo, não como objetivo da próxima fase.

**Não foi iniciada.** Esta fase termina aqui.
