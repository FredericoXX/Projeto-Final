# Auditoria da preparação do assistente institucional

**Veredito: PARCIALMENTE CONFIRMADO.** Os gates aplicáveis passaram em execução nova, mas três requisitos não estão integralmente satisfeitos: revalidação perante revogação concorrente, filtro institucional do adaptador simulado e proveniência dos resultados de erro. O incremento precisa dessas correções antes de ser confirmado como concluído. Nenhuma correção foi aplicada.

## Estado efetivamente verificado

- Data: **2026-10-09**, contexto do utilizador Europe/Kiev.
- Repositório local: C:/dev/agentic-rag-assistant; origin: https://github.com/FredericoXX/Projeto-Final.git. A auditoria não consultou outros projetos nem o estado remoto.
- Branch: **feat/institutional-permissions-and-requests-preparation**.
- HEAD e base efetiva (merge-base com main): **ca482803676f6509db5f7c851ff7fbe9e10404a4**. Não há commits do incremento após essa base: a implementação auditada está na árvore de trabalho e no índice.
- Antes de criar este relatório: 71 caminhos versionados alterados/eliminados em relação a HEAD e 26 ficheiros não versionados. AdminRoute.tsx → PermissionRoute.tsx tem o rename no índice e alterações adicionais fora do índice.
- Manifesto SHA-256 dos caminhos e conteúdos do incremento: **1aad3acce1cc2d4b655dbae53f23930e8122b36d3d609bc23437c3ca23d6b02e**. O [ficheiro de evidências](2026-10-09-institutional-preparation-evidence.json) contém o estado Git completo e os hashes por ficheiro; identifica também os ficheiros novos que git diff não mostra.
- Python 3.12.10, Node 22.22.0, npm 11.4.2; ambiente Windows.

A especificação foi o prompt de preparação disponibilizado pelo utilizador, complementado pelos critérios do prompt de confirmação. O relatório do Claude Code foi tratado como uma declaração a verificar. Foram lidos a constituição, o estado atual, os quality gates e ambos os workflows. Não foi encontrado AGENTS.md aplicável na raiz, nos diretórios ascendentes inspecionados ou no projeto (pesquisa incluindo ficheiros ocultos, excluindo dependências e .git).

Não houve alterações a código, migrações, configurações ou expectativas de testes; não houve commit, push, merge ou deploy. A instalação de dependências e o build criaram os artefactos normais ignorados pelo Git. Os únicos novos artefactos de projeto criados pela auditoria são este relatório e o JSON de evidências.

## Falhas, por impacto

### F1 — Alta: operações em curso conservam autorização após revogação gravada

**Evidência:** [auth.py](../../backend/app/api/dependencies/auth.py), get_current_user/require_permission; [document_service.py](../../backend/app/services/document_service.py), create_document, linha 66; [external_identity_service.py](../../backend/app/services/external_identity_service.py), link_account, linha 60; [academic_request_service.py](../../backend/app/services/academic_request_service.py), _query, linha 75; [conversation_service.py](../../backend/app/services/conversation_service.py), update_conversation, linha 125.

A autenticação relê o papel e o estado no início de cada pedido, mas estes caminhos não voltam a validar a conta e a permissão na operação sensível. _query verifica o papel do objeto current_user recebido, sem recarregar a conta ativa. link_account confia na autorização anterior do admin. create_document e update_conversation não revalidam a conta antes de gravar.

Reproduções por HTTP numa base dedicada de auditoria:

| Interleaving após autenticação/autorização e antes do serviço original | Resultado observado | Pedido seguinte |
| --- | --- | --- |
| knowledge_manager despromovido para student com commit noutra sessão; POST /documents continua | **201**, documento criado | 403 |
| segundo admin despromovido para student com commit noutra sessão; PUT /users/{id}/external-identity continua | **200**, associação criada | 403 em /users |
| aluno desativado com commit noutra sessão; GET /academic-requests continua | **200**, três pedidos devolvidos | 401 |
| aluno desativado com commit noutra sessão; PATCH da própria conversa continua | **200**, título alterado | 401 |

São ensaios determinísticos da janela de concorrência: wrappers temporários em memória executaram uma transação independente entre a dependência de autorização e a função original, mantendo esta sem alterações. Não se trata de pedidos iniciados depois da revogação: estes são corretamente recusados. A falha é especificamente a ausência da revalidação concorrente exigida pelos prompts.

O contraste está em [message_service.py](../../backend/app/services/message_service.py), create_message, [conversation_answering_service.py](../../backend/app/services/conversation_answering_service.py), ask_in_conversation, e [human_handoff_service.py](../../backend/app/services/human_handoff_service.py), request_human_handoff: esses caminhos recarregam conta/instituição sob lock. Os testes novos de identidade obsoleta cobrem mensagens, mas não as quatro operações acima.

**Correção necessária, não aplicada:** revalidar estado, instituição e permissão persistidos junto da leitura/escrita sensível; serializar essa validação com alterações de conta quando necessário. A consulta institucional deverá também proteger a validade da associação e revalidar antes de entregar o resultado de uma futura chamada externa. Acrescentar testes das janelas demonstradas e rever os restantes endpoints privilegiados.

### F2 — Média: o adaptador simulado não aplica o filtro por instituição

**Evidência:** [mock.py](../../backend/app/institutional/providers/mock.py), query_academic_requests, linhas 85 e 95. A procura usa apenas identity.external_subject e SYNTHETIC_REQUESTS.get(subject, ()); identity.institution_id nunca participa na seleção. As constraints da associação local permitem legitimamente o mesmo external_subject em instituições diferentes.

**Reprodução:** foram criadas duas instituições e, em cada uma, um aluno associado administrativamente a SYNTH-STUDENT-0001. Ambos os GET /academic-requests devolveram 200 com exatamente os mesmos três pedidos: REQ-0001-A, REQ-0001-B e REQ-0001-C. Só a instituição da proveniência mudou.

O snapshot é sintético e global: este ensaio **não demonstra fuga de dados reais**. Demonstra que o filtro institucional pedido para o adaptador não está implementado, nem fica validado para futura substituição. O limite está reconhecido na secção 11 de institutional-access.md, mas não satisfaz a exigência de filtrar sempre por instituição e identidade autorizada.

O teste test_students_of_two_institutions_are_isolated usa sujeitos diferentes (0001 e 0002). Confirma o transporte da instituição ao adaptador, mas passa mesmo quando o adaptador a ignora. test_the_same_subject_may_exist_in_two_institutions só verifica a criação das associações.

**Correção necessária, não aplicada:** delimitar os snapshots pelo par instituição/identificador externo ou vincular cada instância de adaptador à instituição autorizada, rejeitando identidades exteriores a esse âmbito. Testar sujeitos iguais em instituições diferentes com conjuntos sintéticos distintos, incluindo consulta por identificador de pedido alheio.

### F3 — Média: proveniência incompleta nos resultados sem sucesso

**Evidência:** [academic_request.py](../../backend/app/schemas/academic_request.py), InstitutionalProvenanceRead, linha 35, admite apenas success e no_data; [academic_request_service.py](../../backend/app/services/academic_request_service.py), _query, lança InstitutionalAccessError antes de construir proveniência; [error_handlers.py](../../backend/app/core/error_handlers.py), institutional_access_error_handler, linha 94, devolve apenas detail.code e detail.message.

Os resultados access_denied (403), not_configured (503) e unavailable (502) foram executados diretamente pelo handler real. Nenhum transporta origem, instituição, momento ou campos utilizados. Os testes de endpoint da suite confirmam os códigos correspondentes, mas não exigem proveniência nos erros. Também o detalhe sem dados termina num 404 genérico.

A proveniência de sucesso e da lista vazia está correta. A lacuna refere-se à exigência do prompt de preparação, secção 5, de transportar proveniência e resultado do acesso no resultado da consulta. A afirmação do relatório de Claude de proveniência em cada resposta é mais abrangente do que o comportamento implementado.

**Correção necessária, não aplicada:** definir metadados mínimos seguros para os resultados de erro e ampliar o contrato respetivo, sem persistência indiscriminada nem exposição de identificadores alheios. Quando a fonte não foi consultada, assinalar isso e manter atualização/campos utilizados ausentes ou vazios. Preservar respostas indistinguíveis para pedido alheio e inexistente.

## Verificação requisito a requisito

“Confirmado” nesta tabela significa comportamento demonstrado nos testes indicados e/ou inspeção identificada; não substitui o veredito global. “Parcial” aponta a lacuna concreta.

| Requisito | Estado | Implementação e evidência | Verificação e lacuna |
| --- | --- | --- | --- |
| Base, branch e incremento completo | Confirmado | HEAD, merge-base, git status, diff HEAD e manifesto | Base ca482803; alterações no índice, fora dele e ficheiros novos incluídos |
| Matriz centralizada e backend como fronteira | Confirmado para pedidos sem corrida | core/permissions.py; api/dependencies/auth.py; schemas/user.py | test_matrix_covers_every_role_and_no_role_inherits_another; test_auth_me_exposes_the_permissions_of_the_persisted_role. F1 limita concorrência |
| student/user: conversas e recursos próprios | Confirmado para posse; parcial para desativação concorrente | conversation_service.py:63 e :94; academic_request_service.py:75 | test_no_role_reaches_another_accounts_conversation; test_user_role_may_also_consult_own_requests. F1 |
| admin sem documentos nem conversas alheias | Confirmado | routes/documents.py; conversation_service.py:63 | test_admin_cannot_manage_documents; test_admin_cannot_read_list_count_or_mutate_other_accounts_conversations; testes de /ask e /handoff ajustados |
| knowledge_manager documental, sem contas/instituição/dados alheios | Confirmado para permissões iniciais | permissions.py; routes/documents.py; services documentais | test_knowledge_manager_cannot_manage_accounts_or_institution; test_knowledge_manager_manages_documents_of_own_institution_only. F1 na revogação |
| staff, ausência de novos perfis/operador | Confirmado | Role e ROLE_PERMISSIONS; routers e frontend | staff sem permissões especiais; inexistência de fila/painel inspecionada; testes de posse |
| Criação de knowledge_manager por admin e preservação de contas | Confirmado | schemas/user.py; routes/users.py; migration d1a7c3e9b4f2 | test_admin_creates_a_knowledge_manager_account; test_knowledge_manager_role_migration_preserves_accounts_and_guards_downgrade |
| Leitura/listagem/contagem/mutações/mensagens/fontes | Confirmado para posse e citações; parcial para revogação | conversation_service.py; message_service.py; conversation_answering_service.py; message_source_service.py | Suites de conversas, answering, fontes e lifecycle aprovadas; F1 na renomeação |
| Alteração de papel/desativação/concor­rência | Parcial | get_current_user; locks nas mensagens, /ask e E1 | Testes de pedido seguinte e identidade obsoleta em mensagens aprovados; quatro reproduções adicionais falham, F1 |
| Associação administrativa sem prova por email nem escolha pelo aluno | Confirmado para pedidos sem corrida | external_identity_service.py; schemas/external_identity.py; models/user_external_identity.py; routes/users.py | test_non_admin_accounts_cannot_link_anyone_including_themselves; test_email_equality_never_creates_a_link; test_link_payload_rejects_extra_fields_and_blank_subjects. F1 para admin revogado |
| Integridade e isolamento das associações | Confirmado | FKs compostas e uniques em model/migration e filtro institution_id no serviço | test_admin_of_another_institution_sees_the_account_as_nonexistent; test_a_subject_cannot_be_linked_to_two_accounts; teste da migration |
| Contrato neutro e adaptador substituível | Confirmado | institutional/contracts.py e dependencies.py; serviço separado | test_service_is_independent_of_retrieval_and_generation; test_result_contract_rejects_incoherent_combinations. Contexto académico futuro documentado, sem inventar protocolo |
| Login local; nenhum SSO/API real inventado | Confirmado | routes/auth.py; institutional/; documentação | Inspeção: email/password local, apenas mock/disabled, sem adaptador ou credenciais universitárias |
| Desativada por omissão; mock apenas development/test; arranque sem API | Confirmado | core/config.py; institutional/dependencies.py; .env.example | test_integration_is_disabled_by_default; test_simulated_mode_is_refused_outside_development_and_test; test_disabled_integration_shows_no_simulated_data; importação e suite sem chave de LLM |
| Sem rede externa ou LLM na consulta | Confirmado | institutional/providers/mock.py; routes/academic_requests.py | test_simulated_query_makes_no_network_call_and_needs_no_llm; bloqueio explícito de rede/gerador/retriever nesse teste |
| Cinco resultados distintos, sem decisões automáticas | Confirmado | InstitutionalAccessOutcome; error_handlers.py; academic_request_service.py | Testes success/no_data/denial/unavailable/disabled e test_outcomes_are_distinct_from_decision_outcomes |
| Lista/detalhe, estado oficial, atualização e próximo passo da fonte | Confirmado no snapshot atual | academic_request_service.py; schemas/academic_request.py | test_detail_returns_own_request; test_official_status_is_kept_as_received_and_next_step_only_when_given |
| Identificadores manipulados e isolamento do adaptador | Parcial | Validação Path e filtro por subject no mock | test_another_students_request_is_indistinguishable_from_a_missing_one; test_malformed_request_identifiers_never_reach_the_provider; F2 para instituição |
| Interface PT/EN, vazio/erros e aviso de demonstração | Confirmado por testes de componentes | features/academicRequests/; i18n/pt.ts e en.ts; router.tsx; AppLayout.tsx | 16 testes em academicRequests.test.tsx, incluídos nos 112; navegação, autorização, lista, detalhe, vazio, erros e PT. Sem revisão visual em browser |
| Consulta iniciada pelo utilizador, sem notificações ou mutações académicas | Confirmado | Só GET nas rotas; hooks.ts:USER_INITIATED | Inspeção: sem polling/refetch por foco/reconexão/retry; sem notificações, webhooks, emails, SMS, push, criação/aprovação/cancelamento |
| Proveniência e dados tratados como dados | Parcial | contracts.py; _provenance; schemas e handler | test_linked_student_lists_only_own_requests_with_provenance; interface renderiza texto; F3 nos resultados de erro |
| Sem corpus/vetor/persistência indiscriminada/logs académicos | Confirmado no caminho novo | Serviço sem escrita; logs só tipo de exceção; docs/institutional-access.md §8 | test_query_persists_nothing_and_touches_no_document_index; test_provider_exception_becomes_unavailable_without_leaking_data; inspeção de imports e logs |
| Retrieval, contrato de geração e citações históricas preservados | Confirmado | Sem alteração de app/retrieval, app/answering ou message_source_service; serviços de preservação documental mantidos | Suite completa, incluindo answering, retrieval, referências e snapshots, aprovada |
| E1 funcional, apenas contacto apresentado | Confirmado | human_handoff_service.py; schemas/handoff.py; documentação | Suite test_human_handoff.py aprovada; posse, desativação, mensagem/snapshot do contacto; sem transferência externa |
| D0–D6/R01–R12 e PERSONAL_DATA_REQUIRED não inventados | Confirmado | decision/contracts.py sem alteração; docs/institutional-access.md §§9–10 | Pesquisa no código: sem D0/R01–R12 executáveis e sem mapeamento automático; ausência é limite esperado |
| Documentação e relatórios históricos | Confirmado com limites F1–F3 | README; docs/ai/02-current-state.md:93; docs/database.md; institutional-access.md; notas em A2.2/D4.1 | Secção de branch distingue snapshot histórico; notas aditivas não reescrevem resultados. Não afirmar confirmação completa até corrigir as lacunas |
| Migrações, head e reversão | Confirmado | d1a7c3e9b4f2 e e3b9f1c7a5d8; alembic/env.py; modelo correspondente | Upgrade/current/heads/check numa base descartável; head única; testes de preservação, downgrade guardado e upgrade/downgrade/upgrade aprovados |
| Testes existentes não enfraquecidos para esconder regressões | Confirmado por revisão do diff | Alterações em backend/tests e frontend/auth/routes.test.tsx | Troca do ator documental; inversão justificada do acesso admin; teste de migration fixado à revisão própria. Não identifiquei remoção injustificada de cobertura; faltam os casos F1–F3 |

## Comandos e resultados novos

A suite completa de backend foi executada uma única vez nesta auditoria, sem outra suite a usar a mesma base simultaneamente. Base dedicada: institutional_assistant_test, localhost:5433, distinta de institutional_assistant. A auditoria adicional usou institutional_assistant_audit_bb6cdbdb9ae7, criada e removida pelo ensaio. Os testes de migrations da suite usam ainda uma base descartável própria. Nenhuma migration desta auditoria foi aplicada à base de desenvolvimento ou produção.

| Comando/operação efetivamente executado | Resultado |
| --- | --- |
| git status --short; git branch --show-current; git rev-parse HEAD; git remote -v; git merge-base HEAD main | Estado e base acima |
| git diff --stat; git diff --cached --stat; git diff HEAD --name-only; git ls-files --others --exclude-standard | Incremento local completo identificado |
| git diff --check e git diff --cached --check | Aprovados; sem erros de whitespace; avisos Git de LF/CRLF em alguns ficheiros |
| docker compose config --quiet | Aprovado, exit 0 confirmado separadamente |
| python -m pip check | No broken requirements found |
| python -c 'from app.main import app; print(app.title)' | Agentic Institutional Assistant; integração disabled |
| ruff check . | All checks passed |
| mypy app tests scripts | Success: no issues found in 248 source files |
| python -m pytest -q | **2319 passed, 1 warning, 527.43s**, exit 0 |
| alembic.command.upgrade(cfg, 'head'); current(cfg); heads(cfg); check(cfg) | Equivalentes dos gates CLI, executados pela API oficial do Alembic no script isolado: head **e3b9f1c7a5d8**, No new upgrade operations detected |
| npm ci | Exit 0, 326 packages adicionados; instalação pelo lockfile |
| npm run lint | Aprovado |
| npm run typecheck | Aprovado |
| npm run test:run | **112 passed**, 11 ficheiros, 42.74s |
| npm run build | Aprovado; 124 módulos transformados |
| python audit_probes.py | Exit 0; resultados F1/F2 no JSON de evidências |
| Execução direta do institutional_access_error_handler para três outcomes | Resultados F3: 403/503/502, só detail.code e detail.message |

O warning do backend foi StarletteDeprecationWarning relativo ao uso de httpx no TestClient. npm ci reportou 7 vulnerabilidades (3 moderate, 4 high); package.json e package-lock.json não foram alterados pelo incremento. Esse aviso de dependências foi registado como saída da instalação, não como uma falha nova atribuída à implementação. Não foi executado npm audit fix.

Os executáveis Python/Ruff/Mypy vieram de .venv/Scripts. Para a suite foram definidos ENVIRONMENT=test, INSTITUTIONAL_DATA_PROVIDER=disabled e OPENAI_API_KEY vazia apenas no processo. No ensaio adicional, o bootstrap usou um token sintético apenas em memória. Não foram divulgados segredos da configuração local.

O arranque de processos dentro do sandbox falhou com acesso negado. Os comandos foram executados depois pela ferramenta com escalada aprovada. A leitura inicial e a escrita dos artefactos usaram Node fs; não houve rejeição de aprovação que deixasse verificações bloqueadas.

## Limites e reprodutibilidade

- A revisão da interface foi demonstrada por Vitest/Testing Library/MSW e por inspeção; não foi executado um teste end-to-end em browser contra a API real. O adaptador real não existe neste incremento.
- Os ensaios de corrida são interleavings determinísticos com duas sessões de base de dados; não constituem um teste de carga ou uma prova de todas as ordens possíveis de concorrência.
- As respostas de erro sem proveniência foram verificadas no handler real e confrontadas com código e testes HTTP da suite; o ensaio direto não acrescenta autenticação nem chamadas a uma fonte.
- O isolamento local das associações está demonstrado. F2 refere-se especificamente ao snapshot global do mock e não a dados pessoais reais.
- A auditoria avalia a árvore local, incluindo ficheiros novos. HEAD sozinho não representa esta implementação; usar o manifesto anexo ao reproduzir resultados.
- O script temporário usado foi C:/Users/cmgf1/AppData/Local/Temp/institutional-audit-twfQSG/audit_probes.py. Foi mantido para inspeção local, fora do código do projeto. O JSON preserva os resultados, sem tokens ou dados institucionais reais.

Para reproduzir F1, usar uma base descartável própria, manter get_current_user e require_permission reais, e interpor uma alteração com commit por uma segunda sessão imediatamente antes do serviço original. Restaurar a função no finally. Para F2, associar o mesmo sujeito sintético em duas instituições e comparar items nas respostas. Para F3, chamar institutional_access_error_handler com InstitutionalAccessError de cada outcome e inspecionar as chaves do JSON. Não usar a base partilhada da suite em execuções paralelas.

## Prontidão e próximos pré-requisitos

**Este incremento ainda não está pronto para confirmação plena.** Corrigir F1–F3, acrescentar testes que detetem essas lacunas e voltar a executar os gates no estado corrigido. Os gates aprovados nesta auditoria não eliminam falhas fora da cobertura existente.

Depois da confirmação da preparação, a próxima etapa continua a exigir:

1. Definições integrais e aprovadas de D0–D6 e R01–R12, incluindo condições, prioridades, valores, limiares, ordem e regra por omissão, distinguindo propostas de decisões aprovadas.
2. Decisão explícita sobre como os cinco resultados de acesso e a origem institutional_api entram no diagnóstico e influenciam a ação, sem deduzir PERSONAL_DATA_REQUIRED → ESCALATE.
3. Protocolo real de autenticação e API da instituição, identificador estável validado, contrato de dados e âmbito por instituição, para implementar SSO/adaptador real sem inventar detalhes.
4. Requisitos de persistência mínima, retenção, acesso e reprodutibilidade antes de auditar decisões reais com dados individuais; decisões institucionais sobre finalidade e tratamento ainda por definir, sem conclusão jurídica nesta auditoria.
5. Decisão separada sobre E2 quando exigido pela política. Fila, atribuição, resolução e notificações continuam fora deste incremento; a sua ausência não é uma falha da preparação.

A confirmação futura da preparação não equivale à conclusão do modelo de decisão nem da tese.
