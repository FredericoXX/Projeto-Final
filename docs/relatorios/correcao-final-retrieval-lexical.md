# Correção final do retrieval lexical

Branch: `fix/lexical-retrieval-correctness` · Data: 2026-07-30 · Repositório:
`FredericoXX/Projeto-Final`

---

## Estado inicial

| Item | Valor |
| --- | --- |
| `BASE_SHA` | `ac8214ded5cc0f118704a3a42e38f95ee8310797` (merge do PR #22) |
| Branch criada | `fix/lexical-retrieval-correctness` (não existia local nem remotamente) |
| Working tree antes de começar | limpa (`git status --short` vazio) |
| Migration em head | `e7b1c9d4a2f0` (inalterada) |
| Commits/push/PR | **nenhum** |

A `main` local estava 4 commits atrás; foi atualizada com
`git pull --ff-only origin main` e ficou exatamente no `BASE_SHA` esperado.

### Baseline (antes de qualquer alteração)

| Verificação | Resultado |
| --- | --- |
| `docker compose config --quiet` | OK |
| `python -m pip check` | No broken requirements found |
| `alembic upgrade head` / `current` / `heads` / `check` | `e7b1c9d4a2f0 (head)`; No new upgrade operations detected |
| `python -m pytest -q` | **812 passed, 0 failed, 0 skipped, 1 warning, 184.88s** |
| `ruff check .` | All checks passed |
| `mypy app tests scripts` | Success: no issues found in 134 source files |
| `npm ci` / `lint` / `typecheck` | OK |
| `npm run test:run` | 9 ficheiros, 84 testes, 11.67s |
| `npm run build` | built in 229ms |
| `git status --short` / `git diff -- frontend/package-lock.json` | vazios |

O único *warning* é pré-existente e alheio a esta tarefa
(`StarletteDeprecationWarning` sobre `httpx` no `TestClient`).

### Problemas reproduzidos

Todos os treze pontos do enunciado foram confirmados **a partir do código**, não
assumidos. Os mais relevantes foram reproduzidos por execução:

- `_proximity` devolvia `1.0` para uma correspondência isolada em consultas
  multi-termo (`len(matched_positions) == 1 → return 1.0`, sem olhar ao total);
- `rerank` não tinha gate de conteúdo: com `W_TITLE + W_SECTION = 0.12` e o
  limiar em `0.05`, um chunk com título correspondente e conteúdo irrelevante
  ultrapassava o piso;
- `_ordinal_numeric_expansions` produzia `segunda OR 2` — e o teste
  `test_ordinal_only_query_generates_candidate_via_numeric_expansion` congelava
  esse comportamento como desejável;
- cada variante recebia `LIMIT 25` e o pool agregado (até 100) era cortado *a
  posteriori* por `ts_rank_cd` cru em `_apply_candidate_ceiling`;
- `NumericRange` vivia numa lista à parte e os endpoints ocupavam **duas**
  posições no stream, pelo que `rng:1-12` não participava em frase exata, ordem
  nem proximidade.

---

## Causas confirmadas

| ID | Causa | Impacto | Reprodução |
| --- | --- | --- | --- |
| C1 | Elegibilidade e ranking confundidos: o score era o único critério | 1 termo em 3 chegava ao top_k e ao answering | `rerank` só aplicava `min_relevance_score`; `test_partial_term_match_is_not_enough_evidence` falhava antes da correção |
| C2 | `_proximity` ignorava o total de termos da pergunta | Uma correspondência recebia `prox=1.0` e `+0.14` no score | `test_proximity_of_one_match_in_a_three_term_query_is_not_one` |
| C3 | `title_overlap`/`section_overlap` somados sem gate de conteúdo | Título ou secção sozinhos tornavam um chunk elegível | `test_matching_title_alone_never_creates_eligibility`, `test_matching_section_alone_produces_no_evidence` |
| C4 | Evidência lexical fraca chegava ao answering | O gerador era chamado sobre coincidência de um termo | `test_partial_term_match_persists_no_sources_and_never_calls_provider` |
| C5 | `_ordinal_numeric_expansions` expandia ordinal → cardinal | `"primeira"` recuperava `"Sala 1"` | `test_ordinal_only_query_is_never_expanded_to_a_cardinal` |
| C6 | Orçamento por variante (`25 × 4`) + teto pós-agregação (100) | Até 300 linhas de SQL antes do corte | `test_four_variants_share_the_global_budget` |
| C7 | Corte global por `ts_rank_cd` cru antes do reranking | Um candidato `exact` de FTS baixo podia ser descartado | `_apply_candidate_ceiling` ordenava por `-raw_score` |
| C8 | Intervalos sem posição no stream canónico | `rng:1-12` fora de exact phrase/ordem/proximidade; endpoints partiam a contiguidade | `test_range_participates_in_exact_phrase_and_order` |
| C9 | Formas compactas não geravam o candidato escrito | `01a12` não recuperava `1 a 12` | `test_compact_range_query_retrieves_spaced_content` |
| C10 | Dominância por subconjunto | Evidência complementar apagada | `test_complementary_evidence_is_preserved_not_dominated` |
| C11 | Trace não explicava o orçamento; contagens ambíguas | `candidates_before_threshold` misturava causas | `test_trace_counts_are_mathematically_consistent` |
| C12 | Diagnóstico na v3 e documentação contraditória | README afirmava "não há reranking" enquanto o descrevia | `test_real_retriever_populates_lexical_trace_in_report` |
| C13 | Faltavam testes para os contraexemplos reais | — | 4 ficheiros novos + reescrita de 6 |

---

## Arquitetura final

```
pergunta normalizada
  → plano de variantes (exact, reduced_and, canonical_relaxed_and, reduced_or)
  → orçamento global   = min(100, max(20, top_k × 5))          [antes das queries]
  → quotas por variante (divisão inteira, resto por prioridade)
  → N consultas SQL, cada uma com LIMIT = a sua quota
  → deduplicação por chunk_id (melhor estratégia + melhor ts_rank_cd)
  ─────────────────────────────────────────────────────────────
  → FASE 1: elegibilidade  (só sinais de conteúdo + estratégia)
  → FASE 2: ranking        (só dos elegíveis; título/secção só aqui)
  → limiar mínimo          (a todos os elegíveis, sem exceções)
  → top_k                  (apresentação, não exclusão de relevância)
```

**Candidate generation.** As variantes são planeadas por prioridade e o
orçamento é decidido *antes* de qualquer SQL. Cada consulta usa a sua quota como
`LIMIT`; nenhuma corre sem limite.

**Quotas.** `divmod(limite, nº variantes)`, com o resto distribuído um a um pela
ordem `exact > reduced_and > canonical_relaxed_and > reduced_or`. A soma nunca
excede o orçamento, pelo que `unique_after_dedup ≤ global_candidate_limit` é uma
consequência estrutural.

Duas garantias, e uma terceira que **não** é oferecida — a distinção importa e
uma versão anterior deste relatório exagerava-a:

- **não existe corte global por `ts_rank_cd` cru depois da agregação**: tudo o
  que as consultas devolvem é avaliado (`candidates_evaluated ==
  unique_after_dedup`);
- a quota de cada variante é **reservada**: um candidato `exact` com FTS baixo
  não compete por espaço com candidatos de variantes menos prioritárias;
- **não** se garante que um candidato `exact` chegue *sempre* ao reranker: cada
  variante continua ordenada por `ts_rank_cd` desc e limitada à sua quota em SQL,
  pelo que uma variante com mais correspondências do que a quota fica pelos
  melhores. O orçamento é finito por desenho.

**Deduplicação.** Por `chunk_id`, preservando a melhor estratégia e o melhor
`ts_rank_cd`. É a única forma de remoção de "duplicados" no sistema.

**Elegibilidade.** Função pura em `app/retrieval/eligibility.py`, testável sem
PostgreSQL, sobre `ContentMatch` (cobertura, frase exata, ordem, proximidade,
compacidade) e a estratégia.

**Ranking.** Só dos elegíveis. `build_features` — que calcula título, secção,
`table_row`, comprimento, FTS e qualidade da estratégia — **só é chamado depois**
da decisão de elegibilidade.

**Limiar.** Aplica-se a todos os elegíveis, incluindo o melhor e incluindo
frases exatas. Todos os candidatos podem ser removidos.

**top_k.** Corte de apresentação; `final_result_count` no trace conta os
sobreviventes *antes* do `top_k`.

---

## Política de elegibilidade

| Caso | Regra | Resultado |
| --- | --- | --- |
| Consulta sem termos informativos | — | nenhum candidato elegível; retrieval vazio |
| Consulta de **um** termo | correspondência de superfície **ou** recuperação por stemming legítimo do FTS | elegível (`single_term_surface` / `single_term_fts`) |
| Consulta multi-termo, cobertura **zero** | — | **nunca** elegível (`no_content_match`) |
| Consulta multi-termo, condição forte 1 | sintaxe websearch explícita (aspas, `OR`, `-termo`) com estratégia `exact` | elegível (`explicit_syntax`) |
| Consulta multi-termo, condição forte 2 | frase exata no conteúdo | elegível (`exact_phrase`) |
| Consulta multi-termo, condição forte 3 | estratégia `exact` ou `reduced_and` **sem** sintaxe explícita | elegível (`conjunctive_strategy`) |
| Consulta multi-termo, condição forte 4 | `canonical_relaxed_and` + **todos** os termos contextuais correspondidos + **≥1** marcador `ord:`/`rng:` correspondido | elegível (`canonical_relaxed`) |
| Consulta multi-termo, condição forte 5 | `matched ≥ required_matches(n)` **e** `coverage ≥ 0.5` | elegível (`coverage`) |
| Nenhuma condição cumprida | — | `insufficient_coverage` |

A separação entre as condições 1 e 3 é uma correção de honestidade do trace. A
estratégia `exact` serve dois papéis: numa consulta normal prova que a tsquery
**conjuntiva** casou os termos exigidos; numa consulta com operadores explícitos
a mesma estratégia pode ser deliberadamente **disjuntiva** — `aulas OR exames`
corresponde a um dos lados por desenho. Registar essa união como
`conjunctive_strategy` seria factualmente errado, por isso existe a base
`explicit_syntax`. Em ambos os casos, cobertura zero continua a excluir. O token
`or` deixou também de contar como termo informativo (é sempre um operador para o
PostgreSQL; contá-lo baixava artificialmente a cobertura de `aulas OR exames`
para 1/3).

```python
required_matches(n) = 1                          se n <= 1
required_matches(n) = max(2, ceil(n * 0.5))      se n >= 2
```

| n termos | 2 | 3 | 4 | 5 | 6 | 7 | 12 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mínimo exigido | 2 | 2 | 2 | 3 | 3 | 4 | 6 |
| cobertura implícita | 1.00 | 0.67 | 0.50 | 0.60 | 0.50 | 0.57 | 0.50 |

`MIN_COVERAGE_RATIO = 0.5` é uma constante única; não há regras para palavras
(`regime`, `avaliação`, `exames`, `chamada`, `calendário`) nem para instituições.
**Título, secção, `table_row`, comprimento, `ts_rank_cd` e qualidade da
estratégia não figuram em lado nenhum desta tabela** — por construção não podem
criar evidência. O resultado vazio é legítimo.

---

## Fórmula final do score

| Componente | Peso | Notas |
| --- | --- | --- |
| `coverage` | 0.40 | dominante |
| `exact_phrase` | 0.16 | sequência canónica informativa contígua |
| `proximity` | 0.14 | ver abaixo |
| `ordered` | 0.08 | fração de pares consecutivos na ordem certa |
| `title_overlap` | 0.07 | calculado **só** após elegibilidade |
| `table_row_bonus` | 0.06 | exige `coverage ≥ 0.5` **e** `compactness ≥ 0.5` |
| `section_overlap` | 0.05 | calculado **só** após elegibilidade |
| `fts_norm × length_factor` | 0.02 | sinal auxiliar combinado |
| `strategy_quality` | 0.02 | derivado de `STRATEGY_PRIORITY` |

Soma = 1.0, validada com `math.isclose` no import e coberta por
`test_ranking_weights_sum_to_one` (substitui o `assert`, que `python -O` removia).

**Proximity (corrigida):**

```
positional_coverage = posições correspondidas / termos da pergunta
compactness         = posições correspondidas / span
proximity           = positional_coverage × compactness
```

| Caso | Valor |
| --- | --- |
| 0 correspondências | `0.0` |
| 1 de 1 | `1.0` |
| 1 de 2 | `0.5` |
| 1 de 3 | `0.333` |
| 2 de 3 adjacentes | `0.667` |
| 2 de 3 distantes | `< 0.667` |
| 3 de 3 adjacentes | `1.0` |
| ordem inversa | igual à direta (a ordem é do sinal `ordered`) |

Sempre finita, em `[0, 1]`, determinística. A **compacidade** é exposta em
separado porque é ela — e não a proximidade composta — que descreve "as
correspondências estão juntas"; é o que o benefício de `table_row` usa, o que
preserva exatamente a calibração anterior sem inventar um novo número mágico.

**Normalização FTS:** `fts_norm = raw / (raw + 0.1)`, mantendo-a em `[0, 1)`;
multiplicada por `length_factor = 400 / max(len(conteúdo), 400)`.

**Limiar:** `RETRIEVAL_MIN_RELEVANCE_SCORE`, padrão `0.05`, aplicado **depois**
da elegibilidade a todos os elegíveis. O padrão foi reavaliado *após* a
correção e mantido: com a elegibilidade a fazer o trabalho real, o piso passa a
ser residual (um elegível típico tem `coverage ≥ 0.5`, logo `≥ 0.20` só de
cobertura). Validação: `math.isfinite(v)` e `0.0 ≤ v ≤ 1.0`.

**Desempates:** `score↓, coverage↓, strategy_quality↓, raw_score↓,
document_id↑, chunk_index↑, chunk_id↑` — ordem total e determinística.

---

## Estratégias

| Estratégia | Uso | Prioridade | Segurança |
| --- | --- | --- | --- |
| `exact` | consulta normalizada tal como escrita | 4 | preserva a intenção; **única** permitida com aspas, `OR`, negação ou consulta só de ordinal/intervalo |
| `reduced_and` | termos informativos, todos obrigatórios | 3 | conjuntiva; só relaxa palavras funcionais |
| `canonical_relaxed_and` | termos **contextuais** (sem ordinais/intervalos), todos obrigatórios | 2 | o marcador sai apenas da consulta FTS e continua obrigatório na elegibilidade |
| `reduced_or` | termos informativos, qualquer um suficiente | 1 | máxima recuperação; a elegibilidade filtra o ruído |

Requisitos verificados por teste: pelo menos um termo contextual permanece;
nunca uma consulta vazia; nunca só o dígito do ordinal; nunca só os endpoints do
intervalo; `primeira` nunca vira `primeira OR 1`; `segunda` nunca vira
`segunda OR 2`; consulta só de ordinal ou só de intervalo usa apenas `exact`;
sintaxe avançada, aspas, `OR` e negação usam apenas `exact`;
`MAX_INFORMATIVE_TERMS = 12` respeitado; máximo fixo de
`MAX_QUERY_VARIANTS = 4` variantes; sem explosão combinatória.

Exemplos reais:

```
"exames da primeira chamada"        → canonical_relaxed_and = "exames chamada"
"período de inscrições de 01a12"    → canonical_relaxed_and = "periodo inscricoes"
"primeira"                          → plano = (exact,)
"01a12"                             → plano = (exact,)
```

---

## Candidate pool

```
global_candidate_limit = min(CANDIDATE_MAX, max(CANDIDATE_MIN, top_k × CANDIDATE_MULTIPLIER))
                       = min(100, max(20, top_k × 5))
quotient, remainder    = divmod(limite, nº variantes)
quota[i]               = quotient + (1 se i < remainder senão 0)
```

Execução real (`top_k=5`, orçamento 25):

| Cenário | Variantes ativas | Quotas | Soma | Devolvidos | Únicos | Limite observado |
| --- | --- | --- | --- | --- | --- | --- |
| `"Até quando posso mudar o regime de avaliação?"` | exact, reduced_and, reduced_or | 9 / 8 / 8 | 25 | 0 / 0 / 3 | 3 | 3 ≤ 25 |
| `"Qual é o período de inscrições de 01a12?"` | exact, reduced_and, canonical_relaxed_and, reduced_or | 7 / 6 / 6 / 6 | 25 | 0 / 0 / 2 / 2 | 2 | 2 ≤ 25 |
| `"avaliacao"` (40 documentos) | exact | 25 | 25 | 25 | 25 | 25 ≤ 25 |

Invariantes cobertas por teste: soma das quotas ≤ orçamento; nenhuma quota
negativa; nenhuma variante com quota zero quando há orçamento para todas;
distribuição do resto sempre por prioridade; determinismo; nenhuma query sem
`LIMIT`; nenhum corte global por FTS cru após a agregação.

A reserva de quota é verificada por
`test_exact_variant_quota_is_reserved_against_higher_fts_candidates`: um
documento longo, único a corresponder à variante `exact`, com 30 concorrentes
curtos que repetem os termos e só correspondem à disjuntiva. O alvo é avaliado e
fica em **primeiro** (cobertura 3/3 contra 2/3) apesar de ter o **menor**
`ts_rank_cd` **entre os resultados devolvidos** — `trace.results` está limitado
ao `top_k`, pelo que a comparação não abrange todos os avaliados. Basta para
mostrar que não foi a força do FTS que o pôs em primeiro; a asserção compara os
valores reais do trace, pelo que o teste falha se a propriedade se perder.

---

## Ordinais

| Verificação | Resultado |
| --- | --- |
| `1.º`, `1º`, `1.ª`, `1ª`, `1o`, `1a`, `primeiro`, `primeira` | todos ⇒ `ord:1` |
| `2.º`, `2º`, `2.ª`, `2ª`, `2o`, `2a`, `segundo`, `segunda` | todos ⇒ `ord:2` |
| `primeira` ⇄ `1.ª` com contexto | funciona via `canonical_relaxed_and` + ranking canónico |
| Contexto obrigatório | sim: sem termo contextual o plano é só `exact` |
| Query só `"primeira"` contra `"Sala 1 disponível."` | **0 evidências**, 0 candidatos avaliados |
| Query só `"segunda"` contra `"Sala 2 disponível."` | **0 evidências** |
| `12` | permanece cardinal; `12 ≠ ord:1`; `"12 chamada"` ⇒ `["12", "chamada"]` |
| `22` | permanece cardinal; `22 ≠ ord:2` |
| Listas por idioma | pequenas e explícitas (`primeiro..décimo`, `first..tenth`); sem sinónimos |

---

## Intervalos

| Verificação | Resultado |
| --- | --- |
| Canonical stream | `"periodo 1 a 12 inscricoes"` ⇒ `["periodo", "rng:1-12", "inscricoes"]` — **uma** unidade |
| Formas equivalentes | `01a12`, `01 a 12`, `01-12`, `01–12`, `1 a 12` ⇒ o mesmo stream |
| Positions | `periodo=0`, `rng:1-12=1`, `inscricoes=2` |
| Coverage | `rng:1-12` conta como termo |
| Exact phrase | `"periodo 01a12"` é frase exata em `"periodo de 1 a 12"` (`exact=1`) |
| Order | `1.00` |
| Proximity | `1.00` quando adjacente (endpoints não ocupam posições próprias) |
| Zeros à esquerda | irrelevantes: `01a12 == 1 a 12` |
| `0509` | **não** convertido (`ranges == []`, token `"0509"`) |
| `2206` | **não** convertido |
| `20262027` | **não** convertido |
| `Ro` | continua palavra (`TokenKind.WORD`), sem virar número |
| Datas | nunca interpretadas |

Regressão de intervalo (dados reais):

| Posição | Documento | Estratégia | Coverage | Exact | Order | Prox | Score |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Outubro (`1 a 12`) | `canonical_relaxed_and` | 1.000 | 1 | 1.00 | 0.750 | **0.8283** |
| 2 | Novembro (`1 a 13`) | `canonical_relaxed_and` | 0.667 | 0 | 0.50 | 0.444 | 0.4522 |

O concorrente `1 a 13` fica abaixo por não corresponder ao marcador `rng:1-12`.

---

## Limpeza

**Funções removidas**

- `_ordinal_numeric_expansions` (query_planning) — expansão cardinal ampla;
- `_apply_candidate_ceiling` (lexical) — substituída pelas quotas;
- `_canonical_set` e `_proximity` (reranking) — absorvidas por
  `compute_content_match` / `compute_proximity`;
- `_match_range` (lexical_normalization) — wrapper trivial sobre `re.match`.

**Enums e dataclasses removidos**

- `RemovalReason` com o valor `DOMINATED` → substituído por `ExclusionReason`
  (`no_content_match`, `insufficient_coverage`, `below_threshold`);
- `TokenKind.RANGE_ENDPOINT` → `TokenKind.RANGE`;
- `CanonicalOrdinal` — dataclass sem qualquer uso.

**Campos de trace removidos**

`candidate_limit`, `candidate_ceiling`, `unique_candidate_count`,
`candidates_before_threshold`, `removed_by_dominance`, `removed_by_threshold`,
`variant_candidate_counts`, `VariantTrace.candidate_count`,
`RankedResultTrace.removal_reason` — nomes que já não correspondiam ao que
mediam ou contagens ambíguas.

**Duplicações eliminadas**

- `_STRATEGY_RANK` (lexical) e `_STRATEGY_QUALITY` (reranking) eram duas
  ordenações independentes das mesmas estratégias → ambas derivam agora de
  `STRATEGY_PRIORITY`, definida uma única vez em `query_planning`;
- o filtro "token informativo" estava escrito três vezes → `is_informative_surface`;
- `build_lexical_representation` era invocada duas vezes por candidato (uma para
  o conjunto canónico, outra para o stream) → uma só vez;
- `NumericRange.position` duplicava `LexicalToken.position` → removido.

**Código morto verificado**

```
rg "_ordinal_numeric_expansions"  → 0 ocorrências
rg "_apply_candidate_ceiling"     → 0 ocorrências
rg "DOMINATED"                    → 0 ocorrências
rg "removed_by_dominance"         → 0 ocorrências
rg "candidate_ceiling"            → 1 ocorrência: assert de ausência no relatório (teste)
rg "_WEIGHT_SUM"                  → 2: validação com math.isclose + teste que a cobre
```

**Testes substituídos** (validavam comportamento inseguro):
`test_dominated_subset_is_removed_by_dominance_not_threshold`,
`test_exact_phrase_survives_high_threshold`,
`test_ordinal_only_query_generates_candidate_via_numeric_expansion`,
`test_written_ordinal_adds_numeric_form_to_reduced_or`,
`test_single_ordinal_term_gains_reduced_or_variant`,
`test_numeric_ordinal_is_not_duplicated_in_reduced_or`.

**Centralizações:** limite global, distribuição de quotas, política de
elegibilidade, motivos de exclusão, criação do canonical stream, cálculo da
proximidade e prioridades de estratégia têm agora uma implementação única.

---

## Trace e diagnóstico

**Versão:** `DIAGNOSTIC_REPORT_VERSION` 3 → **4**.

**Campos:** `fts_config`, `informative_terms`, `query_ordinals`, `query_ranges`,
`planned_variants`, `global_candidate_limit`, `variants[]`
(`strategy`, `quota`, `returned_count`), `total_returned_before_dedup`,
`unique_after_dedup`, `candidates_evaluated`, `excluded_no_content_match`,
`excluded_insufficient_coverage`, `excluded_below_threshold`,
`final_result_count`, `results[]` (limitado), `excluded[]` (limitado, com motivo
tipado).

**Motivos:** `no_content_match`, `insufficient_coverage`, `below_threshold`.
Não existe nenhum outro — `DOMINATED` desapareceu com a dominância.

**Invariantes** (verificadas por `test_trace_counts_are_mathematically_consistent`
e no teste de diagnóstico):

```
soma(quota)          <= global_candidate_limit
soma(returned_count) == total_returned_before_dedup
unique_after_dedup   <= total_returned_before_dedup
candidates_evaluated == unique_after_dedup
candidates_evaluated == final_result_count
                        + excluded_no_content_match
                        + excluded_insufficient_coverage
                        + excluded_below_threshold
```

O `top_k` **não** conta como exclusão de relevância: `final_result_count` são os
sobreviventes; `results` detalha só os devolvidos.

**Privacidade.** A regra proíbe registar a pergunta **e os seus termos**. Há aqui
duas superfícies distintas, e uma versão anterior desta correção só tratava a
primeira:

- o **log operacional** só emite configuração FTS, contagens e IDs técnicos —
  coberto por `test_retrieval_logs_only_controlled_metadata`;
- o **relatório de diagnóstico** (Markdown *e* JSON) é um artefacto persistido e
  partilhável. O trace devolvido por `search_with_trace` é uma estrutura
  **interna**, em memória, que conhece as formas canónicas dos termos e serve a
  depuração e os testes; o relatório recebe uma projeção **redigida**
  (`redact_lexical_trace`), em que `informative_terms` e `matched_terms` passam a
  **contagens** (`informative_term_count`, `matched_term_count`). Como
  `render_markdown` e `render_json` são ambos gerados a partir dessa projeção,
  **o trace não acrescenta termos derivados a nenhum dos dois artefactos**.

Os ordinais e intervalos permanecem no relatório por serem marcadores
estruturais explicitamente exigidos (`ord:1`, `rng:1-12`) e não conteúdo lexical
da pergunta.

**Âmbito exato desta garantia.** O relatório como um todo **contém
deliberadamente** a pergunta e a resposta esperada de cada entrada
(`QuestionDiagnostic.question` / `expected_answer`): são o input do próprio
operador, indispensáveis para interpretar o diagnóstico, e existem desde a v1 —
é por isso que o artefacto abre com aviso de confidencialidade e não deve ser
publicado sem revisão humana. A garantia acima é mais estreita e diz respeito ao
trace: ele não deriva da pergunta um segundo conjunto de termos canónicos para
arrastar até ao relatório. A proibição literal de registar a pergunta aplica-se
aos **logs**, onde nunca aparece.

Coberto por `test_lexical_trace_does_not_duplicate_question_terms` (verifica
ausência dos termos derivados no Markdown e no JSON, e presença das contagens) e
por `test_trace_never_contains_document_content`.

**Uma única execução:** o diagnóstico continua a chamar `search_with_trace` uma
vez por pergunta, read-only, em transação `READ ONLY`, sem commit, sem OCR, sem
abrir PDF, sem OpenAI e sem answering.

---

## Regressão principal

Pergunta: **"Até quando posso mudar o regime de avaliação?"**
Termos canónicos: `('mudar', 'regime', 'avaliacao')` · orçamento 25 · quotas
9/8/8 · 3 candidatos únicos · 0 exclusões.

| Posição | Documento | Estratégia | Coverage | Score | Resultado |
| --- | --- | --- | --- | --- | --- |
| 1 | Calendário Institucional 2030/2031 (`table_row`) | `reduced_or` | 0.667 | **0.4472** | correto — evento e data no mesmo chunk |
| 2 | Manual de Avaliação (parágrafo) | `reduced_or` | 0.667 | 0.3748 | concorrente genérico, abaixo |
| 3 | Assistente Virtual (parágrafo) | `reduced_or` | 0.667 | 0.3128 | concorrente genérico, abaixo |

A `table_row` correta contém "Mudança do regime de avaliação | Até 6 de novembro
de 2030"; cobre `regime` e `avaliação` (2/3 ≥ 2/3), tem estratégia explícita, o
score está acima do limiar e os concorrentes ficam abaixo. Vence por
`ordered=0.50` (contra `0.00`) e pelo benefício de `table_row`
(`compactness = 0.667 ≥ 0.5`) — **sem qualquer hardcode**: `mudar` não é
associado a `mudança` em lado nenhum. Dados sintéticos com anos 2030/2031.

**Regressão negativa (ordinal):** `"primeira"` contra `"Sala 1 disponível."` →
plano `(exact,)`, 0 candidatos avaliados, **0 evidências**.

**Regressão negativa (cobertura):** ver abaixo.

**Regressão de intervalo:** ver a secção *Intervalos*.

---

## Evidência insuficiente

| Item | Valor |
| --- | --- |
| Documento sintético | `"Regime institucional geral."` (título "Política Interna") |
| Pergunta | `"regime avaliacao exames"` |
| Termos canónicos | `('regime', 'avaliacao', 'exames')` — 3 termos, mínimo exigido 2 |
| Variantes planeadas | `('exact', 'reduced_or')` |
| Candidato parcial | 1 candidato, estratégia `reduced_or`, termos correspondidos `('regime',)` |
| Coverage | **0.333** (1/3) |
| Eligibility decision | `eligible=False` |
| Motivo | `insufficient_coverage` (score `None` — excluído **antes** de ser pontuado) |
| Retrieval | `[]` |
| Answering | `status = "insufficient_evidence"` |
| Chamadas do gerador | **0** |
| `sources` | `[]` |
| `message_source` criadas | **0** (turno conversacional persiste 2 mensagens, 0 fontes) |

O mesmo cenário com o título a corresponder integralmente
(`"Regime Avaliação Exames"` sobre conteúdo administrativo irrelevante) produz
igualmente retrieval vazio — o título não cria elegibilidade. Idem para
`section_title`. Nenhuma resposta fundamentada falsa é persistida.

---

## Ficheiros alterados

| Ficheiro | Alteração | Justificação |
| --- | --- | --- |
| `backend/app/retrieval/eligibility.py` | **novo** | Fase 1 isolada, pura e testável sem PostgreSQL (C1, C3); base `EXPLICIT_SYNTAX` (R3) |
| `backend/app/retrieval/lexical_normalization.py` | intervalo como unidade posicional única; `canonical_stream`; endpoints auxiliares; `TokenKind.RANGE`; remoção de `CanonicalOrdinal` | C8, C9 |
| `backend/app/retrieval/query_planning.py` | `CANONICAL_RELAXED_AND`, `STRATEGY_PRIORITY`, `contextual_terms`, `is_informative_surface`, `MAX_QUERY_VARIANTS`; remoção da expansão cardinal; `WEBSEARCH_OPERATORS`; `uses_advanced_syntax` público | C5, C9, R3 |
| `backend/app/retrieval/reranking.py` | separação conteúdo/auxiliares, `compute_proximity`, `compactness`, remoção da dominância, `ExcludedCandidate`; propaga `explicit_syntax` | C1, C2, C3, C10, R3 |
| `backend/app/retrieval/lexical.py` | orçamento global + quotas antes das consultas; trace com invariantes; remoção do teto pós-agregação; garantia reformulada | C6, C7, C11, R2 |
| `backend/app/core/config.py` | `math.isfinite` (rejeita ±inf, não só NaN); comentário corrigido | secção 20 |
| `backend/app/diagnostics/document_pipeline.py` | versão 4; render dos novos campos e motivos; projeção redigida `LexicalTraceReport` + `redact_lexical_trace` | C12, R1 |
| `backend/tests/test_lexical_eligibility.py` | **novo** — 42 testes | elegibilidade + proximidade + sintaxe explícita |
| `backend/tests/test_candidate_budget.py` | **novo** — 17 testes | limite global + quotas |
| `backend/tests/test_settings_validation.py` | **novo** — 12 testes | NaN, ±inf, limites, padrão |
| `backend/tests/test_lexical_normalization.py` | +8 testes de stream/posições/intervalos | C8 |
| `backend/tests/test_query_planning.py` | testes de relaxação canónica; remoção dos de expansão cardinal | C5 |
| `backend/tests/test_lexical_reranking.py` | evidência complementar, motivos tipados, intervalos | C10 |
| `backend/tests/test_retrieval_reranking.py` | +12 testes: orçamento global, reserva de quota, trace, ordinais negativos, intervalos | C6, C11, R2 |
| `backend/tests/test_retrieval_natural_language.py` | fixtures partilham 2 termos com a pergunta | ver *Nota* abaixo |
| `backend/tests/test_answering_endpoint.py` | +2 testes end-to-end (1/3 termos; título sozinho) | C4 |
| `backend/tests/test_answering_service.py` | +1 teste com retriever **real** | C4 |
| `backend/tests/test_conversation_answering.py` | +1 teste: 0 `message_source` | C4 |
| `backend/tests/test_document_pipeline_diagnostics.py` | v4, invariantes, ausência de dominância; `test_lexical_trace_does_not_duplicate_question_terms` | C12, R1 |
| `backend/tests/test_answering_natural_language.py`, `test_conversation_lifecycle.py`, `test_document_deletion.py` | fixtures adaptadas | ver *Nota* abaixo |
| `README.md`, `.env.example`, `docs/database.md`, `docs/document-core.md`, `docs/answering.md`, `docs/diagnostics/README.md`, `docs/ManualConfiguracao.md` | política, quotas, motivos, v4, limitações; correção das afirmações contraditórias | C12, R2, R4 |
| `docs/relatorios/correcao-final-retrieval-lexical.md` | **novo** — este relatório | entregável da tarefa |

**Total: 25 ficheiros modificados, 5 novos.**

### Nota sobre as fixtures adaptadas

A política obrigatória (`required_matches = max(2, ceil(n × 0.5))`) torna
inelegível um candidato que corresponda a **1 de 2** termos. Vários testes de
*filtros institucionais*, *ciclo de vida da conversa* e *eliminação de
documentos* usavam `"Quando começam as aulas?"` (2 termos) contra documentos que
só continham `aulas` — usavam a correspondência parcial apenas como veículo para
chegar ao caminho que realmente testavam.

Adaptei essas fixtures para partilharem **dois** termos com a pergunta
(`"Quando começam as aulas de setembro?"` e conteúdos com `setembro`),
mantendo a variante `exact` a falhar — ou seja, continuam a exercitar o fallback
disjuntivo. Em `test_natural_question_respects_existing_filters` e
`test_fallback_excludes_future_and_expired_documents` o teste ficou **mais
forte**: agora todos os documentos seriam elegíveis, pelo que o que os exclui é
exclusivamente o filtro (oficial, ativo, validade, instituição), e não uma falha
de correspondência. Nenhum teste de comportamento foi enfraquecido ou removido
para acomodar a implementação.

---

## Ficheiros deliberadamente não alterados

Confirmado com `git diff --stat` e `git status --short` por caminho (todos
vazios):

- `backend/alembic/` — **nenhuma migration nova, nenhuma alterada**; head
  continua `e7b1c9d4a2f0`;
- `backend/app/models/` — schema intacto;
- `backend/app/services/document_extraction_service.py`,
  `document_processing_service.py`, `document_chunking_service.py`,
  `ocr_engine.py`, `ocr_line_reconstruction.py` — OCR, extração e chunking
  intactos (todo o `backend/app/services/` está sem alterações);
- `backend/app/answering/adapters/openai.py` e todo o `backend/app/answering/` —
  prompts, validação e adapter OpenAI intactos;
- `frontend/` — sem uma única alteração (incluindo `package-lock.json`);
- `.github/workflows/` — sem alterações.

`app/services/answering_service.py` **não** foi alterado: a suficiência de
evidência é resolvida inteiramente no retriever, como exigido.

---

## Correções aplicadas após revisão

Uma revisão do diff levantou quatro achados. Todos eram válidos e foram
corrigidos; nenhum foi contestado.

| ID | Achado | Correção |
| --- | --- | --- |
| R1 | **Alta** — o relatório de diagnóstico registava `informative_terms` e `matched_terms`, contrariando a regra que proíbe registar a pergunta e os seus termos. Os logs estavam seguros; o relatório não. | Introduzida a projeção redigida `LexicalTraceReport` + `redact_lexical_trace` em `document_pipeline.py`. O trace interno mantém os termos (memória, depuração, testes); o relatório recebe apenas contagens. Como `render_markdown` e `render_json` derivam ambos da projeção, nenhum recebe termos derivados. |
| R2 | **Alta** — `assert target in evaluated or trace.unique_after_dedup >= 1` era vacuoso (o segundo ramo é sempre verdadeiro), e a afirmação de que um candidato `exact` de FTS baixo "chega sempre" ao reranker era forte demais: cada variante continua ordenada por FTS e limitada à sua quota em SQL. | Teste reescrito com asserções sobre valores reais do trace. Garantia reformulada em `lexical.py`, `docs/database.md` e neste relatório: não há corte **global pós-agregação**; a quota de cada variante é **reservada**; mas uma variante que exceda a própria quota continua a ficar pelos melhores `ts_rank_cd`. |
| R3 | **Média/alta** — todo o candidato `EXACT` com alguma correspondência recebia `CONJUNCTIVE_STRATEGY`, incluindo consultas `OR` e negações, que planeiam apenas `exact` mas são disjuntivas por desenho. Além disso `or` contava como termo informativo (cobertura de `aulas OR exames` = 1/3). | Nova base `EligibilityBasis.EXPLICIT_SYNTAX`, decidida antes da condição conjuntiva; `uses_advanced_syntax` passou a público e é propagado por `rerank` via `explicit_syntax`. `WEBSEARCH_OPERATORS = {"or"}` excluído de `is_informative_surface`. 5 testes novos, incluindo `test_explicit_syntax_still_cannot_rescue_zero_coverage`. |
| R4 | **Média** — `.env.example` dizia "ainda sem recuperação"; `docs/database.md` dizia "não há reranking"; o relatório declarava "21 modificados e 4 novos" e omitia-se a si próprio da tabela de ficheiros. | Ambas as frases corrigidas. Contagens acertadas para **25 modificados e 5 novos**, com o relatório listado na tabela. |

O revisor também não conseguiu correr `docker compose ps` por o Docker Desktop
não estar ativo no seu ambiente. Na execução desta tarefa o serviço estava a
correr (`institutional-assistant-db … Up (healthy)`), e `docker compose config
--quiet` passou em ambos.

### Segunda ronda de revisão

Uma segunda revisão confirmou R3 e R4 e apontou que R1 e R2 estavam corretos no
código, mas com **garantias e testes mais amplos do que o entregue**. Ambos os
reparos eram válidos.

| ID | Reparo | Correção |
| --- | --- | --- |
| R1b | A garantia e o nome `test_report_never_exposes_question_terms` eram amplos demais: o relatório **continua a conter** `QuestionDiagnostic.question` e `expected_answer`, renderizados em Markdown e JSON. O teste serializava apenas `lexical_trace`, não o relatório completo. | Escolhida a primeira opção sugerida: **estreitar a garantia**, não alargar a implementação. Teste renomeado para `test_lexical_trace_does_not_duplicate_question_terms`; docstring, comentário do módulo e `docs/diagnostics/README.md` passam a delimitar o âmbito de forma explícita. Ver justificação abaixo. |
| R2b | O cenário (2 variantes, 30 concorrentes) passaria **também** na arquitetura antiga: `1 exact + 25 reduced_or = 26`, abaixo do antigo teto de 100, pelo que `_apply_candidate_ceiling` nem seria acionado. E "menor `raw_score` de todos os avaliados" comparava apenas `trace.results`, limitado pelo `top_k`. | Novo teste `test_total_rows_fetched_never_exceed_the_global_budget`, com 30 documentos que saturam as **quatro** variantes: assere `total_returned_before_dedup == 25`. A afirmação sobre o `raw_score` foi corrigida para "entre os resultados devolvidos", que é o que `trace.results` permite observar. |

**Sobre R1b — porque estreitar em vez de alargar.** O relatório contém a pergunta
e a resposta esperada desde a v1: são o *input do próprio operador*, sem os quais
o diagnóstico é ininterpretável, e é por isso que o documento abre com um aviso
de confidencialidade e não deve ser publicado sem revisão humana. A regra do
enunciado que proíbe a pergunta é, na secção do diagnóstico, literalmente
"pergunta **em logs**" — e nos logs ela nunca aparece. Remover a pergunta do
relatório seria uma alteração fora do âmbito das treze falhas, que degradaria a
ferramenta sem que nada o exigisse. O que a correção R1 resolve continua a ser
real e vale a pena: o trace derivava da pergunta um **segundo** conjunto de
termos canónicos e arrastava-o para o relatório sem que ninguém o tivesse
pedido. É essa duplicação que desapareceu.

**Sobre R2b — o teste discrimina, verificado por execução.** Para não repetir o
erro de afirmar sem medir, emulei a arquitetura antiga (`distribute_quotas`
substituída por "cada variante recebe o limite inteiro") no mesmo cenário:

```
@@ANTIGO total_returned: 100
@@ANTIGO budget: 25
@@ANTIGO quotas:      [25, 25, 25, 25]
@@ANTIGO devolvidos:  [25, 25, 25, 25]
```

Sob o desenho antigo o SQL devolveria **100** linhas; a asserção
`total_returned_before_dedup == 25` falharia. O ficheiro de verificação era
temporário e foi removido — não faz parte do diff.

Nota lateral encontrada ao montar o cenário: a variante `exact` não recupera
nada em perguntas com stopwords **acentuadas** ("Quando **são**…"), porque
`normalize_text` remove os acentos e `sao` deixa de casar a stopword portuguesa,
passando a termo obrigatório. É um comportamento pré-existente e fora do âmbito
desta tarefa, mas explica por que motivo tantas perguntas naturais dependem das
variantes reduzidas — e está registado aqui para não se perder.

### Terceira ronda de revisão

Uma terceira revisão confirmou que R1b e R2b ficaram resolvidos no código e nos
testes, e apontou que **este relatório** ainda conservava três afirmações da
ronda anterior. Eram inconsistências reais: o código dizia uma coisa e o
entregável dizia outra, mais forte.

| ID | Afirmação desatualizada | Correção |
| --- | --- | --- |
| R1c | "nenhum artefacto persistido pode expor termos" — amplo demais, pela mesma razão de R1b | Passa a "o trace não acrescenta termos derivados a nenhum dos dois artefactos", seguido de um parágrafo **Âmbito exato desta garantia** que declara que pergunta e resposta esperada estão no relatório por desenho |
| R1d | Duas referências ao nome removido `test_report_never_exposes_question_terms` (secção de privacidade e tabela de ficheiros) | Substituídas por `test_lexical_trace_does_not_duplicate_question_terms`. As ocorrências que restam neste relatório estão na tabela de R1b, onde citam o nome **antigo** como o defeito corrigido |
| R2c | "menor `ts_rank_cd` de todos os avaliados", na secção de reserva de quota | Passa a "entre os resultados devolvidos", com a nota de que `trace.results` está limitado ao `top_k` — alinhado com o comentário já presente no teste |

Alteração exclusivamente documental: **nenhum comportamento nem asserção
executável foi alterado**, pelo que as medições das tabelas de validação abaixo
continuam válidas. A varredura por outras ocorrências apanhou ainda dois
comentários com a mesma amplitude excessiva, corrigidos por consistência —
`document_pipeline.py` ("o texto dos termos da pergunta nunca é persistido" ⇒
"as formas canónicas derivadas da pergunta passam a contagens") e
`test_document_pipeline_diagnostics.py` ("nem o Markdown nem o JSON expõem
termos da pergunta" ⇒ "a secção do trace expõe contagens, não os termos
derivados", num comentário sobre um teste que só assere em `trace_payload`).

---

## Testes focados

| Comando | Passed | Failed | Skipped | Warnings | Duração |
| --- | --- | --- | --- | --- | --- |
| `pytest -q tests/test_lexical_normalization.py` | 40 | 0 | 0 | 1 | 1.41s |
| `pytest -q tests/test_lexical_eligibility.py` *(novo)* | 42 | 0 | 0 | 1 | 1.43s |
| `pytest -q tests/test_lexical_reranking.py` | 34 | 0 | 0 | 1 | 2.24s |
| `pytest -q tests/test_query_planning.py` | 39 | 0 | 0 | 1 | 1.33s |
| `pytest -q tests/test_candidate_budget.py` *(novo)* | 17 | 0 | 0 | 1 | 0.75s |
| `pytest -q tests/test_settings_validation.py` *(novo)* | 12 | 0 | 0 | 1 | 0.70s |
| `pytest -q tests/test_retrieval_natural_language.py` | 19 | 0 | 0 | 1 | 10.15s |
| `pytest -q tests/test_retrieval_reranking.py` | 29 | 0 | 0 | 1 | 25.4s |
| `pytest -q tests/test_retrieval.py` | 29 | 0 | 0 | 1 | 12.73s |
| `pytest -q tests/test_answering_service.py` | 16 | 0 | 0 | 1 | 3.39s |
| `pytest -q tests/test_answering_endpoint.py` | 22 | 0 | 0 | 1 | 8.74s |
| `pytest -q tests/test_conversation_answering.py` | 19 | 0 | 0 | 1 | 10.85s |
| `pytest -q tests/test_document_pipeline_diagnostics.py` | 90 | 0 | 0 | 1 | 8.87s |
| `pytest -q tests/test_migrations.py` | 11 | 0 | 0 | 1 | 15.76s |

O *warning* é o `StarletteDeprecationWarning` pré-existente da baseline.

---

## Validação completa

| Verificação | Resultado |
| --- | --- |
| `pytest -q` | **923 passed, 0 failed, 0 skipped, 1 warning, 241.97s** (baseline: 812) |
| `ruff check .` | All checks passed |
| `mypy app tests scripts` | Success: no issues found in **138** source files |
| `python -m pip check` | No broken requirements found |
| `alembic current` | `e7b1c9d4a2f0 (head)` |
| `alembic heads` | `e7b1c9d4a2f0 (head)` |
| `alembic check` | No new upgrade operations detected |
| `docker compose config --quiet` | OK (exit 0) |
| frontend `npm run lint` | OK |
| frontend `npm run typecheck` | OK |
| frontend `npm run test:run` | 9 ficheiros, 84 testes, 14.42s |
| frontend `npm run build` | built in 217ms |
| `git diff --check` | OK (exit 0) |

**CI:** o workflow `backend-checks.yml` não foi alterado e continua a executar
todas as verificações — Docker Compose config, Tesseract, dependências, import
da aplicação, Ruff, `mypy app tests scripts`, `alembic upgrade head`,
`alembic check` e `pytest -q`. Nenhuma verificação foi removida; o workflow do
frontend não foi tocado.

---

## Limitações restantes

**OCR.** Não é corrigido nem adivinhado. `"Exames da 12 chamada"` continua a ser
lido como cardinal `12`; `0509` continua ambíguo; `Ro` continua palavra. O
sistema pode recuperar essas linhas pelos termos reais, mas **nunca** afirma que
`12` é "a primeira".

**Stemming.** Atua apenas na geração de candidatos (PostgreSQL FTS). É o que
permite `matrículas` ⇄ `matrícula` e `começa` ⇄ `começam` — e é também o motivo
pelo qual um documento pode entrar no pool sem cobertura de superfície, sendo
depois filtrado pela elegibilidade.

**Lematização.** O reranker **não** faz lematização geral. `mudar` e `mudança`
não são garantidamente equivalentes: na regressão principal a linha correta vence
por cobrir `regime` e `avaliação`, não por qualquer relação entre `mudar` e
`mudança`.

**Sinónimos.** Não existem, nem institucionais nem gerais.

**Semântica.** Não existe. Sem embeddings, sem pesquisa vetorial, sem LLM no
retrieval. Perguntas cujo vocabulário não partilhe termos suficientes com os
documentos devolvem vazio — por desenho.

**Answering.** Continua a poder alucinar dentro da evidência que recebe. Esta
correção garante que **não recebe** evidência fraca, não que a resposta gerada
seja factualmente perfeita.

**Validação manual.** Os números apresentados vêm de dados **sintéticos**
(2030/2031). O comportamento sobre documentos institucionais reais continua a
exigir validação humana; nenhum documento real foi processado ou usado.

**Escolhas de calibração.** `MIN_COVERAGE_RATIO = 0.5`, `MIN_MATCHED_TERMS = 2`,
os pesos e `STRUCTURE_MIN_COMPACTNESS = 0.5` são decisões conservadoras e
versionadas, não resultados de otimização empírica. A adaptação de fixtures
descrita acima é a consequência prática direta desta escolha: perguntas de dois
termos passam a exigir os dois.

---

## Comandos não executados

Nenhum comando do enunciado foi omitido. Todos os passos das secções 4, 5, 28 e
29 foram executados e os resultados reais constam acima.

---

## Confirmações Git

| Ação | Estado |
| --- | --- |
| Commit | **não** foi criado nenhum |
| Push | **não** foi feito |
| Pull Request | **não** foi criado |
| Merge / rebase / squash / tag / release | **não** |
| Alteração direta da `main` | **não** — a `main` foi apenas atualizada por `pull --ff-only` e ficou em `ac8214d` |
| `git reset --hard` / `clean` / `stash` / `checkout --` / `restore .` | **não** foram usados |
| Alterações existentes apagadas | **nenhuma** |
| Migration nova ou alterada | **nenhuma** |
| Base de desenvolvimento | não foi alterada; nenhum downgrade Alembic |
| Rede durante os testes | não usada; OpenAI não usada |
| Documentos reais | não usados; todas as fixtures são sintéticas |

As alterações estão **locais e não commitadas** na branch
`fix/lexical-retrieval-correctness`, prontas para revisão:
**25 ficheiros modificados e 5 novos** (`git status --short`).
