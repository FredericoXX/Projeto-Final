# Estado atual

**Observação:** 2026-08-19 · `main` em
`adb332bf8f1cf04d762efafacf2d7397337bc634` (merge do Pull Request #58) ·
repositório `FredericoXX/Projeto-Final`

Os factos abaixo descrevem a `main` em
`adb332bf8f1cf04d762efafacf2d7397337bc634`, merge do Pull Request #58 que
integrou a calibração e a avaliação held-out da admissão densa (D4.8.2).
Trabalho em curso noutras branches não é estado deste snapshot e, quando
referido, é identificado como tal.

**Exceção declarada:** a **fusão lexical + densa por RRF** (D4.9) vive na branch
`analysis/d4-9-hybrid-rrf` e ainda **não está na `main`**. O que é trabalho de
branch está identificado como tal em cada afirmação; ver
[Fusão lexical + densa por RRF](#fusão-lexical--densa-por-rrf-d49-branch).

A baseline experimental de dense retrieval (D4.8) **está na `main`** desde o
Pull Request #56, o repooling com a comparação definitiva (D4.8.1) desde o
Pull Request #57 e a admissão densa (D4.8.2) desde o Pull Request #58; as
ressalvas anteriores, que os descreviam como trabalho de branch, deixaram de ser
verdadeiras e foram removidas. O repooling dirigido e o
diagnóstico do ranking (D4.6) estão na `main` desde o Pull Request #54, e as
variantes de ponderação (D4.7) desde o Pull Request #55.

O Evaluation Snapshot **está na `main`** desde o Pull Request #48; a ressalva
anterior, que o descrevia como trabalho de branch, deixou de ser verdadeira e foi
removida. As contagens de execução da secção
[Testes e verificações](#testes-e-verificações) continuam a identificar
explicitamente sobre que conteúdo foram medidas.

O contrato de resultado do retrieval — `RetrievalResult`, trace obrigatório no
contrato e semântica explícita do score — está integrado desde o Pull Request
#43; ver
[Contrato de resultado do retrieval](#contrato-de-resultado-do-retrieval).

Snapshot factual. Não contém regras: os princípios estão em
[`01-project-constitution.md`](01-project-constitution.md), os critérios de
verificação em [`03-quality-gates.md`](03-quality-gates.md) e a manutenção
desta diretoria no [`README.md`](README.md). Se este documento divergir do
repositório, o repositório está certo e o documento está desatualizado.

## Momentos

Momentos 1 a 6 concluídos — [`moments/moment-05.md`](moments/moment-05.md) e
[`moments/moment-06.md`](moments/moment-06.md).

No Momento 5, as decisões de método (Fase 0)
foram aprovadas pelo merge humano do Pull Request #29 (`2b6247c`), e o corpus
sintético com a rubrica (Fase 1) pelo merge humano do **Pull Request #30**,
integrado na `main` em `7846f08`. O mecanismo de avaliação offline (Fase 2) foi
aprovado pelo merge humano do **Pull Request #31**, integrado na `main` em
`aa72fcd`, e a baseline (Fase 3) pelo merge humano do **Pull Request #32**,
integrado na `main` em `0ed640cb`. O fecho corretivo foi integrado pelo
**Pull Request #33**, merge `0069809ba3c4acd506990242af13edcb6bda57d4`, sem
alterar a baseline.

O **Momento 6** — caracterização do protótipo antes da evolução dos contratos —
foi aprovado pelo merge humano do **Pull Request #35**, commit da implementação
`c885ddf`, merge `a87cd8b14c464953a5fb3114b62e3588d39ccb3b`. É um momento
puramente aditivo: acrescentou testes de caracterização e documentação, **sem
alterar código de produção**. Satisfez a **Fase 0 da issue #24**, cujas Fases 1
a 4 foram integradas depois dele (ver
[Política de admissibilidade da evidência](#política-de-admissibilidade-da-evidência)).
O mapa oficial dos temas está no [`README.md`](README.md#momentos).

Depois do Momento 6, e fora da numeração dos momentos, foram integrados o
**Pull Request #41** (fecho documental da issue #24, merge `2b3c91e`), o
**Pull Request #42** (contratos provisórios de decisão, merge `e3f43f4`), o
**Pull Request #43** (contrato de resultado do retrieval, merge `d6dd75b`), o
**Pull Request #44** (fecho documental A3/A4.2 e caracterização A6.0, merge
`73fe8ef`), o **Pull Request #45** (carregamento tardio do provider, A6.1,
merge `6ae9bad`), o **Pull Request #46** (especificação científica da política
de decisão, A2.2, merge `42187e7c`), o **Pull Request #47** (encaminhamento
humano E1, A2.3a, merge `311d917`), o **Pull Request #48** (Evaluation
Snapshot, merge `6235b57`), o **Pull Request #49** (Pilot Corpus P1 e protocolo
de *ground truth*, D4.1, merge `d3055d7`), o **Pull Request #50** (baseline
lexical real sobre P1/S1, D4.2, merge `a88f4ae`) e o **Pull Request #51**
(experimento controlado da correspondência lexical, D4.3, merge `5514d8b`) e o
**Pull Request #52** (condição pareada com diacríticos, D4.4, merge `b42f9ed`) e
o **Pull Request #53** (orçamento de candidatos e ranking, D4.5, merge
`85c0055`), o **Pull Request #54** (repooling dirigido e diagnóstico do
ranking, D4.6, merge `1a62016`), o **Pull Request #55** (ablação e reponderação
do ranking lexical, D4.7, merge `47c1e9c`) e o **Pull Request #56** (baseline
experimental de dense retrieval, D4.8, merge `22b59fc`) — ver
[Trabalho arquitetural em aberto](#trabalho-arquitetural-em-aberto).

## Arquitetura

Monorepo com três peças:

- **`backend/`** — aplicação FastAPI (Python 3.12), executada localmente a
  partir do virtual environment;
- **`frontend/`** — interface web (React 18 + TypeScript + Vite), ver
  [`frontend/README.md`](../../frontend/README.md);
- **`docker-compose.yml`** — um único serviço, `database`
  (`pgvector/pgvector:pg17`). A API não corre em contentor nesta fase.

Os ficheiros originais dos documentos vivem no armazenamento local
(`storage/`, ignorado pelo Git); o PostgreSQL guarda metadados, texto extraído
e segmentos.

Módulos do backend, em [`backend/app/`](../../backend/app/):

| Diretoria | Responsabilidade |
| --- | --- |
| `api/routes/`, `api/dependencies/` | superfície HTTP, autenticação e autorização |
| `services/` | regras de negócio, transações e concorrência |
| `models/`, `schemas/` | entidades ORM e contratos de pedido/resposta |
| `storage/` | abstração de armazenamento (`Protocol` + implementação local) |
| `documents/` | domínio documental partilhado, incluindo a política canónica de admissibilidade da evidência e as composições `RetrievalEligibility` / `CitationPersistenceEligibility` |
| `decision/` | contratos provisórios de domínio da decisão agêntica (A2.1): tipos puros. `DecisionOutcome.ESCALATE` ganhou o seu primeiro consumidor com a A2.3a; os restantes continuam sem consumidores |
| `retrieval/` | contrato de resultado (`RetrievalResult`), planeamento de consulta, elegibilidade lexical, ranking, configuração FTS |
| `answering/` | contratos neutros, contexto, prompts, validação e adaptador de fornecedor |
| `evaluation/` | contratos e artefactos da avaliação offline do Momento 5 e a identidade reprodutível do contexto experimental (Evaluation Snapshot); não é importado pela aplicação |
| `diagnostics/` | ferramenta interna de observação do pipeline documental |
| `core/` | configuração, segurança, normalização de texto, idioma, erros |

`app/core/` inclui ainda `contact.py` (validação determinística de email/URL de
contacto) e `handoff_message.py` (mensagem determinística do encaminhamento
humano), ambos acrescentados pela A2.3a.

Em `app/evaluation/`, e fora do que `__init__.py` reexporta, vivem também
`results.py` (canonicalização e digest do Momento 5), `snapshot.py`,
`snapshot_builder.py`, `retrieval_metrics.py`, `lexical_variants.py`,
`ground_truth_identity.py`, `candidate_budget.py`, `repooling.py`,
`ranking_variants.py`, `dense_baseline.py` e `lexical_dense_comparison.py`. A
exclusão do `__init__.py` é deliberada: importar
`app.evaluation.assets` não pode carregar `sqlalchemy` nem as Settings, e essa
garantia está fixada por um teste em subprocesso.

`scripts/` contém `seed_demo_institution`, `rebuild_document_chunks`,
`diagnose_document_pipeline`, `evaluate_answering_offline` (avaliação offline
determinística), `build_moment05_baseline` (composição da baseline),
`evaluate_retrieval_baseline` (baseline lexical sobre um Pilot Corpus),
`evaluate_retrieval_experiment` (variantes de correspondência lexical),
`evaluate_diacritics_experiment` (condição pareada com diacríticos),
`evaluate_candidate_budget_experiment` (políticas de orçamento),
`diagnose_ranking_signals` (repooling e sinais de ranking),
`evaluate_ranking_variants` (ablação e reponderação do ranking),
`embed_pilot_corpus` e `evaluate_dense_baseline` (condição densa) e
`evaluate_lexical_dense_comparison` (comparação definitiva depois do repooling,
integrada pelo PR #57).

## Superfície da API

Endpoints sob `/api/v1`: `health`, `institutions`, `auth`, `users`,
`conversations`, `bootstrap`, `documents`, `retrieval`, `answering`, incluindo
`POST /conversations/{id}/handoff` (A2.3a).

Detalhe por área: [`README.md`](../../README.md) (bootstrap e autenticação),
[`docs/document-core.md`](../document-core.md) (documentos, versões, OCR,
chunking), [`docs/database.md`](../database.md) (esquema, recuperação, regras
de segurança), [`docs/answering.md`](../answering.md) (respostas e turnos
conversacionais), [`docs/diagnostics/README.md`](../diagnostics/README.md).

## Base de dados

15 migrations em [`backend/alembic/versions/`](../../backend/alembic/versions/),
head `a5c31f70b8d2` (`add_institution_human_support_contact`). Histórico completo
em [`docs/database.md`](../database.md).

A extensão `pgvector` está ativa como infraestrutura e não é usada pela
recuperação atual. A migration `c4f7ab19d3e5` acrescenta a tabela experimental
`chunk_embeddings`, com chave primária composta `(chunk_id, provider, model)`;
**nenhuma rota a lê** — ver
[Baseline experimental de dense retrieval](#baseline-experimental-de-dense-retrieval).

O isolamento institucional é aplicado por filtros nos services e por foreign
keys compostas que garantem integridade relacional. **Não existe Row-Level
Security**: uma consulta escrita sem filtro institucional não é bloqueada pela
base de dados.

## Abordagem técnica em vigor

Estado atual, reversível — pode mudar com a revisão da literatura e a avaliação
do protótipo:

- recuperação **lexical e determinística** sobre PostgreSQL Full-Text Search,
  com configuração por idioma, planeamento de variantes de consulta,
  elegibilidade separada de ranking e pesos versionados no código;
- **sem** embeddings, pesquisa vetorial, semântica ou híbrida, reranking por
  modelo, sinónimos ou LLM no retrieval;
- geração de respostas por um adaptador de fornecedor (atualmente OpenAI), com
  validação determinística e estrutural;
- **sem** memória conversacional no prompt, segundo LLM de validação,
  confidence score, idempotência ou feedback;
- encaminhamento humano **E1 solicitado pelo utilizador** (A2.3a):
  determinístico, sem retrieval e sem LLM. **Sem** escalação decidida pelo
  sistema, ticketing, fila ou operador — ver
  [Encaminhamento humano E1](#encaminhamento-humano-e1);
- processamento documental **síncrono**, sem filas nem workers;
- execução local, sem serviços externos no retrieval e sem rede nos testes.

Precisões factuais, verificadas neste snapshot:

- **Dependência do fornecedor.** O contrato `AnswerGenerator` é neutro e todo o
  conhecimento do SDK vive em `app/answering/providers/openai.py`. O pacote
  `openai` continua a ser uma dependência obrigatória de instalação, mas a A6.1
  deixou de o carregar no import dos contratos, do pacote `app.answering` ou da
  aplicação. A composition root importa o adapter apenas dentro do ramo
  `provider == "openai"`; resolver outro provider não carrega o SDK. Resolver
  OpenAI carrega o adapter, ainda sem construir cliente, usar chave ou chamar a
  rede. A ausência de chave ou modelo só produz efeito (503) quando a geração é
  necessária.
- **Processamento documental.** Depende atualmente do storage, de
  `storage_path` e de `mime_type` — a extração resolve o caminho no storage e
  seleciona o extrator pelo tipo de conteúdo. A independência face à origem
  aplica-se às camadas a jusante (chunking, retrieval, answering), que operam
  sobre texto e metadados persistidos.
- **Logs do answering.** Incluem `institution_id`, reason codes, contagens e
  outros metadados controlados. Não incluem a pergunta, a resposta, o contexto
  documental, prompts, respostas brutas do fornecedor nem credenciais. A
  formulação "apenas reason codes e contagens" seria inexata.

## Contrato de resultado do retrieval

Integrado pelo **Pull Request #43** (merge `d6dd75b`), sem alterar comportamento
público. `Retriever.search(...)` devolve um resultado estruturado em vez de uma
lista:

```
Retriever.search(db, query, context, top_k, official_only)
        │
        └── RetrievalResult
                ├── evidence         tuple[Evidence, ...] pela ordem do ranking
                ├── trace            RetrievalTrace (obrigatório)
                └── score_semantics  ScoreSemantics
```

- **`trace`** é obrigatório para qualquer implementação e transporta contagens
  neutras (`candidates_evaluated`, `result_count_before_limit`). O retriever
  lexical devolve a subclasse `LexicalRetrievalTrace`, com variantes de
  consulta, quotas, motivos de exclusão e componentes de ranking. O trace
  deixou de ser uma capacidade descoberta por introspeção: `search_with_trace`
  e o acesso por `getattr` no diagnóstico foram removidos, e o consumidor
  estreita o tipo por `isinstance`.
- **`score_semantics`** declara como interpretar `Evidence.score`: no retriever
  lexical, `ScoreKind.LEXICAL_RELEVANCE`, versão `lexical_composite_v1`, e
  `comparable_across_queries=False`. O score é **relevância lexical composta** —
  não é confidence, não é probabilidade, e não é semanticamente comparável entre
  consultas diferentes, porque a cobertura é a fração dos termos daquela
  pergunta.
- **`Evidence` não mudou** e os schemas e payloads HTTP também não: a semântica
  do score vive no resultado, não em cada evidência.

Não existe `RetrievalOutcome`: o resultado não classifica a suficiência da
evidência. Interpretar contagens ou motivos de exclusão seria decidir
answerability, que não pertence a esta camada.

`ScoreKind` tem um terceiro membro, `DENSE_SIMILARITY`, acrescentado pela D4.8.
Foi a única alteração a
`app/retrieval/base.py` e é **aditiva**: nenhum valor existente mudou de nome ou
de significado, e o retriever lexical continua a declarar
`LEXICAL_RELEVANCE`/`lexical_composite_v1`. O membro existe porque uma
similaridade vetorial e uma relevância lexical composta são quantidades de
famílias diferentes, e reutilizar o valor lexical tornaria a
incomparabilidade invisível — ver
[Baseline experimental de dense retrieval](#baseline-experimental-de-dense-retrieval).

## Encaminhamento humano E1

**Estado:** integrado na `main` pelo Pull Request #47 (A2.3a). Enquadramento
científico: **DSR3 — Design & Development**. É implementação, não avaliação: a
A2.3a **não** realiza DSR4 nem DSR5, e o encaminhamento **não foi avaliado
empiricamente**.

O que passou a existir, e o que continua a não existir:

| Existe | Não existe |
| --- | --- |
| `POST /api/v1/conversations/{id}/handoff`, sem payload | `DecisionPolicy`, `DefaultDecisionPolicy`, matriz de decisão, `policy_version` |
| `DecisionOutcome.ESCALATE` como desfecho operacional real | `AnswerabilityEvaluator`, `RequestSpecificity` |
| origem `user_requested` | origem `system_decision` — escalação decidida pelo sistema |
| um destino humano **default por instituição** (`institutions.human_support_*`) | tipologia de destinos, encaminhamento por assunto, múltiplos destinos |
| mensagem `assistant` determinística com snapshot do destino no `extra_metadata` | tabelas `escalations`, `turn_decisions`, `support_tickets`, filas |
| — | ticket, atribuição de operador, SLA, notificação interna, UI de operador (E2) |

A A2.3a implementa a **capacidade de escalar**, não a política que decide
quando escalar. A única decisão observada é "o utilizador pediu atendimento
humano", que é uma ação explícita e não uma inferência normativa: por isso não
depende das decisões O1–O7 da A2.2, que continuam em aberto e continuam a
bloquear a escalação decidida pelo sistema.

Propriedades fixadas por teste:

- **determinismo** — o handoff não chama o Retriever nem o AnswerGenerator, não
  carrega o SDK do fornecedor e não faz chamada externa. A rota não declara
  essas dependências e `human_handoff_service` não importa `app.retrieval` nem
  `app.answering`;
- **snapshot histórico** — alterar a configuração da instituição depois de um
  encaminhamento não reescreve a mensagem antiga, tal como em `MessageSource`;
- **isolamento** — conversa de outro tenant responde 404, e a verificação de
  acesso precede a validação do destino;
- **atomicidade** — destino não configurado ou conversa `closed`/`archived`
  respondem 409 sem persistir mensagem e sem alterar `conversation.updated_at`;
- **sem idempotência**, por decisão explícita: duas solicitações produzem duas
  mensagens. O duplo clique acidental é travado no frontend pelo estado
  `pending`.

O contrato de `/ask` **não mudou**: `AnsweringResponse.status` e
`ConversationAskResponse.status` continuam a declarar exatamente `answered` e
`insufficient_evidence`, e `answering_service.ask()` mantém o comportamento
`evidence == () → insufficient_evidence`. O handoff tem contrato próprio, o que
evita alterar prematuramente a API caracterizada no Momento 6.

Detalhe em [`docs/answering.md`](../answering.md) e
[`docs/database.md`](../database.md).

## Evaluation Snapshot

**Estado:** integrado na `main` pelo Pull Request #48 (merge `6235b57`).
Enquadramento: **DSR3 — Design & Development**; é infraestrutura **para**
DSR4/DSR5, e não realiza nem uma nem outra. O seu **primeiro uso sobre corpus
real** está descrito em [Pilot Corpus P1](#pilot-corpus-p1).

Dá identidade determinística ao contexto experimental de uma avaliação, para que
duas medições possam ser declaradas comparáveis em vez de presumidas. Sem isso,
"pergunta + resultado" não é reprodutível: se o corpus ou a configuração de
recuperação mudarem entretanto, o mesmo pedido produz outro resultado sem que
nada o assinale.

```
app/evaluation/snapshot.py          contratos + canonicalização + digest (puro)
app/evaluation/snapshot_builder.py  construção sobre a base, via RetrievalEligibility
```

Duas identidades com semântica distinta: `corpus_digest` identifica apenas o
corpus elegível; `snapshot_id` identifica a experiência — corpus, instituição,
data de referência e configuração de recuperação. A separação permite observar
"mesmo corpus, recuperação diferente" e o caso inverso.

Factos que importam não sobredeclarar:

- o corpus é **exatamente** o conjunto de `RetrievalEligibility`; nenhuma
  condição C1–C11 foi reescrita ou duplicada;
- a identidade dos segmentos usa hashes **recalculados em SQL** sobre `content`
  e `normalized_content` — este último é o texto efetivamente pesquisado, de que
  a coluna gerada `search_vector` deriva. Nenhum texto documental atravessa a
  fronteira da base;
- `app/retrieval/lexical.py` ganhou `LEXICAL_PIPELINE_VERSION`, constante pura
  que identifica planeamento, normalização, elegibilidade lexical, indexação e
  ranking. `SCORING_VERSION` cobre apenas os pesos do rerank, pelo que sozinha
  deixaria passar alterações materiais. **Não altera comportamento nem contrato
  público**;
- `reference_date` é parâmetro **obrigatório e explícito** e participa sempre no
  `snapshot_id`; não existe qualquer `date.today()` no builder;
- a canonicalização reutiliza `app.evaluation.results.canonical_json`, a
  serialização canónica única do projeto; `hash()` do Python nunca é usado;
- **nenhuma tabela e nenhuma migration** foram criadas — decisão explícita: não
  existe consumidor operacional, e o snapshot é um valor recalculável e
  serializável;
- **nenhum endpoint HTTP** foi criado;
- o score continua declarado como **relevância lexical**, nunca confiança.

Detalhe, incluindo o que entra e o que não entra na identidade e as limitações
declaradas, em
[`docs/relatorios/evaluation-snapshot.md`](../relatorios/evaluation-snapshot.md).

## Pilot Corpus P1

**Estado:** instanciação piloto **iniciada**. Primeiro corpus contextual real
processado e primeiro Evaluation Snapshot real produzido. Enquadramento:
**início de DSR4 — Demonstration**. DSR4 **não** está validada e DSR5 **não**
começou: não houve utilizadores, não houve medição e **nenhuma métrica de
recuperação foi calculada**.

Sete documentos públicos do repositório normativo oficial da Universidade de
Cabo Verde foram inventariados; **seis** entraram no corpus e um foi recusado
pela API por exceder o limite de upload configurado. A ingestão usou
exclusivamente os endpoints já existentes (`POST /documents`,
`POST /documents/{id}/versions`), num locatário dedicado ao piloto, para que o
corpus do snapshot seja exatamente P1 e não "os documentos que estão na base".

| Facto | Valor |
| --- | --- |
| Documentos no corpus | 6 (de 7 candidatos) |
| Versões processadas | 6, todas `processed` |
| Segmentos elegíveis | 1834 |
| Extração por OCR | 1 documento (PDF integralmente digitalizado) |
| `snapshot_id` de S1 | `a94f940229152a3b61860b370df8cb3ea8fe1a0e7236d65e86fe4b5118baf4c1` |
| `corpus_digest` de S1 | `e8a0f08b5ecf37821244e62c266a48b1d64c928cabb75e0e23e08f9c895a447e` |
| `reference_date` | `2026-08-15` |
| Reprodutibilidade | duas execuções sobre estado inalterado produziram artefactos **byte a byte idênticos** |

Factos que importa não sobredeclarar:

- **nenhum ficheiro institucional real está no repositório.** Os PDF, o texto
  extraído, os segmentos e o snapshot serializado vivem em `storage/`, ignorada
  pelo Git. São versionados apenas metadados públicos, em `docs/evaluation/`;
- **nenhum documento real entrou em testes.** A suite continua a usar corpus
  sintético; o Pilot Corpus é um artefacto de demonstração separado;
- **nenhuma alteração foi feita ao retrieval**, ao pipeline documental ou a
  qualquer código de produção;
- o *ground truth* criado é **de recuperação**, não de política: nenhuma anotação
  afirma `ANSWER`, `CLARIFY`, `ABSTAIN` ou `ESCALATE`, que continuam a depender
  de O1–O7;
- as 14 perguntas piloto são **construídas a partir de documentos públicos**, e
  não perguntas reais de estudantes;
- a anotação tem **um único anotador** (`SINGLE_ANNOTATOR_PILOT`), sem medida de
  concordância;
- `valid_from`/`valid_until` estão a `NULL` em todos os documentos, porque a
  convenção institucional de vigência é uma dependência Uni-CV com estado
  desconhecido. O corpus não tem, por isso, discriminação temporal.

A ingestão de documentos reais expôs um defeito não corrigido nesta fase,
**BUG-D4.1-01**: a extração nativa em modo `layout` acrescenta apenas espaços, e
a segmentação orça em coordenadas do texto bruto, pelo que o preenchimento
consome o orçamento do segmento — num dos documentos, 83,2 % dos caracteres são
espaços e a média de `normalized_content` cai para 65 caracteres. Está
classificado e reservado para Pull Request separado; se for corrigido, a
segmentação muda, o `corpus_digest` muda com ela e S1 deixa de ser o contexto
experimental em vigor — exigindo um novo snapshot. **Não** exige subir
`LEXICAL_PIPELINE_VERSION`, que cobre apenas etapas de `app/retrieval/` e não a
extração nem a segmentação.

Detalhe, incluindo critérios de inclusão e exclusão, proveniência, rubrica de
relevância, protocolo de anotação e as métricas preparadas mas não executadas,
em
[`docs/relatorios/d4-1-pilot-corpus-ground-truth.md`](../relatorios/d4-1-pilot-corpus-ground-truth.md).

## Baseline lexical sobre P1/S1

**Estado:** integrada na `main` pelo Pull Request #50 (merge `a88f4ae`). É a
primeira medição de recuperação sobre documentação institucional real.
Enquadramento: **avaliação técnica formativa** que alimenta DSR5; não é DSR5
concluída, porque não houve utilizadores e a amostra não sustenta inferência.

O que passou a existir: `app/evaluation/retrieval_metrics.py` (métricas puras —
Recall@k, MRR, nDCG@k — sem SQLAlchemy nem Settings, e **não** reexportado por
`__init__.py`) e `scripts/evaluate_retrieval_baseline.py`. **Nenhum endpoint
HTTP, nenhuma tabela, nenhuma migration**, e **nenhuma alteração ao retrieval, à
segmentação, à extração ou ao ground truth**.

Resultados macro sobre as 12 perguntas medidas de P1/S1:

| Métrica | Valor |
| --- | --- |
| Recall@1 / @3 / @5 | 0,2083 / 0,4167 / **0,4583** |
| MRR | 0,3750 |
| nDCG@1 / @3 / @5 | 0,2500 / 0,3323 / 0,3630 |

Factos que importa não sobredeclarar:

- **não é o desempenho do assistente na Uni-CV.** Corpus piloto de seis
  documentos, perguntas construídas, anotador único, julgamentos incompletos e
  BUG-D4.1-01 presente. É baseline **diagnóstica**;
- o snapshot é **condição de execução**: o runner reconstrói S1 e recusa medir se
  `snapshot_id` ou `corpus_digest` divergirem;
- a execução é **determinística** — `result_digest`
  `b00ca87b01f47a1aa618c775354940f8b4d9d45903c01ae999efd4e9a0cc7fb4`, idêntico
  entre execuções, calculado sobre o payload sem o carimbo temporal;
- **o modo de falha dominante não é ordenação.** Nenhum alvo foi devolvido em má
  posição: sete foram devolvidos, dois foram vistos e rejeitados pela
  elegibilidade lexical, cinco nunca chegaram a candidatos;
- **as seis falhas têm um único mecanismo**: a cobertura da elegibilidade compara
  **formas canónicas exatas** contra um limiar de 0,5, enquanto a geração de
  candidatos usa Full-Text Search **com *stemming***. Um segmento pode ser
  recuperado e depois rejeitado por a forma de superfície diferir —
  `residencia` contra `residencias`;
- **fragmentação de segmentos foi testada e refutada** como causa das falhas
  medidas. A afirmação paralela sobre privação do conjunto de candidatos
  **estava errada e foi corrigida pelo D4.3** — ver
  [Experimento da correspondência lexical](#experimento-da-correspondência-lexical);
- **o impacto de BUG-D4.1-01 na baseline é INCONCLUSIVO.** O defeito existe e é
  observável, mas nenhuma falha medida lhe é atribuível: no caso examinado, os
  segmentos caberiam no orçamento e, mesmo unidos, não passariam a
  elegibilidade;
- **nenhum distractor temporal anotado foi recuperado** — não por desambiguação,
  mas porque o sistema recupera pouco;
- **nenhuma decisão entre lexical e denso/híbrido foi tomada**, e nada nos
  resultados a autoriza enquanto duas das seis falhas forem divergências de
  flexão que normalização morfológica resolveria.

A medição expôs um segundo defeito, **BUG-D4.2-01** (MEDIUM), **não corrigido**:
o texto é normalizado sem acentos antes do Full-Text Search, e o *stemmer*
português depende do acento na regra `-ção` — `prorrogação` e `prorrogar`
conflaem, `prorrogacao` e `prorrogar` não. Corrigi-lo altera o comportamento do
retrieval e obrigaria a subir `LEXICAL_PIPELINE_VERSION`. O seu impacto **nesta
baseline** não está demonstrado: o segmento afetado foi recuperado apesar disso e
caiu depois na cobertura exata, que não usa *stemming*. O impacto do defeito foi
depois **confirmado experimentalmente** pela D4.4 — ver
[Condição pareada com diacríticos](#condição-pareada-com-diacríticos).

Detalhe, incluindo resultados por pergunta, destino de cada segmento-alvo e
análise de tipos de falha, em
[`docs/relatorios/d4-2-lexical-baseline-p1-s1.md`](../relatorios/d4-2-lexical-baseline-p1-s1.md);
artefacto da execução em
[`docs/evaluation/retrieval-baseline-p1-s1.json`](../evaluation/retrieval-baseline-p1-s1.json).

## Experimento da correspondência lexical

**Estado:** integrado na `main` pelo Pull Request #51 (merge `5514d8b`). É um
**experimento offline**, não uma alteração: compara três políticas de
correspondência × duas condições de conjunto de candidatos sobre o mesmo P1/S1,
sem tocar em `PostgresLexicalRetriever`, em `decide_eligibility`, no corpus nem
no *ground truth*.

O que passou a existir: `app/evaluation/lexical_variants.py` (projeção pura do
espaço de termos, **não** reexportada por `__init__.py`) e
`scripts/evaluate_retrieval_experiment.py`. **Nenhum endpoint HTTP, nenhuma
tabela, nenhuma migration, nenhuma alteração de produção.** A célula de controlo
reproduz a baseline do D4.2 e o comando recusa executar se não reproduzir.

O que os resultados mostram, e que importa não sobredeclarar:

- **sob as condições de produção, a normalização morfológica não resolve falha
  nenhuma.** Recall@5 e MRR ficam idênticos à baseline (0,4583 e 0,3750);
  ganham-se 0,012 de nDCG@5 e perde-se precisão no topo de uma pergunta;
- **uma única pergunta foi recuperada em todo o experimento**, e só combinando
  radicalização com a remoção da quota de candidatos — célula que fica abaixo da
  baseline em MRR e nDCG@5. É uma interação, não o efeito de uma das partes;
- **BUG-D4.2-01 ficou por testar nesta fase.** A variante que preserva acentos é
  **inavaliável** com o *ground truth* histórico: as perguntas foram escritas sem
  diacríticos (0 de 163 *tokens*), pelo que a projeção fica assimétrica e quebra
  correspondências que a baseline tinha. **Não é um defeito do artefacto** — o
  D4.1 declara as perguntas como construídas e a tipologia real como categoria B,
  UNKNOWN, pelo que nada demonstra que escrever sem acentos esteja errado. É uma
  propriedade do *ground truth*, e estudá-la exigiu uma **versão acentuada
  pareada**, não a reescrita do original — feita depois pela D4.4;
- **a previsão do D4.2 sobre Q008 não se confirmou nas condições medidas.** A
  pergunta não é recuperada em nenhuma das seis células. A D4.4 mostrou depois
  que a forma acentuada em falta só podia vir da **pergunta**, e que com ela a
  previsão se confirma;
- **a quota de candidatos é uma restrição real, mas em interação.** Dentro da
  política de correspondência atual o D4.2 estava certo — os alvos seriam
  rejeitados de qualquer forma; o que o D4.3 mostra é que a quota impede uma
  política alternativa de os alcançar. O orçamento global (25) reparte-se em
  quotas que **não são redistribuídas** quando as variantes conjuntivas devolvem
  zero: uma consulta com 240 correspondências ficou com quota 6;
- **retirar a quota, isoladamente, piora o resultado** (Recall@5 0,3750 contra
  0,4583), porque o ranking não aguenta o conjunto maior;
- **nenhuma célula supera a baseline em MRR**;
- **a pergunta sem evidência continua a devolver zero resultados** nas seis
  células, incluindo com um conjunto de candidatos 33 vezes maior — as variantes
  não são relaxamento disfarçado;
- **nenhuma variante foi adotada**, e **nenhuma decisão entre lexical e
  denso/híbrido foi tomada**.

Detalhe, incluindo métricas por célula, resultados por pergunta e a análise dos
distractores, em
[`docs/relatorios/d4-3-lexical-eligibility-experiment.md`](../relatorios/d4-3-lexical-eligibility-experiment.md);
artefacto da execução em
[`docs/evaluation/retrieval-experiment-p1-s1.json`](../evaluation/retrieval-experiment-p1-s1.json).

## Condição pareada com diacríticos

**Estado:** integrada na `main` pelo Pull Request #52 (merge `b42f9ed`). É um
**experimento offline** que isola uma variável — os diacríticos da pergunta —
sem tocar em produção, no corpus, no *ground truth* histórico nem nos artefactos
do D4.2/D4.3. **Nenhum ficheiro de produção foi modificado.**

O que passou a existir: `app/evaluation/ground_truth_identity.py` (digest do
*ground truth* e controlo de pareamento, puro, **não** reexportado por
`__init__.py`), `scripts/evaluate_diacritics_experiment.py` e um conjunto de
perguntas **novo**, `docs/evaluation/retrieval-ground-truth-p1-diacritics.json`.
**Nenhum endpoint HTTP, nenhuma tabela, nenhuma migration, nenhuma alteração de
produção.**

### Identidade do *ground truth*

O D4.3 registou que o `snapshot_id` **não** cobre o conjunto de perguntas.
Existe agora um `ground_truth_digest` determinístico, calculado com
`canonical_json` e SHA-256 — nunca com `hash()` do Python:

| Conjunto | Digest |
| --- | --- |
| Histórico | `1f05f49ae8f596175b6943734c3778d73280e6a2f89da7886db08434e6db8ea2` |
| Pareado | `8abe153628ea07207e8f7ddf9651a80d759d9006f9acb2542dedede83c34f51d` |

O âmbito é declarado (`measurement_relevant_fields`) e cobre exatamente o que a
medição lê: esquema, contrato, corpus, protocolo operativo e, por pergunta, id,
texto, idioma, exclusões e julgamentos. **Não é um hash do ficheiro** — prosa,
etiquetas de dificuldade e `temporal_scope` ficam de fora por não entrarem em
métrica nenhuma. `snapshot_id`, `corpus_digest` e `reference_date` também ficam
de fora, para **desacoplar** a identidade das perguntas do estado do corpus: o
mesmo conjunto conserva o seu digest quando S1 for substituído. `corpus_id`
entra, por ser rótulo estável da população e não estado.

### Resultados

Seis células — três políticas de correspondência × dois conjuntos de perguntas —
todas com a quota de candidatos de produção. As duas condições produzem a mesma
`tsquery` e **os mesmos 104 candidatos**, porque `normalize_text` remove acentos
antes da consulta; só a projeção do lado da pergunta difere.

| Célula | R@5 | MRR | nDCG@5 |
| --- | --- | --- | --- |
| A1 / A2 `exact_canonical` | 0,4583 | 0,3750 | 0,3630 |
| B1 / B2 `stem_normalized` | 0,4583 | 0,3750 | 0,3749 |
| C1 `stem_accented`, perguntas sem acentos | 0,2917 | 0,2500 | 0,2412 |
| **C2** `stem_accented`, perguntas acentuadas | **0,5417** | **0,4583** | **0,4582** |

Factos que importa não sobredeclarar:

- **BUG-D4.2-01 está CONFIRMADO.** Uma pergunta que nenhuma outra condição
  recupera — Q008 — é recuperada em posição 1, com o mecanismo verificado ao
  nível do termo: `stem(prorrogacao) = prorrogaca` quebra a regra `-ção` que
  `stem(prorrogação) = prorrog` satisfaz, e esta última conflui com
  `stem(prorrogar)`;
- **o efeito é específico, não geral.** `exact_canonical` e `stem_normalized`
  saem **idênticas** nas duas condições, como previsto antes de medir: não leem
  o texto acentuado. Sobre a melhor política sem acentos, C2 difere em
  **exatamente uma pergunta**;
- **C2 é a única célula, em D4.2/D4.3/D4.4, que supera a baseline de produção** —
  +0,0833 de Recall@5 e de MRR, +0,0952 de nDCG@5 — e fá-lo devolvendo **um**
  resultado adicional, que é o alvo: zero resultados não julgados novos, zero
  distractores novos;
- **a remoção de diacríticos erra nos dois sentidos.** C1 fica **abaixo** da
  baseline porque a assimetria destrói correspondências que a igualdade exata
  tinha (`antecedencia` → `antecedenc` deixa de casar com `antecedência` →
  `antecedent`);
- **a correção de produção não está determinada.** O experimento varia o lado da
  **pergunta**; produção recebe o que o utilizador escreve. Se o utilizador
  escrever sem acentos, nenhuma alteração ao lado documental recupera Q008. Qual
  das duas formas representa o utilizador real é dependência de **categoria B,
  UNKNOWN**;
- **o *ground truth* histórico não foi alterado**, e o pareado não o substitui:
  as 14 perguntas mantêm julgamentos, `temporal_scope` e exclusões, e a prova de
  pareamento é uma igualdade exata de cadeias após remoção de marcas
  combinantes. Nenhuma pergunta exigiu reformulação; três (Q010, Q011, Q013) não
  tinham acentos a restituir e servem de **controlos nulos**;
- **as cinco falhas semânticas continuam por resolver** (Q003, Q006, Q007, Q009,
  Q012) e **nenhuma variante foi adotada**. Nenhuma alteração ao caminho lexical
  as resolveu até à D4.7; a D4.8 mostrou que quatro delas são recuperadas por uma
  estratégia densa, e a D4.8.1 confirmou-o com os julgamentos completos — ver
  [Baseline experimental de dense retrieval](#baseline-experimental-de-dense-retrieval).

Detalhe, incluindo a prova de pareamento, o mecanismo de Q008 ao nível do termo e
as guardas de replicação do D4.2/D4.3, em
[`docs/relatorios/d4-4-diacritics-paired-experiment.md`](../relatorios/d4-4-diacritics-paired-experiment.md);
artefacto da execução em
[`docs/evaluation/retrieval-experiment-diacritics-p1-s1.json`](../evaluation/retrieval-experiment-diacritics-p1-s1.json).

## Orçamento de candidatos e ranking

**Estado:** integrado na `main` pelo Pull Request #53 (merge `85c0055`). É um
**experimento offline** que varia uma coisa — quantas linhas
cada variante de consulta pode devolver e quando o teto é aplicado — sem tocar em
`PostgresLexicalRetriever`, na elegibilidade, nos pesos do ranking, no limiar, no
corpus nem no *ground truth*.

O que passou a existir: `app/evaluation/candidate_budget.py` (políticas de
orçamento e classificação de destino, puro, **não** reexportado por
`__init__.py`) e `scripts/evaluate_candidate_budget_experiment.py`. **Nenhum
endpoint HTTP, nenhuma tabela, nenhuma migration, nenhuma alteração de
produção.** A célula de controlo reproduz a baseline do D4.2 e o comando recusa
executar se não reproduzir.

Três políticas sobre o orçamento global de 25 — `current_quota` (produção),
`redistribute_unused` (o **mesmo** teto, com a quota não usada a cair para as
variantes seguintes) e `global_limited_pool` (sem teto por variante, corte global
depois da recolha) — cruzadas com dois painéis de correspondência. O painel que
decide é `exact_canonical`; `stem_normalized` é diagnóstico.

Passou a ser possível dizer **onde** cada alvo parou. O D4.2 só via o *trace* e
classificava o caso ambíguo como `NOT_RETURNED_INDETERMINATE`; aqui o conjunto de
candidatos é conhecido por inteiro e a lista ordenada é guardada antes do corte,
o que acrescenta `RANKED_OUTSIDE_TOP_K` ao vocabulário e torna o destino uma
observação.

O artefacto guarda ainda, em `target_candidate_positions`, a posição de cada um
dos **16** segmentos de grau 2 na ordenação FTS sem teto — variante, posição,
total e quota aplicável. É evidência versionada, não uma sondagem avulsa: o
runner **recusa escrever** se essas posições não explicarem os destinos
observados.

| Condição (painel de produção) | R@5 | MRR | nDCG@5 | candidate recall |
| --- | --- | --- | --- | --- |
| `current_quota` | **0,4583** | **0,3750** | **0,3630** | 0,6250 |
| `redistribute_unused` | 0,3750 | 0,2569 | 0,2623 | **0,9167** |
| `global_limited_pool` | 0,3750 | 0,2569 | 0,2623 | **0,9167** |

Factos que importa não sobredeclarar:

- **a quota atual restringe mesmo o conjunto de candidatos.** Quinze dos
  dezasseis alvos estão nos **13 primeiros** resultados da sua consulta e a quota
  efetiva é 6 ou 8; redistribuir o orçamento não usado reduz os alvos nunca
  avaliados de **5 para 1** e sobe o `candidate_recall` 0,29;
- **mas o orçamento não é a alavanca.** Sob correspondência de produção, os
  quatro alvos recém-admitidos são **todos** rejeitados pela elegibilidade
  (`insufficient_coverage`). Zero recuperações;
- **e o ranking piora com um conjunto maior.** Dois alvos que estavam no top 5
  saem dele e outros três descem. Em Q011, quatro das cinco posições passam a ser
  ocupadas por um documento que o *ground truth* declara com
  `document_level_relevance` **0**. O saldo é −0,0833 de Recall@5 e −0,1181 de
  MRR;
- **Q009 confirma a interação prevista pelo D4.3**: com o orçamento
  redistribuído **e** correspondência por radical, o alvo passa de
  `NEVER_A_CANDIDATE` a `RETURNED` em posição 3. Precisa das duas alterações — e
  bastam 25 candidatos, sem remover o limite;
- **`global_limited_pool` não se justifica sobre `redistribute_unused`** neste
  corpus: resultado idêntico em todas as 14 perguntas, a **6 vezes** o custo de
  leitura (2105 linhas contra 350);
- **a pergunta sem evidência continua a devolver zero** nas seis condições,
  incluindo onde 261 linhas foram lidas — nenhuma política produziu evidência
  espúria;
- **são dois bloqueios distintos, e a fase não os funde.** Quatro alvos morrem na
  **elegibilidade** — o bloqueio já caracterizado pelo D4.3, que o orçamento não
  toca — e dois na **ordenação**. O que fica demonstrado é que *o ranking torna
  inseguro ampliar o orçamento e explica as regressões medidas*, **não** que seja
  o principal bloqueio de todas as falhas;
- **nenhuma política é recomendada para implementação**, e a consequência
  operacional é manter a quota como está: não por estar bem dimensionada, mas
  porque alargá-la sem corrigir a discriminação a jusante troca uma falha
  silenciosa por uma regressão medida.

Detalhe, incluindo a posição de cada alvo na ordenação FTS, o destino por
pergunta e a análise das regressões, em
[`docs/relatorios/d4-5-candidate-budget-ranking-experiment.md`](../relatorios/d4-5-candidate-budget-ranking-experiment.md);
artefacto da execução em
[`docs/evaluation/retrieval-experiment-candidate-budget-p1-s1.json`](../evaluation/retrieval-experiment-candidate-budget-p1-s1.json).

## Repooling dirigido e diagnóstico do ranking

**Estado:** integrado na `main` pelo Pull Request #54 (merge `1a62016`). É
**diagnóstico**, não afinação: nenhum peso, limiar, fórmula, orçamento,
elegibilidade ou retrieval de produção foi alterado.

O que passou a existir: `app/evaluation/repooling.py` (controlo do repooling,
puro, **não** reexportado por `__init__.py`),
`scripts/diagnose_ranking_signals.py` e um *ground truth* **novo**,
`docs/evaluation/retrieval-ground-truth-p1-repooled.json`. **Nenhum endpoint
HTTP, nenhuma tabela, nenhuma migration, nenhuma alteração de produção.**

### Repooling

O D4.5 mediu o ranking com 26 dos 33 resultados da condição ampliada por julgar.
Foram anotados os **34** pares por julgar da **união dos top 5 de todas as seis
células** do D4.5 — união, e não só a condição ampliada, para que a comparação
entre condições não fique assimétrica.

| | Valor |
| --- | --- |
| `ground_truth_digest` antes | `1f05f49ae8f596175b6943734c3778d73280e6a2f89da7886db08434e6db8ea2` |
| `ground_truth_digest` depois | `ada6b38886a06910e425e4be164099a3a63320050890253404064e3fde88586e` |
| Julgamentos novos | 34 — **27** grau 0, **6** grau 1, **1** grau 2 |
| Cobertura dos resultados devolvidos | 9/23 e 7/33 → **23/23 e 33/33** |

O conjunto histórico **não foi tocado**, e a regra é imposta por código:
**acrescentar julgamentos é legítimo, rever os existentes não é** — uma revisão
silenciosa tornaria a série D4.2–D4.5 incomparável sem que nada o assinalasse. Os
identificadores mantêm-se, ao contrário do conjunto pareado do D4.4: aqui as
perguntas são as mesmas letra a letra, e é o digest que distingue as versões.

Factos que importa não sobredeclarar:

- **o repooling mudou o quadro do D4.5.** Cerca de **84 %** da regressão de
  nDCG@5 medida naquela fase (−0,1007) era artefacto de resultados por julgar:
  sob anotação completa fica em **−0,0166**. A perda de Recall@5 (−0,0833) não se
  move e a de MRR quase não se move;
- **uma das quatro regressões não existia.** O único grau 2 novo — P1-DOC-002/57,
  a segunda publicação da lista de UCT no ano perguntado — estava em **posição 1
  em todas as seis células**. O que o D4.5 leu como "o alvo foi empurrado" era
  outra resposta correta à frente da primeira. Q004 passa a ter `RR = 1,00` nas
  duas condições;
- **os sinais atuais discriminam na maioria dos casos observáveis, mas não em
  todos**: 6 casos do tipo A (reponderáveis), 1 alvo do tipo B (dominado em todos
  os sinais, nas duas condições) e 16 do tipo C — o alvo não chega ao ranking, e
  isso pertence às etapas **anteriores** a ele: 10 por a elegibilidade os
  rejeitar e 6 por nunca serem candidatos, que é orçamento e não elegibilidade;
- **dois dos nove sinais estão a medir outra coisa.** `structure_table_row` exige
  `structure_type == "table_row"`, e esse tipo existe em **um** dos seis
  documentos do corpus: 56 segmentos no P1-DOC-002, **zero** nos restantes cinco,
  incluindo o documento OCR P1-DOC-003 que detém a evidência correta de Q011.
  Mede qualidade de extração e não pertinência. É a mesma família do
  BUG-D4.1-01, agora com efeito de ranking documentado. `section_overlap` premeia
  secções que contêm o ano por acidente de titulação;
- **são três modos de falha, não um**: densidade lexical (um cabeçalho vence o
  conteúdo dentro do mesmo documento), assimetria de extração entre documentos, e
  ausência de sinal;
- **nenhum peso foi alterado** e nenhuma alteração de ranking é recomendada nesta
  fase.

Detalhe, incluindo a decomposição sinal a sinal de cada comparação e o critério
de dominância, em
[`docs/relatorios/d4-6-ranking-diagnostics.md`](../relatorios/d4-6-ranking-diagnostics.md);
artefacto da execução em
[`docs/evaluation/ranking-diagnostics-p1-s1.json`](../evaluation/ranking-diagnostics-p1-s1.json).

## Variantes de ponderação do ranking

**Estado:** integrado na `main` pelo Pull Request #55 (merge `47c1e9c`). É um
**experimento offline**: nenhum peso, limiar, fórmula, sinal, orçamento ou
retrieval de produção foi alterado.

O que passou a existir: `app/evaluation/ranking_variants.py` (vetores de pesos e
score alternativo, puro, **não** reexportado por `__init__.py`) e
`scripts/evaluate_ranking_variants.py`. **Nenhum endpoint HTTP, nenhuma tabela,
nenhuma migration, nenhuma alteração de produção.** A célula de controlo
reproduz as células repooled da D4.6 e o comando recusa executar se não
reproduzir.

Sete vetores escritos à mão a partir de hipóteses nomeadas — três ablações
(`structure_table_row` removido e reduzido, `section_overlap` removido), três
reponderações (`title_overlap` reforçado, `proximity` reduzido, e a composição
das duas primeiras) e o controlo — cruzados com as duas políticas de orçamento.
**Sem otimização, sem pesquisa em grelha, sem pesos negativos.**

Factos que importa não sobredeclarar:

- **sob o orçamento de produção, nenhuma variante justifica adoção.** Cinco das
  seis são **bit a bit idênticas** à baseline; a sexta (`section_overlap`
  removido) move um alvo de grau 2 da posição 4 para a 3 numa pergunta, o que
  vale `+0,0035` de nDCG@5 e não toca em Recall@5 nem em MRR;
- **isto qualifica a D4.6.** Os modos de falha ali diagnosticados são em larga
  medida propriedades do **conjunto ampliado**, não do sistema em produção: sob a
  quota atual, o concorrente do ano errado que motivava a ablação estrutural em
  Q011 **nem sequer é candidato**;
- **os ganhos reais existem fora de produção.** Sob o orçamento ampliado, a
  composição «sem bónus estrutural + título reforçado» leva Q011 de R@5 0,50 a
  **1,00** e nDCG@5 de 0,387 a 0,850, sem regressões; e reduzir a proximidade a
  metade recupera Q001. Ambos dependem de uma política de orçamento que a D4.5
  recomendou **não** adotar;
- **reforçar o título sozinho não faz nada**, porque a renormalização financia
  esse reforço tirando peso à cobertura, que apontava no mesmo sentido. As duas
  alterações só compõem porque uma paga a outra;
- **o caso B da D4.6 continua insolúvel por reponderação**, como a aritmética da
  dominância exigia. Onde parece melhorar, o alvo entrou no top 5 por
  deslocamento de terceiros e continua abaixo do concorrente que o domina;
- **zero regressões** em qualquer variante, painel ou pergunta; e **zero**
  candidatos abaixo do limiar, o que confirma que as variantes só reordenam e
  nunca alteram quem é devolvido;
- **uma variante ficou marcada `REPOOLING_REQUIRED`** por promover ao top 5 um
  segmento não julgado. O *ground truth* **não** foi alterado nesta fase.

Detalhe, incluindo os vetores normalizados, os deltas por pergunta e a análise da
composição, em
[`docs/relatorios/d4-7-ranking-variants.md`](../relatorios/d4-7-ranking-variants.md);
artefacto da execução em
[`docs/evaluation/ranking-variants-p1-s1.json`](../evaluation/ranking-variants-p1-s1.json).

## Baseline experimental de dense retrieval

**Estado:** a **D4.8** está na `main` desde o Pull Request #56, o **repooling com
a comparação definitiva** (D4.8.1) desde o Pull Request #57 e a **calibração da
admissão densa** (D4.8.2) desde o Pull Request #58. A **fusão lexical + densa
por RRF** (D4.9) vive na branch `analysis/d4-9-hybrid-rrf` e **não está na
`main`**. Em todos os casos é um **experimento offline**: o
retrieval de produção não foi alterado e
`app.retrieval.dependencies.get_retriever` continua a devolver
`PostgresLexicalRetriever`, fixado por teste.

O que existe na `main` (D4.8): o pacote `app/embeddings/` (contratos neutros
`EmbeddingModel`/`EmbeddingIdentity`, factory com import tardio e adapter
OpenAI), `app/retrieval/dense.py` (`PostgresDenseRetriever`),
`app/evaluation/dense_baseline.py` (união, exclusivos e pedidos de repooling,
puro, **não** reexportado por `__init__.py`), `scripts/embed_pilot_corpus.py`,
`scripts/evaluate_dense_baseline.py`, a tabela `chunk_embeddings` (migration
`c4f7ab19d3e5`, aditiva, chave primária `(chunk_id, provider, model)`) e as
settings `EMBEDDING_PROVIDER` / `OPENAI_EMBEDDING_MODEL`; e, desde o Pull
Request #57 (D4.8.1), `app/evaluation/lexical_dense_comparison.py`,
`scripts/evaluate_lexical_dense_comparison.py`, a guarda
`verify_requests_satisfied` em `app/evaluation/repooling.py` e o *ground truth*
repooled; e, desde o Pull Request #58 (D4.8.2), `app/evaluation/dense_admission.py`,
`app/evaluation/dense_admission_vectors.py` e os quatro comandos da fase. O que a
branch acrescenta (D4.9) está descrito em
[Fusão lexical + densa por RRF](#fusão-lexical--densa-por-rrf-d49-branch).
**Nenhum endpoint HTTP, nenhuma alteração a `document_chunks`, ao
`search_vector`, ao ranking ou ao answering.**

Configuração medida: `text-embedding-3-small`, 1536 dimensões, cosseno, sem
normalização aplicada pela aplicação, sem índice ANN, sem limiar. O texto
embebido é `content` (forma original) e não `normalized_content`. A
admissibilidade documental vem inteira de `RetrievalEligibility`, aplicada no
PostgreSQL — similaridade vetorial nunca a contorna.

A identidade do índice — `provider`, `model`, `configuration_version` — é
guardada nas três colunas e **filtrada pelas três**, por uma definição única
(`ChunkEmbedding.matches_identity`) partilhada pela recuperação, pela cobertura e
pelo digest. Duas guardas recusam medir: **cobertura** (todo o segmento
admissível tem vetor dessa identidade) e **homogeneidade** (sem vetores de outra
configuração, sem vetores cujo conteúdo o chunk já não tem). Como a cobertura
filtra pela identidade completa, uma reindexação a meio já lhe aparece como
cobertura parcial; a homogeneidade acrescenta o **diagnóstico** nesse caso — «são
de outra configuração», e não «falta indexar» — e é a **única** a apanhar o vetor
obsoleto, que satisfaz a identidade e conta como coberto. O SHA do conteúdo é
recalculado do `content` atual, não comparado com o `content_sha256` persistido.

### O repooling (D4.8.1, integrado pelo PR #57)

Os 31 resultados que a D4.8 deixou por julgar — **todos de C1** — foram julgados.
O conjunto novo,
[`retrieval-ground-truth-p1-lexical-dense-repooled.json`](../evaluation/retrieval-ground-truth-p1-lexical-dense-repooled.json),
tem `ground_truth_digest` `bbaea746…1b1301` e estende o repooled da D4.6
(`ada6b388…88586e`) sem remover nem rever julgamento nenhum: **0 removidos, 0
revistos**, perguntas inalteradas letra a letra, `snapshot_id` e `corpus_digest`
iguais. Verificado por `verify_repooling` e por `verify_requests_satisfied`, que
prova que se julgou **exatamente** a lista de pedidos e mais nada.

Acrescentados: **26 de grau 0, 3 de grau 1, 2 de grau 2**. Os dois graus 2
(Q006/`004-60` e Q007/`007-152`) subiram o denominador do Recall dessas duas
perguntas de 1 para 2. A união dos dois top 5 passou a estar **inteiramente
julgada** (`COMPARABLE`).

### Resultados definitivos (D4.8.1, integrado pelo PR #57)

Doze perguntas medidas, macro-média. **Substituem as métricas provisórias de C1
na D4.8**; as de C0 não mudaram em nenhuma casa decimal, porque os 31
julgamentos eram todos de resultados que C0 nunca devolveu.

| Métrica | C0 lexical | C1 denso | Delta |
| --- | ---: | ---: | ---: |
| Recall@1 | 0,2500 | **0,5833** | +0,3333 |
| Recall@3 | 0,4167 | **0,8333** | +0,4167 |
| Recall@5 | 0,4583 | **0,8750** | +0,4167 |
| MRR | 0,4167 | **0,8194** | +0,4028 |
| nDCG@1 | 0,3333 | **0,7778** | +0,4444 |
| nDCG@3 | 0,3637 | **0,7677** | +0,4040 |
| nDCG@5 | 0,3867 | **0,7987** | +0,4120 |

Factos que importa não sobredeclarar:

- **os rankings são os da D4.8, posição a posição**, nas duas condições, e o
  `index_digest` é o mesmo (`451d9f2f…d9370c`, 1834 vetores). A única coisa que
  mudou foram os julgamentos, e o comando recusa executar se algum ranking
  divergir. C0 continua a reproduzir também o ranking do D4.2;
- **a complementaridade é quase toda numa direção.** Dos 19 alvos de grau 2, 8
  são recuperados por ambas, **8 só por C1** e **1 só por C0** (Q011/`003-37`);
  2 por nenhuma. Ao nível da pergunta: 5 são resolvidas só por C1, **nenhuma só
  por C0**, 6 por ambas e 1 por nenhuma. Dos 8 comuns, 6 estão em posições
  diferentes — isso é **diferença de ranking, não complementaridade**, e o
  artefacto conta as duas coisas em separado;
- **C0 não é dominado.** Em Q011 (desambiguação entre os dois calendários) C1
  enche quatro das cinco posições com o ano errado e cai de R@5 1,00 para 0,50;
  por nDCG@5, C0 é favorecida em Q005 e Q011;
- **C1 nunca devolve vazio, e isso é agora avaliável.** C1 devolveu 70 de 70
  resultados possíveis; C0 devolveu 23 e zero em seis perguntas. Na única
  pergunta sem evidência no corpus (Q013), C1 devolveu cinco segmentos, **todos
  julgados grau 0** — a abstenção de C0 estava certa e os cinco são falsos
  positivos. Nas outras cinco abstenções, C0 estava **errada**: existia
  evidência, e em quatro delas C1 encontrou-a. A capacidade de recusar é
  constitucionalmente necessária; o seu exercício concreto neste corpus acertou
  **uma vez em seis**;
- **C1 compra recall com precisão por resultado devolvido**: 43 dos seus 70
  resultados são grau 0 (61,4 %), contra 12 dos 23 de C0 (52,2 %); em graus 2,
  16 contra 9. Nenhum limiar denso foi criado, e a ausência de limiar continua
  fixada por teste;
- **a experiência é reprodutível, e o artefacto tem dois digests para o poder
  ser.** Três execuções deram rankings, graus, métricas e `result_digest`
  (`b708a70e…7a003`) **idênticos**, e **5 das 70 similaridades de C1
  diferentes**, com desvio máximo de 1,78 × 10⁻³ — a mesma não-determinação do
  fornecedor que a D4.8 mediu ao reembeber o índice, aqui no *embedding da
  pergunta*. O `result_digest` é o **canónico** e descreve o **resultado**
  (âmbito `provider_independent_fields`: sem a similaridade bruta de C1, com o
  score de C0, as posições, os graus e todas as métricas); o `execution_digest`
  (âmbito `full_payload`) cobre o *payload* como foi escrito e **muda** com a
  deriva, que fica assim preservada e visível em vez de arredondada para fora.
  Com dois digests, o artefacto não é verificável pela guarda genérica de digest
  único: quem o consumir usa `artefact_digests`;
- **Q014 continua excluída** das métricas por ambiguidade temporal. Nenhuma
  interpretação foi inventada, e os dois julgamentos de grau 2 incompatíveis
  continuam ambos no conjunto;
- **o BUG-D4.2-01 não foi corrigido.** Q008 é recuperada por C1 na posição 1
  porque a estratégia densa não passa pelo *stemmer* — o defeito do caminho
  lexical continua lá;
- **nenhuma arquitetura híbrida foi implementada**, e a recomendação mudou. A
  D4.8 concluiu que a complementaridade justificava experimentar um híbrido
  (D4.9); com os julgamentos completos, a D4.8.1 concluiu **D** — C1 aumenta o
  recall de forma inequívoca mas não tem critério de admissibilidade, e uma
  fusão sobre uma condição que devolve sempre `top_k` herdaria essa
  incapacidade. O próximo passo recomendado passou a ser um **estudo de
  admissibilidade/limiar denso**, antes do híbrido — feito pela D4.8.2. A fusão
  em si foi medida depois, pela D4.9, e confirmou a previsão: C2 herda de C1 a
  incapacidade de se abster (ver
  [Fusão lexical + densa por RRF](#fusão-lexical--densa-por-rrf-d49-branch)).

Detalhe da fase que está na `main` em
[`docs/relatorios/d4-8-dense-baseline-p1-s1.md`](../relatorios/d4-8-dense-baseline-p1-s1.md),
incluindo a secção «Correções posteriores» que regista o que a D4.8.1
substituiu; o repooling, a comparação definitiva e a decisão em
[`docs/relatorios/d4-8-1-lexical-dense-repooling.md`](../relatorios/d4-8-1-lexical-dense-repooling.md).
Artefactos em
[`docs/evaluation/dense-baseline-p1-s1.json`](../evaluation/dense-baseline-p1-s1.json),
[`docs/evaluation/dense-repooling-requests-p1-s1.json`](../evaluation/dense-repooling-requests-p1-s1.json),
[`docs/evaluation/retrieval-ground-truth-p1-lexical-dense-repooled.json`](../evaluation/retrieval-ground-truth-p1-lexical-dense-repooled.json)
e
[`docs/evaluation/lexical-dense-comparison-p1-s1.json`](../evaluation/lexical-dense-comparison-p1-s1.json).

## Admissão e abstenção da condição densa (D4.8.2, integrada pelo PR #58)

**Estado:** na `main` desde o Pull Request #58. Experimento offline: a política
existe como artefacto medido e **não** como comportamento do sistema. O
retrieval de produção e o *answering* não foram alterados.

A D4.8.1 recomendou um estudo de admissibilidade antes do híbrido. Esta fase
fê-lo, e não como procura do melhor limiar: pergunta se uma regra escolhida
**apenas em DEV**, sob critério pré-registado, se transporta para cenários
independentes.

O que o PR #58 integrou: `app/evaluation/dense_admission.py` e
`app/evaluation/dense_admission_vectors.py` (puros, **não** reexportados por
`__init__.py`), `scripts/freeze_dense_admission_vectors.py`,
`scripts/seal_dense_admission_split.py`, `scripts/calibrate_dense_admission.py`,
`scripts/evaluate_dense_admission_heldout.py` e sete artefactos versionados em
`docs/evaluation/dense-admission-*.json`.

Desenho, resumido:

- **conjunto novo e complementar** — 30 cenários, 49 perguntas (25 respondíveis,
  24 sem evidência no corpus), 258 julgamentos na rubrica de três graus. O
  conjunto da D4.8.1 e o seu *ground truth* **não foram tocados**;
- **cada NO_EVIDENCE validado contra o corpus completo** por busca normalizada
  (o OCR espaçado torna o `grep` literal incapaz de provar ausência) e leitura.
  A validação reclassificou **três** candidatos como respondíveis;
- **split por cenário**, determinístico e sem gerador aleatório — DEV 16
  cenários / 27 perguntas, HELD-OUT 14 / 22;
- **barreira de leakage operacional**: a calibração lê um ficheiro que não
  contém uma única pergunta, rótulo ou cenário selado; não tem argumento para o
  dataset completo; e a sua porta de entrada levanta `LeakageError` se lhe
  apontarem o dataset. Cinco testes fixam-no, um deles lendo o ficheiro DEV como
  texto;
- **vetores de pergunta congelados** com identidade completa, `content_sha256` e
  `vector_digest`, servidos por um `EmbeddingModel` que recusa texto
  desconhecido — o que torna as decisões reprodutíveis apesar da deriva do
  fornecedor;
- **protocolo pré-registado** com 21 políticas candidatas, orçamento de
  abstenção falsa de 0,20, métrica primária e desempate fixados antes de
  qualquer medição.

Resultado: a calibração selecionou `R1, min_top1 = 0,60` (as 15 variantes com
margem `top1 - top2` foram todas excluídas pelo orçamento). No HELD-OUT a
política reteve **0,84** do benefício medido em DEV — abstenção correta 0,60
contra 0,71 — com abstenção falsa de 0,083, dentro do orçamento: **decisão A, a
política generalizou**. Risco de responder sem evidência caiu de 0,45 para 0,27
e o ruído de 3,36 para 2,80 segmentos irrelevantes por pergunta admitida, ao
preço de uma pergunta respondível em doze — que no HELD-OUT custou evidência
real.

Duas ressalvas que o relatório desenvolve: **a similaridade não é confiança** —
`comparable_across_queries` continua `False` — e 0,60 é uma propriedade desta
distribuição de perguntas contra este índice, não um limiar transportável. O
modo de falha que a política **não** cobre é a pergunta cuja resposta existe no
corpus para outro ano: produz as similaridades mais altas de todo o conjunto.

Detalhe em
[`docs/relatorios/d4-8-2-dense-admission.md`](../relatorios/d4-8-2-dense-admission.md).

## Fusão lexical + densa por RRF (D4.9, branch)

**Estado:** trabalho de branch (`analysis/d4-9-hybrid-rrf`), **não está na
`main`**. Experimento offline de fusão de rankings. Não existe
`PostgresHybridRetriever`, não há endpoint, e
`app.retrieval.dependencies.get_retriever` continua a devolver
`PostgresLexicalRetriever`, fixado por teste.

A fase **não executa retrieval**: consome os rankings já versionados pela D4.8.1
e reordena-os. Não precisa de base de dados, do fornecedor de embeddings nem de
rede, e há teste em subprocesso que o confirma.

O que a branch acrescenta: `app/evaluation/hybrid_rrf.py` (puro, **não**
reexportado por `__init__.py`), `scripts/evaluate_hybrid_rrf.py` e o artefacto
[`docs/evaluation/hybrid-rrf-p1-s1.json`](../evaluation/hybrid-rrf-p1-s1.json).

Configuração: Reciprocal Rank Fusion com `k_rrf = 60` — o valor usado no artigo
que introduziu o método, Cormack, Clarke & Buettcher (2009), onde é descrito
como fixado durante uma investigação piloto noutro corpus, e não como valor
derivado — `source_depth = 5`, `final_top_k = 5`, soma em aritmética racional
exata, e desempate declarado sem preferência por condição. **Não houve grid
search de `k_rrf`.**

A fusão trabalha sobre **posições**, não sobre scores: `reciprocal_rank_fusion`
recebe sequências de identidades e o score é descartado antes da fronteira do
módulo. Somar `lexical_composite_v1` com similaridade do cosseno produziria um
número sem unidade — as duas grandezas declaram `comparable_across_queries`
`False`. Um segmento ausente de uma condição soma **um termo só**: não recebe
rank sintético, porque um retriever que não devolveu um segmento não se
pronunciou sobre ele.

Resultado sobre as 12 perguntas medidas, macro-média:

| Métrica | C0 | C1 | C2 | C2 − C1 |
| --- | --- | --- | --- | --- |
| Recall@5 | 0,4583 | 0,8750 | 0,9167 | +0,0417 |
| MRR | 0,4167 | 0,8194 | 0,8750 | +0,0556 |
| nDCG@5 | 0,3867 | 0,7987 | 0,8251 | +0,0264 |

Nenhuma métrica desce e nenhuma pergunta resolvida por C1 se perde. C2 preserva
o único alvo de grau 2 exclusivo de C0 e os oito exclusivos de C1.

A leitura honesta do agregado é a sua estrutura: em **cinco** das doze perguntas
C0 devolve zero resultados e a fusão é a identidade; das sete restantes, quatro
mudaram — Q011 (+0,533 de nDCG@5) e Q005 (+0,220) contra Q001 (−0,118) e Q003
(−0,317). O ganho agregado é a soma desses quatro.

Q003 é o caso a reter sobre o **método**: C0 devolveu um único resultado, de
grau 0, que por estar em primeiro lugar do seu ranking soma exatamente o mesmo
termo que o alvo de grau 2 que C1 tinha em primeiro. O RRF é indiferente à
espessura do ranking, e o desempate — arbitrário, mas fixado antes de medir —
resolveu o empate a favor do distrator.

Q013 mostra que fundir **não** resolve abster-se: C0 devolve zero, C1 devolve
cinco irrelevâncias, C2 devolve as mesmas cinco. A política `top1 >= 0,60` da
D4.8.2 **não** foi aplicada — fundir e admitir são dois mecanismos, e alterá-los
na mesma experiência tornaria o resultado inatribuível.

Decisão: **A — HYBRID_SUPPORTED**, que nesta amostra significa «justifica
investigar mais», não «está provado». Não autoriza promoção para produção.

Uma ressalva que distingue esta fase da D4.8.2: o critério de decisão foi
**declarado na implementação e registado como fixado antes da execução**, mas
não é pré-registo auditável — a regra e o resultado vivem na mesma árvore de
trabalho e nenhum commit os separa, pelo que o histórico não prova a ordem
temporal. A D4.8.2 tinha essa garantia, com o protocolo selado por
`protocol_digest` antes da calibração; a D4.9 não a repetiu. A margem é
apertada (ganho 0,0264 contra um limiar de 0,02), e o artefacto transporta a
reserva em `decision_rule.pre_registration_caveat`.

Detalhe em
[`docs/relatorios/d4-9-hybrid-rrf-p1-s1.md`](../relatorios/d4-9-hybrid-rrf-p1-s1.md).

## Testes e verificações

Os testes do backend usam PostgreSQL real numa base dedicada; os do frontend
usam MSW, sem rede nem backend.

Contagem de execução medida em **2026-08-19**, sobre o conteúdo da fusão por RRF
na branch `analysis/d4-9-hybrid-rrf` (base `adb332b`, antes de qualquer merge):
**2047 passed, 1 warning** (`python -m pytest -q`). O warning é o
`StarletteDeprecationWarning` pré-existente de `fastapi/testclient.py`. Na mesma
data e sobre o mesmo conteúdo, `mypy app tests scripts` reporta **226 source
files** sem erros e `ruff check` passa sobre `app`, `scripts` e `tests`. O
frontend **não foi alterado** por este trabalho.

Os 44 testes adicionais face à `main` vivem todos num ficheiro novo,
`tests/test_evaluation_hybrid_rrf.py`, e nenhum teste existente foi editado. A
contagem anterior, medida sobre a D4.8.2 em `7b85b50`, era de **2003 passed** e
**223 source files**.

Os 63 testes que a D4.8.2 acrescentou vivem todos num ficheiro novo,
`tests/test_evaluation_dense_admission.py`. **Nenhum teste existente
foi alterado, enfraquecido ou removido, e nenhum ficheiro de teste existente foi
tocado.**

Proveniência imediata: sobre o conteúdo da baseline experimental de dense
retrieval (base `47c1e9c`, hoje na `main` em `22b59fc`) a execução deu **1883
passed** (2026-08-16, **213 source files** no mypy), dos quais 100 acrescentados
por `tests/test_retrieval_dense.py` (46),
`tests/test_evaluation_dense_baseline.py` (30) e
`tests/test_embeddings_contracts.py` (23), mais um caso em
`tests/test_migrations.py` para a migration `c4f7ab19d3e5`.

Proveniência histórica, para leitura das diferenças: sobre o conteúdo das
variantes de ponderação do ranking (base `1a62016`, hoje na `main` em
`47c1e9c`, integrado em `22b59fc`) a execução deu **1783 passed** (2026-08-16, **200 source files** no
mypy), dos quais 39 acrescentados por
`tests/test_evaluation_ranking_variants.py`. Sobre o conteúdo do
repooling e diagnóstico do ranking (base `85c0055`, hoje na `main` em
`1a62016`) a execução deu **1744 passed** (2026-08-16, **197 source files** no
mypy), dos quais 42 acrescentados por `tests/test_evaluation_repooling.py`.
Sobre o conteúdo do experimento do orçamento de candidatos (base `b42f9ed`, hoje
na `main` em `85c0055`), **1702 passed** (2026-08-16, **194 source files** no
mypy), dos quais 43 acrescentados por
`tests/test_evaluation_candidate_budget.py`. Sobre o conteúdo da condição
pareada com diacríticos (base `5514d8b`, hoje na `main` em `b42f9ed`) a execução
deu **1659 passed** (2026-08-15, **191 source files** no mypy), dos quais 82
acrescentados por `tests/test_evaluation_ground_truth_identity.py` (64) e
`tests/test_evaluation_diacritics_experiment.py` (18); sobre o conteúdo do
experimento da correspondência lexical (base `a88f4ae`, hoje na `main` em
`5514d8b`), **1577 passed** (2026-08-15, **187 source files** no
mypy), dos quais 26 acrescentados por `tests/test_evaluation_lexical_variants.py`
(10) e `tests/test_evaluation_experiment_guard.py` (16). A execução sobre o conteúdo
do Evaluation Snapshot (base `311d917`, hoje na `main` em `6235b57`) deu
**1493 passed** (2026-08-14, **178 source files** no mypy), dos quais 79
acrescentados por `tests/test_evaluation_snapshot_unit.py` (48) e
`tests/test_evaluation_snapshot_corpus.py` (31); sobre a `main` em `311d917`,
**1414 passed** (A2.3a, 2026-08-13, **174 source files**); sobre `6ae9bad`,
**1287 passed** (2026-08-12, **167 source files**); sobre `d6dd75b`,
**1280 passed**; sobre `e3f43f4`, **1263 passed**. O tempo de execução varia
entre corridas e não deve ser lido como medida de desempenho.

Existe uma **baseline estrutural offline** das respostas fundamentadas,
produzida pelo Momento 5 e versionada em
[`docs/relatorios/moment-05-baseline-p1.json`](../relatorios/moment-05-baseline-p1.json),
com a verificação correspondente em
[`moment-05-verification.md`](../relatorios/moment-05-verification.md). Mede a
população P1 sobre 19 casos sintéticos, é reproduzível (mesmo `results` e mesmo
`result_digest` entre execuções) e não observou qualquer defeito comportamental.
O seu alcance e os seus limites estão em [Limitações conhecidas](#limitações-conhecidas).

Workflows em vigor:
[`backend-checks.yml`](../../.github/workflows/backend-checks.yml) (sem filtro
de paths) e
[`frontend-checks.yml`](../../.github/workflows/frontend-checks.yml) (apenas
para `frontend/**`), este com Node.js 22. Os comandos correspondentes estão em
[`03-quality-gates.md`](03-quality-gates.md).

## Limitações conhecidas

- Sem Row-Level Security: o isolamento depende das queries e da autorização.
- Recuperação sem compreensão semântica; perguntas cujo vocabulário não
  corresponda ao dos documentos devolvem `insufficient_evidence`.
- Geração experimental, sem garantia de ausência de alucinações; a validação é
  estrutural, não semântica.
- Processamento síncrono: documentos grandes atrasam a resposta do upload.
- Armazenamento local único, sem réplicas nem backup automático.
- OCR não corrige nem adivinha texto.
- O encaminhamento humano **apenas direciona**: apresenta um destino ao
  utilizador e regista a decisão. Não cria caso, não notifica ninguém, não
  atribui operador e não garante prazo de resposta. O sistema nunca decide
  sozinho encaminhar.
- Numa instituição **sem destino configurado**, a ação continua visível em
  conversas ativas e o pedido é recusado com 409 e erro controlado. A interface
  não a esconde porque não tem como saber a configuração: ler a instituição
  exige autorização de administrador, e expô-la ao utilizador comum seria
  superfície de API nova. É uma limitação assumida, não um descuido.
- A medição reprodutível da qualidade das respostas cobre **apenas a população
  P1** — estrutural, offline, sobre corpus sintético e respostas controladas de
  um gerador falso. **P2 e P3 não foram medidas**, pelo que as métricas humanas
  e as partes humanas das métricas híbridas constam da baseline como não
  medidas. Não existe, por isso, **medição semântica do fornecedor real**, e a
  baseline **não demonstra ausência de alucinações**.

Limitações detalhadas por área nos documentos canónicos correspondentes.

## Política de admissibilidade da evidência

**Issue #24 — "Política de elegibilidade da evidência: uma base partilhada,
finalidades distintas"**: **implementação concluída**. A regra que decide se um
segmento documental pode ser usado como evidência estava escrita em três sítios
e em três formas — filtros SQL na recuperação lexical, expressão booleana na
revalidação de fontes citadas e lista de condições nomeadas no diagnóstico —
sem nada que verificasse a coerência entre elas. Existe agora uma única
definição semântica, com as diferenças declaradas.

| Fase | Pull Request | Resultado |
| --- | --- | --- |
| Fase 0 | #35 | caracterização do comportamento existente, sem alterar produção |
| Fase 1 | #37 | `app/documents/retrievability.py` com as condições nomeadas e as duas composições, sem alterar consumidores |
| Fase 2 | #38 | retrieval lexical passa a consumir `RetrievalEligibility` |
| Fase 3 | #39 | revalidação de citações passa a consumir `CitationPersistenceEligibility` |
| Fase 4 | #40 | diagnóstico passa a consumir `RetrievalEligibility`; D2 resolvida |

Arquitetura resultante:

```
app.documents.retrievability
        │
        ├── RetrievalEligibility            (condições base + C5)
        │       ├── PostgresLexicalRetriever
        │       └── diagnóstico documental
        │
        └── CitationPersistenceEligibility  (condições base, sem C5)
                └── revalidação/persistência de citações
```

A distinção de domínio (Decisão 7 da issue) está **formalizada no código**, e
são três situações que não devem ser confundidas:

- **`RetrievalEligibility`** responde a "este chunk pode fundamentar uma
  resposta **agora**". Inclui C5 — a versão tem de ser a `processed` mais
  recente do documento;
- **`CitationPersistenceEligibility`** responde a "esta evidência foi
  legitimamente usada para gerar **esta** resposta". **Não** inclui C5: se a
  versão N foi usada na geração e N+1 for processada antes da persistência, N
  continua a ser a fonte correta. O teste de proveniência N → N+1 confirma que N
  deixa de ser recuperável sem deixar de ser a fonte histórica persistida;
- **`MessageSource`**, depois de persistido, é um **snapshot histórico**: a
  leitura devolve-o tal como foi gravado e **nunca** é reavaliado por política
  nenhuma.

A divergência **D2** — o diagnóstico não avaliava o idioma do chunk — foi
**resolvida na Fase 4 / PR #40**: o diagnóstico passou a avaliar
`chunk_language_compatible` através de `RetrievalEligibility` e declara
explicitamente a política que aplicou. O retrieval **não** mudou nesta fase: já
aplicava C8; o que estava incompleto era o diagnóstico. C12 ("existe alguma
versão `processed`?") permanece deliberadamente fora da política, na camada de
seleção do diagnóstico, por ser uma propriedade do conjunto de versões e não de
uma linha.

A elegibilidade **lexical** (`app/retrieval/eligibility.py`, se o conteúdo de um
candidato corresponde à pergunta) continua um conceito distinto da
admissibilidade **documental** descrita aqui, e não foi fundida com ela.

O repositório não tem `docs/adr/` nem `CONTEXT.md`, e não existe decisão tomada
sobre criá-los.

## Trabalho arquitetural em aberto

A issue #24 está **encerrada** (`CLOSED`/`completed`) e a sua implementação
concluída.

O Pull Request #42 introduziu, em `app/decision/contracts.py`, quatro contratos
provisórios de domínio para a decisão de resposta — `ScopeClass`,
`RequestConstraint`, `AnswerabilityClass` e `DecisionOutcome`. O módulo continua
a ser **apenas vocabulário**: não existe `DecisionPolicy` e não existe qualquer
mapeamento entre contratos.

A A2.3a deu a `DecisionOutcome.ESCALATE` o seu **primeiro consumidor
funcional**, no encaminhamento humano E1. Isso não é uma política:
o desfecho decorre de uma ação explícita do utilizador, não de uma inferência
sobre o pedido. `ScopeClass`, `RequestConstraint` e `AnswerabilityClass`
continuam sem consumidores, e os mapeamentos que a A2.1 declarou proibidos —
`PERSONAL_DATA_REQUIRED → ESCALATE`, `NOT_ANSWERABLE → ABSTAIN` — continuam
inexistentes.

O Pull Request #46 integrou a **A2.2**, a especificação científica da política
de decisão. As sete decisões normativas O1–O7 continuam **em aberto**, e três
delas (O2, O3, O6) determinam comportamento observável. É por isso que a
escalação decidida pelo sistema não está implementada: o que a A2.3a torna real
é o nível **E1** de O6 (destino designado e apresentado ao utilizador), que a
A2.2 identificou como implementável sem essas decisões.

O Pull Request #43 formalizou o resultado do retrieval (ver
[Contrato de resultado do retrieval](#contrato-de-resultado-do-retrieval)) mas
**não** consumiu nada disso numa decisão: o answering continua a tratar zero
evidências como fallback determinístico e ignora deliberadamente o trace. A
A2.3a também não alterou isto — o encaminhamento humano é uma capacidade
paralela ao pipeline de resposta, não um ramo dentro dele.
Situações causalmente distintas que produzem zero evidências — corpus não
admissível, ausência de correspondência lexical, cobertura insuficiente, limiar
de relevância — continuam a colapsar no mesmo estado `insufficient_evidence`.

Continua **não decidida** qualquer mudança na abordagem de recuperação em
produção. A D4.8 mediu uma condição densa offline e recomendou experimentar uma
arquitetura híbrida; a D4.8.1 completou os julgamentos e **reviu essa
recomendação**, pedindo primeiro um estudo de admissibilidade; a D4.8.2 fez esse
estudo e mediu que uma regra de limiar único calibrada só em DEV generaliza para
cenários independentes deste corpus; a D4.9, na branch
`analysis/d4-9-hybrid-rrf`, mediu a fusão por RRF e concluiu **A**, que nesta
amostra significa «justifica investigar mais». Nada disso alterou o sistema:
**recomendar ou medir uma experiência não é adotar uma arquitetura**, nenhuma
política de abstenção existe no *answering*, nenhum retriever híbrido existe e
nenhuma rota mudou de estratégia. Ver
[Baseline experimental de dense retrieval](#baseline-experimental-de-dense-retrieval),
[Admissão e abstenção da condição densa](#admissão-e-abstenção-da-condição-densa-d482-integrada-pelo-pr-58)
e
[Fusão lexical + densa por RRF](#fusão-lexical--densa-por-rrf-d49-branch).

## Divergências documentais conhecidas

Afirmações da documentação canónica que não correspondem ao código neste
snapshot.

**Nenhuma divergência documental canónica conhecida no snapshot observado.**

As divergências anteriormente registadas aqui foram corrigidas **na fonte**:

- o âmbito do `mypy` em [`docs/document-core.md`](../document-core.md) e
  [`README.md`](../../README.md) passou a `mypy app tests scripts`, que é o que a
  CI executa;
- a lista "fora do âmbito" de [`docs/document-core.md`](../document-core.md)
  passou a declarar-se como âmbito da entrega inicial e a remeter para a secção
  que descreve o OCR local, entretanto implementado;
- o risco "sem OCR" passou a descrever as falhas controladas reais (OCR
  desativado ou runtime indisponível, timeout, limite de páginas, resultado vazio
  numa página necessária, dados de idioma em falta);
- o risco "sem DELETE" passou a distinguir o `DELETE` documental existente da
  ausência de política automática de retenção/limpeza;
- a afirmação de que o isolamento multi-institucional é "garantido em duas
  camadas" passou a separar os papéis: os filtros da aplicação decidem o
  isolamento das queries, as foreign keys compostas garantem integridade
  relacional, e não existe Row-Level Security;
- [`docs/diagnostics/README.md`](../diagnostics/README.md) deixou de descrever
  D2 como a única mudança possível de veredicto do formato v5;
- a §5 de [`01-project-constitution.md`](01-project-constitution.md) descrevia o
  SDK do fornecedor como "importado quando a aplicação é carregada", o que
  deixou de ser verdade com a A6.1 (Pull Request #45). Passou a enunciar o
  princípio duradouro e a remeter o estado corrente para este documento;
- a §4 de [`01-project-constitution.md`](01-project-constitution.md) descrevia a
  distinção entre "recuperável agora" e "legitimamente citado então" como
  "atualmente em discussão na issue #24". A issue está encerrada e a distinção
  está formalizada no código; a afirmação temporal foi removida e o princípio de
  auditabilidade preservado.

A divergência sobre o conteúdo dos logs do answering tinha já sido corrigida em
[`docs/answering.md`](../answering.md): a descrição passou a ser específica do
log de rejeição da validação e inclui `institution_id`.

Documentos **históricos** — [`moments/moment-06.md`](moments/moment-06.md),
[`docs/relatorios/`](../relatorios/) e
[`ConfigInicial.md`](../../ConfigInicial.md) — registam o estado do momento em
que foram escritos e **não** são divergências: não devem ser atualizados para
descrever o presente.
