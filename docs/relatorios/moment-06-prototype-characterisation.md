# Verificação — Momento 6, caracterização do protótipo

Segundo [`05-verification-template.md`](../ai/05-verification-template.md).

## Identificação

| Campo | Valor |
| --- | --- |
| Título | Caracterização do protótipo antes da evolução dos contratos |
| Data | 2026-08-10 |
| Branch | `test/prototype-characterisation` |
| Repositório | `FredericoXX/Projeto-Final` |
| Momento | [`moment-06.md`](../ai/moments/moment-06.md) |
| Issue relacionada | [#24 — Política de elegibilidade da evidência](https://github.com/FredericoXX/Projeto-Final/issues/24) |
| Gate aplicado | **backend**, segundo [`03-quality-gates.md`](../ai/03-quality-gates.md) |

## Veredicto

**Aprovado.** A caracterização está verde, a Fase 0 da issue #24 está
satisfeita, as mutações de sensibilidade foram restauradas e o estado final não
altera código de produção. A integração e a aprovação humana ainda não
ocorreram.

> A frase anterior descreve o estado no momento da verificação e é mantida como
> registo histórico. A integração ocorreu depois: ver
> [Integração e fecho](#integração-e-fecho).

## Estado inicial

| Item | Valor |
| --- | --- |
| `BASE_SHA` | `6e2d09cfd3348fbc9fbe842a53953a767ecd3be4` |
| Branch criada a partir de | `main` em `6e2d09c` |
| Working tree encontrada | quatro ficheiros de testes não versionados; nenhuma alteração de produção |
| `HEAD` final | permanece `6e2d09c`; o trabalho está no working tree, sem commit futuro inventado |
| Migration em head | `e7b1c9d4a2f0`, head única |
| Commits / push / Pull Request | nenhum |

O `HEAD` esperado pelo enunciado coincidiu com o estado real; não foi
necessário escolher outra baseline nem reverter trabalho da `main`.

## Baseline

Antes de continuar a implementação, os três ficheiros de testes já presentes
executaram **18 testes: 18 passed, 0 failed, 1 warning, 7.96 s**. O warning é o
`StarletteDeprecationWarning` pré-existente de `fastapi/testclient.py`.

O inventário confirmou que não existia
`docs/ai/moments/moment-06.md` nem relatório do Momento 6. Existia já cobertura
substancial em testes anteriores; ela foi referenciada em vez de duplicada.

## Problema reproduzido

Confirmado por leitura e execução:

- answering devolve só fontes citadas e preserva a ordem produzida pelo
  gerador;
- zero evidências termina antes do provider;
- os cinco reason codes de validação produzem 502 seguro;
- o turno conversacional persiste duas mensagens e, quando aplicável, fontes
  numa única transação;
- retrieval, revalidação de citações e diagnóstico exprimem a elegibilidade em
  três formas diferentes;
- C5 pertence ao retrieval atual, mas não à persistência de citações;
- o diagnóstico atual não avalia C8, embora retrieval e persistência a
  apliquem;
- os schemas públicos declaram hoje exatamente dois statuses.

Não foi observada necessidade de alterar o protótipo.

## Ficheiros alterados

| Ficheiro | Estado | Razão |
| --- | --- | --- |
| `backend/tests/moment06_support.py` | novo | helpers sintéticos, gerador determinístico e callback de interleaving |
| `backend/tests/test_moment06_answering_characterisation.py` | novo | lacunas de answering, reason codes HTTP e startup sem credenciais |
| `backend/tests/test_moment06_evidence_eligibility_characterisation.py` | novo | C8, C12, D1/D2 e proveniência histórica N → N+1 |
| `backend/tests/test_moment06_public_contracts_characterisation.py` | novo | forma exata do retrieval e statuses públicos |
| `docs/ai/moments/moment-06.md` | novo | especificação documental ausente no SHA base |
| `docs/relatorios/moment-06-prototype-characterisation.md` | novo | este relatório factual |

## Ficheiros deliberadamente não alterados

Não foram alterados `backend/app/`, `backend/alembic/`, `backend/scripts/`,
`frontend/`, `.github/`, `backend/app/evaluation/` nem qualquer corpus, schema,
rubrica ou baseline do Momento 5. As cinco mutações de sensibilidade em código
de produção foram temporárias e integralmente restauradas antes do gate final.

## Testes adicionados

| Ficheiro | Teste | Comportamento caracterizado |
| --- | --- | --- |
| `test_moment06_answering_characterisation.py` | `test_sources_follow_generator_citation_order_and_omit_uncited_evidence` | resposta, ordem das citações e omissão de evidência não citada |
| idem | `test_each_structural_reason_code_produces_502_upstream_error` (5 casos) | cinco reason codes, 502 seguro e emissão controlada do motivo |
| idem | `test_application_starts_and_serves_without_openai_credentials` | startup e health sem credenciais OpenAI |
| idem | `test_provider_absence_only_fails_when_generation_is_actually_executed` | short-circuit sem evidência antes do provider |
| `test_moment06_evidence_eligibility_characterisation.py` | `test_c8_chunk_language_divergent_from_document_is_excluded_from_retrieval` | C8 isolada de C7 no retrieval |
| idem | `test_c8_chunk_language_divergent_is_rejected_by_citation_revalidation` | C8 na persistência de citações |
| idem | `test_d2_diagnostic_does_not_evaluate_chunk_language` | divergência D2 atual |
| idem | `test_c12_absence_of_processed_version_is_reported_as_its_own_condition` | C12 como ausência de linhas |
| idem | `test_c5_is_absent_from_citation_revalidation_which_accepts_a_superseded_version` | D1: C5 ausente da persistência |
| idem | `test_phase_zero_issue_24_preserves_historical_provenance_when_n_plus_one_is_processed` | sequência completa N → N+1 |
| `test_moment06_public_contracts_characterisation.py` | `test_retrieval_search_item_exposes_exactly_the_current_field_set` | forma completa do JSON de retrieval |
| idem | `test_retrieval_schema_and_evidence_dataclass_declare_the_same_fields` | acoplamento atual `Evidence` → schema público |
| idem | `test_both_answering_surfaces_declare_exactly_the_same_two_statuses` | conjunto exato dos statuses nos schemas |
| idem | `test_answering_ask_returns_only_the_two_declared_statuses` | ambos os statuses no endpoint independente |
| idem | `test_conversation_ask_returns_only_the_two_declared_statuses` | ambos os statuses no endpoint conversacional |

São 15 funções de teste e **19 casos pytest**, por causa dos cinco casos
parametrizados dos reason codes.

## Cobertura já existente reutilizada

- zero evidências, fallback, provider não chamado e 503 quando aplicável:
  `test_answering_service.py`, `test_answering_endpoint.py` e
  `test_conversation_answering.py`;
- mensagens, `reply_to_message_id`, `extra_metadata["answer_status"]`,
  atomicidade, rollback e ausência de `MessageSource` no fallback:
  `test_conversation_answering.py`;
- isolamento no retrieval, answering e persistência:
  `test_retrieval.py`, `test_answering_endpoint.py`,
  `test_conversation_answering.py`, `test_message_source_integrity.py` e
  `test_multi_institution_integrity.py`;
- integridade de versões e fontes históricas:
  `test_referenced_document_versions.py`;
- reason codes na função pura: `test_answering_units.py`;
- artefactos e reprodução da baseline: `test_evaluation_*.py`.

## Matriz da Fase 0 da issue #24

| Condição | Cobertura | Teste principal | Observação |
| --- | --- | --- | --- |
| C1 — chunk pertence à instituição | coberto previamente | `test_cross_institution_chunk_is_rejected_by_postgres`; `test_institution_isolation_applies_to_regular_user_and_admin` | FK composta + filtro SQL observável; sem alegação de RLS |
| C2 — documento pertence à instituição | coberto previamente | `test_version_rejects_document_from_another_institution`; teste de isolamento do retrieval | relação impossível na base e query limitada ao tenant |
| C3 — versão pertence à instituição | coberto previamente | testes de integridade de chunks/document versions | FK composta e revalidação por instituição |
| C4 — versão está `processed` | coberto previamente | `test_nonprocessed_latest_version_does_not_hide_previous_processed` | versão não processada não é selecionada |
| C5 — maior `version_number` entre `processed` | prévio + novo | `test_latest_processed_version_replaces_older_in_search`; testes D1 e N → N+1 | condição de conjunto; deliberadamente ausente da persistência |
| C6 — documento ativo | coberto previamente | `test_inactive_future_and_expired_documents_are_excluded` | aplicado no PostgreSQL |
| C7 — idioma do documento | coberto previamente | `test_portuguese_and_english_searches_work` | contexto e documento compatíveis |
| C8 — idioma do chunk | novo | três testes C8/D2 | isolado por alteração direta permitida da linha de teste |
| C9 — `valid_from` | coberto previamente | `test_inactive_future_and_expired_documents_are_excluded` | inclui limite e nulidade na suite existente |
| C10 — `valid_until` | coberto previamente | `test_inactive_future_and_expired_documents_are_excluded` | inclui expiração e nulidade |
| C11 — fonte oficial | coberto previamente | `test_official_only_defaults_true_and_false_allows_both` | condição só se aplica com `official_only=True` |
| C12 — existe versão `processed` | prévio + novo | `test_document_without_processed_version_is_not_searched`; teste C12 do diagnóstico | ausência de linhas, não condição fabricada numa linha |

**Fase 0 da issue #24 = satisfeita.** C1–C12, D1 e D2 têm cobertura
executável ou demonstração da invariante relacional correspondente; não foi
criado qualquer módulo ou política da futura Fase 1.

## Proveniência histórica N → N+1

Resultado explícito: **PASS**.

1. N foi criada, processada e devolvida pelo retrieval.
2. Durante `RecordingAnswerGenerator.generate`, o callback criou e processou
   N+1 pela API real.
3. O turno terminou com 201 e `status="answered"`.
4. Uma pesquisa posterior devolveu apenas N+1.
5. O `MessageSource` persistido manteve a instituição, documento, chunk e
   versão N realmente usados.
6. O histórico da conversa continuou a devolver a fonte N sem reavaliar C5.

## Divergência D2 — comportamento conhecido

`DIVERGENCE-D2` é reproduzida: perante um chunk de idioma diferente do
documento, retrieval e revalidação de citações recusam a linha, mas o
diagnóstico atual mantém o veredicto elegível porque não possui uma condição
para o idioma do chunk. Isto descreve o comportamento de `6e2d09c`; não o
declara correto nem o transforma em requisito normativo. A eventual mudança
pertence à Fase 4 da issue #24.

## Contratos HTTP caracterizados

`POST /api/v1/retrieval/search` devolve o envelope exato `query`, `language`,
`items`. Cada item possui exatamente:

```text
chunk_id
document_id
document_version_id
document_title
chunk_index
content
score
language
official_source
source_url
valid_from
valid_until
```

Nos caminhos de sucesso, `POST /api/v1/answering/ask` (200) e
`POST /api/v1/conversations/{id}/ask` (201) expõem exatamente:

```text
answered
insufficient_evidence
```

## Testes de sensibilidade da caracterização

Cada perturbação foi aplicada separadamente, o teste indicado falhou pela
razão esperada, a implementação foi restaurada e o mesmo teste voltou a passar.

| Comportamento | Perturbação temporária | Teste que detetou a mudança | Falha esperada observada? | Produção restaurada? |
| --- | --- | --- | --- | --- |
| ordem das fontes | `reversed(cited_ids)` | `test_sources_follow_generator_citation_order_and_omit_uncited_evidence` | sim — `['E1', 'E3']` em vez de `['E3', 'E1']` | sim; teste verde |
| short-circuit sem evidência | condição temporariamente desativada | `test_provider_absence_only_fails_when_generation_is_actually_executed` | sim — 503 em vez de 200 | sim; teste verde |
| forma de `Evidence` | campo temporário `score_kind` | `test_retrieval_schema_and_evidence_dataclass_declare_the_same_fields` | sim — campo extra detetado | sim; teste verde |
| statuses públicos | status temporário `escalated` | `test_both_answering_surfaces_declare_exactly_the_same_two_statuses` | sim — terceiro valor detetado | sim; teste verde |
| proveniência N → N+1 | C5 temporariamente aplicada à persistência | teste central N → N+1 | sim — 409 em vez de 201 | sim; teste verde |

Após as cinco restaurações, os hashes do conteúdo dos ficheiros temporariamente
tocados coincidiram com `HEAD`, não ficou diff ou staging de produção e a suite
completa passou.

## Testes focados

| Comando | Passed | Failed | Warnings | Duração |
| --- | --- | --- | --- | --- |
| três ficheiros do Momento 6, estado inicialmente encontrado | 18 | 0 | 1 pré-existente | 7.96 s |
| teste central N → N+1 | 1 | 0 | 1 pré-existente | 1.22 s |
| três ficheiros do Momento 6, estado final | 19 | 0 | 1 pré-existente | 7.55 s |
| reprodução da baseline do Momento 5 | 1 | 0 | 1 pré-existente | 0.16 s |

## Baseline do Momento 5

O teste oficial de reprodução passou. O `result_digest` permanece:

```text
75d936182d9b8a675b43da208f04e1e7168c439c1fdbace04a865283731dd345
```

`moment-05-baseline-p1.json`, `app/evaluation/`, o corpus e a rubrica não têm
diff. Nenhum resultado histórico foi recalculado ou alterado.

## Validação completa

| Verificação | Resultado |
| --- | --- |
| `docker compose config --quiet` | **PASS** — sem saída |
| `python -m pip check` | **PASS** — `No broken requirements found.` |
| `python -c "from app.main import app; print(app.title)"` | **PASS** — `Agentic Institutional Assistant` |
| `ruff check .` | **PASS** — `All checks passed!` |
| `mypy app tests scripts` | **PASS** — sem issues em 155 source files |
| primeira passagem de `python -m pytest -q` | **FAIL** — 1138 passed, 5 novos testes falharam por dependência da configuração global de logging; ver A1 |
| passagem final de `python -m pytest -q` | **PASS** — 1143 passed, 1 warning pré-existente, 236.84 s |
| `alembic upgrade head` | **PASS** — sem operações pendentes |
| `alembic current` | **PASS** — `e7b1c9d4a2f0 (head)` |
| `alembic heads` | **PASS** — `e7b1c9d4a2f0 (head)`, head única |
| `alembic check` | **PASS** — `No new upgrade operations detected.` |
| `git diff --check` + verificação `--no-index --check` dos ficheiros novos | **PASS** — sem erros de whitespace |

## Achados

| # | Severidade | Achado | Evidência | Estado |
| --- | --- | --- | --- | --- |
| A1 | Baixa | a primeira versão dos cinco testes HTTP de reason codes dependia de `caplog` e da configuração global de logging, ficando sensível à ordem da suite | focados verdes; na primeira suite completa, 5 falhas por ausência de records apesar do 502 correto | resolvido apenas nos testes: interceção direta de `logger.warning`; focados e suite completa verdes |

Nenhum defeito comportamental novo da aplicação foi observado. A divergência D2
já especificada na issue #24 foi confirmada e permanece deliberadamente sem
correção neste momento.

## FOLLOW-UP

| Descrição | Risco | Ficheiro/módulo | Porque está fora do Momento 6 | Tratamento provável |
| --- | --- | --- | --- | --- |
| executar a Fase 1 da issue #24 | duplicação das políticas continua até à refatoração | `app.retrieval.lexical`, `message_source_service`, diagnóstico | este momento só caracteriza | próximo trabalho, após aprovação deste momento |
| decidir a evolução intencional dos contratos/statuses | mudança pública acidental se não for declarada | schemas de retrieval/answering | este momento fixa, não redesenha | momento arquitetural posterior |

## Limitações remanescentes

Esta caracterização não demonstra que o comportamento atual seja correto.
Demonstra apenas qual é o comportamento do protótipo neste SHA e fornece testes
capazes de detetar alterações futuras nesse comportamento.

Em particular, não mede qualidade semântica, não chama o fornecedor real, não
prova ausência de alucinações, não introduz RLS e não implementa as políticas
futuras da issue #24.

## Comandos não executados

- gate de frontend — não aplicável, porque `frontend/**` não foi alterado;
- qualquer fase de produção da issue #24 — proibida neste momento;
- chamadas reais ao provider — proibidas; os testes correram sem credenciais e
  sem rede.

## Confirmações Git

| Ação | Estado |
| --- | --- |
| Commit | não |
| Push | não |
| Pull Request | não |
| Merge / rebase / squash / tag | não |
| Alteração direta da `main` | não |
| `git reset --hard` / `clean` / `stash` / `restore` | não |
| Migration nova ou alterada | não |
| Código de produção alterado no estado final | não |
| Base de desenvolvimento alterada | não — já estava em head; sem operações pendentes |
| Rede usada durante os testes | não |
| Documentos institucionais reais usados | não |
| Artefactos do Momento 5 alterados | não |
| Ficheiros fora do âmbito autorizado | não |

As linhas acima descrevem o estado **no momento em que a verificação foi
executada** e não são reescritas retroativamente. A integração posterior está
registada na secção seguinte.

## Integração e fecho

Verificação executada **antes da integração**, sobre a baseline
`6e2d09cfd3348fbc9fbe842a53953a767ecd3be4`. A implementação foi posteriormente
versionada no commit `c885ddf24f4f0ef27f451942d3b7ca52ab8000f1` e integrada na
`main` pelo merge humano do **Pull Request #35**, merge
`a87cd8b14c464953a5fb3114b62e3588d39ccb3b`, a 2026-08-10. O workflow
**Backend checks** do Pull Request concluiu com sucesso em `c885ddf`.

| Item | Valor |
| --- | --- |
| Pull Request | [#35](https://github.com/FredericoXX/Projeto-Final/pull/35) — `test/prototype-characterisation` → `main` |
| Commit da implementação | `c885ddf24f4f0ef27f451942d3b7ca52ab8000f1` |
| Merge na `main` | `a87cd8b14c464953a5fb3114b62e3588d39ccb3b` |
| Diff integrado | 6 ficheiros, 1628 linhas acrescentadas, 0 removidas |
| Código de produção alterado | não — nenhum ficheiro em `backend/app/`, `backend/alembic/`, `backend/scripts/`, `frontend/` ou `.github/` |
| Artefactos do Momento 5 | intactos |
| CI do Pull Request | **Backend checks: success** |

Documentação alinhada com o fecho, em trabalho documental subsequente:
[`moment-06.md`](../ai/moments/moment-06.md) passou a **Concluído** e
[`02-current-state.md`](../ai/02-current-state.md) passou a descrever o
snapshot `a87cd8b`.

Uma cautela deliberada, para que a leitura futura não a infira como garantia: o
teste que obriga `Evidence` e `RetrievalEvidenceRead` a declararem exatamente os
mesmos campos caracteriza o **acoplamento atual**, e não uma invariante
arquitetural. Quando um campo como `score_kind` for acrescentado, a decisão de
o tornar interno ou público tem de ser tomada conscientemente; alterar esse
teste nessa altura é evolução deliberada do contrato, não contorno de uma
verificação.

As cinco mutações dos testes de sensibilidade foram temporárias e revertidas,
pelo que não são verificáveis retroativamente pelo histórico Git — consequência
natural da técnica, e não uma omissão. O que é verificável é que o diff
integrado não as contém e que o CI ficou verde.

## Próximo passo

O próximo trabalho permitido é a **Fase 1 da issue #24**. Não iniciar
automaticamente.
