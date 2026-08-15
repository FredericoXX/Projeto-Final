# D4.1 — Pilot Corpus institucional e protocolo de *ground truth* para recuperação

Relatório de fase. Documento **histórico**: regista o desenho, as observações e
as decisões no momento em que foram tomadas. O estado corrente vive em
[`docs/ai/02-current-state.md`](../ai/02-current-state.md).

## 1. Objetivo

Criar as condições para medir a recuperação sobre documentação institucional
**real**, com corpus, proveniência e contexto experimental explicitamente
identificados. A pergunta desta fase é:

> Conseguimos demonstrar e medir o *retrieval* atual sobre documentação
> institucional real, com corpus, proveniência e contexto experimental
> explicitamente identificados?

E **não**:

> Como podemos melhorar já o *retrieval*?

Nenhuma melhoria de recuperação foi feita, e nenhuma foi decidida. A melhoria só
será considerada depois de existir uma baseline medida.

## 2. Enquadramento DSR

| Elemento | Fase |
| --- | --- |
| Evaluation Snapshot (infraestrutura, Pull Request #48) | DSR3 — Design & Development |
| Pilot Corpus real ingerido e primeiro snapshot real produzido | **início** de DSR4 — Demonstration |
| Protocolo de *ground truth* de recuperação, rubrica e perguntas piloto | preparação de DSR5 — Evaluation |
| Baseline lexical medida | ainda **não executada** |

A formulação correta do que esta fase alcançou é **"instanciação piloto
iniciada; primeiro corpus contextual processado; primeiro snapshot real
produzido"**. DSR4 **não** está validada, e DSR5 **não** começou: não houve
utilizadores, não houve medição e não houve métrica calculada.

## 3. Baseline Git

| Item | Valor |
| --- | --- |
| `origin/main` verificada | `6235b572b7ac33c79b08b9aa52e42c4967d747d2` (merge do Pull Request #48) |
| Branch de trabalho | `docs/d4-1-pilot-corpus`, criada a partir de `origin/main` |
| Working tree no início | limpa |
| Migrations | nenhuma criada; head continua `a5c31f70b8d2` |

`origin/main` tinha avançado face à baseline indicada no enunciado — o Pull
Request #48 foi entretanto integrado. O trabalho começou sobre
`feat/evaluation-snapshot` (`228fe60`), cuja árvore é **idêntica** à de
`origin/main` (`git diff origin/main HEAD` vazio) por ser a branch que o PR #48
integrou. Como essa branch já cumpriu o seu propósito, o trabalho foi movido para
uma branch própria a partir de `origin/main`, em vez de continuar numa branch já
integrada. A baseline real é `6235b57`.

## 4. Separação de autorização A / B / C

A "autorização institucional" não é um bloqueio único. Esta fase separa-a em
três categorias e trabalha **apenas com A**.

| Categoria | Conteúdo | Estado | Evidência |
| --- | --- | --- | --- |
| **A** — documentação institucional pública | atos normativos publicados no repositório oficial *Normativos Uni-CV* | **utilizada** | acesso verificado por HTTP sem autenticação em 2026-08-15; ver §8 |
| **B** — informação institucional não pública | tipologia real de pedidos, procedimentos internos, destinos de encaminhamento, convenções de vigência | **UNKNOWN** | [`a2-2-decision-policy-specification.md`](a2-2-decision-policy-specification.md) §13.1: não existe registo documentado de autorização |
| **C** — participantes humanos | estudantes, operadores, entrevistas, sessões de utilização | **UNKNOWN** | idem §13.1 |

Nenhum estado foi inventado. B e C continuam por esclarecer com a orientadora e
com a instituição, e nada nesta fase depende deles — com uma exceção declarada:
a **convenção de vigência** (§9) pertence a B, e a sua ausência tem consequência
observável no corpus.

### 4.1 Público não significa "pode ser commitado"

Os documentos foram usados como **objeto de estudo**; nenhum ficheiro
institucional real entrou no repositório. Os PDF, o texto extraído, os segmentos
e o *snapshot* serializado vivem em `storage/pilot-corpus/`, diretoria ignorada
pelo Git (`.gitignore:20`, `/storage/`). A verificação está registada em §12.

O que é versionado são **apenas metadados públicos**: título, URL pública,
instituição, tipo, idioma, ato normativo, *checksum*, data de acesso, estado de
acesso público e motivo de inclusão ou exclusão — o conjunto explicitamente
admitido para este trabalho. Nenhum excerto documental foi copiado para
documentação versionada.

## 5. Critérios de inclusão

Um documento só entra no Pilot Corpus se satisfizer **todos**:

1. origem institucional oficial verificável;
2. acesso público verificável, sem autenticação;
3. conteúdo relacionado com atendimento académico;
4. sem dados pessoais como objeto do corpus;
5. versão ou data razoavelmente identificável;
6. formato processável pelo sistema (PDF, TXT ou Markdown);
7. relevância suficiente para gerar perguntas de atendimento;
8. proveniência documentável.

## 6. Critérios de exclusão

Excluem-se notícias promocionais sem valor normativo, publicações em redes
sociais, documentos de origem duvidosa, cópias não oficiais quando existe fonte
oficial, documentos com dados pessoais, documentos internos obtidos sem
autorização, páginas sem conteúdo estável, duplicados sem diferença material e
versões obsoletas quando não sejam necessárias para testar temporalidade. O
motivo de exclusão é sempre registado.

## 7. Dimensão do corpus

Não foi fixado um número-alvo. O Pilot Corpus usa o **menor conjunto capaz de
representar os tipos de dificuldade documental** que se pretende demonstrar. A
cobertura conseguida, e o que ficou por cobrir:

| Dificuldade | Coberta por | Estado |
| --- | --- | --- |
| PDF textual simples | P1-DOC-004, P1-DOC-006 | coberta |
| Tabelas | P1-DOC-002 (calendário), P1-DOC-005 (tabela de emolumentos) | coberta |
| Datas e prazos | P1-DOC-002, P1-DOC-003 | coberta |
| Regras normativas por artigo | P1-DOC-004, P1-DOC-006, P1-DOC-007 | coberta |
| Estruturas documentais diferentes | deliberação + calendário + regulamento + tabela | coberta |
| OCR | P1-DOC-002 (0 caracteres nativos em 4 páginas) | coberta |
| Documentos semelhantes entre si | P1-DOC-002 e P1-DOC-003 (mesmo tipo, anos letivos diferentes) | coberta |
| Referência entre documentos | P1-DOC-006 remete datas para o calendário | coberta |
| **Versões documentais do mesmo documento** | — | **não coberta** |

A última linha é uma lacuna declarada: os dois calendários são **atos normativos
distintos**, não duas versões do mesmo documento lógico, e modelá-los como
versões seria factualmente falso — além de tornar o mais antigo irrecuperável
por C5. Não foi localizada, como publicação autónoma, a versão revogada do
regulamento das residências. Fabricar um par de versões violaria o princípio de
não inventar documentos, pelo que a dificuldade fica por cobrir e é registada
como tal. O mecanismo de versionamento continua coberto pelos testes sintéticos
existentes.

## 8. Proveniência

Todos os documentos vêm do repositório normativo oficial da Universidade de Cabo
Verde:

```
https://www.unicv.edu.cv/pt/universidade/normativos-uni-cv/6-conselho-da-universidade
```

Verificação realizada em **2026-08-15**:

- a página de listagem responde `HTTP/1.1 200 OK` sem autenticação;
- cada ato normativo tem página própria, e o ficheiro é servido por uma ligação
  de partilha pública;
- o descarregamento devolveu `HTTP 200` e conteúdo PDF válido em todos os sete
  casos, sem credenciais.

O estado `public_access_status` é **`VERIFIED_PUBLIC`** para os sete candidatos.
Nenhum candidato ficou em `PUBLIC_BUT_USAGE_UNCLEAR`, `NOT_PUBLIC` ou
`UNVERIFIED`; se ficasse, seria excluído desta fase em vez de presumido.

O manifest completo, com `checksum_sha256`, data de acesso e motivo de inclusão
ou exclusão por item, está em
[`docs/evaluation/pilot-corpus-manifest.json`](../evaluation/pilot-corpus-manifest.json).

**Dados pessoais.** Os atos normativos são assinados por titulares de órgãos
(nomes de quem preside). Isso é parte do ato público publicado e não torna dados
pessoais o *objeto* do corpus; nenhum documento cujo objeto sejam dados pessoais
foi incluído. Não foi encontrada informação pessoal de estudantes.

## 9. Vigência: uma decisão que não podia ser tomada

`valid_from` e `valid_until` ficaram **a `NULL` em todos os documentos**.

Não é omissão. Determinar a vigência de um calendário ou de um edital exige a
**convenção institucional** que a A2.2 já identificou como dependência Uni-CV
com estado desconhecido (§13, "convenções de vigência (editais, calendários)").
Inferi-la a partir do título — por exemplo, assumir que o calendário de 2023/24
caducou — seria inventar regra institucional, exatamente o que esta fase proíbe.

Consequência observável, e deliberadamente não contornada: **os dois calendários
são simultaneamente elegíveis** em qualquer `reference_date`, porque C9 e C10 são
satisfeitas por ausência de limites. O corpus contém, portanto, duas respostas
plausíveis e mutuamente incompatíveis para perguntas sobre prazos sem ano
explícito. Esta é uma propriedade **do corpus e da lacuna institucional**, não um
defeito do *retrieval*, e é precisamente a situação que o *ground truth* tem de
saber representar (Q004, Q011).

## 10. Inventário do Pilot Corpus P1

| ID | Documento | Tipo | Público? | Incluído? | Motivo |
| --- | --- | --- | --- | --- | --- |
| P1-DOC-001 | Estatuto do Estudante | estatuto | `VERIFIED_PUBLIC` | **Não** | 34,43 MB excede `DOCUMENT_MAX_FILE_SIZE_MB=20`; API recusou com `413 payload_too_large` |
| P1-DOC-002 | Calendário Académico 2025/2026 | calendário | `VERIFIED_PUBLIC` | Sim | prazos de atendimento; PDF integralmente digitalizado, exercita OCR |
| P1-DOC-003 | Calendário Académico 2023/2024 | calendário | `VERIFIED_PUBLIC` | Sim | mesmo tipo noutro ano letivo; documentos semelhantes e discriminação temporal |
| P1-DOC-004 | Regulamento Geral Provisório dos Cursos de Graduação | regulamento | `VERIFIED_PUBLIC` | Sim | matrícula, inscrição, frequência e avaliação |
| P1-DOC-005 | Regulamento das Propinas e Emolumentos e Tabela de Taxas | regulamento | `VERIFIED_PUBLIC` | Sim | tabela de valores; informação em tabela |
| P1-DOC-006 | Regulamento da Outorga de Grau | regulamento | `VERIFIED_PUBLIC` | Sim | graduação e certificação; remete datas para o calendário |
| P1-DOC-007 | Regulamento das Residências Universitárias (revisão) | regulamento | `VERIFIED_PUBLIC` | Sim | serviços ao estudante e ação social |

Nenhum conteúdo integral é reproduzido aqui.

A exclusão de P1-DOC-001 é registada como **resultado experimental**, não como
decisão editorial: é o documento com maior relevância potencial para o
atendimento ao estudante, e a configuração atual impede-o de entrar no corpus.

## 11. Ingestão

Foi usado **exclusivamente o pipeline já implementado**, pelo caminho HTTP
documentado no [`README.md`](../../README.md). Nenhum pipeline novo foi escrito e
nenhum passo foi curto-circuitado.

```
POST /api/v1/institutions                      (X-Bootstrap-Token)
POST /api/v1/auth/register-initial-admin       (X-Bootstrap-Token)
POST /api/v1/auth/login                        → JWT
POST /api/v1/documents                         (JWT admin)   → Document
POST /api/v1/documents/{id}/versions           (JWT admin)   → DocumentVersion
                                                              → extração
                                                              → OCR quando aplicável
                                                              → chunking
                                                              → processing_status
```

A aplicação foi executada localmente (`uvicorn app.main:app`, porta 8077) contra
o PostgreSQL do `docker-compose.yml`. O processamento é síncrono dentro do
pedido de *upload*, tal como o estado atual descreve.

**Locatário dedicado.** Foi criada uma instituição própria para o piloto
(`UNICV-P1`), em vez de reutilizar as instituições de desenvolvimento já
existentes na base — que contêm 12 documentos avulsos de testes manuais. Sem
isso, o *snapshot* identificaria "os documentos que estão na base", que é
exatamente o que esta fase recusa afirmar. O corpus de S1 é, por construção,
apenas P1.

## 12. Resultados do pipeline

| Documento | Processamento | Método | OCR | Páginas | Chunks | Elegível | Resultado |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P1-DOC-001 | — | — | — | 70 | 0 | **Não** | `413 payload_too_large`; nenhuma versão criada |
| P1-DOC-002 | `processed` | `ocr` | **Sim** | 4 | 108 | Sim | qualidade `high`; 56 segmentos `table_row` |
| P1-DOC-003 | `processed` | `native` | Não | 5 | 76 | Sim | qualidade `high`; texto de origem degradado (§13.3) |
| P1-DOC-004 | `processed` | `native` | Não | 30 | 589 | Sim | qualidade `high` |
| P1-DOC-005 | `processed` | `native` | Não | 24 | 482 | Sim | qualidade `high`; 83,2 % dos caracteres são espaços (§13.1) |
| P1-DOC-006 | `processed` | `native` | Não | 8 | 156 | Sim | qualidade `high` |
| P1-DOC-007 | `processed` | `native` | Não | 23 | 423 | Sim | qualidade `high` |

Nenhum documento que falhou foi escondido. `extraction_quality` é `high` em
todos os processados — incluindo naqueles cujo texto está materialmente
degradado, o que é em si uma observação sobre o significado do campo.

**Elegibilidade.** Os 1834 segmentos das seis versões processadas são todos
elegíveis sob `RetrievalEligibility` com `language=pt`, `official_only=true` e
`reference_date=2026-08-15`. A verificação foi feita contra
`select_eligible_chunk_ids`, a própria política, e não contra uma reimplementação:
o conjunto devolvido pela política tem cardinalidade 1834, igual à soma dos
`chunk_count` das entradas do *snapshot*.

## 13. Problemas encontrados

Nenhum foi corrigido nesta fase, por disciplina de âmbito. Um defeito exposto
por documentos reais é evidência DSR, não um desvio a resolver pelo caminho.

### 13.1 BUG-D4.1-01 — o preenchimento de layout consome o orçamento do segmento

| Campo | Valor |
| --- | --- |
| **Severidade** | HIGH |
| **Tipo de documento** | PDF textual com layout tabular ou colunar |
| **Etapa do pipeline** | extração nativa → segmentação |
| **Comportamento esperado** | um segmento de até 1200 caracteres transporta ~1200 caracteres de texto pesquisável |
| **Comportamento observado** | em P1-DOC-005, 83,2 % dos caracteres de um segmento são espaços; a média de `normalized_content` é de **65 caracteres** por segmento |

**Reprodução.** `app/services/document_extraction_service.py` extrai com
`page.extract_text(extraction_mode="layout")`. Comparando os dois modos do
`pypdf` sobre a mesma página, o número de caracteres **não brancos é idêntico**
(1201 contra 1201 em P1-DOC-005; 1870 contra 1870 em P1-DOC-006): o modo
`layout` acrescenta **apenas espaços**, inflacionando o comprimento total entre
1,6× e 4,2×. A segmentação orça em coordenadas do texto bruto
(`unit.end_char - unit.start_char > chunk_size`), porque o contrato
`content == extracted_text[start_char:end_char]` o exige. O preenchimento
consome, portanto, o orçamento do segmento.

**Impacto.** A densidade de texto pesquisável por unidade de evidência cai até
cerca de 1/18 do previsto. Como a cobertura lexical é medida sobre
`normalized_content`, um segmento de 65 caracteres só pode corresponder a
poucos termos; e o orçamento global de candidatos (25 para `top_k=5`) é gasto em
segmentos esparsos. Isto afeta a baseline que vai ser medida a seguir, e tem de
ser lido como parte do sistema medido, não descontado dela.

**Recomendação.** Tratar em Pull Request separado. A questão de desenho —
segmentar sobre texto normalizado mantendo a rastreabilidade de posição, ou
normalizar o preenchimento antes de segmentar — não é decidida aqui.

### 13.2 FINDING-D4.1-02 — palavras unidas nos PDF de origem

| Campo | Valor |
| --- | --- |
| **Severidade** | MEDIUM |
| **Etapa** | anterior ao pipeline |

Ocorrências sistemáticas de palavras coladas (`aentrada`, `dodiploma`,
`CONSELHODA`, `matriculaseinscricoes`). Presentes **nos dois modos de extração**,
logo inerentes ao espaçamento de caracteres dos ficheiros de origem e **não
causadas pelo pipeline**. Não é um defeito do artefacto.

**Impacto.** A recuperação lexical não consegue corresponder um termo da pergunta
a um *token* colado. É uma limitação real da recuperação exclusivamente lexical
sobre estes documentos, e é evidência a considerar na futura análise lexical
contra densa/híbrida — sem que isso antecipe qualquer decisão.

### 13.3 FINDING-D4.1-03 — a decisão de OCR olha para a quantidade, não para a qualidade

| Campo | Valor |
| --- | --- |
| **Severidade** | MEDIUM |
| **Etapa** | decisão de OCR por página |

P1-DOC-003 é um documento digitalizado com camada de texto produzida por
terceiros e de baixa qualidade (contém marcas de tabulação por pontos, ruído do
tipo `••••` e palavras coladas). Como o número de caracteres nativos ultrapassa
`DOCUMENT_OCR_MIN_NATIVE_CHARS`, o OCR **nunca corre**, e o resultado é pior do
que o obtido em P1-DOC-002, onde o OCR do próprio sistema correu e produziu
segmentos `table_row` limpos.

O comportamento está documentado ("o OCR nunca corre em páginas com texto nativo
suficiente"), pelo que é **limitação de desenho, não defeito**. O que os
documentos reais acrescentam é a demonstração de que o critério de quantidade
pode escolher a pior das duas fontes disponíveis.

### 13.4 FINDING-D4.1-04 — o limite de upload exclui o documento mais relevante

| Campo | Valor |
| --- | --- |
| **Severidade** | LOW (configuração) |
| **Etapa** | validação do upload |

`DOCUMENT_MAX_FILE_SIZE_MB=20` exclui o Estatuto do Estudante (34,43 MB). A
recusa é controlada e correta (`413`, mensagem sem detalhe interno). Regista-se
porque o critério de dimensão não está correlacionado com a relevância
documental, e o documento excluído é o mais central para o atendimento ao
estudante. Alterar o limite é decisão de configuração fora do âmbito desta fase.

### 13.5 Observação menor

A segmentação estrutural produz segmentos de 1 carácter (mínimo observado em
quatro documentos) e, em P1-DOC-002, segmentos `paragraph` que contêm apenas
separadores de tabela. Registado como ruído de baixo impacto; não investigado.

## 14. Evaluation Snapshot S1

Produzido com o **builder real**
(`app.evaluation.snapshot_builder.build_evaluation_snapshot`). Nenhuma identidade
foi recalculada à mão e nenhuma condição de elegibilidade foi reescrita.

| Campo | Valor |
| --- | --- |
| `schema_version` | `1` |
| `snapshot_id` | `a94f940229152a3b61860b370df8cb3ea8fe1a0e7236d65e86fe4b5118baf4c1` |
| `corpus_digest` | `e8a0f08b5ecf37821244e62c266a48b1d64c928cabb75e0e23e08f9c895a447e` |
| `reference_date` | `2026-08-15` |
| `strategy` | `lexical` |
| `pipeline_version` | `lexical_pipeline_v1` |
| `scoring_version` | `lexical_composite_v1` |
| `score_kind` | `lexical_relevance` |
| `comparable_across_queries` | `false` |
| `language` | `pt` |
| `top_k` | `5` |
| `official_only` | `true` |
| `fts_config` | `portuguese` |
| `min_relevance_score` | `0.05` |
| `candidate_limit` | `25` |
| Versões documentais representadas | **6** |
| Documentos representados | **6** |
| Segmentos representados | **1834** |

O par passa a poder ser nomeado: **Pilot Corpus P1 · Evaluation Snapshot S1**.

### 14.1 Reprodutibilidade verificada

O *builder* foi executado **duas vezes sobre estado inalterado**:

| Execução | `snapshot_id` | `corpus_digest` |
| --- | --- | --- |
| 1 | `a94f9402…baf4c1` | `e8a0f08b…5a447e` |
| 2 | `a94f9402…baf4c1` | `e8a0f08b…5a447e` |

Os dois artefactos serializados são **byte a byte idênticos**
(SHA-256 `54781abd99be300d248558cb3124d8c42cb504e14a5a9b4a9206887e8e02585a` em
ambos). O critério de paragem correspondente **não** foi acionado.

### 14.2 Identidade não é arquivo

O `snapshot_id` prova que dois contextos experimentais são o mesmo ou são
diferentes. **Não restaura o corpus.** Reproduzir uma execução exige o *snapshot*
serializado **e** os dados; o *snapshot* identifica o corpus que existia, não
impede que os documentos mudem depois. A terminologia do relatório do Pull
Request #48 é mantida sem alteração.

O artefacto serializado completo, com as entradas por versão, vive em
`storage/pilot-corpus/evaluation-snapshot-S1.json` — **não versionado**, porque
contém identificadores de uma instalação local concreta. O manifest versionado
documenta a proveniência; não permite recalcular o digest noutra máquina.

## 15. Protocolo de *ground truth* para recuperação

### 15.1 Âmbito, e o que fica de fora

O protocolo responde a **uma** pergunta:

> Dada uma pergunta, que evidência documental deveria ser recuperada?

E **não** a:

> O sistema deveria responder, clarificar, abster-se ou encaminhar?

A segunda depende das decisões normativas **O1–O7**, que continuam em aberto. Os
dois *ground truths* são objetos separados e assim permanecem: nenhum campo desta
anotação afirma `DecisionOutcome`, `AnswerabilityClass`, `ScopeClass` ou
`RequestConstraint`.

Exemplo da separação, com um caso real do corpus: para *"Até quando posso pedir a
anulação da matrícula do primeiro semestre?"*, o *ground truth* de recuperação
afirma que o segmento 24 de P1-DOC-002 é diretamente relevante. **Não** afirma
que o desfecho correto seja `ANSWER`.

### 15.2 Contrato

```json
{
  "schema_version": "2",
  "contract": "retrieval_ground_truth",
  "corpus_id": "P1",
  "snapshot_id": "<identidade do EvaluationSnapshot>",
  "corpus_digest": "<identidade do corpus>",
  "reference_date": "<data de referência da experiência>",
  "annotation_mode": "SINGLE_ANNOTATOR_PILOT",
  "relevance_scale": { "0": "…", "1": "…", "2": "…" },
  "metric_protocol": { "…": "ver §19" },
  "questions": [
    {
      "question_id": "Q001",
      "question": "<pergunta em linguagem de atendimento>",
      "language": "pt",
      "question_origin": "constructed_from_public_documents",
      "temporal_scope": "2025/2026",
      "difficulty_types": ["date_deadline", "table_information"],
      "no_relevant_evidence": false,
      "excluded_from_metrics": false,
      "exclusion_reason": null,
      "evidence_judgments": [
        { "corpus_item_id": "P1-DOC-002", "chunk_index": 24, "relevance": 2, "note": "<justificação>" },
        { "corpus_item_id": "P1-DOC-003", "chunk_index": 25, "relevance": 0, "note": "<distractor>" }
      ],
      "document_level_relevance": [
        { "corpus_item_id": "P1-DOC-002", "relevance": 2 }
      ],
      "annotation": {
        "annotator_1": "author",
        "annotator_2": null,
        "adjudication_status": "NOT_APPLICABLE_SINGLE_ANNOTATOR"
      },
      "notes": null
    }
  ]
}
```

O campo chama-se **`evidence_judgments`**, e não `relevant_evidence`: contém
**todos** os julgamentos, incluindo os de grau 0. Chamar `relevant_evidence` a
uma lista que aloja distractores seria contraditório, e os graus 0 são
necessários — é sobre eles que se mede a contaminação por outro ano letivo.
`no_relevant_evidence` continua a ser o campo que declara ausência de evidência.

**`temporal_scope`** declara o ano letivo a que a pergunta se refere, ou
`not_time_dependent`, ou `unscoped`. Existe porque a relevância de um prazo
depende do ano, e o corpus não tem vigência que o decida (§9).

Template sem dados institucionais em
[`docs/evaluation/retrieval-ground-truth-template.json`](../evaluation/retrieval-ground-truth-template.json);
anotações do piloto em
[`docs/evaluation/retrieval-ground-truth-p1-seed.json`](../evaluation/retrieval-ground-truth-p1-seed.json).

### 15.3 Evidência ao nível do segmento

A relevância é anotada ao nível do **segmento**, porque é o segmento que o
*retriever* devolve como unidade de evidência. `document_level_relevance` é
mantida como informação **secundária**, útil para análise agregada e para o caso
em que a evidência está dispersa.

### 15.4 Âncora de identidade

Cada segmento é ancorado por `corpus_item_id` + `chunk_index`, e não por UUID. O
`chunk_index` é determinístico dado o mesmo ficheiro e a mesma **configuração de
extração e segmentação** — que é o que o produz, e que
`LEXICAL_PIPELINE_VERSION` **não** cobre (§15.8). A âncora é, por isso, estável e
legível enquanto o `corpus_digest` não mudar; os UUID de
`document` e `document_version` que compunham S1 vivem no artefacto local
`storage/pilot-corpus/S1-identifier-binding.json`, porque identificam uma
instância concreta da base e não o corpus.

### 15.5 Regra de identidade das perguntas

`Q` seguido de três dígitos, atribuídos **por ordem de criação** e nunca
reutilizados. A identidade não depende da ordem dos ficheiros, da ordem de
leitura da base nem de qualquer ordenação acidental. Uma pergunta removida deixa
o seu identificador vago; não é reatribuído.

### 15.6 Ligação obrigatória ao *snapshot*

Cada conjunto de anotações declara o `snapshot_id` contra o qual vale. A unidade
experimental verificável é:

```
Pergunta Q_n  +  Snapshot S1  +  Ground Truth
```

**Sem `snapshot_id` a anotação não é utilizável.**

### 15.7 Alteração do corpus

Se o corpus mudar materialmente, gera-se **novo snapshot**. As anotações de S1
**não** são reutilizadas silenciosamente contra S2: é preciso determinar, item a
item, quais continuam válidas e quais exigem revisão. Uma anotação cujo
`chunk_index` deixe de existir, ou cujo documento tenha mudado de `chunk_digest`,
é revista obrigatoriamente.

### 15.8 Duas identidades que não se confundem

Distinção que este relatório afirmou mal numa primeira redação, e que importa
fixar:

| Muda o quê | Efeito |
| --- | --- |
| **Extração ou segmentação** (por exemplo, corrigir BUG-D4.1-01) | mudam `content`, `normalized_content`, `chunk_index` e `chunk_count` → muda `chunk_digest` → muda **`corpus_digest`** → **novo snapshot (S2)** e revisão obrigatória das âncoras |
| **Recuperação** — planeamento, normalização lexical, elegibilidade lexical, expressão FTS, orçamento de candidatos | sobe **`LEXICAL_PIPELINE_VERSION`** → muda `snapshot_id` com `corpus_digest` **igual** |

`LEXICAL_PIPELINE_VERSION` está declarada em
[`backend/app/retrieval/lexical.py`](../../backend/app/retrieval/lexical.py) e
cobre exclusivamente etapas de `app/retrieval/`. **Não cobre extração nem
segmentação**, que vivem em `app/services/`. Corrigir BUG-D4.1-01 exige,
portanto, **novo `corpus_digest` e novo snapshot** — e **não** exige subir a
versão lexical, a menos que o comportamento da recuperação mude também.

É exatamente esta a separação que o desenho do snapshot quis tornar observável:
`corpus_digest` igual com `snapshot_id` diferente significa "mesmo corpus, outra
recuperação"; o inverso significa "o corpus mudou".

### 15.9 Anotação

O desenho prevê **Annotator A, Annotator B e adjudicação**. Nesta fase existe
**um único anotador** (o autor), pelo que o modo é declarado
`SINGLE_ANNOTATOR_PILOT` e `adjudication_status` é
`NOT_APPLICABLE_SINGLE_ANNOTATOR`. Não se inventam dois anotadores.

**Limitação declarada:** sem segundo anotador não há medida de concordância, e as
anotações refletem o julgamento de uma só pessoa — a mesma que construiu as
perguntas. O contrato está desenhado para acomodar dupla anotação posterior sem
alteração de formato.

## 16. Rubrica de relevância

Escala de três graus. Cada grau tem critério explícito e teste de decisão.

### Grau 0 — irrelevante

O segmento **não contribui** para responder ao pedido. Inclui o caso importante
do **distractor**: um segmento sobre o mesmo assunto mas referente a outro ano
letivo, a outro público ou a outro procedimento. Recuperar um distractor não é um
acerto parcial — é um erro, porque conduziria a informação incorreta.

*Teste:* se este segmento fosse a única evidência apresentada, a pessoa ficaria
sem resposta ou com resposta errada.

### Grau 1 — parcialmente útil

O segmento é **relevante mas insuficiente sozinho**. Enquadra, localiza, remete
para outro documento, ou acrescenta uma condição a uma regra que está noutro
sítio. Contém contexto verdadeiro e pertinente, mas não a informação pedida.

*Teste:* se este segmento fosse a única evidência apresentada, a pessoa
reconheceria que está no sítio certo, mas continuaria sem a resposta.

*Exemplo real (Q012):* o Regulamento da Outorga de Grau declara que as datas da
cerimónia são fixadas no calendário académico. É verdadeiro e necessário, e não
contém data nenhuma.

### Grau 2 — evidência diretamente relevante

O segmento **contém a informação pedida** e é suficiente, sozinho, para
fundamentar a resposta ao pedido tal como foi formulado.

*Teste:* se este segmento fosse a única evidência apresentada, a pessoa teria a
resposta.

Notas de aplicação: podem existir vários segmentos de grau 2 para a mesma
pergunta, quando o documento repete a informação em sítios diferentes (Q001);
graus são atribuídos **face à pergunta**, não à qualidade intrínseca do segmento;
e um segmento com texto degradado que ainda assim contém a informação recebe
grau 2 — a rubrica anota a evidência que existe, não a que se desejaria.

### 16.1 Casos sem evidência

Uma pergunta cuja informação não existe no corpus é representada por
`no_relevant_evidence = true` e `relevant_evidence = []`.

Isto é um **facto sobre o corpus**. Não é `NOT_ANSWERABLE`, não é `ABSTAIN` e não
é `insufficient_evidence`: esses são conceitos de política ou de estado do
sistema, e a sua atribuição depende de O1–O7. A conversão automática de um no
outro é explicitamente proibida por este protocolo.

## 17. Perguntas piloto

**Origem: `constructed_from_public_documents`.** Foram construídas pelo autor a
partir dos documentos públicos. **Não são perguntas reais de estudantes** e não
devem ser descritas como tal em nenhum documento posterior. A tipologia real de
pedidos pertence à categoria B, cujo estado é UNKNOWN.

As perguntas são formuladas em linguagem de atendimento, não copiadas de títulos
ou de epígrafes. Onde o corpus diz *"outorga de grau"*, a pergunta diz
*"entrega dos diplomas"*; onde o corpus diz *"frequência"*, a pergunta diz
*"presença"*.

| ID | Pergunta (abreviada) | `temporal_scope` | Dificuldade | *Ground truth* |
| --- | --- | --- | --- | --- |
| Q001 | início das aulas | 2025/2026 | data, tabela, lexicalmente próxima | 2 × grau 2 + 1 distractor |
| Q002 | prazo de anulação da matrícula | 2025/2026 | data, tabela, documentos semelhantes | 1 × grau 2 + 2 distractores |
| Q003 | período de renovação da matrícula | 2025/2026 | paráfrase, data, tabela | 1 × grau 2 + 3 distractores |
| Q004 | publicação da lista de inscritos em UCT | 2025/2026 | acrónimo, documentos semelhantes | 1 × grau 2 + 2 distractores |
| Q005 | obrigatoriedade de presença nas práticas | — | sinónimo, regra em secção | 1 × grau 2 + 2 × grau 1 |
| Q006 | percentagem mínima na componente laboratorial | — | regra numérica | 1 × grau 2 + 1 × grau 1 |
| Q007 | duração máxima do alojamento | — | paráfrase, regra | 1 × grau 2 |
| Q008 | antecedência para prorrogar alojamento | — | regra numérica, prazo | 1 × grau 2 |
| Q009 | como candidatar-se a residência | — | paráfrase, secção | 1 × grau 2 + 3 × grau 1 |
| Q010 | custo do concurso especial para diplomados CESP | — | acrónimo, tabela de valores | 1 × grau 2 |
| Q011 | primeiro dia de aulas do 2.º semestre | 2023/2024 | desambiguação entre anos | 2 × grau 2 |
| Q012 | data da cerimónia de entrega de diplomas | 2025/2026 | referência entre documentos | 1 × grau 2 + 1 distractor + 1 × grau 1 noutro documento |
| Q013 | recuperar palavra-passe do portal | — | **sem evidência no corpus** | `no_relevant_evidence = true` |
| Q014 | prazo de anulação da matrícula, **sem ano** | `unscoped` | **ambiguidade temporal** | 2 × grau 2 incompatíveis; `excluded_from_metrics` |

**Catorze** perguntas e **32 julgamentos** (16 de grau 2, 7 de grau 1, 9 de grau
0), anotadas por completo em
[`retrieval-ground-truth-p1-seed.json`](../evaluation/retrieval-ground-truth-p1-seed.json).
Todas as 32 âncoras foram verificadas por consulta contra os segmentos reais de
S1: **0 falhas**.

**A ausência de Q013 foi verificada**, não presumida: as duas únicas ocorrências
de "portal" no corpus referem submissão de programas de disciplinas por docentes,
e "credenciados" refere acreditação de profissionais de comunicação. Nenhuma tem
que ver com credenciais de estudante.

### 17.1 O ano letivo tem de estar na pergunta

Numa primeira redação, Q002, Q003 e Q012 não indicavam o ano letivo. Com dois
calendários simultaneamente elegíveis e nenhum com vigência declarada (§9), isso
tornava a relevância **indeterminável**: o corpus contém, para a mesma pergunta,
duas respostas igualmente fundamentadas.

O caso não era hipotético. **Os quatro** têm entrada concorrente no calendário de
2023/2024: prazo próprio de anulação da matrícula, entregas próprias das listas
de inscritos em UCT, renovação de matrículas no 2.º semestre com intervalo
próprio, e uma entrada própria de cerimónia de outorga de grau.

Correção adotada, em duas partes:

1. **Q002, Q003, Q004 e Q012 passaram a declarar o ano letivo** e ganharam os
   segmentos concorrentes anotados a **grau 0**. Ficam *well-posed* e medíveis, e
   os distractores passam a medir contaminação entre anos em vez de a esconder.
2. **Q014 preserva a formulação natural sem ano**, com as duas interpretações
   anotadas a grau 2 e `excluded_from_metrics = true`. A formulação que um
   estudante usaria não se perde, e não contamina as métricas com uma relevância
   que ninguém consegue decidir sem a convenção institucional de vigência.

**Nota metodológica sobre como estes distractores foram encontrados.** Numa
redação intermédia deste relatório afirmou-se que o calendário de 2023/2024 não
continha cerimónia de outorga de grau, e que não existiam datas próprias de
renovação de matrículas no 2.º semestre. **Ambas as afirmações eram falsas.** A
consulta de verificação tinha devolvido os segmentos corretos (chunks 41 e 29),
mas o resultado foi lido truncado nos primeiros ~140 caracteres, e a informação
está no fim de segmentos longos e ruidosos. A conclusão foi tirada sobre a parte
não observada.

Fica como aviso operacional para a fase de medição: **nos documentos deste corpus
a inspeção truncada não é fiável.** BUG-D4.1-01 produz segmentos onde o conteúdo
útil está disperso entre longas cadeias de preenchimento, e o ruído de extração
de P1-DOC-003 agrava-o. Qualquer verificação de ausência tem de ler o segmento
completo, e uma ausência não pode ser declarada a partir de uma amostra truncada.

Detalhe de Q012 que importa para a análise de falhas: o intervalo de datas da
cerimónia **coincide** entre os dois calendários. O segmento de 2023/2024 é
anotado a grau 0 por ser o ano errado, mas recuperá-lo produziria a resposta certa
**pela razão errada** — e a coincidência não é garantida noutro ano.

### 17.2 Porque catorze e não sessenta

Não se afirma que catorze perguntas sejam suficientes para validade estatística, e
não se fixa aqui a dimensão final da amostra. Isto é um **piloto**: o objetivo é
cobrir os principais tipos de caso e **validar o protocolo**, não estimar
métricas com intervalo de confiança. A dimensão final será decidida com
protocolo metodológico próprio, depois de o protocolo estar validado.

## 18. Limitações

- **Um único anotador.** Sem concordância entre anotadores; ver §15.8.
- **Perguntas construídas.** Não representam distribuição real de pedidos; a
  tipologia real depende de B.
- **Vigência indeterminada.** Nenhum documento tem `valid_from`/`valid_until`; a
  discriminação temporal do corpus é, por isso, nula (§9).
- **Versões documentais não cobertas.** O corpus não contém duas versões do mesmo
  documento lógico (§7).
- **Corpus pequeno e enviesado para o normativo.** Seis documentos, todos do
  Conselho da Universidade. Não cobre editais, guias de serviços nem páginas
  institucionais.
- **O corpus mede-se com os defeitos que tem.** BUG-D4.1-01 afeta a densidade de
  evidência de quatro dos seis documentos, e a baseline que se seguir mede o
  sistema **com** esse defeito. Descontá-lo seria inventar um sistema que não
  existe.
- **`extraction_quality` não é medida de qualidade real.** É `high` em documentos
  cujo texto está materialmente degradado.
- **Conjunto de julgamentos incompleto.** Construído por inspeção dirigida, não
  por *pooling*. Precision@k e MRR são **pessimistas** por construção; Recall@k e
  nDCG@k têm enviesamento **indeterminado** (§19.2). Nenhuma métrica é comparável
  entre sistemas sem *repooling*.
- **A verificação de ausência é frágil neste corpus.** Segmentos longos e
  ruidosos escondem informação no fim; uma inspeção truncada produziu, durante
  este trabalho, duas afirmações de ausência que eram falsas (§17.1). Qualquer
  ausência tem de ser verificada sobre o segmento completo.
- **Reprodutibilidade local.** S1 é reproduzível na instalação onde foi
  produzido; o manifest versionado documenta proveniência, não permite recalcular
  o digest noutra máquina.
- **Nenhuma métrica foi calculada.** Não há Recall@k, MRR, nDCG nem Precision@k
  neste relatório, por decisão de âmbito.

## 19. Métricas a preparar

Preparadas, **não executadas**. Cada uma com justificação; nenhuma acrescentada
para aumentar a quantidade.

| Métrica | Justificação | Estado |
| --- | --- | --- |
| **Recall@k** | responde à primeira pergunta que interessa — *o retrieval encontrou a evidência que existia?* Se a evidência não é recuperada, nada a jusante a pode recuperar | **obrigatória** |
| **MRR** | a posição importa: `top_k=5` e o contexto do gerador é limitado; evidência recuperada em quinto lugar não tem o mesmo valor que em primeiro | recomendada |
| **nDCG@k** | única compatível com a rubrica de três graus — distingue grau 2 de grau 1, o que Recall e MRR não fazem | recomendada, condicionada à rubrica |
| **Precision@k** | interpretável apenas se o número de segmentos relevantes for conhecido e pequeno; com distractores anotados a grau 0, mede a contaminação por outro ano letivo | condicional |

### 19.1 Protocolo de cálculo

Sem isto, duas implementações produzem números diferentes a partir do mesmo
ficheiro. Fica fixado no contrato, em `metric_protocol`, e não na cabeça de quem
implementar:

| Decisão | Valor | Porquê |
| --- | --- | --- |
| Valores de `k` | 1, 3 e 5; **`k` primário = 5** | 5 é o `top_k` registado em S1; 1 e 3 mostram a sensibilidade à posição |
| Limiar de relevância binária | **grau 2** | Recall@k e MRR contam **apenas** grau 2. Um segmento que não responde sozinho não demonstra que a evidência foi encontrada; contar grau 1 inflacionaria o Recall com contexto |
| Ganho para nDCG | 0 → 0, 1 → 1, **2 → 3** | ganho não linear, para que um grau 2 não seja substituível por dois grau 1. IDCG calculado sobre os julgamentos da própria pergunta, ordenados por ganho decrescente |
| Segmentos não julgados | `ASSUMED_IRRELEVANT` (grau 0) | convenção habitual; o efeito por métrica está em §19.2 e **não é uniforme** |
| Completude do conjunto relevante | `DIRECTED_JUDGMENT_INCOMPLETE` | ver §19.2 |
| Perguntas `no_relevant_evidence = true` | **excluídas** de Recall, MRR e nDCG | as três métricas são indefinidas sem conjunto relevante. Reporta-se apenas a contagem de segmentos devolvidos — e essa contagem, por si só, **não** é um veredicto de política |
| Perguntas `excluded_from_metrics = true` | excluídas de tudo | exige `exclusion_reason` preenchido |

### 19.2 O conjunto relevante é incompleto, e o enviesamento não tem um só sentido

As anotações foram construídas por **inspeção dirigida do corpus**, não por
*pooling* dos resultados de vários sistemas. O conjunto é, por construção,
incompleto: podem existir segmentos genuinamente relevantes que não foram
julgados e que, sob `ASSUMED_IRRELEVANT`, contam como grau 0.

Uma redação anterior desta secção afirmava que Recall@k seria por isso um "limite
superior otimista" e que a convenção subestimaria Precision **e** nDCG. **Só a
parte sobre Precision estava correta.** O efeito real, por métrica:

| Métrica | Sentido do enviesamento | Porquê |
| --- | --- | --- |
| **Precision@k** | **pessimista**, garantido | um relevante não julgado conta 0 no numerador e o denominador é `k`, fixo. A Precision medida nunca excede a verdadeira |
| **Recall@k** | **indeterminado** | julgar de menos encolhe **numerador e denominador**. Um sistema que recupere todo o conjunto julgado mede 1,0 com Recall verdadeiro inferior — sobrestima; um sistema que recupere sobretudo relevantes **não** julgados mede baixo com Recall verdadeiro alto — subestima |
| **nDCG@k** | **indeterminado** | os *gaps* não julgados reduzem o DCG, mas o IDCG é aqui calculado sobre os julgamentos da própria pergunta e encolhe também. O quociente pode mover-se em qualquer direção |
| **MRR** | **pessimista**, garantido | o *rank* do primeiro relevante **julgado** nunca é anterior ao do primeiro relevante **verdadeiro**, porque o mínimo sobre um subconjunto é sempre ≥ o mínimo sobre o conjunto. Logo o *reciprocal rank* medido nunca excede o verdadeiro |

A assimetria entre MRR e Recall não é acidental e vale explicá-la: o **Recall tem
denominador `|R|`**, que encolhe com o conjunto julgado e pode empurrar o
quociente para cima; o **MRR e a Precision não têm** — o primeiro depende apenas
da posição do primeiro acerto, e a segunda tem denominador `k` fixo. É por isso
que duas métricas com conjunto incompleto têm sentido garantido e duas não têm.
Exemplo mínimo para o MRR: relevantes verdadeiros nas posições 1 e 5, apenas o da
posição 5 julgado — medido `1/5`, verdadeiro `1`.

As duas garantias de pessimismo valem enquanto os julgamentos positivos forem
**corretos**, isto é, enquanto o conjunto julgado estiver contido no verdadeiro.
Um falso positivo na anotação quebra-as.

Consequência prática, a declarar sempre que um número for reportado: **nenhuma
destas métricas é comparável entre sistemas sem *repooling*.** Antes de comparar
lexical com denso ou híbrido, o conjunto tem de ser repoolado com os resultados de
ambos e reanotado, sob pena de favorecer aquele cujos resultados serviram de base
à anotação. Para um único sistema medido uma única vez, os números continuam a ter
valor descritivo — mas não são estimativas não enviesadas do desempenho
verdadeiro, e não devem ser apresentados como tal.

**Uma métrica não é uma decisão de arquitetura.** Não se fixa aqui qualquer
limiar do tipo *"Recall abaixo de X implica embeddings"*. A futura decisão entre
lexical e denso/híbrido terá de considerar tipos de falha, distribuição, custo,
benefício, literatura e experiência controlada — não um número isolado.

## 20. Fora de âmbito, e confirmado como não feito

Não foi implementado, e nada neste trabalho o inicia: *embeddings*, recuperação
densa, pgvector no *retrieval*, híbrido, novo BM25, SPLADE, *reranker* semântico,
reescrita de consulta, segundo ciclo de recuperação, *agent loop*,
`DecisionPolicy`, `AnswerabilityEvaluator`, `RequestSpecificity`,
`DecisionReason`, `system_decision`, escalação automática, *thumbs up/down*,
questionário, SUS, telemetria de utilizador e *dashboard* de operador.

**Nenhuma alteração foi feita ao *retrieval*.** A baseline lexical, quando for
medida, mede o sistema tal como está em `origin/main`.

## 21. Bloqueios

| Bloqueio | Categoria | Efeito |
| --- | --- | --- |
| Convenção institucional de vigência | B (UNKNOWN) | `valid_from`/`valid_until` a `NULL`; corpus sem discriminação temporal |
| Tipologia real de pedidos | B (UNKNOWN) | perguntas continuam construídas, não observadas |
| Segundo anotador | organizacional | sem medida de concordância |
| O1–O7 | metodológico | *policy ground truth* não pode ser criado |

Nenhum destes bloqueia a baseline lexical de recuperação, que só precisa de
corpus, *snapshot* e *ground truth* de recuperação — os três existem.

## 22. Próximo passo

**Baseline lexical real**, e nada antes disso:

```
retrieval atual (inalterado)
        +
Snapshot S1  ·  Pilot Corpus P1
        +
Retrieval Ground Truth (14 perguntas; 12 entram nas métricas)
        ↓
Recall@k  ·  MRR  ·  nDCG@k justificados
        ↓
análise de tipos de falha
        ↓
(só então) decisão experimental: lexical vs denso/híbrido
```

A baseline **não foi iniciada** nesta fase, por decisão explícita: o corpus, o
*snapshot* e o protocolo tinham de estar definidos primeiro, e estão.

Fica também em aberto, como trabalho separado, o Pull Request que trate
BUG-D4.1-01. Se for tratado **antes** da baseline, a segmentação muda, o
`corpus_digest` muda com ela e S1 deixa de ser o contexto experimental em vigor —
o que exigirá **novo snapshot (S2)** e a revisão das anotações nos termos de
§15.7. Não exigirá subir `LEXICAL_PIPELINE_VERSION`, pela razão dada em §15.8.

---

Esta fase não serviu para provar que a arquitetura atual é boa. Serviu para criar
as condições em que é possível descobrir, com evidência, se é ou não.
