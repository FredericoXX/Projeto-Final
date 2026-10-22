# Política de decisão v1.7 — integração experimental

> **Estado: incremento experimental implementado em desenvolvimento, não
> avaliado.** Branch `feat/decision-policy-v1-7-experimental`, criada a partir de
> `origin/main` em `d87ed34641141093f9aabf6ca7045f73411fe323` (merge do PR #66),
> em 2026-10-22, sem commit. A "matriz inicial" abaixo foi escrita antes de
> qualquer alteração de código e fica como registo; o estado efetivo está na
> "Matriz de conformidade final".

Especificação de trabalho: o prompt de alteração do artefacto segundo a
*Política de decisão de resposta e protocolo de rotulagem v1.7* (1 de outubro de
2026). O documento da política propriamente dito **não está no repositório nem
disponível a esta tarefa**. As definições usadas aqui são as que o prompt
explicita; o que o prompt nomeia sem definir fica assinalado como dependente do
documento (ver "Dependências do documento v1.7").

A política v1.7 é uma especificação de trabalho sujeita a calibração. Este
incremento implementa uma extensão **experimental**, utilizável em
desenvolvimento, desativada por omissão. Nada aqui declara aprovação da
orientadora, protocolo congelado, originalidade demonstrada ou resultados de
avaliação.

## Matriz de conformidade inicial

Legenda da coluna "Existente": o que o código de `d87ed34` já faz, verificado
por leitura do código e não dos comentários.

| ID | Requisito (v1.7) | Existente em `d87ed34` | Lacuna | Alteração planeada | Verificação planeada |
| --- | --- | --- | --- | --- | --- |
| V01 | Modo experimental selecionável, desativado por omissão; B0 preservado (answered→ANSWER, insufficient_evidence→ABSTAIN) | só B0 (`answering_service.ask`, `/ask`) | não existe modo de política | setting `DECISION_POLICY_MODE` (`disabled` por omissão) e endpoints próprios; `/ask` inalterado | testes de compatibilidade B0 e de modo desativado |
| V02 | Contratos tipados D0–D6, entradas dos estimadores, resultado, razão estruturada, catálogo, contexto | `app/decision/contracts.py`: 4 enumerações A2.1 | D0, D3, D5, D6, razão, resultado, contexto | `app/decision/dimensions.py`, reutilizando os valores serializados existentes | testes de contrato e de serialização |
| V03 | D0 = admissibilidade via `RetrievalEligibility` (C1–C11) + autorização por papel; sem fundir com `CitationPersistenceEligibility`, sem C5 na segunda | `app/documents/retrievability.py` C1–C11, consumido pelo retrieval e pelas fontes | sem autorização por papel | condição nova de autorização documental, nas duas políticas; C5 continua só na primeira | testes de composição e de proveniência N→N+1 |
| V04 | D1 in_scope/out_of_scope segundo o domínio configurado | `ScopeClass` sem consumidor | sem estimação | estimador D1; fora de âmbito termina sem recuperação | testes R01 e de não recuperação |
| V05 | D2 conjunto (vazio sem restrições) com `personal_data_required` e `administrative_action_required` | só `PERSONAL_DATA_REQUIRED` | falta ato administrativo | acrescentar `ADMINISTRATIVE_ACTION_REQUIRED` | testes de procedimento vs. ato/dado pessoal |
| V06 | D3 especificidade, leituras, materialidade, distinguibilidade, suporte admissível por leitura; geral ≠ ambíguo | não existe | dimensão inteira | contrato D3 e cobertura por leitura calculada só sobre evidência admissível | testes R06, cobertura desigual, D0 antes de D3 |
| V07 | D4 itens, suporte completo por item, ids, lacunas, total/parcial/nenhuma, parcial enganosa | `AnswerabilityClass` sem consumidor | decomposição e derivação | contrato D4 com derivação determinística da suficiência | testes R09–R12 |
| V08 | D5 conflito não resolúvel sobre o mesmo item e condições; sem hierarquia jurídica | não existe | dimensão inteira | contrato D5 validado (≥ 2 evidências admissíveis, mesmo item) | testes R07/R08 |
| V09 | D6 catálogo institucional versionado de serviços competentes; destino genérico não prova competência | `human_support_*` da instituição (destino genérico do E1) | catálogo inexistente | tabela versionada de catálogo, validação de contactos, resolução por tema | testes de catálogo e de destino ausente |
| V10 | Estimadores substituíveis, saída estruturada validada, doubles nos testes, adaptador real em dev, sem palavras-chave como juízo; falha não inventa valores | não existe | tudo | protocolo de estimadores, double determinístico, adaptador OpenAI isolado, roteiro sintético só em dev/test | testes de validação, de falha e de importação preguiçosa |
| V11 | Ordem de recolha ≠ precedência; D1/D2 terminam cedo; leituras e itens antes da recuperação; D0 antes de D3/D4/D5 | não existe | orquestração | `app/services/decision_service.py` | testes de fluxo |
| V12 | `DecisionPolicy` pura e determinística, primeira regra terminal, R01–R12, razão reconstruível | não existe | tudo | `app/decision/policy.py` | testes das doze regras, precedência, pureza |
| V13 | Gerador substantivo só em ANSWER; citações por item; R10 declara itens não suportados | gerador chamado sempre que há evidência | sem distinção de ações | ANSWER usa o gerador existente com validação por item | teste "gerador chamado só em ANSWER" |
| V14 | CLARIFY com 2–3 leituras em pergunta fechada; ABSTAIN/ESCALATE com modelos versionados; conflito cita ambas | só fallback e mensagem E1 | modelos novos | `app/decision/messages.py` versionado | testes de mensagem |
| V15 | ESCALATE: serviço, contacto, motivo, resumo; E1 como recomendação; origem automática distinta da pedida pelo utilizador | E1 por pedido do utilizador (`handoff_trigger=user_requested`) | encaminhamento automático | `handoff_trigger=policy_decision`, sem afirmar envio | testes de metadados e de texto |
| V16 | Diagnóstico temporal de evidência excluída; altera a mensagem, não a ação; ausência de resultados não autoriza inventar desatualização | não existe | tudo | consulta diagnóstica com C9/C10 relaxadas, sem conteúdo | testes de diagnóstico |
| V17 | Autorização documental por papel, separada do isolamento, versionada, aplicada no contexto, nas fontes e na persistência; sem expor existência | não existe; `documents.manage` só governa gestão | tudo | coluna `access_roles` (migração), condição na política, filtro na leitura das fontes | testes de dois papéis e de isolamento |
| V18 | `reference_date` injetado de forma coerente; data fixa em avaliação | `datetime.now` em dois pontos distintos (`answering_service` e `conversation_answering_service`) | incoerência possível na meia-noite | data única por pedido, propagada | testes de limites de validade |
| V19 | Contratos públicos do modo experimental com ação, regra, versão; auditoria detalhada protegida | — | tudo | schemas novos; tabela `decision_records` sem endpoint de leitura | testes de contrato e de proteção |
| V20 | Persistência dos turnos com locks, autorização, integridade e rechecagem de fontes | `conversation_answering_service` | turnos da política | reutilizar locks e `revalidate_and_lock_sources` | testes de persistência e de revogação |
| V21 | Interface: resposta/citações, opções de clarificação, motivo de abstenção, destino recomendado; continuação de clarificação revalidada | B0 e E1 | tudo | modo experimental na conversa; continuação por leitura | testes MSW |
| V22 | Registo: policy_version, regra, D0–D6 e origem, versões, evidências, diagnóstico, data, snapshot, run_id, tentativas, falhas, duração, custo; replay; sem raciocínio interno; falhas técnicas ≠ ABSTAIN | — | tudo | `decision_records` + replay | testes de replay e de falhas |
| V23 | Executor B0, B1-plena, B1-composição, P-oráculo, P-e2e, A-sem-filtro, A-sem-diagnóstico com packets pareados | avaliação offline do answering (A1–A8) e snapshots | tudo | `app/evaluation/policy_v1/` | testes de pareamento, gold, ablações |
| V24 | Três execuções numeradas; primeira é a principal; moda secundária; empate→primeira; tentativas/timeouts fixos | — | tudo | executor de runs | testes |
| V25 | M1–M9; intervalos para zero e para diferenças emparelhadas; limiares propostos configuráveis | — | tudo | métricas e intervalos | testes |
| V26 | Ferramenta de rotulagem P2 (check/oracle) com esquema dependente e acordo | `p2_labels_tool.py` indisponível | tudo | implementação equivalente documentada | testes |
| V27 | Receita de congelamento reproduzível com digests por artefacto | `canonical_json` sem `allow_nan=False` | receita v1.7 | `freeze.py` própria | testes de reprodutibilidade |
| V28 | P1 e D4.10/D4.10a preservados; P2 só para o novo conjunto | P1 e D4.10 versionados | — | nenhum ficheiro histórico alterado | `git diff` sobre os artefactos históricos |
| V29 | Documentação: estado atual, comentários obsoletos, relatório de integração | — | — | este relatório e `02-current-state.md` | revisão |

## Dependências do documento v1.7

O prompt usa códigos que não define e que não existem no repositório: as
métricas M3–M9 (para além da descrição temática), os cenários F02, F03, F14 e
F15, os princípios DP1–DP6 e a configuração de recuperação por leitura. Onde o
prompt descreve o conteúdo, a implementação segue a descrição e usa nomes
descritivos; a correspondência numérica fica marcada como **pendente de
verificação contra o documento**.

## Matriz de conformidade final

Estado em 2026-10-22, na branch `feat/decision-policy-v1-7-experimental`, a partir de `d87ed34`, **sem commit**.

Legenda:

- **Implementado**: existe em código operacional, tem testes e foi verificado.
- **Parcial**: existe, mas com um limite declarado.
- **Bloqueado**: depende de algo indisponível, que é nomeado.

| ID | Estado | Ficheiros principais | Testes que o demonstram |
| --- | --- | --- | --- |
| V01 modo experimental; B0 preservado | Implementado | `app/core/config.py` (`DECISION_POLICY_MODE`), `app/api/routes/decision.py` | `test_policy_mode_is_disabled_by_default`, `test_b0_ask_is_unchanged_when_the_policy_is_enabled`; a suite B0 existente passa sem alterações de expectativa |
| V02 contratos D0–D6, razão, resultado, contexto | Implementado | `app/decision/dimensions.py`, `app/decision/contracts.py` | `test_decision_policy.py`, `test_decision_contracts.py` |
| V03 D0 = `RetrievalEligibility` + C13; sem fusão com `CitationPersistenceEligibility`; C5 só na primeira | Implementado | `app/documents/retrievability.py` | `test_evidence_retrievability_unit.py` (composição), `test_document_role_authorization.py` |
| V04 D1 | Implementado (estimador) | `app/decision/estimators/` | `test_r01_out_of_scope_abstains_without_retrieval_or_generation` |
| V05 D2 com ato administrativo e dado pessoal | Implementado | `contracts.py`, `policy.py` | testes R02–R05, `test_administrative_action_precedes_personal_data` |
| V06 D3 | Implementado | `dimensions.py`, `pipeline.py` | testes R06, `test_unequal_coverage_does_not_clarify...`, `test_a_general_request_is_not_automatically_ambiguous` |
| V07 D4 | Implementado | `dimensions.py` (suficiência derivada) | R09–R12, `test_r11_misleading_partial_answer_is_not_answered` |
| V08 D5 | Implementado | `dimensions.py`, `policy.py` | testes R07/R08, `test_resolvable_conflict_is_not_a_conflict_for_the_policy`, conflito via API |
| V09 D6 catálogo versionado; destino genérico não prova competência | Implementado | `models/decision_catalog.py`, `services/decision_catalog_service.py`, `decision/catalog.py` | `test_constraints_escalate_only_to_a_catalog_service...`, testes de catálogo |
| V10 estimadores substituíveis, validados, sem keywords | Implementado; **qualidade não medida** | `decision/estimators/base.py`, `providers/openai.py`, `prompts.py`, `definitions.py` | `test_decision_estimators.py` (validação, falhas, tentativas, importação preguiçosa) |
| V11 ordem de recolha; D0 antes de D3/D4/D5 | Implementado | `services/decision_service.py` | `test_coverage_with_inadmissible_evidence_is_rejected...`, `test_invalid_estimator_reference_to_inadmissible_evidence_is_rejected`, R01 sem recuperação |
| V12 `DecisionPolicy` pura, R01–R12, razão reconstruível | Implementado | `decision/policy.py` | `test_decision_policy.py` (incluindo a pureza por AST e o replay) |
| V13 gerador só em ANSWER; citações por item; lacuna em R10 | Implementado | `decision/pipeline.py` | testes R09/R10, `test_answer_without_a_citation_for_an_item_is_a_technical_failure...`; o gerador não é chamado em R01, R02–R05 nem R06 |
| V14 mensagens versionadas; CLARIFY 2–3; conflito cita ambas | Implementado | `decision/messages.py` | testes de CLARIFY, conflito e procedimento |
| V15 ESCALATE como recomendação E1; origem automática | Implementado | `messages.py`, `decision_service._public_metadata` | `test_constraints_escalate_only...` ("não foi enviado", `handoff_trigger`) |
| V16 diagnóstico temporal | Implementado | `decision_service.gather_evidence`, `dimensions.only_outside_validity_found` | `test_expired_relevant_evidence_changes_the_message_but_not_the_action`, `test_no_results_never_invent_an_outdated_notice`, `test_no_temporal_notice_when_current_evidence_was_also_found`, `test_temporal_diagnostic_never_changes_the_action` |
| V17 autorização por papel | Implementado; **F14 não avaliado** | `models/document.py`, migração, `retrievability.py`, `message_source_service.py`, `retrieval_service.py`, frontend de documentos | `test_document_role_authorization.py`, `test_role_restricted_documents_never_reach...`, `test_sources_of_documents_later_restricted_are_withheld_on_read`, `test_uncited_admissible_evidence_must_still_be_authorized_at_persistence`, `test_temporal_notice_documents_must_still_be_authorized_at_persistence` |
| V18 `reference_date` coerente; limites | Implementado | `answering_service.py`, `conversation_answering_service.py`, `decision_service.py` | `test_one_reference_date_is_used_across_the_turn`, `test_validity_limits_are_inclusive_at_the_reference_date` |
| V19 contratos públicos e auditoria protegida | Implementado | `schemas/decision.py`, `models/decision_record.py` | `test_decision_record_is_protected_and_replays_to_the_same_decision` |
| V20 persistência com locks, revalidação e rechecagem | Implementado | `decision_service._persist_turn` | `test_revocation_during_estimation_persists_nothing` (401/409, sem locks durante a estimação) |
| V21 interface | Implementado | `frontend/src/features/conversations/DecisionDetails.tsx`, `ConversationPage.tsx`, `decisionSnapshot.ts` | `decision.test.tsx` (7 testes), `documents.test.tsx` (papéis) |
| V22 registo, replay, falhas ≠ ABSTAIN; utilização | Implementado; tentativas e tokens por estimador, gerador e modelo B1; custo monetário **não** calculado (sem tarifa) | `decision_records`, `scripts/replay_decision_record.py` | `test_estimator_failure_is_technical_and_never_an_abstention`, replay, `test_every_model_condition_records_attempts_and_tokens`, `test_openai_generator_reports_usage_without_exposing_it` |
| V23 sete condições sobre packets | Implementado; **não executado** | `app/evaluation/policy_v1/conditions.py`, `packets.py`, `executor.py`, `baseline_openai.py` | `test_policy_v1_evaluation.py` (pareamento, ausência de ouro, ablações confinadas, executor sobre a base de dados) |
| V24 três execuções; primária; moda; empate | Implementado | `runs.py` | `test_primary_is_the_first_run_and_ties_go_to_it` |
| V25 M1–M9 e intervalos | **Parcial**: M1 e M2 como definidos; M3–M8 provisórios pela ordem do prompt; **M9 por atribuir**; M7 a partir de juízos humanos; atribuição de erros por replay | `metrics.py`, `statistics.py`, `config.py` | `test_m1_and_m2_follow_their_definitions`, `test_policy_v1_evaluation_audit.py` (identificadores, M7, atribuição), testes de Wilson, Newcombe e κ |
| V26 ferramenta de rotulagem | Implementado (equivalente documentado) | `labels.py`, `scripts/p2_labels_tool.py`, `docs/evaluation/policy-v1/labels.schema.json` | testes de esquema dependente, `check`, troca A1/A2, `oracle` |
| V27 congelamento reproduzível e verificação formal (incluindo o catálogo D6) | Implementado | `freeze.py`, `artifacts.py`, `scripts/freeze_policy_v1_artifacts.py` | testes de bytes exatos, NaN, NFC e manifesto; `test_formal_freeze_verifies_every_artifact_commit_and_tree`, `test_changed_code_artifacts_no_longer_match_the_freeze`, `test_oracle_tool_requires_the_frozen_case_file` |
| V28 P1 e D4.10/D4.10a intactos; P2 só para o novo conjunto | Implementado | `docs/evaluation/policy-v1/` | `git diff origin/main` vazio sobre os artefactos históricos |
| V29 documentação | Implementado | `docs/decision-policy.md`, este relatório, `02-current-state.md`, notas de versão em `institutional-access.md` e `answering.md` | — |

## Componentes mantidos, adaptados e substituídos

- **Mantidos**:
  - autenticação, revalidação concorrente e isolamento institucional (PR #66);
  - ingestão, retrievers e gerador (`AnswerGenerator`);
  - validação de citações e rechecagem transacional das fontes;
  - E1 pedido pelo utilizador;
  - B0 (`/ask`);
  - `CitationPersistenceEligibility` sem C5.
- **Adaptados**:
  - `RetrievalEligibility` e `CitationPersistenceEligibility` ganham C13;
  - `RetrievalContext` passa a levar o papel;
  - `answering_service.ask` recebe a data de referência;
  - `revalidate_and_lock_sources` recebe o papel persistido;
  - a leitura das fontes verifica o acesso;
  - `contracts.py` ganha `administrative_action_required`.
- **Acrescentados** (nada foi substituído):
  - política, dimensões, estimadores, mensagens e catálogo;
  - o turno `/decide`;
  - `decision_records`;
  - a avaliação v1.

## Correspondência D0–D6 / R01–R12 / DP1–DP6

- **D0–D6 e R01–R12**: ver as secções 3 e 5 de
  [`../decision-policy.md`](../decision-policy.md) e a tabela em `policy.py`.
- **DP1–DP6**: não definidos no prompt nem no repositório. A correspondência
  com os princípios de desenho candidatos fica **pendente do documento v1.7**;
  nenhuma correspondência foi inventada.

## Verificações executadas (2026-10-23, depois da segunda auditoria)

| Verificação | Resultado |
| --- | --- |
| `docker compose config --quiet` | OK |
| `python -m pip check` | sem conflitos |
| import da aplicação | OK; não carrega o SDK nem `app.evaluation` |
| `ruff check .`; `ruff format --check` nos ficheiros novos | passa |
| `mypy app tests scripts` | **294** ficheiros sem erros |
| `pytest -q` | **2575 passed, 1 warning** (o `StarletteDeprecationWarning` pré-existente), depois das correções da segunda auditoria e dos quatro testes do executor (eram 2563 depois da primeira auditoria) |
| Alembic numa base PostgreSQL descartável, depois removida | head única `a8c4e2f6b1d9`; `upgrade head`, `current` e `check` sem diferenças; `downgrade c4f7ab19d3e5` e novo `upgrade head` |
| Frontend: `npm ci`, lint, typecheck, `test:run`, build | **120** testes em 12 ficheiros; tudo verde. O `npm audit` reporta 8 vulnerabilidades de tooling (3 moderadas, 5 altas), fora do âmbito; o lockfile não mudou |

**Instabilidade observada.** `tests/test_document_versions.py::test_concurrent_uploads_get_distinct_sequential_version_numbers`:

- falhou 3 vezes em no máximo ~70 execuções nesta branch, com `StoragePathError`
  em `LocalDocumentStorage.resolve_path`: uma na primeira suite completa, uma
  em 10 execuções isoladas e uma no ciclo usado para capturar o erro;
- passou nas 40 execuções seguintes e na suite final; em `origin/main` passou
  as 55 vezes em que foi executado;
- o armazenamento não tem alterações nesta branch;
- hipótese, não confirmada: `Path.resolve()` no Windows com diretórios criados
  em concorrência.

Fica registada como instabilidade ambiental por investigar, não como resolvida.

## Pendente e bloqueios concretos

1. **Documento v1.7**:
   - a confirmação de M3–M8 (provisórios) e a atribuição de M9;
   - os critérios da qualidade da mensagem (M7);
   - os cenários F02, F03, F14 e F15;
   - DP1–DP6;
   - a redação exata das definições.
2. **Estimadores reais**: o adaptador OpenAI nunca foi executado (sem
   autorização nem chave nesta tarefa). A qualidade de D1–D5 é desconhecida.
3. **Catálogo institucional real**: só existem catálogos sintéticos de teste.
   Os serviços e contactos da Uni-CV estão por configurar e validar.
4. **Autorizações aplicáveis**:
   - a configuração real de `access_roles`;
   - F14 exige um corpus sintético identificado ou autorizado.
5. **Anotação humana**: o conjunto P2 e os rótulos de A1, A2 e da adjudicação
   não existem; nenhum foi criado. Sem A2, só há piloto declarado.
6. **Avaliação formal**: não executada. O executor recusa-se sem corpus,
   adjudicação e protocolo congelados.
7. **Calibração**:
   - os limiares κ = 0,60, δ = 5 pp e divergência de 20 %, e a proposta de
     28/136 casos, continuam propostas;
   - a cobertura desigual (F15) é uma hipótese revisável.

"Implementado em dev" não significa "avaliado".

## Correções da auditoria de 2026-10-22

A auditoria independente classificou o incremento como **FAIL — substancialmente
correto, mas incompleto**, com sete lacunas. As reproduzíveis por teste (5 e 6)
foram reproduzidas antes de corrigidas: os testes novos falhavam com o código
anterior.

| Achado | Correção | Testes |
| --- | --- | --- |
| 1. M3–M9 não formalizados; M7 só `not_measured`; sem atribuição de erros | identificadores versionados em `config.METRIC_IDS`: M3–M8 **provisórios** pela ordem do prompt, **M9 por atribuir**; M7 a partir de juízos humanos identificados (`MessageRatingSet`); atribuição de erros por replay contrafactual da mesma política, com causas `single`, `multiple` ou `indeterminate` e inspeção humana pendente (`attribution.py`) | `test_policy_v1_evaluation_audit.py` (identificadores, M7, quatro casos de atribuição) |
| 2. snapshot sem papel | `build_evaluation_snapshot(..., requester_role)`; o papel e a versão de C13 entram na identidade **só quando há papel**, pelo que os snapshots históricos de P1 mantêm o `snapshot_id`; o executor passa o papel do caso | `test_snapshot_identity_includes_the_role_only_when_given`; os testes de snapshot existentes passam sem alteração |
| 3. congelamento formal contornável | política, esquema, prompts e configuração são gerados a partir do código e verificados de novo; `--formal` exige todos os artefactos, `code_commit` = `--commit` = `HEAD` e árvore limpa; o `oracle` verifica o ficheiro de casos e os artefactos do código; o script de congelamento recusa artefactos de código como ficheiros e uma árvore por limpar | `test_formal_freeze_verifies_every_artifact_commit_and_tree`, `test_changed_code_artifacts_no_longer_match_the_freeze` (4 artefactos), `test_code_artifacts_cannot_be_supplied_as_files`, `test_oracle_tool_requires_the_frozen_case_file` |
| 4. utilização das condições com modelo incompleta | `GeneratedAnswer.usage` (opcional, preenchido pelo adaptador OpenAI); B0, P-e2e, A-sem-diagnóstico e B1 registam tentativas e tokens, também nas falhas; o adaptador B1 deixa de descartar a utilização; o registo operacional separa estimador e gerador. O custo monetário continua `None`, por não haver tarifa configurada | `test_every_model_condition_records_attempts_and_tokens`, `test_openai_generator_reports_usage_without_exposing_it`, asserção no registo de `test_decision_record_is_protected...` |
| 5. C13 só nas fontes citadas | `_lock_relied_on_documents`: na persistência, depois do lock da instituição, todos os documentos das evidências admissíveis, citadas ou não, e do diagnóstico são relidos sob `FOR SHARE` com o papel persistido; um documento vedado ou eliminado dá 409 | `test_uncited_admissible_evidence_must_still_be_authorized_at_persistence`, `test_temporal_notice_documents_must_still_be_authorized_at_persistence` |
| 6. aviso temporal com evidência vigente | `only_outside_validity_found`: o aviso exige documentos excluídos **e** nenhuma evidência vigente a suportar, cobrir ou contradizer o pedido | `test_no_temporal_notice_when_current_evidence_was_also_found` |
| 7. DP1–DP6 | **não corrigível** sem o documento normativo ou uma decisão formal de dispensa; nenhuma correspondência foi inventada | — |

Expectativa alterada, com a justificação escrita no próprio teste:
`test_m1_and_m2_follow_their_definitions` afirmava `v1_7_id = None` para o
encaminhamento excessivo. Passou a afirmar o identificador provisório `M3` e que
M9 continua por atribuir.

## Correções da segunda auditoria (2026-10-23)

A segunda auditoria classificou o incremento como **conformidade parcial**:

- três achados fechados (snapshot por papel, C13 na persistência, aviso
  temporal);
- três parciais;
- DP1–DP6 aberto.

As duas lacunas bloqueantes foram reproduzidas por teste antes de corrigidas:
cinco testes de utilização falhavam com o código anterior, e o catálogo não
tinha forma canónica de congelamento.

| Achado | Correção | Testes |
| --- | --- | --- |
| Catálogo D6 da avaliação não congelado | o catálogo é um artefacto obrigatório (`REQUIRED_ARTIFACTS`), com snapshot canónico validado pelas regras da publicação (`catalog_bytes`); o executor formal verifica o congelamento **depois** de ler o catálogo ativo da base de dados e antes de qualquer caso; o P-oráculo, no executor e em `p2_labels_tool oracle`, verifica o catálogo | `test_the_catalog_is_a_required_frozen_artifact`, `test_formal_verification_rejects_a_catalog_different_from_the_frozen_one`, `test_oracle_tool_rejects_a_catalog_different_from_the_frozen_one`; no próprio executor, contra a base de teste e com o catálogo publicado pela API, `test_executor_refuses_an_active_catalog_different_from_the_frozen_one` (modo formal e P-oráculo fora dele: sai com `EXIT_NOT_FROZEN` sem correr casos) e o controlo positivo `test_executor_accepts_the_frozen_active_catalog_and_reaches_the_cases`. Desligar a verificação do catálogo no executor faz falhar três dos quatro casos destes dois testes, incluindo os dois de recusa |
| Utilização do gerador perdida nas falhas | `generate_with_usage` anexa a utilização à exceção: uma tentativa, ou zero se o gerador não estava configurado; numa saída rejeitada pela validação ficam os tokens devolvidos. O registo operacional (`_record_failure`) e P-e2e e B0 guardam essa utilização; antes do gerador, `generator` é `null` | `test_operational_failure_after_the_generator_records_its_attempt` (falha do fornecedor e output inválido), `test_operational_failure_before_the_generator_records_no_generator_attempt`, `test_p_e2e_failure_after_the_generator_records_its_attempt` |

Expectativas alteradas, com a justificação escrita nos próprios testes: os
testes que montavam um manifesto "completo" com sete artefactos passaram a
incluir o catálogo:

- `test_freeze_manifest_identifies_every_artifact`;
- `test_oracle_requires_identified_and_frozen_adjudication`;
- `test_formal_freeze_verifies_every_artifact_commit_and_tree`;
- `test_oracle_tool_requires_the_frozen_case_file`.

Na revisão seguinte, foram corrigidas três descrições que tinham ficado com a
lista antiga de artefactos:

- a docstring de `artifacts.py` passou de "sete" para "oito" artefactos;
- `freeze_policy_v1_artifacts.py` passou a incluir `catalog` entre os
  artefactos fornecidos como ficheiro;
- `run_policy_v1_evaluation.py` passou a incluir o catálogo no modo formal.

Continuam formalmente pendentes, sem invenção:

- M9 por atribuir, e M3–M8 provisórios;
- DP1–DP6.

Por isso, a conformidade integral não pode ser declarada.
