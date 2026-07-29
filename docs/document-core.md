# Núcleo Documental (Fase 2)

## Objetivo da fase

Esta fase acrescenta ao protótipo a base documental sobre a qual a
futura camada de recuperação de informação irá trabalhar: registo de
documentos institucionais, versionamento dos ficheiros, upload
controlado, armazenamento local abstrato, extração de texto e consulta
administrativa dos metadados e do texto extraído.

A etapa seguinte desta fase acrescentou a segmentação do texto extraído
em *chunks* internos (tabela `document_chunks`, sem endpoint público) —
ver a secção "Segmentos de documentos" em [`docs/database.md`](database.md).

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
do servidor).

## Extração com OCR local (PDFs digitalizados)

PDFs são analisados **página a página**, de forma determinística e
conservadora:

1. cada página tenta primeiro a extração nativa (pypdf, com modo de
   preservação de layout e fallback seguro para o modo simples);
2. uma página com pelo menos `DOCUMENT_OCR_MIN_NATIVE_CHARS` caracteres
   úteis usa o texto nativo — **o OCR nunca corre em páginas com texto
   nativo suficiente** e o mesmo texto nunca é duplicado por OCR;
3. para texto insuficiente, a inspeção estrutural reconhece imagens
   diretas, imagens dentro de Form XObjects, imagens inline e operações
   de desenho vetorial; uma exceção nesta análise fica explicitamente
   inconclusiva, nunca equivale a "sem imagem";
4. quando existe evidência visual, não existe texto ou a inspeção foi
   inconclusiva, a página é renderizada uma vez a baixa resolução (72 DPI,
   no máximo 1.000.000 pixels) para distinguir conteúdo de uma página
   aproximadamente vazia;
5. a deteção de vazio converte o preview para grayscale, ignora 2% de
   margem, usa a cor modal como fundo, tolera diferenças de até 18 níveis
   e considera ruído de até 0,1% dos pixels; os limiares são genéricos e
   não contêm regras específicas de documentos ou calendários;
6. pouco texto sem outro conteúdo visual mantém o texto nativo; pouco
   texto com conteúdo visual relevante escolhe OCR, sem combinar nem
   duplicar as duas fontes;
7. apenas uma página visualmente vazia permanece vazia. Se até o preview
   falhar, a página segue pelo caminho OCR e pelos seus limites/erros
   seguros, em vez de ser declarada vazia sem prova.

A ordem das páginas nunca muda e o separador persistido continua a ser
`PAGE_SEPARATOR = "\f"`. O runtime OCR (Tesseract, local e offline —
nenhum serviço externo, nenhuma rede, nenhum download de modelos) só é
verificado quando alguma página exige OCR; a sua ausência **não impede o
arranque da aplicação** nem o processamento de documentos nativos. Para
verificar o runtime local: `tesseract --version`.

O preview de decisão é sempre fechado e não substitui nem duplica uma
renderização OCR em alta resolução. Só páginas classificadas para OCR usam
a renderização normal, que também é sempre fechada.

Renderização e OCR são limitados por configuração (`.env.example`):
`DOCUMENT_OCR_DPI` (72–600), `DOCUMENT_OCR_MAX_PIXELS_PER_PAGE` (a
escala de renderização é reduzida automaticamente para nunca exceder o
limite), `DOCUMENT_OCR_TIMEOUT_SECONDS` e `DOCUMENT_OCR_MAX_PAGES`
(documentos com mais páginas OCR do que o limite falham de forma
controlada). O OCR pode ser desativado com `DOCUMENT_OCR_ENABLED=false`;
nesse caso, um documento que exija OCR fica `failed` com "OCR is
required for this document but is disabled.". O idioma do OCR deriva do
idioma persistido do documento (`pt` → `por`, `en` → `eng`; outros
idiomas usam o fallback explícito `DOCUMENT_OCR_LANGUAGES`, por omissão
`por+eng`). O processamento continua **síncrono**: o OCR pode aumentar
significativamente a latência do upload/reprocessamento de PDFs
digitalizados.

As linhas OCR são reconstruídas por geometria, sem depender da ordem
`block/paragraph/line` do Tesseract. Tokens vazios e confianças inválidas
são ignorados; coordenadas anómalas são limitadas apenas para os cálculos,
sem corrigir o texto reconhecido. O agrupamento usa sobreposição vertical,
distância entre centros e alturas medianas relativas. Depois, linhas são
ordenadas verticalmente e as palavras horizontalmente.

Dentro de cada linha, a largura mediana por carácter, a altura mediana e a
distribuição dos gaps distinguem espaço normal de separação de coluna. Um
outlier suficientemente grande gera `" | "` independentemente da resolução.
Uma célula esquerda pode ser associada à linha seguinte somente quando existe
alinhamento das margens, pequena distância vertical e uma coluna direita
observável na segunda linha; na dúvida, as linhas permanecem separadas. Não
há procura de datas ou termos, correção ortográfica, validação de ordinais,
interpretação semântica, grelha completa ou deteção de células fundidas.

Cada versão processada regista metadados de extração (expostos em
`DocumentVersionRead` e no relatório de diagnóstico, que **não**
reexecuta OCR):

- `extraction_method`: `native` (todas as páginas com conteúdo são
  nativas), `ocr` (todas exigiram OCR) ou `mixed`; páginas vazias não
  alteram, sozinhas, o método;
- `extraction_quality`: `high`/`medium`/`low` — regra conservadora e
  determinística: a pior qualidade entre as páginas com conteúdo
  (páginas OCR: `low` abaixo de `DOCUMENT_OCR_MIN_CONFIDENCE`, `high` a
  partir de 80 de confiança média, `medium` entre ambos);
- `extraction_warning`: presente quando o processamento **terminou com
  sucesso** mas com qualidade baixa ("OCR completed, but the extracted
  text may require manual review.") — qualidade baixa nunca é tratada
  como falha, e falha nunca usa este campo;
- `extraction_details`: metadados por página (método, contagens,
  confiança, qualidade, aviso) — nunca texto integral, imagens ou
  caminhos.

Versões históricas anteriores a esta funcionalidade mantêm estes campos
`NULL` (sem backfill). Falhas de OCR são controladas e seguras:
runtime indisponível, timeout, limite de páginas, resultado vazio numa
página necessária ou dados de idioma em falta deixam a versão `failed`
com uma mensagem curta; uma versão `failed` pode ser reprocessada
(`POST .../reprocess`) depois de instalar/ativar o OCR.

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

## Segmentação documental estruturada

`document_chunking_service.chunk_text` recebe somente o texto extraído e a
configuração de tamanho/overlap. Não depende de `UploadFile`, rota multipart,
filename, `source_url`, instituição, fornecedor de armazenamento ou OCR; uma
futura integração com API institucional pode alimentar o mesmo contrato.

A estratégia `structured_v1`:

1. separa páginas por `PAGE_SEPARATOR = "\f"`; páginas vazias não produzem
   chunks, a numeração começa em 1 e nenhum conteúdo inclui o separador;
2. constrói unidades contíguas com offsets globais e classifica heurísticas
   pequenas de `heading`, `paragraph`, `table_row` e `list_item`; uma linha
   curta genérica só é título quando está isolada por uma quebra em branco e
   existe conteúdo posterior, evitando confundir a primeira linha curta de um
   parágrafo corrido com um título;
3. mantém o título observado como `section_title` dos chunks subsequentes,
   sem copiar esse título artificialmente para `content`;
4. emite cada `table_row` pequena separadamente, sem a fundir com outra linha
   para preencher o limite;
5. agrupa parágrafos compatíveis e itens consecutivos (`list_block`) apenas
   dentro da mesma página/secção;
6. usa `character_fallback_v1` somente quando uma unidade individual excede
   `DOCUMENT_CHUNK_SIZE_CHARS`.

O fallback prefere quebra de linha, depois espaço e finalmente o limite da
janela. O overlap configurado existe apenas entre fragments da mesma unidade
longa, garante progresso e nunca passa para outra unidade ou página. Esses
chunks são marcados como `fallback_fragment`.

Todos os chunks continuam auditáveis:
`content == extracted_text[start_char:end_char]`; `end_char` é exclusivo,
SHA-256 é calculado sobre `content` original e `normalized_content` reutiliza
a normalização lexical existente. Chunks novos persistem `page_number`,
`section_title`, `structure_type` e `chunking_strategy`. Os tipos permitidos
são `heading`, `paragraph`, `table_row`, `list_item`, `list_block`, `mixed` e
`fallback_fragment`; as estratégias permitidas são `structured_v1` e
`character_fallback_v1`.

As quatro colunas são anuláveis. Chunks históricos permanecem válidos com
`NULL`, sem backfill e sem atribuição fictícia de página/estratégia. O fluxo
continua extração → chunking → substituição atómica → `processed`; versões
citadas permanecem bloqueadas. A persistência rejeita uma coleção nova vazia
antes de remover o conjunto anterior. Retrieval, ranking, `top_k`, answering,
prompts, OpenAI e `message_sources` não foram alterados por esta estratégia.

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
o vetor lexical gerado dos chunks (configuração FTS **por idioma**:
`portuguese`/`english`/`simple`, ver `app/retrieval/fts_config.py`),
`websearch_to_tsquery`, `@@` e `ts_rank_cd`.

A consulta considera apenas a versão `processed` de maior número por
documento e exclui documentos inativos, fora da validade, noutro idioma ou
noutra instituição. `official_only` é verdadeiro por omissão. A resposta
expõe conteúdo original e metadados da fonte, nunca campos internos, e não
gera uma resposta final.

Perguntas naturais ("Quando começam as aulas?") são suportadas por
variantes determinísticas (`app/retrieval/query_planning.py`): a consulta
exata, os termos informativos (sem artigos, preposições, interrogativos e
auxiliares comuns de PT/EN) com AND, e com OR. A partir do Momento 4, o
retriever executa **todas** as variantes permitidas, agrega os candidatos
num *candidate pool* limitado (deduplicado por `chunk_id`) e aplica um
**reranking lexical determinístico** (`app/retrieval/reranking.py`):
cobertura dos termos, frase exata, proximidade, ordem, título/secção,
benefício condicionado de `table_row` e comprimento, com o `ts_rank_cd`
apenas como sinal auxiliar. Ordinais padrão e intervalos numéricos
explícitos são canonizados na comparação de cobertura
(`app/retrieval/lexical_normalization.py`), sem corrigir OCR nem
interpretar datas. Um limiar mínimo (`RETRIEVAL_MIN_RELEVANCE_SCORE`) e a
dominância entre candidatos removem coincidências fracas; o `score` público
passa a ser a relevância lexical composta em `[0, 1]`. Todos os filtros
institucionais aplicam-se a todas as variantes; operadores explícitos
(aspas, OR, `-termo`) usam apenas a tentativa exata, preservando a intenção.
Uma pergunta composta apenas por termos funcionais ("O que é?") não pesquisa
de todo e devolve zero evidências. Sem LLM, sem embeddings e sem sinónimos —
a baseline continua lexical e experimental, sem compreensão semântica.

Para dados anteriores ao chunking automático ou reconstrução
administrativa, execute `python -m scripts.rebuild_document_chunks`. O
script não reextrai ficheiros, substitui chunks idempotentemente e aceita
`--institution-id` e `--document-id`. Cada versão é relida sob lock; versões
citadas são ignoradas, registadas apenas pelo ID e motivo controlado, e
contabilizadas em `skipped_referenced`. O resumo apresenta versões encontradas,
processadas e estruturadas, chunks gerados, `table_row`, fragments de fallback,
versões citadas ignoradas e falhas. O script usa apenas `extracted_text`
persistido: não reabre PDF, não executa OCR, não usa OpenAI/rede e não imprime
conteúdo.

Sobre esta baseline existe ainda a geração experimental de respostas
fundamentadas, documentada em [`docs/answering.md`](answering.md): o endpoint
independente `POST /api/v1/answering/ask` não persiste, enquanto
`POST /api/v1/conversations/{conversation_id}/ask` guarda atomicamente as
duas mensagens e snapshots apenas das fontes citadas. Ambos devolvem fallback
determinístico quando não há evidências.

## Diagnóstico do pipeline documental

`python -m scripts.diagnose_document_pipeline`, executado a partir de
`backend/`, é uma ferramenta interna, removível e exclusivamente de
diagnóstico. Ela observa os dados já persistidos de uma versão — metadados,
`extracted_text`, chunks e resultados do retriever lexical existente — e gera
um relatório técnico Markdown ou JSON. Não corrige nenhuma etapa e não altera
o comportamento da aplicação.

Pré-requisitos: PostgreSQL e a configuração normal do backend acessíveis,
migrations atualizadas, virtual environment existente ativa e um ID explícito
da instituição autorizada. O utilizador precisa ainda de um ficheiro JSON de
perguntas válido dentro da raiz do repositório e de acesso de escrita a
`docs/diagnostics/generated/`. Relatórios nessa diretoria são ignorados pelo
Git porque podem conter IDs e pequenos excertos institucionais.

Argumentos obrigatórios:

- `--institution-id UUID`, `--questions-file PATH` e `--output PATH`;
- exatamente um de `--document-id UUID`, `--version-id UUID` ou
  `--filename TEXT`.

Argumentos opcionais:

- `--format markdown|json` (padrão: `markdown`);
- `--reference-date YYYY-MM-DD` (padrão: data UTC atual);
- `--top-k INTEGER` entre 1 e 20 (padrão: 5);
- `--official-only` (padrão) ou `--include-non-official`;
- `--max-excerpt-chars INTEGER` entre 80 e 1000 (padrão: 240);
- `--overwrite`, necessário para substituir conscientemente um relatório.

A seleção por `document-id` usa a versão de maior número, qualquer que seja o
estado. A seleção por `version-id` usa exatamente a versão indicada. A seleção
por `filename` é exata e case-insensitive dentro da instituição; várias versões
do mesmo documento não são ambíguas, mas vários documentos lógicos com o mesmo
nome geram erro controlado. O nome nunca é usado para construir um caminho nem
para abrir o ficheiro armazenado.

O relatório distingue dois conceitos:

- `selected_version`: versão pedida explicitamente ou versão carregada mais
  recente do documento;
- `effective_retrieval_version`: versão `processed` de maior número que o
  retriever atual considera.

Assim, uma versão mais recente `failed` ou `processing` pode ser analisada ao
lado de uma versão processada anterior efetivamente usada na pesquisa. A
ausência de versão efetiva é registada como condição de elegibilidade, não
altera o documento nem dispara reprocessamento.

O ficheiro de perguntas é uma lista JSON não vazia. Cada item aceita apenas
`id`, `question`, `language`, `expected_answer` e `expected_facts`; cada facto
tem `name` e uma lista não vazia de `alternatives`. IDs duplicados, campos
desconhecidos e strings vazias são rejeitados. A fixture em
`backend/tests/fixtures/` é exclusivamente sintética. O exemplo sanitizado do
calendário está em
`docs/diagnostics/examples/calendar-2026-2027.example.json` e os respetivos
valores esperados devem ser confirmados por uma pessoa contra a fonte antes de
serem tratados como referência.

As conclusões principais são:

- `EXTRACTION_FAILURE`: facto esperado ausente de `extracted_text`;
- `CHUNK_INTEGRITY_FAILURE`: facto extraído ausente dos chunks ou chunk
  relevante com offsets/conteúdo incoerentes;
- `DOCUMENT_NOT_RETRIEVAL_ELIGIBLE`: os filtros atuais excluem a evidência;
- `RETRIEVAL_FAILURE`: evidência elegível existe, mas o conjunto recuperado não
  cobre todos os factos esperados;
- `PRE_GENERATION_PIPELINE_OK`: não foi detetada falha antes da geração; a
  formulação final deve ser analisada posteriormente.

Findings são riscos ou observações adicionais. Em particular,
`CONTEXT_FRAGMENTATION_RISK` significa que os factos estão divididos entre
chunks, mas isso não é automaticamente uma falha: o answering atual pode
receber vários chunks no mesmo contexto e o diagnóstico mede também a cobertura
pela união dos resultados. Outros findings assinalam proximidade/ocorrências
concorrentes, diferença entre versão selecionada e efetiva, uso de outro
documento ou ausência da versão efetiva.

A ferramenta aplica `institution_id` em todas as suas consultas SQL. Ao chamar
o retriever existente, reutiliza os filtros institucionais dele e verifica que
todos os resultados pertencem à instituição pedida. Antes das leituras inicia
uma transação PostgreSQL com `SET TRANSACTION READ ONLY`; não executa `commit` e
faz rollback no final, portanto uma escrita acidental é rejeitada pela própria
base. A sessão é sempre fechada pela CLI.

O diagnóstico não importa nem instancia o cliente OpenAI, não chama o answering
pipeline e não usa rede. Também não abre o PDF, não repete extração, não executa
OCR, não interpreta tabelas visualmente, não recria chunks, não muda retrieval,
não gera respostas e não modifica a base de dados.

Códigos de saída:

| Código | Significado |
| --- | --- |
| 0 | relatório concluído, mesmo quando identifica falha funcional |
| 2 | argumentos, paths ou ficheiro de perguntas inválidos |
| 3 | instituição não encontrada |
| 4 | documento não encontrado ou filename ambíguo |
| 5 | versão não encontrada ou documento sem versões |
| 6 | versão selecionada sem `extracted_text` utilizável |
| 7 | erro controlado de base de dados |
| 8 | falha na escrita atómica do relatório |
| 9 | destino existente sem `--overwrite` |

Exemplo Markdown, a partir de `backend/`:

```powershell
python -m scripts.diagnose_document_pipeline --institution-id "<INSTITUTION_ID>" --filename "Calendário Academico para Cursos de Graduação para o ano letivo de 2026-2027.pdf" --questions-file "../docs/diagnostics/examples/calendar-2026-2027.example.json" --output "../docs/diagnostics/generated/calendar-2026-2027.md" --format markdown --reference-date "2026-10-01" --top-k 5 --official-only
```

Para JSON, use o mesmo comando com output `.json` e `--format json`. Os dois
formatos são produzidos a partir do mesmo objeto interno; a renderização não
repete o retrieval. O único valor de domínio a substituir no exemplo é
`<INSTITUTION_ID>`. Não publique o resultado sem revisão humana e nunca force a
inclusão dos relatórios de `generated/` no Git.

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
