# Núcleo Documental (Fase 2)

## Objetivo da fase

Esta fase acrescenta ao protótipo a base documental sobre a qual a
futura camada de recuperação de informação irá trabalhar: registo de
documentos institucionais, versionamento dos ficheiros, upload
controlado, armazenamento local abstrato, extração de texto e consulta
administrativa dos metadados e do texto extraído.

A etapa seguinte desta fase acrescentou a segmentação do texto extraído
em *chunks* internos (tabela `document_chunks`, sem endpoint público) —
ver a secção "Document chunks" em [`docs/database.md`](database.md).

**Fora do âmbito desta fase** (deliberadamente não implementado):
embeddings, pgvector no domínio documental, pesquisa semântica ou híbrida,
RAG completo, integração com LLM, agentes, OCR, importação
de páginas web, filas/workers, S3 e interface frontend. A abordagem de
recuperação de informação continua a ser uma questão em aberto para a
revisão da literatura.

## Modelo de dados

Duas entidades, separadas de propósito:

- **`documents`** — o documento lógico e os seus metadados
  institucionais (título, descrição, idioma, origem, validade, estado).
- **`document_versions`** — cada ficheiro/revisão concreta desse
  documento. Regulamentos, calendários e manuais são atualizados ao
  longo do tempo; o versionamento preserva o histórico sem perder as
  versões anteriores.

Os ficheiros binários **não** são guardados no PostgreSQL: o ficheiro
original vive no armazenamento local e a base guarda apenas os
metadados, o caminho relativo (`storage_path`) e o texto extraído
(`extracted_text`).

O isolamento multi-institucional é garantido em duas camadas, como no
resto do projeto: filtros por `institution_id` nos services e foreign
keys compostas no PostgreSQL (`documents.created_by_user_id`,
`document_versions.document_id` e
`document_versions.uploaded_by_user_id` têm de pertencer à mesma
instituição da própria linha). Ver
[`docs/database.md`](database.md) para o esquema completo.

## Permissões

Nesta fase, **todos** os endpoints documentais são administrativos
(`require_admin`) e limitados à instituição do admin autenticado.
Staff, student e user não têm gestão documental direta. Um documento ou
versão de outra instituição responde **404** (nunca 403), para não
revelar a existência do recurso. Nenhum `institution_id` é aceite do
cliente. Não foi criada uma nova matriz de permissões.

## Armazenamento local

Abstração em `backend/app/storage/`: um `Protocol` (`DocumentStorage`)
com as operações `save_temp`, `move_to_final`, `open`, `delete`,
`exists` e `resolve_path`, e uma implementação local
(`LocalDocumentStorage`). A lógica de negócio depende do Protocol, o
que permite substituir o armazenamento (ex.: S3) sem alterar services.

Estrutura em disco (sempre debaixo de `DOCUMENT_STORAGE_PATH`):

```text
storage/documents/
  {institution_id}/
    {document_id}/
      {version_id}/
        source.<ext>
```

Regras de segurança:

- os caminhos guardados na base são sempre **relativos** ao storage root;
- o nome de ficheiro do cliente nunca entra na construção de caminhos —
  é sanitizado com `Path(filename).name` e preservado apenas como
  metadado (`original_filename`);
- `resolve_path` valida que nenhum caminho resolvido sai do root
  (proteção contra path traversal);
- a pasta `storage/` está no `.gitignore` e nunca é versionada.

Configuração (`.env`):

```env
DOCUMENT_STORAGE_PATH=storage/documents
DOCUMENT_MAX_FILE_SIZE_MB=20
```

## Formatos suportados

| Formato | Extensão | MIME guardado | Validação adicional |
|---|---|---|---|
| PDF | `.pdf` | `application/pdf` | assinatura `%PDF-` no início do conteúdo |
| Texto | `.txt` | `text/plain` | UTF-8 (com ou sem BOM) |
| Markdown | `.md` | `text/markdown` | UTF-8 (com ou sem BOM); `text/plain` declarado também é aceite |

Respostas de erro no upload:

- ficheiro vazio → **422**;
- extensão/tipo não suportado, tipo declarado incompatível ou PDF sem
  assinatura válida → **415** (`unsupported_media_type`);
- ficheiro acima de `DOCUMENT_MAX_FILE_SIZE_MB` → **413**
  (`payload_too_large`);
- checksum SHA-256 duplicado na mesma instituição → **409** (o mesmo
  conteúdo pode existir em instituições diferentes).

## Upload e versionamento

O upload é feito em streaming (blocos de 1 MB): tamanho e SHA-256 são
calculados durante a escrita para um ficheiro temporário, sem carregar
o ficheiro inteiro em memória. Depois da validação, o número de versão
é atribuído sob um lock da linha do documento (`SELECT ... FOR
UPDATE`) — dois uploads concorrentes nunca recebem o mesmo número — com
a UNIQUE constraint `(document_id, version_number)` como segunda
defesa. O ficheiro é movido atomicamente para o caminho final antes do
commit; se o commit falhar, o ficheiro final é removido e não ficam
órfãos (os temporários são sempre removidos em caso de erro).

## Estados de processamento

A extração de texto corre de forma **síncrona** dentro do pedido de
upload (decisão de protótipo; os services estão estruturados para uma
futura execução assíncrona, mas não existem filas nem workers).

| Estado | Significado |
|---|---|
| `pending` | versão registada, extração ainda não iniciada |
| `processing` | extração em curso |
| `processed` | texto extraído **e chunks persistidos** com sucesso — uma versão nunca fica `processed` antes de os seus chunks estarem gravados |
| `failed` | a extração ou a segmentação/persistência dos chunks falhou; o ficheiro original fica guardado para reprocessamento e a versão não mantém chunks |

O upload devolve **201 mesmo que a extração falhe** — a versão foi
criada; o resultado fica visível em `processing_status` e
`processing_error`. As mensagens de erro são curtas e seguras (sem
traceback, caminhos ou detalhes internos; esses ficam apenas no logging
do servidor). Um PDF sem texto extraível (ex.: digitalizado) fica
`failed` com a mensagem "No extractable text was found. OCR is not
available in this prototype." — não existe OCR nesta fase.

O reprocessamento
(`POST .../versions/{version_id}/reprocess`) reexecuta a extração sobre
o ficheiro original sem criar nova versão; uma versão já em
`processing` responde 409. Os chunks da versão são substituídos por
inteiro (sem duplicados nem restos parciais); os chunks de outras
versões do mesmo documento nunca são tocados. Se uma versão já tiver sido
citada por uma resposta persistida, o reprocessamento responde 409 **antes**
de alterar estado, texto ou chunks; deve ser carregada uma nova versão. Esta
regra preserva a evidência histórica. Uma FK sem cascade de `message_sources`
para `document_chunks` impede apagar ou reassociar o chunk citado, e o trigger
`trg_document_chunks_prevent_referenced_update` rejeita qualquer `UPDATE`
direto dessa linha.

## Endpoints

Todos sob `/api/v1`, autenticados com Bearer JWT de um admin:

```text
POST   /documents                                          cria documento lógico (201)
GET    /documents?limit&offset&is_active&official_source&language
GET    /documents/{document_id}
PATCH  /documents/{document_id}                            atualização parcial; is_active=false desativa
POST   /documents/{document_id}/versions                   multipart/form-data, campo "file" (201)
GET    /documents/{document_id}/versions                   ordenado por version_number DESC
GET    /documents/{document_id}/versions/{version_id}      metadados (sem storage_path nem texto)
GET    /documents/{document_id}/versions/{version_id}/content?offset&limit
GET    /documents/{document_id}/versions/{version_id}/download
POST   /documents/{document_id}/versions/{version_id}/reprocess
DELETE /documents/{document_id}                            eliminação permanente (204); ver regras abaixo
```

## Eliminação de documentos

`DELETE /api/v1/documents/{document_id}` (apenas admin, isolamento
institucional com 404) elimina permanentemente um documento **nunca
citado**: chunks, versões e o próprio documento numa única transação, e
depois os ficheiros do storage. Regras:

- **documento citado** (qualquer chunk/versão referenciado por uma
  `MessageSource`) → **409**: o histórico auditável nunca é destruído.
  A alternativa é **desativar** o documento (`is_active=false`), que o
  exclui de novas recuperações mas preserva respostas e fontes antigas;
- versão em estado `processing` → 409 (condição transitória);
- o checksum fica livre: o mesmo ficheiro pode voltar a ser carregado.

Concorrência: upload de versões e eliminação partilham um **advisory
lock transacional por documento** (pg_advisory_xact_lock) — a eliminação
nunca fotografa uma lista de versões que um upload em curso ainda vai
alargar, e um upload que perca a corrida falha com 404 limpo e sem
ficheiros órfãos. Contra o fluxo conversacional, a ordem de locks de
linhas (versões → documento) é a mesma da revalidação de fontes: quem
perder a corrida recebe 409/conflito sem estados parciais.

Storage: a base tem prioridade. As tarefas de limpeza são registadas na
tabela `storage_cleanup_tasks` **na mesma transação** que elimina os
registos — se o registo das tarefas falhar, a eliminação inteira faz
rollback (nunca há 204 sem limpeza agendada de forma durável). Depois do
commit, cada ficheiro é removido e a respetiva tarefa concluída; as que
falharem permanecem na tabela e são reconciliadas na eliminação seguinte
ou via `document_service.reconcile_pending_deletions` (concorrência-segura
com `FOR UPDATE SKIP LOCKED`). Limitação documentada do armazenamento
local síncrono: não é uma transação distribuída, não há fila nem daemon —
resíduos temporários de ficheiros são possíveis até à reconciliação
seguinte, mas nunca sem tarefa durável associada.

## Recuperação lexical experimental

`POST /api/v1/retrieval/search` permite a qualquer utilizador autenticado
pesquisar evidências da própria instituição. A rota delega num contrato
neutro `Retriever`; a implementação atual, `PostgresLexicalRetriever`, usa
o vetor lexical gerado dos chunks, `websearch_to_tsquery('simple', ...)`,
`@@` e `ts_rank_cd`.

A consulta considera apenas a versão `processed` de maior número por
documento e exclui documentos inativos, fora da validade, noutro idioma ou
noutra instituição. `official_only` é verdadeiro por omissão. A resposta
expõe conteúdo original e metadados da fonte, nunca campos internos, e não
gera uma resposta final.

Perguntas naturais ("Quando começam as aulas?") são suportadas por
pesquisa progressiva determinística (`app/retrieval/query_planning.py`):
primeiro a consulta exata atual; sem resultados, os termos informativos
(sem artigos, preposições, interrogativos e auxiliares comuns de PT/EN)
com AND; por fim com OR. A primeira estratégia com evidências vence e os
resultados nunca são misturados. Todos os filtros institucionais aplicam-se
a todas as estratégias; consultas com operadores explícitos (aspas, OR,
`-termo`) usam apenas a tentativa exata, preservando a intenção. Uma
pergunta simples composta apenas por termos funcionais ("O que é?") não
pesquisa de todo e devolve zero evidências — uma correspondência por
coincidência de palavras funcionais não tem valor informativo. Sem
chamadas adicionais a LLM, sem embeddings, sem stemming e sem sinónimos —
a baseline continua lexical e experimental, sem compreensão semântica.

Para dados anteriores ao chunking automático ou reconstrução
administrativa, execute `python -m scripts.rebuild_document_chunks`. O
script não reextrai ficheiros, substitui chunks idempotentemente e aceita
`--institution-id` e `--document-id`. Cada versão é relida sob lock; versões
citadas são ignoradas, registadas apenas pelo ID e motivo controlado, e
contabilizadas em `skipped_referenced`. O resumo contém found, processed,
chunks created, skipped referenced e failures.

Sobre esta baseline existe ainda a geração experimental de respostas
fundamentadas, documentada em [`docs/answering.md`](answering.md): o endpoint
independente `POST /api/v1/answering/ask` não persiste, enquanto
`POST /api/v1/conversations/{conversation_id}/ask` guarda atomicamente as
duas mensagens e snapshots apenas das fontes citadas. Ambos devolvem fallback
determinístico quando não há evidências.

Notas:

- a eliminação permanente é `DELETE /documents/{id}` (ver "Eliminação de
  documentos" acima) e só é permitida para documentos nunca citados; a
  desativação — `PATCH /documents/{id}` com `{"is_active": false}` — é a
  alternativa para documentos citados;
- o idioma de um documento deixa de ser alterável depois de existir
  pelo menos uma versão (409) — uma tradução é um novo documento lógico;
- o endpoint de conteúdo é paginado por caracteres (`offset` default 0,
  `limit` default 50000, máximo 100000) e responde 409 para versões que
  não estejam `processed`;
- exemplo de criação:

```json
POST /api/v1/documents
{
  "title": "Regulamento Académico 2026",
  "description": "Versão consolidada",
  "language": "pt",
  "source_url": "https://exemplo.edu/regulamento.pdf",
  "official_source": true,
  "valid_from": "2026-01-01",
  "valid_until": "2026-12-31"
}
```

## Testes

A partir de `backend/` (venv ativo, base de dados Docker em execução):

```powershell
pytest -q
ruff check .
mypy app tests
alembic upgrade head
alembic check
```

Os testes documentais usam PostgreSQL real e um diretório temporário
por teste para o armazenamento (nunca escrevem no storage de
desenvolvimento). A fixture de PDF é gerada deterministicamente em
`tests/pdf_utils.py`, sem dependências adicionais.

## Riscos e limitações do protótipo

- processamento síncrono: um PDF grande atrasa a resposta do upload;
- sem OCR: PDFs digitalizados ficam `failed`;
- sem DELETE nem retenção/limpeza de ficheiros de versões antigas;
- armazenamento local único (sem réplicas nem backup automático);
- o texto extraído fica integralmente no PostgreSQL — adequado ao
  volume de um protótipo, a rever quando a camada de retrieval for
  decidida;
- a extração de TXT/Markdown lê o ficheiro completo (limitado pelo
  máximo configurado por ficheiro);
- validação de tipo baseada em extensão + assinatura (PDF) + declaração
  MIME — suficiente para o protótipo, não é uma verificação forense de
  conteúdo.
