# Estado atual

**Observação:** 2026-08-08 · commit `0069809ba3c4acd506990242af13edcb6bda57d4` (`main`) · repositório
`FredericoXX/Projeto-Final`

Os factos abaixo descrevem o conteúdo de
`0069809ba3c4acd506990242af13edcb6bda57d4`, o merge do Pull Request #33 que
fechou de forma corretiva o Momento 5 após a integração da Fase 3. Trabalho em
curso em branches não fundidas não é estado deste SHA e, quando referido, é
identificado como tal.

Snapshot factual. Não contém regras: os princípios estão em
[`01-project-constitution.md`](01-project-constitution.md), os critérios de
verificação em [`03-quality-gates.md`](03-quality-gates.md) e a manutenção
desta diretoria no [`README.md`](README.md). Se este documento divergir do
repositório, o repositório está certo e o documento está desatualizado.

## Momentos

Momentos 1 a 5 concluídos — [`moments/moment-05.md`](moments/moment-05.md). As
decisões de método (Fase 0)
foram aprovadas pelo merge humano do Pull Request #29 (`2b6247c`), e o corpus
sintético com a rubrica (Fase 1) pelo merge humano do **Pull Request #30**,
integrado na `main` em `7846f08`. O mecanismo de avaliação offline (Fase 2) foi
aprovado pelo merge humano do **Pull Request #31**, integrado na `main` em
`aa72fcd`, e a baseline (Fase 3) pelo merge humano do **Pull Request #32**,
integrado na `main` em `0ed640cb`. O fecho corretivo foi integrado pelo
**Pull Request #33**, merge `0069809ba3c4acd506990242af13edcb6bda57d4`, sem
alterar a baseline. Com este merge, o Momento 5 está concluído e o Momento 6 é
o próximo a iniciar. O mapa oficial dos temas está no
[`README.md`](README.md#momentos).

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

Contagens estruturais medidas neste SHA: 45 ficheiros `test_*.py` no backend
(em 48 módulos de [`backend/tests/`](../../backend/tests/), incluindo
`conftest.py` e utilitários) e 9 ficheiros de teste no frontend. Os testes do
backend usam PostgreSQL real numa base dedicada; os do frontend usam MSW, sem
rede nem backend.

Não há contagem de testes executados registada para este SHA. A última
validação completa registada consta de
[`docs/relatorios/correcao-final-retrieval-lexical.md`](../relatorios/correcao-final-retrieval-lexical.md),
de 2026-07-30, e diz respeito a outro commit — não é o estado atual.

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

## Trabalho arquitetural em aberto

**Issue #24 — "Política de elegibilidade da evidência: uma base partilhada,
finalidades distintas"** (`FredericoXX/Projeto-Final`, aberta, etiqueta
`ready-for-agent`).

A regra que decide se um segmento documental pode ser usado como evidência está
escrita em três sítios e em três formas — filtros SQL na recuperação lexical,
expressão booleana na revalidação de fontes citadas, e lista de condições
nomeadas no diagnóstico. Nada verifica que as três se mantêm coerentes. A issue
propõe extrair as invariantes comuns e declarar as diferenças intencionais, sem
alterar comportamento funcional.

É uma **refatoração arquitetural independente**. Não está implementada, não faz
parte do Momento 5, e a sua divisão em um ou vários Pull Requests está por
decidir.

A distinção de domínio entre "recuperável agora" e "legitimamente citado então"
(Decisão 7 da issue) é uma decisão de domínio **pendente de formalização** e
possível fonte de decisão arquitetural futura. O repositório não tem `docs/adr/`
nem `CONTEXT.md`, e não existe decisão tomada sobre criá-los.

## Divergências documentais conhecidas

Afirmações da documentação canónica que não correspondem ao código neste SHA.
Estas divergências não foram corrigidas pela tarefa que criou esta diretoria.

| Documento | Afirmação | O que o código faz |
| --- | --- | --- |
| [`docs/document-core.md`](../document-core.md), [`README.md`](../../README.md) | `mypy app tests` | a CI executa `mypy app tests scripts` |
| [`docs/document-core.md`](../document-core.md) (linha 17, "Fora do âmbito desta fase") | OCR deliberadamente não implementado | OCR local implementado — `app/services/ocr_engine.py`, `ocr_line_reconstruction.py`, limites `DOCUMENT_OCR_*`; o próprio documento descreve-o na secção "Extração com OCR local" |
| [`docs/document-core.md`](../document-core.md) (linha 580, "Riscos e limitações") | "sem OCR: PDFs digitalizados ficam `failed`" | PDFs que exigem OCR podem ser processados; ficam `failed` quando o OCR está desativado, indisponível ou termina numa das falhas controladas documentadas (limite de páginas, timeout, resultado vazio, dados de idioma ausentes ou erro do runtime) |
| [`docs/document-core.md`](../document-core.md) (linha 581) | "sem DELETE" | `DELETE /api/v1/documents/{document_id}` existe — `app/api/routes/documents.py`, `delete_document` no service |

As três divergências do [`docs/document-core.md`](../document-core.md) são
contradições **internas** ao próprio documento: as secções históricas de âmbito e
de riscos não acompanharam o trabalho posterior descrito no mesmo ficheiro.
Ficam registadas aqui até serem corrigidas na fonte; a correção não pertence ao
Momento 5.

A divergência sobre o conteúdo dos logs do answering foi corrigida na fonte em
[`docs/answering.md`](../answering.md): a descrição passou a ser específica do
log de rejeição da validação e inclui `institution_id`.
