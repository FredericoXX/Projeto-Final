# Evaluation Snapshot — identidade reprodutível do contexto experimental

Relatório da implementação. Documento **histórico**: regista o desenho e as
decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Problema científico

Uma medição da forma

```
pergunta + resultado
```

não é reprodutível. Se o corpus documental ou a configuração de recuperação
mudarem entre duas execuções, o mesmo pedido produz outro resultado e **nada no
registo o assinala**. Uma comparação entre duas medições feitas em momentos
diferentes não consegue distinguir "o sistema melhorou" de "o corpus mudou".

O problema é concreto e já observável neste artefacto: o corpus elegível depende
da data de referência (`valid_from`/`valid_until`), do idioma, da restrição a
fontes oficiais e de qual é a versão `processed` mais recente de cada documento.
Nenhuma dessas variáveis é hoje registada junto de um resultado.

## 2. Objetivo

Dar **identidade determinística e auditável** ao contexto experimental, de modo
a evoluir para:

```
pergunta + EvaluationSnapshot + ground truth
        ↓
resultado experimental reprodutível
```

O objetivo **não** é copiar a base de dados nem construir experiment tracking.
É obter uma identidade científica reutilizável nas fases seguintes.

## 3. Baseline

| Item | Valor |
| --- | --- |
| `main` verificada | `311d917072c31066ec16c4ff8cfc90420cc35b02` (merge do Pull Request #47, A2.3a) |
| Branch de trabalho | `feat/evaluation-snapshot` |
| Migrations | nenhuma criada; head continua `a5c31f70b8d2` |

## 4. Desenho adotado

Dois módulos, com a fronteira decidida por uma garantia já existente:

```
app/evaluation/snapshot.py          contratos imutáveis + canonicalização + digest
        │                           puro: sem SQLAlchemy, sem Settings
        ▼
app/evaluation/snapshot_builder.py  construção a partir da base de dados
                                    consome RetrievalEligibility
```

A separação não é estética. `app/evaluation/__init__.py` é executado ao importar
`app.evaluation.assets`, e um teste em subprocesso
(`test_evaluation_package_validates_assets_in_isolation`) fixa que essa
importação **não** carrega `sqlalchemy`, `app.core.config` nem o SDK do
fornecedor. O módulo puro tem de poder viver desse lado da fronteira; o builder
não pode. Nenhum dos dois é reexportado por `__init__.py`, exatamente como
`app.evaluation.results` já não era.

Não foi criado endpoint HTTP: o snapshot é infraestrutura científica interna, e
não existe consumidor operacional que o justifique.

## 5. O que entra na identidade

### `corpus_digest` — uma entrada por versão documental elegível

| Campo | Porque é material |
| --- | --- |
| `document_id` | identidade do documento |
| `document_version_id` | identifica a versão concreta que compunha o corpus |
| `document_title` | entra no **ranking** (sobreposição com o título, peso 0.07) e no payload enviado ao gerador |
| `source_url` | é enviado ao gerador em cada evidência (`answering/context.py`); dois corpora que difiram nele apresentam contexto diferente |
| `language` | decide elegibilidade (C7/C8) e a configuração FTS |
| `official_source` | decide elegibilidade quando `official_only` está ativo (C11) |
| `valid_from` / `valid_until` | decidem vigência face à data de referência (C9/C10) |
| `checksum_sha256` | prova **qual** ficheiro concreto compunha o corpus |
| `chunk_count` | uma resegmentação altera as unidades recuperáveis |
| `chunk_digest` | digest dos sinais de cada segmento que participam na recuperação |

`chunk_digest` cobre, por segmento e ordenados por `chunk_index`:
`content_sha256`, `normalized_content_sha256`, `section_title` e
`structure_type`.

Os **dois hashes** são necessários porque a recuperação lê duas colunas
diferentes: `content` é o texto que o gerador recebe como evidência;
`normalized_content` é o texto **efetivamente pesquisado**, de que a coluna
gerada `search_vector` deriva e sobre o qual a cobertura lexical é medida. Uma
renormalização mudaria o comportamento da recuperação sem tocar no conteúdo
original.

Ambos são **recalculados a partir das colunas vivas**, em SQL
(`encode(sha256(convert_to(...,'UTF8')),'hex')`, função de core desde o
PostgreSQL 11), e **não** lidos de `document_chunks.content_sha256`: um hash
persistido é uma afirmação sobre o conteúdo, e uma identidade científica não
deve herdar uma afirmação possivelmente desatualizada. Calcular na base tem duas
consequências desejáveis: nenhum texto documental atravessa a fronteira da base,
e o custo de memória não cresce com o corpus. A coincidência com
`hashlib.sha256` é verificada por teste.

`section_title` e `structure_type` entram porque participam no ranking lexical
(sobreposição com o título da secção, benefício condicionado de `table_row`).

### `snapshot_id` — corpus, contexto e configuração

```
schema_version + institution_id + reference_date + corpus_digest + retrieval
```

`retrieval` captura, tudo **lido da implementação real** e nada inventado:

| Campo | Origem |
| --- | --- |
| `strategy` | única estratégia implementada (`lexical`) |
| `pipeline_version` | `LEXICAL_PIPELINE_VERSION` (`lexical_pipeline_v1`) |
| `scoring_version` | `LEXICAL_SCORE_SEMANTICS.version` (`lexical_composite_v1`) |
| `score_kind` | `LEXICAL_SCORE_SEMANTICS.kind` |
| `comparable_across_queries` | `LEXICAL_SCORE_SEMANTICS.comparable_across_queries` |
| `language` | parâmetro da experiência |
| `top_k` | corte de apresentação e base do orçamento de candidatos |
| `official_only` | parâmetro que altera a elegibilidade |
| `fts_config` | `resolve_fts_config(language)` |
| `min_relevance_score` | `settings.retrieval_min_relevance_score` |
| `candidate_limit` | `global_candidate_limit(top_k)` **já resolvido** |

`candidate_limit` guarda o valor efetivo e não as três constantes que o compõem
(`CANDIDATE_MIN`, `CANDIDATE_MAX`, `CANDIDATE_MULTIPLIER`): assim, alterar essas
constantes muda a identidade mesmo com o mesmo `top_k`.

**`pipeline_version` e `scoring_version` não são redundantes.** `SCORING_VERSION`
está declarado em `app/retrieval/reranking.py` como identificando apenas os
**pesos e o limiar do rerank**. Mas o resultado de uma pesquisa depende de mais
etapas, e todas podem mudar sem que nenhum peso mude: planeamento da consulta
(variantes, prioridades, `MAX_INFORMATIVE_TERMS`, tokenização, operadores de
websearch), normalização lexical e formas canónicas, elegibilidade lexical
(cobertura mínima, bases de admissão), expressão da coluna gerada
`search_vector`, e a repartição do candidate pool. `LEXICAL_PIPELINE_VERSION`
foi introduzida em `app/retrieval/lexical.py` para cobrir esse conjunto —
constante pura, sem alteração de comportamento nem de contrato público — e
**subi-la é obrigatório** quando qualquer uma dessas etapas muda. Sem ela, uma
alteração ao planeamento produziria resultados diferentes declarando o mesmo
`snapshot_id`.

`score_kind` e `comparable_across_queries` registam que o score é **relevância
lexical**, não confiança nem probabilidade, e que não é comparável entre
perguntas diferentes. Nenhum limiar novo foi introduzido e nenhuma calibração
foi feita.

## 6. O que fica deliberadamente de fora

| Excluído | Porquê |
| --- | --- |
| `description` | não participa na recuperação, no ranking nem no contexto do gerador |
| `page_number` | transportado pelo candidato lexical mas **nunca lido** por `build_features`; não viaja em `Evidence`. Uma mudança de paginação que altere a recuperação altera também o conteúdo dos segmentos, que já é identificado — incluí-lo produziria falsos positivos de "o corpus mudou" |
| `is_active` | constante `True` em qualquer entrada elegível — nunca varia |
| `version_number` | redundante: a entrada já identifica **qual** versão era a efetiva |
| `created_at` / `updated_at` | voláteis; não alteram o resultado |
| `storage_path`, `original_filename` | caminho de armazenamento e metadados do ficheiro; §22 exclui-os |
| texto de `content`, `extracted_text`, `normalized_content` | entram apenas como **hash**; o digest não pode ser canal para exfiltrar texto documental |
| `chunk_id` | identidade técnica instável face a resegmentação; o digest de conteúdo é mais informativo |
| pesos individuais do ranking | já identificados por `scoring_version`; duplicá-los criaria duas fontes de verdade |
| credenciais, chaves, prompts, respostas do fornecedor | nunca entram em artefactos |

`document_title` e `source_url` **entram**, ao contrário de `description`,
porque atravessam a experiência para lá da elegibilidade: o título é sinal de
ranking, e ambos são enviados ao gerador dentro do payload de evidência
(`app.answering.context.evidence_payload`). São metadados públicos do documento
— do mesmo tipo que `MessageSource` já persiste como snapshot — e não são dados
pessoais.

## 7. Canonicalização

Reutiliza `app.evaluation.results.canonical_json`, que o projeto já declara como
a sua serialização canónica única: UTF-8, `ensure_ascii=False`, chaves
ordenadas, separadores `(",", ":")` e sem newline final. **Não foi criada uma
segunda canonicalização** — divergiria da primeira à primeira alteração.

Regras fixadas por teste:

- **arrays** — as entradas do corpus são ordenadas por
  `(str(document_id), str(document_version_id))` e os segmentos por
  `chunk_index`; a ordem de leitura da base nunca participa;
- **UUID** — forma canónica minúscula com hífenes, via `str()`;
- **datas** — ISO-8601 `YYYY-MM-DD`; ausência serializa como `null`;
- **opcionais** — presentes com valor `null`, nunca omitidos;
- **digest** — SHA-256 da serialização canónica;
- **`schema_version`** — participa nos dois payloads, para que uma mudança de
  formato mude a identidade em vez de colidir com ela.

`hash()` do Python **nunca** é usado: é aleatorizado por processo. A propriedade
é verificada por um teste em subprocesso que constrói o mesmo snapshot com três
valores diferentes de `PYTHONHASHSEED` e compara os digests, e por uma
verificação AST de que o módulo não chama `hash`.

## 8. `corpus_digest` vs `snapshot_id`

As duas identidades são mantidas porque respondem a perguntas diferentes, e é
essa separação que torna possível a comparação controlada:

| Observação | Leitura |
| --- | --- |
| `corpus_digest` igual, `snapshot_id` diferente | mesmo corpus, contexto ou recuperação diferentes |
| `corpus_digest` diferente, `snapshot_id` diferente | o corpus mudou |
| ambos iguais | mesma experiência |

Uma identidade única não permitiria distinguir a primeira linha das restantes.

## 9. Data de referência

`reference_date` é **parâmetro obrigatório e explícito**. Não existe qualquer
chamada a `date.today()` no builder: uma reconstrução posterior que fosse buscar
a data corrente reconstruiria outro corpus e chamar-lhe-ia o mesmo.

**Decisão sobre a semântica (T7).** A data participa **sempre** no
`snapshot_id`, mesmo quando não altera o corpus observado. É variável
experimental declarada, não detalhe de execução: duas medições com datas
diferentes não são a mesma experiência, e a coincidência dos corpora é
contingente — deixaria de valer noutra data. Quem precisa de saber se o corpus
coincidiu compara `corpus_digest`, que deliberadamente **não** inclui a data.

## 10. Integração com `RetrievalEligibility`

O corpus é exatamente o conjunto que `RetrievalEligibility` considera
admissível. A consulta parte de `select_eligible_chunk_ids`, que já reúne os
filtros de linha (C1–C4, C6–C11) e a subquery da versão efetiva (C5).

**Nenhuma condição foi reescrita, reinterpretada ou parcialmente copiada.** Uma
segunda definição de "documento elegível" divergiria da primeira e tornaria o
snapshot uma ficção. Se a política mudar, o corpus muda com ela — e é isso que
se pretende.

A propriedade é fixada por um teste que compara o conjunto de versões do
snapshot com o conjunto que a política devolve diretamente.

## 11. Persistência

**Não foi criada tabela e não foi criada migration.** Decisão explícita.

A pergunta de §13 — "para criar e usar snapshots reprodutíveis nas próximas
experiências, é necessário persistir o snapshot no domínio operacional?" — tem
resposta **não** nesta fase:

- não existe consumidor operacional: nenhum endpoint, serviço ou fluxo da
  aplicação lê snapshots;
- o snapshot é um **valor** derivado deterministicamente do estado da base; pode
  ser recalculado a qualquer momento a partir dos mesmos dados e parâmetros;
- é serializável por `as_payload()`, pelo que uma execução de avaliação futura o
  versiona como artefacto JSON, exatamente como o Momento 5 já faz com a sua
  baseline;
- criar uma tabela agora seria schema para um consumidor que não existe.

Se uma fase posterior precisar de consultar snapshots transversalmente — por
exemplo para comparar execuções sem reler os artefactos — a decisão volta a ser
tomada com esse requisito concreto em mãos.

## 12. Testes

| Grupo | Ficheiro | Prova |
| --- | --- | --- |
| Determinismo (T1) | unit | mesmas entradas → mesmo `snapshot_id` e `corpus_digest` |
| Conteúdo pesquisado | corpus | renormalizar um segmento muda a identidade; hashes recalculados, não herdados da coluna; SHA-256 do PostgreSQL == `hashlib` |
| `source_url` | corpus | ausente → presente → alterado produzem três identidades distintas |
| Equivalência com a política | corpus | `chunk_digest` por versão **reconstruído a partir das linhas da própria política** e comparado com o do snapshot; perder um segmento numa versão presente muda a identidade |
| `page_number` | unit | ausente da identidade, por decisão documentada |
| Ordem acidental (T2) | unit + corpus | reverter/baralhar entradas e segmentos não muda a identidade |
| Alteração material (T3, T4) | unit + corpus | cada campo da entrada, versão nova, adição/remoção |
| Inelegível (T5) | corpus | quatro documentos inelegíveis não movem a identidade |
| Data de referência (T6, T7) | unit + corpus | altera o corpus quando altera vigência; participa sempre no `snapshot_id` |
| Configuração (T8) | unit | cada um dos onze parâmetros muda o `snapshot_id` |
| Irrelevante (T9) | corpus | `description` não move a identidade |
| Estabilidade (T10, T12) | unit | subprocesso com três `PYTHONHASHSEED`; AST sem `hash()` |
| Representação (T11) | unit | UUID canónico, datas ISO, `null` explícito |
| Política (T13) | corpus | identidade dos segmentos do snapshot == a derivada de `select_eligible_chunk_ids` |
| `/ask` (T14) | pré-existente | `test_moment06_public_contracts_characterisation.py` fixa os dois estados |
| Momento 5 (T15) | unit | `result_digest` do artefacto versionado fixado por constante |
| Casos temporais A–H | corpus | vigência, versão efetiva, `pending`, inativo, oficialidade, idioma do documento e do chunk |
| Multi-tenancy | corpus | corpora estruturalmente idênticos em dois locatários não colidem |

**Sondas de mutação**, aplicadas e integralmente revertidas (reversão confirmada
por SHA-256 dos ficheiros):

| Mutação | Detetada por |
| --- | --- |
| remover a ordenação canónica | 2 testes de ordem |
| retirar `top_k` da identidade | teste parametrizado `[top-k]` + conjunto exato de campos |
| ignorar `reference_date` | teste da semântica da data |
| `snapshot_id` como UUID aleatório | determinismo, ordem e estabilidade entre processos |
| ignorar a política de elegibilidade | 11 testes de corpus |
| alterar o conteúdo mantendo a contagem de segmentos | teste de equivalência com a política (a versão anterior, que comparava contagens, teria passado) |

## 13. Limitações

Declaradas, não contornadas:

- **a identidade não substitui o artefacto.** O `snapshot_id` prova que dois
  contextos são o mesmo ou são diferentes; não reconstrói o contexto. Para
  reproduzir uma execução é preciso o snapshot serializado **e** os dados;
- **o snapshot descreve o contexto, não a medição.** Não há resultados, métricas
  nem *ground truth*; nada aqui avalia o que quer que seja;
- **não há garantia de recuperabilidade histórica.** O snapshot identifica o
  corpus que existia; não impede que documentos sejam alterados depois. Um
  `corpus_digest` diferente prova que mudou, mas não reconstrói o estado
  anterior;
- **isolamento institucional sem RLS.** A garantia é a combinação do filtro da
  política, das foreign keys compostas e da autorização de quem invoca o
  builder. A base **não** tem Row-Level Security, e este trabalho não altera
  isso.

## 14. Enquadramento DSR

**DSR3 — Design & Development.** É construção de artefacto: um contrato, uma
canonicalização e um builder, com os testes que fixam as suas propriedades.

**Não é DSR4 nem DSR5.** Nada foi demonstrado com utilizadores e nada foi
avaliado empiricamente. O snapshot é infraestrutura *para* essas fases: sem ele,
uma medição futura não seria comparável nem defensável metodologicamente.

## 15. Próxima fase

O snapshot não decide nada sobre a abordagem de recuperação, e não deve ser lido
como início dessa decisão. A sequência que ele destranca é:

```
corpus institucional autorizado
        ↓
ground truth / protocolo de anotação
        ↓
baseline lexical real (com snapshot registado)
        ↓
medição de retrieval
        ↓
decisão experimental: lexical vs dense/híbrido
```

A precedência continua a ser a autorização institucional: sem corpus real
autorizado não há *ground truth*, e sem *ground truth* a medição não tem
referência contra a qual comparar.
