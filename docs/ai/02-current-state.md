# Estado atual

**Observação:** 2026-08-12 · commit `e3f43f4359cc0f71c7e7fc3638dbef13048ada87` (`main`) · repositório
`FredericoXX/Projeto-Final`

Os factos abaixo descrevem o conteúdo de
`e3f43f4359cc0f71c7e7fc3638dbef13048ada87`, o merge do Pull Request #42 que
integrou os contratos provisórios de decisão (A2.1). Trabalho em curso em
branches não fundidas não é estado deste SHA e, quando referido, é identificado
como tal.

O snapshot técnico aqui descrito é o da `main` em `e3f43f4`. A branch que
acrescenta o contrato de resultado do retrieval (A3/A4.1 — `RetrievalResult`,
trace no contrato e semântica explícita do score) **não está integrada** e
nada neste documento a pressupõe; o seu merge será registado quando ocorrer.

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
**Pull Request #41** (fecho documental da issue #24, merge `2b3c91e`) e o
**Pull Request #42** (contratos provisórios de decisão, merge `e3f43f4`) — ver
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
| `decision/` | contratos provisórios de domínio da decisão agêntica (A2.1): tipos puros, **sem consumidores** |
| `retrieval/` | planeamento de consulta, elegibilidade lexical, ranking, configuração FTS |
| `answering/` | contratos neutros, contexto, prompts, validação e adaptador de fornecedor |
| `evaluation/` | contratos e artefactos da avaliação offline do Momento 5; não é importado pela aplicação |
| `diagnostics/` | ferramenta interna de observação do pipeline documental |
| `core/` | configuração, segurança, normalização de texto, idioma, erros |

`scripts/` contém `seed_demo_institution`, `rebuild_document_chunks`,
`diagnose_document_pipeline`, `evaluate_answering_offline` (avaliação offline
determinística) e `build_moment05_baseline` (composição da baseline).

## Superfície da API

Endpoints sob `/api/v1`: `health`, `institutions`, `auth`, `users`,
`conversations`, `bootstrap`, `documents`, `retrieval`, `answering`.

Detalhe por área: [`README.md`](../../README.md) (bootstrap e autenticação),
[`docs/document-core.md`](../document-core.md) (documentos, versões, OCR,
chunking), [`docs/database.md`](../database.md) (esquema, recuperação, regras
de segurança), [`docs/answering.md`](../answering.md) (respostas e turnos
conversacionais), [`docs/diagnostics/README.md`](../diagnostics/README.md).

## Base de dados

14 migrations em [`backend/alembic/versions/`](../../backend/alembic/versions/),
head `e7b1c9d4a2f0` (`localize_search_vector_by_language`). Histórico completo
em [`docs/database.md`](../database.md).

A extensão `pgvector` está ativa como infraestrutura e não é usada pela
recuperação atual.

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
  confidence score, idempotência, feedback ou escalonamento humano;
- processamento documental **síncrono**, sem filas nem workers;
- execução local, sem serviços externos no retrieval e sem rede nos testes.

Precisões factuais, verificadas neste SHA:

- **Dependência do fornecedor.** O contrato `AnswerGenerator` é neutro e todo o
  conhecimento do SDK vive em `app/answering/providers/openai.py`, mas esse
  módulo é importado por `app/answering/dependencies.py` no carregamento da
  aplicação: o SDK da OpenAI **é uma dependência de runtime**, ainda que
  isolada por adapter. A aplicação arranca sem chave de API; a ausência só
  produz efeito (503) quando a geração é necessária.
- **Processamento documental.** Depende atualmente do storage, de
  `storage_path` e de `mime_type` — a extração resolve o caminho no storage e
  seleciona o extrator pelo tipo de conteúdo. A independência face à origem
  aplica-se às camadas a jusante (chunking, retrieval, answering), que operam
  sobre texto e metadados persistidos.
- **Logs do answering.** Incluem `institution_id`, reason codes, contagens e
  outros metadados controlados. Não incluem a pergunta, a resposta, o contexto
  documental, prompts, respostas brutas do fornecedor nem credenciais. A
  formulação "apenas reason codes e contagens" seria inexata.

## Testes e verificações

Contagens estruturais medidas em 2026-08-11: 53 ficheiros `test_*.py` no backend
(em 57 módulos de [`backend/tests/`](../../backend/tests/), incluindo
`conftest.py` e utilitários) e 9 ficheiros de teste no frontend. Os testes do
backend usam PostgreSQL real numa base dedicada; os do frontend usam MSW, sem
rede nem backend.

Contagem de execução sobre a `main` em `e3f43f4`: **1263 passed, 1 warning,
243.44 s** (`python -m pytest -q`, 2026-08-12). O warning é o
`StarletteDeprecationWarning` pré-existente de `fastapi/testclient.py`.
`mypy app tests scripts` reporta 165 source files.

As contagens estruturais acima (53 ficheiros `test_*.py`) foram medidas em
2026-08-11, antes do Pull Request #42, e não incluem
`tests/test_decision_contracts.py`.

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
`RequestConstraint`, `AnswerabilityClass` e `DecisionOutcome`. São **tipos puros
sem consumidores**: nenhum módulo os importa, e apagá-los não alteraria o
comportamento do sistema. Não existe `DecisionPolicy`, não existe qualquer
mapeamento entre eles, e as questões de investigação que os governam continuam
em aberto.

Continua **não decidida** qualquer mudança na abordagem de recuperação — dense,
híbrida, embeddings ou reranking por modelo. Este documento não deve ser lido
como anúncio de trabalho iniciado nessa direção.

## Divergências documentais conhecidas

Afirmações da documentação canónica que não correspondem ao código neste SHA.

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
  D2 como a única mudança possível de veredicto do formato v5.

A divergência sobre o conteúdo dos logs do answering tinha já sido corrigida em
[`docs/answering.md`](../answering.md): a descrição passou a ser específica do
log de rejeição da validação e inclui `institution_id`.

Documentos **históricos** — [`moments/moment-06.md`](moments/moment-06.md),
[`docs/relatorios/`](../relatorios/) e
[`ConfigInicial.md`](../../ConfigInicial.md) — registam o estado do momento em
que foram escritos e **não** são divergências: não devem ser atualizados para
descrever o presente.
