# D4.9 — Fusão lexical + densa por Reciprocal Rank Fusion sobre P1/S1

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
a decisão no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Motivação

A [D4.8.1](d4-8-1-lexical-dense-repooling.md) mediu C0 (lexical) contra C1
(densa) sobre a união repooled dos dois top 5 e encontrou **complementaridade
real**: alvos de grau 2 que só C1 recuperava, e pelo menos um que só C0
recuperava. Nenhuma pergunta era resolvida exclusivamente por C0, mas isso não é
o mesmo que dizer que C0 não trazia nada — trazia evidência que C1 não via, e a
questão em aberto era se essa evidência sobrevive a uma fusão.

Esta fase mede exatamente isso, e só isso.

## 2. Hipótese

> A fusão dos rankings de C0 e C1 por uma política baseada apenas em posição
> aproveita a complementaridade observada e melhora a recuperação de evidência
> relevante, sem degradação desproporcionada de ranking ou de ruído.

A hipótese podia ser rejeitada, e o critério que a rejeitaria foi escrito antes
de a experiência correr. Sobre o alcance dessa afirmação, ver §16 — não é
pré-registo auditável, e o relatório não a usa como se fosse.

## 3. Contexto experimental

| Item | Valor |
| --- | --- |
| `origin/main` | `adb332bf8f1cf04d762efafacf2d7397337bc634` (PR #58, D4.8.2) |
| Branch | `analysis/d4-9-hybrid-rrf` |
| `snapshot_id` | `a94f9402…baf4c1` — inalterado |
| `corpus_digest` | `e8a0f08b…5a447e` — inalterado |
| `ground_truth_digest` | `bbaea746…1b1301` — o repooled lexical+denso da D4.8.1, inalterado |
| Fonte | `lexical-dense-comparison-p1-s1.json`, `result_digest` `b708a70e…f7a003` |
| Perguntas medidas | 12 (Q013 e Q014 fora, pelas razões herdadas) |
| `result_digest` D4.9 | `16171d6c6bf6ebcebac289a321e22c6d34ff8abcf1d50854566e0fc2d88112c6` |
| `execution_digest` D4.9 | `636609d71312725ca386ba859c316b00b7c66e338f15131ed92d4ffd0cebcd10` |

A fase **não executou retrieval**. Não contactou a base de dados, o fornecedor
de embeddings nem a rede: leu os rankings persistidos e reordenou-os. Há teste
em subprocesso que confirma que importar os módulos desta fase não carrega
`sqlalchemy`, `openai` nem `fastapi`.

## 4. Condições

- **C0** — ranking lexical, exatamente como a D4.8.1 o registou;
- **C1** — ranking denso, exatamente como a D4.8.1 o registou;
- **C2** — fusão por RRF dos top 5 de C0 e C1.

C0 e C1 não foram reexecutados: foram **reproduzidos**. O runner recalcula as
suas métricas a partir dos rankings guardados e exige que coincidam, casa a
casa, por pergunta e no agregado, com as que a D4.8.1 gravou. Não é cerimónia —
é o que prova que C2 é medido pelo mesmo protocolo e não por uma segunda
implementação que produz números parecidos. Se divergisse, a execução parava
antes de escrever seja o que for.

## 5. Porquê RRF, e porquê não score fusion

As duas grandezas não são somáveis. `lexical_composite_v1` é relevância lexical
composta em [0, 1]; a condição densa devolve similaridade do cosseno. Ambas
declaram `comparable_across_queries = False` — não são comparáveis nem consigo
próprias entre perguntas, quanto mais uma com a outra. Somá-las produziria um
número sem unidade cuja variação seria dominada, pergunta a pergunta, pela que
tivesse maior amplitude naquela pergunta.

A posição não tem esse problema: o primeiro lugar significa o mesmo nas duas
condições. É por isso que a fusão trabalha sobre ranks.

E não é só uma declaração de intenção: `reciprocal_rank_fusion` **recebe
sequências de identidades**, não resultados. O score é descartado antes da
fronteira do módulo. Não há por onde entrar, e há teste que perturba todos os
scores do artefacto de origem e confirma que o ranking fundido, o agregado e a
decisão não mudam num único valor.

## 6. Fonte congelada nos top 5

A fusão lê exatamente os top 5 que a D4.8.1 registou. Não se aumentou a
profundidade para 10, 20 ou 25.

A razão é de atribuição: aumentar a profundidade mudaria o orçamento de
candidatos lexical, o universo de candidatos, a cobertura possível e a
necessidade de novos julgamentos. O resultado passaria a misturar «efeito da
fusão» com «efeito de recuperar mais fundo», e nenhum dos dois ficaria medido.

Há uma consequência metodológica que compensa o custo: a união dos dois top 5 já
foi inteiramente repoolada e julgada, pelo que **C2 só pode reordenar segmentos
já julgados**. `unjudged_in_top_k` é 0 nas três condições, verificado por
guarda e por teste.

## 7. Configuração

```
método       Reciprocal Rank Fusion
fórmula      RRF(d) = Σ 1 / (k_rrf + rank_i(d)),  ranks 1-based
k_rrf        60
source_depth 5
final_top_k  5
aritmética   racional exata (Fraction), arredondada só na escrita
```

`k_rrf = 60` é o valor usado no artigo que introduziu o método — Cormack, Clarke
& Buettcher (2009), [SIGIR 2009](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf).
Não lhe chamo canónico: os autores descrevem-no como fixado durante uma
**investigação piloto**, noutro corpus, e não como valor derivado de coisa
nenhuma. É uma convenção herdada, e a única propriedade que esta fase lhe
reclama é **não ter sido escolhido aqui**.

Não houve grid search. Procurar o `k_rrf` que maximiza uma métrica sobre doze
perguntas produziria um número ajustado a esta amostra e apresentá-lo-ia como
propriedade do método.

A soma é feita em aritmética racional exata. Com vírgula flutuante, dois empates
genuínos podiam diferir no último bit e o desempate declarado nunca chegaria a
correr — o que, como se verá em §12, teria escondido o caso mais informativo da
fase.

**Ausência não é penalização.** Um segmento que só uma condição devolveu soma um
termo só. Não recebe `1 / (k_rrf + 999)` nem qualquer rank sintético: um
retriever que não devolveu um segmento não se pronunciou sobre ele, e
inventar-lhe uma posição transformaria silêncio em juízo negativo.

Desempate, declarado antes de medir e **sem preferência por condição**:

1. maior `rrf_score`, em aritmética exata;
2. menor `best_rank` entre as condições que o devolveram;
3. menor `corpus_item_id`;
4. menor `chunk_index`.

Um critério que preferisse C0 ou C1 estaria a decidir, dentro do mecanismo em
avaliação, parte daquilo que a experiência pergunta. A identidade do segmento
basta para tornar a regra total.

## 8. Métricas

Macro-média sobre as 12 perguntas medidas, mesmo *ground truth*, mesmo
`metric_protocol`, mesmas exclusões.

| Métrica | C0 lexical | C1 densa | C2 híbrida | C2 − C1 |
| --- | --- | --- | --- | --- |
| Recall@1 | 0,2500 | 0,5833 | **0,6250** | +0,0417 |
| Recall@3 | 0,4167 | 0,8333 | 0,8333 | 0,0000 |
| Recall@5 | 0,4583 | 0,8750 | **0,9167** | +0,0417 |
| MRR | 0,4167 | 0,8194 | **0,8750** | +0,0556 |
| nDCG@1 | 0,3333 | 0,7778 | **0,8333** | +0,0556 |
| nDCG@3 | 0,3637 | 0,7677 | 0,7837 | +0,0160 |
| nDCG@5 | 0,3867 | 0,7987 | **0,8251** | +0,0264 |

Nenhuma métrica desce.

## 9. Onde o ganho está — e onde não está

O agregado esconde a estrutura, e a estrutura é o resultado.

**Em cinco das doze perguntas C0 não devolveu nada.** Q006, Q007, Q008, Q009 e
Q012: a recuperação lexical devolve zero resultados e a fusão é, por
construção, a identidade. C2 é literalmente C1 nessas perguntas.

Restam **sete perguntas onde a fusão podia agir**. Mexeu em quatro:

| Pergunta | nDCG@5 C1 | nDCG@5 C2 | Δ |
| --- | --- | --- | --- |
| Q011 | 0,387 | 0,920 | **+0,533** |
| Q005 | 0,686 | 0,906 | **+0,220** |
| Q001 | 0,914 | 0,796 | −0,118 |
| Q003 | 0,945 | 0,628 | −0,317 |

Soma +0,3167, dividida por 12, dá exatamente o +0,0264 do agregado. **O
resultado da fase são quatro perguntas: duas a subir e duas a descer.**

## 10. Complementaridade

```
alvos de grau 2 exclusivos de C0:  1  →  preservados por C2:  1
alvos de grau 2 exclusivos de C1:  8  →  preservados por C2:  8
alvos promovidos face a C1:        2
alvos despromovidos face a C1:     2
perguntas melhoradas face a C1:    2
perguntas pioradas face a C1:      2
perguntas resolvidas por C1 e perdidas por C2:  nenhuma
```

**Q011 é a razão pela qual esta fase existia.** C1 tinha um alvo de grau 2
(`P1-DOC-003#37`) que **nunca viu** — não estava no seu top 5 — e que C0 tinha
em primeiro lugar. C2 recupera-o para a terceira posição e simultaneamente
promove para primeiro o alvo que C1 tinha em segundo. Os dois alvos de grau 2
passam a estar no top 5. `reciprocal_rank` de 0,50 para 1,00; nDCG@5 de 0,387
para 0,920.

Isto é complementaridade a funcionar, e é um caso concreto e não uma média:
evidência que a condição densa perdia foi recuperada pela fusão, sem que nada
tivesse de saber que a perdia.

**Q005** é o segundo padrão: o alvo estava em ambas as condições, em primeiro
lugar em C0 e em terceiro em C1. A concordância promove-o para primeiro.

## 11. Regressões

**Q001** é o custo normal da fusão. C1 tinha dois alvos de grau 2 nas posições 1
e 3; C2 mantém o primeiro em primeiro mas empurra o segundo de 3 para 4, porque
dois distratores lexicais (`#89` e `#10`) se intercalaram. O `reciprocal_rank`
não muda — a pergunta continua resolvida — mas o nDCG@5 desce 0,118. É o preço
de misturar um ranking pior com um melhor.

**Q003 é o caso que vale a pena ler devagar.** C0 devolveu **um único resultado**:
`P1-DOC-002#12`, grau 0. C1 devolveu cinco, com o alvo de grau 2 (`#44`) em
primeiro lugar.

Na fusão, o único resultado de C0 está em primeiro lugar do *seu* ranking, e
soma portanto `1/61` — exatamente o mesmo termo que o alvo de C1, também em
primeiro lugar. **Empate exato.** O `best_rank` é 1 nos dois. O desempate cai na
identidade, e `chunk_index` 12 é menor do que 44: o distrator fica à frente do
alvo. `reciprocal_rank` de 1,00 para 0,50, nDCG@5 de 0,945 para 0,628.

Duas coisas a registar, sem as confundir:

1. **RRF é indiferente à espessura do ranking.** Uma condição que devolveu um
   resultado tem o seu primeiro lugar tão pesado quanto o de uma condição que
   devolveu cinco. Não há nada no método que distinga «a minha melhor hipótese
   entre cinco» de «a única coisa que encontrei». Este é um resultado sobre o
   método, não sobre este corpus.
2. **O desempate decidiu uma métrica.** Um desempate que preferisse C1, ou a
   condição com mais resultados, teria dado Q003 a favor do alvo — e o MRR
   agregado subiria de 0,875 para ~0,917. Registo-o como **sensibilidade a uma
   escolha arbitrária declarada na implementação** — com a mesma reserva do §16
   quanto à ordem temporal — e não como correção: mudar o desempate depois de
   ver que ele custou uma pergunta seria exatamente a afinação que esta fase se
   comprometeu a não fazer. Fica para uma avaliação independente, como hipótese
   a testar com o seu próprio conjunto.

## 12. Q013 — a pergunta sem evidência no corpus

```
C0:  0 resultados
C1:  5 resultados, todos de grau 0
C2:  5 resultados, todos de grau 0
```

A fusão **não ajuda nada** aqui, e não havia razão para esperar que ajudasse.
C0 não devolve nada, C1 devolve cinco irrelevâncias, e a fusão de nada com cinco
irrelevâncias são as mesmas cinco irrelevâncias. C2 é tão incapaz de se abster
como C1.

Nenhum limiar híbrido é proposto ou implementado. A admissão foi estudada — e
fechada — na [D4.8.2](d4-8-2-dense-admission.md), e a política `top1 >= 0,60`
**não** foi aplicada nesta fase: fundir e admitir são dois mecanismos, e
alterá-los na mesma experiência tornaria o resultado inatribuível a qualquer um
dos dois.

Q013 continua excluída de Recall, MRR e nDCG por indefinição — não há alvo, as
métricas não estão definidas, e a contagem de segmentos devolvidos não é um
veredicto de política.

## 13. Q014

Continua **excluída de todas as métricas**, pela razão herdada: o corpus tem dois
calendários simultaneamente elegíveis, nenhum com vigência declarada, e existem
duas respostas corretas e incompatíveis. A D4.9 não resolve a ambiguidade
temporal nem inventa uma convenção de vigência — fundir rankings não produz
informação institucional que o corpus não tem.

## 14. Limitações

1. **Um único corpus (P1) e um único snapshot (S1).** Nada aqui demonstra
   generalização para outra instituição, outro acervo ou outro idioma.
2. **Doze perguntas medidas, e o resultado são quatro.** Em cinco delas a fusão
   é a identidade porque C0 devolve zero. O agregado move-se com uma pergunta:
   inverter Q003 sozinho mudaria o MRR em quatro casas decimais.
3. **Um único anotador**, sem medida de concordância entre anotadores.
4. **Um único modelo de embeddings** e um único índice vetorial.
5. **`source_depth` = 5.** A fusão só pode reordenar o que as condições já viam;
   nada diz sobre o que aconteceria com profundidade maior.
6. **`k_rrf` herdado do artigo original e não afinado.** O resultado não é o
   melhor RRF possível neste corpus, e não pretende ser.
7. **O desempate é arbitrário e teve efeito medível** (§11). Está declarado na
   implementação e registado como fixado antes da execução — com a reserva do
   §16 sobre o que o histórico prova — e isso torna-o auditável na sua forma,
   não o torna certo.
8. ***Ground truth* incompleto por construção** (`DIRECTED_JUDGMENT_INCOMPLETE`):
   o sentido do enviesamento difere por métrica e está documentado no protocolo.
9. **O híbrido não foi avaliado com política de admissão própria.** Q013 mostra
   que continua sem saber recusar.
10. **O resultado não autoriza promoção para produção.**

## 15. Decisão

**A — HYBRID_SUPPORTED**, pelo critério declarado na implementação e aplicado
sem interpretação (sobre o estatuto desse critério, ver §16):

- nenhuma pergunta resolvida por C1 foi perdida por C2;
- `Recall@5` não desce (+0,0417);
- `nDCG@5` sobe 0,0264, acima do `material_delta` de 0,02;
- o único alvo de grau 2 exclusivo de C0 foi preservado, e os oito exclusivos de
  C1 também.

O que isto autoriza a dizer: **a fusão por posição aproveitou a
complementaridade que a D4.8.1 tinha observado — recuperou, num caso concreto,
evidência que a condição densa perdia — sem perder nenhuma pergunta e sem
degradar nenhuma métrica agregada.**

O que isto **não** autoriza a dizer: que o híbrido é melhor do que o denso de
uma forma que sustente uma mudança de arquitetura. O ganho agregado é a soma de
duas melhorias grandes e duas degradações grandes sobre quatro perguntas, e uma
das degradações (Q003) foi decidida por um critério de desempate arbitrário. Com
esta amostra, «A» significa «vale a pena investigar mais», e não «está provado».

`A` também não diz nada sobre answerability. C2 é uma experiência de
recuperação: não sabe quando deve responder, e Q013 mostra-o.

## 16. O estatuto do critério de decisão

A decisão depende de `MATERIAL_DELTA = 0,02` contra um ganho observado de
0,026388 — uma margem de 0,0064. Vale a pena ser exato sobre o que sustenta esse
limiar.

O valor foi escrito antes de a experiência correr. Mas vive na **mesma árvore de
trabalho** que o resultado, e **nenhum commit separa um do outro**: o histórico
do repositório não prova a ordem temporal. Quem auditar tem o meu testemunho e
não tem mais nada. Por isso o relatório diz «declarado na implementação e
registado como fixado antes da execução», e não «pré-registado» — a segunda
formulação afirma uma garantia que o Git aqui não dá. O artefacto transporta a
mesma reserva no campo `decision_rule.pre_registration_caveat`.

A D4.8.2 tinha essa garantia e esta não tem: lá, o protocolo, o espaço de
parâmetros e o critério de seleção foram selados num artefacto com
`protocol_digest` próprio **antes** da calibração, e o comando de avaliação
verificava-o. A D4.9 não repetiu esse desenho, e devia — é a lição metodológica
desta fase e fica registada como tal.

**Considerei descer para `D`** — `HYBRID_PROMISING_BUT_NEEDS_BROADER_EVALUATION`
descreveria melhor a cautela que o resto do relatório exprime. Não o fiz, e a
razão é que seria pior: a regra implementada, aplicada aos números medidos, dá
`A`. Trocá-la para `D` depois de ver que a margem é apertada é exatamente a
afinação pós-hoc que esta fase se comprometeu a não fazer — e seria uma segunda
decisão sem regra nenhuma por trás, o oposto do que o problema pede. Mantenho
`A` com a reserva declarada, e note-se que, nesta amostra, `A` e `D` conduzem ao
**mesmo próximo passo** (§20): uma avaliação independente mais ampla, sem
promoção para produção. A diferença entre os dois rótulos não altera nenhuma
ação.

## 17. Reprodutibilidade

O comando correu **duas** vezes, com `result_digest`, `execution_digest`,
rankings, graus, métricas e decisão idênticos. Ao contrário da D4.8.1, aqui os
dois digests são estáveis por construção: nenhuma quantidade deste artefacto vem
do fornecedor, pelo que uma divergência seria sinal e não deriva.

Sondas de mutação, ambas revertidas: atribuir um rank sintético à condição
ausente faz falhar três testes; ordenar o ranking de origem pelo score original
em vez da posição faz falhar o teste de independência de score.

## 18. Reprodução

```bash
cd backend

python -m scripts.evaluate_hybrid_rrf \
    --comparison ../docs/evaluation/lexical-dense-comparison-p1-s1.json \
    --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-lexical-dense-repooled.json \
    --output ../docs/evaluation/hybrid-rrf-p1-s1.json --overwrite
```

Não é preciso base de dados, chave de API nem rede.

## 19. O que esta fase não fez

Não alterou o retrieval de produção — `app.retrieval.dependencies.get_retriever`
continua a devolver `PostgresLexicalRetriever`, fixado por teste. Não criou
`PostgresHybridRetriever`, não ligou a condição densa à API, não tocou no
*answering*, no frontend, na base de dados nem nas migrations. Não reabriu a
D4.8.2. Não implementou reranking, cross-encoder, fusão de scores, novo modelo
de embeddings, reescrita de consultas nem alteração de profundidade.

Não foi feito commit, push nem Pull Request.

## 20. Próximo passo

Uma avaliação independente e mais ampla do híbrido antes de qualquer decisão de
produção. O que ela precisa de ter, e esta fase não teve:

- **mais perguntas onde C0 devolva alguma coisa** — cinco das doze não puderam
  contribuir, e o efeito da fusão só é observável nas restantes;
- **o desempate como variável**, testado com o seu próprio conjunto, dado o que
  Q003 mostrou;
- **profundidade de fonte como variável separada**, com o repooling que ela
  exige;
- **a hipótese `hybrid + admission`** como experiência distinta, porque Q013
  deixa claro que fundir não resolve abster-se.

Nada disto foi implementado.
