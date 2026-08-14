# Notas sobre a base de dados

## Histórico de migrações

| Ordem | Revisão | Descrição |
|---|---|---|
| 1 | `db13417f9dc4` | Ativa a extensão `pgvector` |
| 2 | `de4e133df3c9` | Cria a tabela `institutions` |
| 3 | `9cf6ff5ac49c` | Cria a tabela `users` com `institution_id` e os campos multi-institucionais necessários |
| 4 | `9ec09d09f22f` | Cria as tabelas `conversations` e `messages` |
| 5 | `3ed4bcad52c8` | Adiciona chaves estrangeiras multi-institucionais compostas e as restrições únicas que as suportam |
| 6 | `5f638cb2d2c3` | Adiciona restrições CHECK de valores de domínio para `users.role`, `conversations.status` e `messages.role` |
| 7 | `1482b165c943` | Cria as tabelas `documents` e `document_versions` (núcleo documental) |
| 8 | `68cb34527411` | Cria a tabela `document_chunks` e a restrição única de suporte em `document_versions` |
| 9 | `b7e2d8a9f4c1` | Adiciona o `search_vector` lexical gerado e o respetivo índice GIN |
| 10 | `c8b4f2d9e6a1` | Adiciona `reply_to_message_id`, `message_sources` persistidas, restrições compostas de integridade e o trigger de imutabilidade de chunks citados |
| 11 | `800e7b121e93` | Cria `storage_cleanup_tasks` (tarefas duráveis de limpeza de arquivos, enfileiradas na transação de eliminação do documento) |
| 12 | `f2a91c47d3b8` | Adiciona metadados de extração a `document_versions` (`extraction_method`, `extraction_quality`, `extraction_warning` e `extraction_details` JSONB; anuláveis e limitados por CHECK; linhas históricas permanecem NULL, sem backfill) |
| 13 | `4a7c1e9d2b63` | Adiciona metadados estruturais anuláveis a `document_chunks` (`page_number`, `section_title`, `structure_type`, `chunking_strategy`), com CHECKs e sem backfill |
| 14 | `e7b1c9d4a2f0` | Localiza o `search_vector` por idioma: a coluna gerada passa a escolher `portuguese`/`english`/`simple` pela subtag primária de `language`. Revectoriza os chunks históricos automaticamente, sem backfill; recria o índice GIN. Reversível para `simple` |
| 15 | `a5c31f70b8d2` | Adiciona o destino humano default a `institutions` (`human_support_name`, `human_support_email`, `human_support_url`; anuláveis, sem backfill) e o CHECK que exige configuração completa ou totalmente ausente |

Como o projeto ainda está em desenvolvimento exclusivamente local, sem
ambientes partilhados, dados de produção ou bases de dados permanentes, a
migração de `users` foi reescrita no próprio local para criar a tabela já com o
formato correto para o modelo multi-institucional, em vez de adicionar uma
quarta migração para alterá-la depois. Não existe uma migração separada para
“completar `users`”: a própria migração histórica está agora correta.

A tabela `users`, criada por `9cf6ff5ac49c`, possui:

- `id` — UUID, chave primária, gerado pela aplicação por omissão no ORM;
- `institution_id` — UUID, `NOT NULL`, chave estrangeira para
  `institutions.id`, indexado;
- `full_name` — `String(255)`, `NOT NULL`;
- `email` — `String(255)`, `NOT NULL`, globalmente único;
- `password_hash` — `String(255)`, `NOT NULL`;
- `role` — `String(50)`, `NOT NULL`, valor padrão do servidor `"user"`;
- `is_active` — `Boolean`, `NOT NULL`, valor padrão do servidor `true`;
- `created_at` — timestamp com fuso horário, `NOT NULL`, padrão `now()`;
- `updated_at` — timestamp com fuso horário, `NOT NULL`, padrão `now()`.

A unicidade de `email` continua global, não limitada por instituição. Isso não
mudou em relação ao desenho original e não foi revisto nesta etapa.

As tabelas `institutions`, `users`, `conversations` e `messages` possuem APIs
completas: gestão de instituições, gestão de utilizadores limitada à
instituição do administrador autenticado, autenticação baseada em JWT + Argon2
(login e registo do administrador inicial) e uma API de conversas/mensagens
limitada à instituição do utilizador autenticado — e, para não administradores,
às próprias conversas. Consulte
[`app/api/routes/institutions.py`](../backend/app/api/routes/institutions.py),
[`app/api/routes/users.py`](../backend/app/api/routes/users.py),
[`app/api/routes/auth.py`](../backend/app/api/routes/auth.py) e
[`app/api/routes/conversations.py`](../backend/app/api/routes/conversations.py).

Uma conversa pertence a uma instituição e a um utilizador e agrupa as mensagens
trocadas numa sessão do assistente. O endpoint conversacional experimental já
pode persistir um turno fundamentado completo, mas a abordagem final de
recuperação continua em aberto para a revisão da literatura. O pgvector
permanece disponível como infraestrutura e não é usado pela baseline lexical.

O `user_id` de uma mensagem regista o seu autor real: para `role="user"`, é o
utilizador que a enviou; para `role="system"`, é o administrador que a criou
manualmente (consulte `message_service.create_message`). Isso torna as mensagens
de sistema auditáveis. O campo só é `NULL` em mensagens automáticas
`"assistant"` criadas pelo fluxo de respostas conversacionais; o papel
`"system"` **não** implica um `user_id` nulo.

A migração `c8b4f2d9e6a1` adiciona o campo anulável
`messages.reply_to_message_id`. Mensagens do assistente criadas pelo fluxo de
respostas apontam para a mensagem do utilizador no mesmo turno. Uma chave
estrangeira composta `(reply_to_message_id, conversation_id, institution_id)`
garante que o alvo pertence à mesma conversa e instituição, e um CHECK rejeita
autorreferências. Mensagens manuais de utilizador ou sistema mantêm o campo nulo;
ele não é aceite por `MessageCreate`.

## Destino humano default (`institutions.human_support_*`)

A migração `a5c31f70b8d2` acrescenta a `institutions` a configuração mínima do
encaminhamento humano E1 (ver [`docs/answering.md`](answering.md)):

- `human_support_name` — `String(255)`, anulável;
- `human_support_email` — `String(320)`, anulável;
- `human_support_url` — `String(2048)`, anulável.

É **um único destino por instituição**. Não existem — nem devem ser inferidos
daqui — telefone, taxonomia de departamentos, regras de encaminhamento por
assunto, prioridade, horário de funcionamento, SLA, identificador de operador
ou fila.

A configuração vive num de dois estados, e o CHECK
`ck_institutions_human_support_configuration` recusa qualquer estado
intermédio. São duas condições combinadas — nenhum campo presente pode ser
vazio, e a forma do conjunto tem de ser válida:

```sql
   (human_support_name  IS NULL OR btrim(human_support_name,  E' \t\n\r\f\v') <> '')
AND (human_support_email IS NULL OR btrim(human_support_email, E' \t\n\r\f\v') <> '')
AND (human_support_url   IS NULL OR btrim(human_support_url,   E' \t\n\r\f\v') <> '')
AND (
       (human_support_name IS NULL
        AND human_support_email IS NULL
        AND human_support_url IS NULL)
    OR (human_support_name IS NOT NULL
        AND (human_support_email IS NOT NULL OR human_support_url IS NOT NULL))
)
```

Um nome sem contacto não encaminha ninguém; um contacto sem nome não identifica
o serviço. E um valor presente mas em branco é dado corrompido: `IS NOT NULL`
sozinho aceitaria `"   "` como nome e contacto, produzindo uma configuração
formalmente completa que o handoff apresentaria como um destino vazio. Cada
campo é validado **por si** — um email em branco é recusado mesmo quando existe
um URL válido que já satisfaria a exigência de "pelo menos um contacto".

O conjunto de corte do `btrim` é explícito de propósito. O `btrim(x)` sem
segundo argumento — o padrão usado em `document_chunks` — corta apenas
espaços, pelo que deixaria passar um valor composto só por tabs ou newlines. A mesma regra é aplicada antes do INSERT/UPDATE por
`is_valid_human_support_configuration` (`app/schemas/institution.py`) e por
`institution_service.validate_human_support_configuration`, que a avalia sobre
o **estado final** de um PATCH parcial — o que nenhum schema consegue fazer
sozinho. A constraint é a defesa em profundidade para quem contorne a API.

As três colunas começam `NULL` e **não recebem backfill**: nenhuma instituição
existente ganha um contacto que ninguém configurou, e o estado "tudo NULL"
satisfaz a constraint, pelo que a migração não falha sobre dados existentes.
Nenhum contacto institucional real entra no repositório; o seed de demonstração
usa valores sintéticos com o TLD reservado `.invalid`.

Os valores são validados de forma determinística por `app/core/contact.py`
antes de chegarem à base: o URL só pode ser `http`/`https`, e o email é
verificado estruturalmente (sem implementar a RFC 5322 nem acrescentar
dependências).

## Núcleo documental (`documents` e `document_versions`)

A migração `1482b165c943` adiciona a camada documental, intencionalmente
dividida em duas tabelas: `documents` representa o documento institucional
lógico (regulamento, calendário, manual etc.) e os seus metadados;
`document_versions` representa cada arquivo ou revisão concreta enviada, para
que um documento possa ser atualizado sem perder o histórico.

`documents` (todas as linhas limitadas por `institution_id`):

- `id` (UUID gerado pela aplicação), `institution_id` (FK para
  `institutions`) e `created_by_user_id`, com uma FK composta
  `(created_by_user_id, institution_id)` → `users(id, institution_id)`, que
  obriga o criador a pertencer à mesma instituição;
- `title`, `description`, `language` (sensível à instituição e resolvido pela
  mesma regra `resolve_language` das conversas), `source_url`,
  `official_source`, `is_active` e `valid_from`/`valid_until`, com um CHECK que
  exige `valid_from <= valid_until`;
- um `UNIQUE (id, institution_id)` degenerado que suporta as chaves
  estrangeiras compostas de `document_versions`.

`document_versions`:

- chaves estrangeiras compostas `(document_id, institution_id)` →
  `documents(id, institution_id)` e `(uploaded_by_user_id, institution_id)` →
  `users(id, institution_id)`; o próprio PostgreSQL rejeita combinações entre
  instituições;
- `UNIQUE (document_id, version_number)`, segunda defesa após o bloqueio
  `SELECT ... FOR UPDATE` usado para atribuir números de versão, e
  `UNIQUE (institution_id, checksum_sha256)`, pois o mesmo conteúdo pode existir
  em instituições diferentes, mas nunca duas vezes na mesma;
- CHECKs: `version_number > 0`, `size_bytes > 0`,
  `processing_status IN ('pending','processing','processed','failed')` e
  `page_count IS NULL OR page_count >= 0`;
- o arquivo binário reside no armazenamento local (`storage_path` é sempre
  relativo à raiz); o PostgreSQL guarda apenas metadados e o texto extraído
  (`extracted_text`).

Consulte [`docs/document-core.md`](document-core.md) para a documentação
completa da fase: endpoints, regras de upload, estados de processamento,
estrutura de armazenamento e limitações.

## Segmentos de documentos (`document_chunks`)

A migração `68cb34527411` adiciona `document_chunks`, os segmentos
determinísticos do texto extraído de cada versão. Os chunks são uma
**estrutura interna**: não há endpoint público, e `normalized_content`,
`content_sha256` e os offsets nunca são expostos pela API. Eles suportam as
experiências lexicais atuais enquanto a estratégia final de recuperação de
informação continua indefinida. RAG não é uma decisão arquitetural consolidada;
a fase 3 adiciona apenas a baseline lexical experimental descrita abaixo, sem
embeddings nem recuperação vetorial.

Cada linha possui:

- `id` (UUID gerado pela aplicação), `institution_id`, `document_id` e
  `document_version_id`, com uma FK composta de três colunas
  `(document_version_id, document_id, institution_id)` →
  `document_versions(id, document_id, institution_id)`, apoiada por um
  `UNIQUE (id, document_id, institution_id)` degenerado em `document_versions`.
  O PostgreSQL rejeita um chunk que aponte para uma versão, documento ou
  instituição incorretos; as verificações do serviço não são a única defesa;
- `chunk_index` (base zero e `UNIQUE (document_version_id, chunk_index)`),
  `content` (fatia original em que
  `content == extracted_text[start_char:end_char]`), `normalized_content`
  (consulte `app/core/text_normalization.py`: NFKD, sem diacríticos, com
  casefold e espaços colapsados, usado na pesquisa lexical),
  `content_sha256`, `start_char`/`end_char` (offset final exclusivo), `language`
  (herdado do documento no momento da segmentação) e `created_at`;
- `page_number` (base um), `section_title` (título observado, não copiado para
  `content`), `structure_type` (`heading`, `paragraph`, `table_row`,
  `list_item`, `list_block`, `mixed` ou `fallback_fragment`) e
  `chunking_strategy` (`structured_v1` ou `character_fallback_v1`). Estes quatro
  campos são anuláveis: linhas históricas permanecem `NULL`, sem backfill;
- CHECKs: `chunk_index >= 0`, `start_char >= 0`, `end_char > start_char`,
  `btrim(content) <> ''`, `btrim(normalized_content) <> ''`,
  `page_number IS NULL OR page_number > 0` e listas fechadas para tipo e
  estratégia;
- índices em `institution_id`, `document_id`, `document_version_id` e
  `(institution_id, language)`. O par `(document_version_id, chunk_index)` já
  é indexado pela restrição UNIQUE, portanto não há índice duplicado. Não
  existem colunas vetoriais ou de embeddings; o vetor lexical gerado abaixo
  não se relaciona com pgvector.

A segmentação integra o processamento síncrono
(`document_processing_service.process_version`): extração → segmentação
estruturada → substituição atómica do conjunto da versão
(`document_chunk_service.replace_version_chunks`, sem commit próprio) → versão
marcada como `processed`, tudo numa transação. `PAGE_SEPARATOR = "\f"` é uma
fronteira obrigatória: não entra em `content`, os offsets permanecem globais e
nenhum overlap atravessa página.

`structured_v1` classifica unidades contíguas por pequenas heurísticas locais:
títulos, parágrafos, linhas que contêm `" | "` e itens de lista. Linhas de
tabela que cabem no limite são chunks próprios e nunca são fundidas entre si;
parágrafos e listas só são agrupados quando página, secção e tipo são
compatíveis. `character_fallback_v1` é reservado a uma unidade individual
maior do que `DOCUMENT_CHUNK_SIZE_CHARS`; prefere quebra de linha/espaço e o
overlap fica dentro dessa unidade. Nenhuma etapa interpreta datas, corrige OCR
ou usa LLM. Uma linha curta sem marcador explícito só é tratada como título
quando está isolada por uma quebra em branco e existe conteúdo posterior.

Uma versão nunca fica `processed` sem os seus chunks. Uma falha na segmentação
ou persistência reverte a transação, não deixa chunks parciais e marca a versão
como `failed` com uma mensagem curta e segura. Uma versão `failed` não mantém
chunks; possuí-los equivale a estar `processed`. Uma substituição vazia é
rejeitada antes da remoção do conjunto existente. O reprocessamento substitui
apenas os chunks da versão, protegido pelo mesmo `SELECT ... FOR UPDATE`.
Versões históricas preservam os seus conjuntos, e o upload de uma nova versão
nunca altera as anteriores.

O rebuild administrativo continua a usar exclusivamente `extracted_text`
persistido e ignora versões citadas. Não reabre PDF nem executa OCR. O
retrieval lexical continua a consultar somente `content`,
`normalized_content`/`search_vector`; os novos metadados não participam no
ranking, filtros, score ou `top_k`. Answering e snapshots de `message_sources`
também permanecem inalterados.

## Fontes de mensagens persistidas (`message_sources`)

A migração `c8b4f2d9e6a1` adiciona uma linha por fonte efetivamente citada numa
mensagem do assistente. Ela guarda o ID da evidência, a ordem da citação, um
snapshot de metadados públicos do documento e `content_sha256`.
`institution_id` existe apenas para garantir integridade entre instituições; a
linha nunca guarda `user_id`, perfil institucional, pergunta, resposta,
conteúdo do chunk, prompt, resposta do fornecedor, tokens ou credenciais.

A integridade é aplicada no PostgreSQL, não apenas nos serviços:

- `(message_id, institution_id, message_role)` referencia
  `messages(id, institution_id, role)` com `ON DELETE CASCADE`, e um CHECK exige
  `message_role='assistant'`;
- `(chunk_id, document_version_id, document_id, institution_id)` referencia a
  mesma identidade de quatro colunas em `document_chunks`, sem cascata de
  eliminação;
- `reply_to_message_id` e ambas as FKs dependem de restrições UNIQUE explícitas,
  preservando a consistência da conversa e da instituição;
- cada mensagem possui `evidence_id`, `citation_index` e `chunk_id` únicos;
  CHECKs validam índices, formato da evidência (`E1`, `E2`...), título e idioma
  não vazios, tamanho do checksum e intervalo de validade;
- índices de consulta cobrem instituição, chunk, documento e versão. Os índices
  UNIQUE já cobrem o acesso por mensagem/citação, evitando duplicados.

A **admissibilidade documental** avaliada na revalidação não é definida pelo
service. É a política `CitationPersistenceEligibility` de
`app/documents/retrievability.py`, aplicada por `revalidate_and_lock_sources`
através de `explain`, sobre as linhas já bloqueadas. Essa política partilha as
condições base com `RetrievalEligibility` mas **não** inclui a da versão
`processed` mais recente: uma versão superada por N+1 durante a geração
continua a ser a fonte real da resposta e continua admissível aqui. O service
nunca resolve a versão efetiva. O que permanece do lado do service é matéria
distinta — consistência dos identificadores (defesa em profundidade sobre a FK
composta), deteção de metadados alterados durante a geração e integridade do
snapshot (checksums, normalização, coerência com `extracted_text`). Depois de
persistida, a linha é histórica: a leitura devolve o snapshot tal como foi
gravado, sem reavaliar política alguma.

Os metadados do documento são copiados de linhas bloqueadas imediatamente
antes da inserção do turno. Edições posteriores não alteram citações históricas.
A FK do chunk sem cascata impede a eliminação ou reassociação de um chunk
citado. O trigger PostgreSQL
`trg_document_chunks_prevent_referenced_update` também rejeita qualquer
`UPDATE` numa linha citada. Reprocessamento e reconstrução consultam
`message_sources` com o mesmo bloqueio de `DocumentVersion` e rejeitam ou
ignoram versões citadas antes de alterar estado ou conteúdo.

### Vetor de pesquisa lexical localizado por idioma

A migração `b7e2d8a9f4c1` introduziu `search_vector TSVECTOR` como coluna gerada
e armazenada; a migração `e7b1c9d4a2f0` (Momento 4) substitui a expressão única
`simple` por uma seleção de configuração FTS **por idioma**, escolhida pela
subtag primária de `language`:

```sql
CASE
    WHEN lower(split_part(language, '-', 1)) = 'pt'
        THEN to_tsvector('portuguese'::regconfig, normalized_content)
    WHEN lower(split_part(language, '-', 1)) = 'en'
        THEN to_tsvector('english'::regconfig, normalized_content)
    ELSE to_tsvector('simple'::regconfig, normalized_content)
END
```

A aplicação nunca escreve a coluna manualmente. O nome da configuração é sempre
um literal fixo (`portuguese`/`english`/`simple`); `language` é uma referência a
coluna, nunca input interpolado. A seleção é centralizada em
`app/retrieval/fts_config.py` (`resolve_fts_config`), usada tanto na coluna
gerada como na `websearch_to_tsquery` da consulta, para que ambas usem sempre a
mesma configuração para o mesmo idioma. O stemming do PostgreSQL melhora a
**recuperação** (ex.: `matrícula`/`matrículas`, `começa`/`começam` colapsam no
mesmo stem em `portuguese`; `enrollment`/`enrollments` em `english`). Como o
`normalized_content` já vem sem acentos, o stemming atua sobre texto sem
diacríticos; alguns pares (`avaliar`/`avaliação`, `mudar`/`mudança`) **não**
colapsam nesse regime — nem no FTS, nem na cobertura (que compara formas de
superfície/canónicas, não stems). Um chunk cuja evidência usa uma dessas
variantes é recuperado e ordenado pelos **restantes** termos da pergunta: por
exemplo, a linha "Mudança do regime de avaliação | Até 6 de novembro" fica em
primeiro para "mudar o regime de avaliação" porque cobre `regime` e
`avaliação` (não porque `mudar` seja associado a `mudança`). Chunks históricos
são revectorizados automaticamente pela coluna gerada, sem backfill. O índice
GIN `ix_document_chunks_search_vector` suporta `@@`.

#### Etapa A — candidate generation

`PostgresLexicalRetriever` planeia variantes determinísticas da consulta
(`app/retrieval/query_planning.py`) e executa-as **todas** contra o índice GIN,
com a configuração FTS do idioma. Por ordem de prioridade:

| Estratégia | Uso | Prioridade | Segurança |
| --- | --- | --- | --- |
| `exact` | consulta normalizada tal como foi escrita | 4 | preserva integralmente a intenção; única variante permitida com sintaxe explícita |
| `reduced_and` | termos informativos, todos obrigatórios | 3 | conjuntiva: só relaxa palavras funcionais |
| `canonical_relaxed_and` | termos **contextuais** (sem ordinais/intervalos), todos obrigatórios | 2 | o ordinal/intervalo sai apenas da consulta FTS e continua obrigatório na elegibilidade |
| `reduced_or` | termos informativos, qualquer um suficiente | 1 | máxima recuperação; a elegibilidade filtra o ruído |

A `canonical_relaxed_and` existe para o caso em que a pergunta e o documento
escrevem a mesma coisa de formas diferentes: “exames da **primeira** chamada”
⇄ “Exames da **1.ª** chamada”, ou “inscrições de **01a12**” ⇄ “inscrições
**1 a 12**”. A consulta FTS passa a ser apenas `exames chamada` /
`periodo inscricoes`; o marcador canónico (`ord:1`, `rng:1-12`) volta a ser
exigido na fase de elegibilidade. **Nunca** se pesquisa pelo dígito do ordinal
nem pelos endpoints do intervalo isolados: `primeira` jamais se torna
`primeira OR 1` — se o fizesse, a pergunta “primeira” recuperaria “Sala 1”.
Uma consulta composta apenas por ordinais/intervalos (“primeira”, “01a12”) não
tem contexto que a ancore e planeia **só** a variante exact.

Os candidatos de todas as variantes são **agregados** e deduplicados por
`chunk_id`, preservando a melhor estratégia e o melhor `ts_rank_cd`. O teto do
candidate pool é um **orçamento global decidido antes das consultas**:

```
global_candidate_limit = min(100, max(20, top_k × 5))
```

Esse orçamento é repartido por **quotas** entre as variantes ativas (divisão
inteira, com o resto atribuído às variantes mais prioritárias), e cada consulta
SQL usa a sua quota como `LIMIT`. Nenhuma consulta corre sem `LIMIT` e a soma das
quotas nunca excede o orçamento.

Daí decorrem duas garantias, que importa não confundir com uma terceira que
**não** é oferecida:

- **não existe corte global por `ts_rank_cd` cru depois da agregação** — tudo o
  que as consultas devolvem é avaliado (`candidates_evaluated ==
  unique_after_dedup` no trace);
- a quota de cada variante é **reservada**: um candidato `exact` com FTS baixo
  não compete por espaço com candidatos de variantes menos prioritárias, por
  mais alto que seja o FTS destes;
- o que **não** se garante: uma variante cujas correspondências excedam a sua
  própria quota continua a ficar pelos melhores `ts_rank_cd` dessa variante. O
  orçamento é finito por desenho, e um candidato pode ficar de fora se dezenas
  de outros do mesmo tipo tiverem FTS superior.

Uma única consulta traz
também os metadados estruturais (`page_number`, `section_title`,
`structure_type`) usados no ranking, sem N+1. Todas as variantes aplicam
**exatamente** os mesmos filtros SQL: instituição, estado ativo, idioma,
validade, `official_only`, versão `processed` mais recente. O reranker nunca
recebe chunks de outra instituição.

Esses filtros **não são definidos pelo retriever**. São a política
`RetrievalEligibility` de `app/documents/retrievability.py`, aplicada por
`_build_statement` através de `as_sql_filters`, com a versão `processed`
efetiva pela subquery canónica do mesmo módulo. Continuam a executar no
PostgreSQL; o que pertence ao retrieval lexical é o mecanismo de pesquisa —
correspondência FTS, quotas, ordenação e `LIMIT`.

Consultas com sintaxe `websearch` explícita — frases entre aspas, `OR` ou
`-termos` negados — planeiam apenas a variante exata, para que a intenção nunca
seja relaxada (`matricula -propinas` nunca volta a procurar “propinas”). Uma
consulta formada só por termos funcionais (“O que é?”) num idioma com lista
conhecida não executa pesquisa alguma e devolve zero evidências.

#### Etapa B — elegibilidade e ranking

A etapa B tem **duas fases distintas**, e essa separação é deliberada: o score
ordena candidatos, **não decide** o que é evidência.

**Fase 1 — elegibilidade** (`app/retrieval/eligibility.py`). Decisão pura sobre
os sinais que dependem só do conteúdo (cobertura, frase exata, ordem,
proximidade) e a estratégia que recuperou o candidato:

- **consulta sem termos informativos** — nenhum candidato é elegível;
- **consulta de um termo** — elegível quando há correspondência de superfície,
  ou quando o candidato foi recuperado por stemming legítimo do PostgreSQL
  (`matrículas` ⇄ `matrícula`), o que se verifica sempre que o índice GIN o
  devolveu;
- **consulta de dois ou mais termos** — é preciso pelo menos uma condição forte:
  1. sintaxe websearch explícita (aspas, `OR`, `-termo`): o utilizador escreveu
     os operadores e o sistema honra essa intenção sem a reavaliar por
     cobertura;
  2. frase exata no conteúdo;
  3. estratégia conjuntiva (`exact` ou `reduced_and`);
  4. `canonical_relaxed_and` com **todos** os termos contextuais correspondidos
     e **pelo menos um** ordinal/intervalo canónico correspondido;
  5. cobertura mínima: `required_matches = max(2, ceil(nº de termos × 0.5))`
     termos correspondidos **e** cobertura ≥ `0.5`.

A distinção entre (1) e (3) importa para a honestidade do trace. A estratégia
`exact` é usada em dois papéis: numa consulta normal prova que a tsquery
**conjuntiva** casou os termos exigidos; numa consulta com operadores explícitos
a mesma estratégia pode ser deliberadamente **disjuntiva** (`aulas OR exames`
casa um dos lados por desenho). Por isso a base registada é `explicit_syntax` e
não `conjunctive_strategy` — classificar uma união como prova conjuntiva seria
factualmente errado. Em qualquer dos casos, cobertura zero continua a excluir.
O token `or` nunca conta como termo informativo: é sempre um operador para o
PostgreSQL.

Um candidato com **cobertura zero** numa consulta multi-termo nunca é elegível —
mesmo que o título corresponda, a secção corresponda, o `ts_rank_cd` seja
elevado, seja uma `table_row` ou seja muito curto. Uma correspondência de 1
termo numa pergunta de 3 não é evidência: o retrieval devolve vazio e o
answering responde `insufficient_evidence`.

**Fase 2 — ranking** (`app/retrieval/reranking.py`), aplicado **apenas** aos
elegíveis, com pesos que são **constantes versionadas** no módulo (não
configuráveis). O score é uma soma ponderada de sinais em `[0, 1]`, com a
cobertura dominante:

| Sinal | Peso |
| --- | --- |
| cobertura dos termos canónicos no conteúdo | 0.40 |
| frase exata (sequência informativa contígua) | 0.16 |
| proximidade | 0.14 |
| ordem dos termos | 0.08 |
| sobreposição com o título do documento | 0.07 |
| benefício condicionado de `table_row` | 0.06 |
| sobreposição com o título da secção | 0.05 |
| `ts_rank_cd` normalizado × fator de comprimento | 0.02 |
| qualidade da estratégia | 0.02 |

O título e a secção só são **calculados** depois da elegibilidade: por
construção, não podem criar evidência, apenas desempatar entre candidatos que já
correspondem no conteúdo.

A proximidade combina quantos termos foram encontrados com quão juntos aparecem:

```
positional_coverage = posições correspondidas / termos da pergunta
compactness         = posições correspondidas / span
proximity           = positional_coverage × compactness
```

Sem correspondências vale `0`; numa consulta de um só termo vale `1.0`; numa
consulta multi-termo, **uma única correspondência nunca chega a `1.0`** (fica em
`1/n`). O benefício de `table_row` usa a *compacidade*, não a proximidade
composta.

A comparação de cobertura usa formas canónicas
(`app/retrieval/lexical_normalization.py`): ordinais padrão (`1.ª`, `1º`, `1o`,
`primeira`… ⇒ `ord:1`) e intervalos numéricos **explícitos** (`01 a 12`,
`01-12`, `01–12`, `01a12`, `1 a 12` ⇒ o mesmo `rng:1-12`). O intervalo é **uma
unidade posicional única** do stream canónico, pelo que participa em cobertura,
frase exata, ordem, proximidade e posições como qualquer outro termo; os
endpoints continuam disponíveis numa representação auxiliar, ancorada na posição
do marcador, sem quebrar a sua contiguidade. Cardinais isolados nunca viram
ordinais (`12` ≠ `ord:1`; `22` ≠ `ord:2`); uma sequência sem separador nunca é
dividida (`0509`, `2206`, `20262027`). O OCR não é corrigido: `Ro` continua
palavra, `12` continua cardinal.

Os candidatos removidos são classificados por **motivo tipado**, registado no
trace: `no_content_match`, `insufficient_coverage` e `below_threshold`. O limiar
(`RETRIEVAL_MIN_RELEVANCE_SCORE`, padrão `0.05`) aplica-se **depois** da
elegibilidade e a **todos** os candidatos elegíveis, incluindo o melhor e
incluindo correspondências de frase exata: se todos ficarem abaixo, o resultado
é vazio. O limiar não substitui o gate de cobertura — é um piso residual sobre
candidatos já elegíveis.

**Não existe dominância por subconjunto.** A deduplicação por `chunk_id` já
elimina o mesmo chunk recuperado por várias variantes; chunks **diferentes**
nunca são removidos por corresponderem a menos termos do que outro. Evidência
complementar é preservada e simplesmente ordenada abaixo — quantos resultados
usar é decisão do `top_k`, que não é uma exclusão por relevância.

A ordenação final é totalmente determinística (score↓, cobertura↓, estratégia↓,
`ts_rank_cd`↓, `document_id`↑, `chunk_index`↑, `chunk_id`↑).

O `score` público de `Evidence` passa a representar esta **relevância lexical
composta** em `[0, 1]`, não o valor cru de `ts_rank_cd` (que fica disponível só
no trace interno de diagnóstico). Tudo permanece determinístico e local: sem
embeddings, sem pesquisa vetorial/semântica, sem LLM e sem sinónimos no
retrieval.

### Contrato de resultado do retrieval

`Retriever.search` devolve um `RetrievalResult` (`app/retrieval/base.py`), não
uma lista de evidências:

| Campo | Semântica |
| --- | --- |
| `evidence` | tupla imutável, pela ordem do ranking, já cortada por `top_k` |
| `trace` | `RetrievalTrace` — `candidates_evaluated` e `result_count_before_limit` |
| `score_semantics` | `ScoreSemantics` — como interpretar `Evidence.score` |

O trace genérico é **sempre** produzido e atravessa o contrato. O retriever
lexical devolve `LexicalRetrievalTrace`, uma subclasse que acrescenta variantes,
quotas, `ts_rank_cd` cru, sinais de ranking e os motivos de exclusão
(`no_content_match`, `insufficient_coverage`, `below_threshold`). Esses motivos
são conceitos lexicais — "cobertura" é uma fração de termos correspondidos — e
por isso ficam na subclasse: o contrato neutro tem de continuar válido para uma
estratégia que não tenha termos.

As duas contagens neutras são o que separa "não havia candidatos" de "havia
candidatos e nenhum sobreviveu", e a diferença entre `result_count_before_limit`
e `len(evidence)` diz se o `top_k` truncou. **Não existe** um valor agregado que
resuma o resultado: um estado como "suficiente" afirmaria que a evidência chega
para responder, o que o retrieval não sabe — é uma propriedade da relação entre
o pedido e a evidência, não da pesquisa.

`ScoreSemantics` declara `kind` (`lexical_relevance`), `version` (a identidade da
configuração de pesos e limiar, em `app/retrieval/reranking.py`) e
`comparable_across_queries`, que é **`False`** para o score lexical. Isso deriva
do algoritmo e não de prudência: `coverage` é uma fração do número de termos
*daquela* pergunta, e `exact_phrase`, `ordered` e `proximity` valem `1.0` por
construção numa pergunta de um só termo. Comparar scores entre perguntas
diferentes compara sobretudo o comprimento das perguntas.

Nada disto entra na API pública: o payload de `POST /api/v1/retrieval/search`
mantém exatamente os mesmos campos por item.

Limites que a abordagem **não** ultrapassa, e que importa não confundir com
capacidades:

- o stemming do PostgreSQL atua apenas na **geração de candidatos**; o reranker
  não faz lematização geral. `mudar` e `mudança` não são garantidamente
  equivalentes, e o único motivo pelo qual a linha correta vence é cobrir
  `regime` e `avaliação`;
- não existem sinónimos, nem institucionais nem gerais;
- não existe compreensão semântica das perguntas nem interpretação de datas;
- o OCR não é corrigido nem adivinhado;
- o `score` não é uma probabilidade nem uma confiança factual;
- **o resultado pode ser vazio**, e essa é uma resposta legítima do sistema.

O retrieval opera exclusivamente sobre chunks **já persistidos**: não depende do
`UploadFile`, do armazenamento local, do nome do ficheiro nem da rota de upload.
Documentos obtidos futuramente por uma API institucional externa serão
recuperáveis do mesmo modo, desde que os seus chunks estejam persistidos e
elegíveis; esta branch não adiciona qualquer cliente, connector, scheduler ou
worker para essa integração.

## Regras de segurança institucional

Estas regras foram adicionadas depois de uma revisão de segurança identificar
que a API de instituições era totalmente pública e algumas invariantes
multi-institucionais não eram aplicadas. Elas complementam a limitação por
`institution_id` em cada pedido descrita acima.

- **Ainda não existe o papel `platform_admin`.** Criar uma instituição
  (`POST /api/v1/institutions`) e registar o primeiro administrador
  (`POST /api/v1/auth/register-initial-admin`) são operações de inicialização,
  protegidas por `BOOTSTRAP_TOKEN` no cabeçalho `X-Bootstrap-Token`, não por um
  JWT, pois nesse momento ainda não existe administrador. Token ausente,
  incorreto ou não configurado falha de forma segura com 401. É um substituto
  temporário até existir um papel real de administração da plataforma; consulte
  o [fluxo de inicialização no README](../README.md#inicialização-de-uma-instituição).
- **Ler ou atualizar uma instituição exige um administrador autenticado e fica
  limitado à própria instituição.** `GET /api/v1/institutions`,
  `GET /api/v1/institutions/{id}` e `PATCH /api/v1/institutions/{id}` exigem um
  JWT de administrador válido. Para autorização, o `institution_id` nunca vem
  do payload ou caminho, apenas do utilizador autenticado. Outro `id` é
  informado como 404 (`resource_not_found`), tal como uma instituição
  inexistente, sem confirmar a existência de outro locatário.
- **O campo `is_active` da instituição é verificado em todos os pedidos
  autenticados, não apenas no login.** `get_current_user` volta a verificar o
  estado do utilizador e da instituição em cada chamada. Desativar uma
  instituição invalida imediatamente todos os tokens dos seus utilizadores,
  que recebem 401 no pedido seguinte, inclusive em `/auth/me`. O login também
  falha com 401 e mensagem genérica se a instituição estiver inativa, usando o
  mesmo texto de uma palavra-passe incorreta para não revelar o motivo.
- **Uma instituição deve manter sempre pelo menos um administrador ativo.** Em
  `PATCH /api/v1/users/{id}`, um administrador nunca pode desativar a própria
  conta. Se um utilizador for o último administrador ativo, desativá-lo ou
  alterar o seu papel é rejeitado com 409 `resource_conflict`. Com dois ou mais
  administradores ativos, um deles pode desativar ou alterar o papel de outro.
- **`register_initial_admin` é seguro contra condições de corrida e recusa
  instituições inativas.** Um bloqueio `SELECT ... FOR UPDATE` na instituição
  serializa dois registos concorrentes; apenas um tem sucesso e o outro recebe
  409. O serviço também rejeita com 409 o primeiro administrador de uma
  instituição inativa, pois essa conta não conseguiria iniciar sessão.
- **A invariante do último administrador é aplicada transacionalmente.** Quando
  `PATCH /api/v1/users/{id}` desativaria ou rebaixaria o último administrador,
  `user_service.update_user` bloqueia a instituição antes de contar os
  administradores ativos. Pedidos concorrentes ficam serializados e o segundo
  só volta a contar depois do commit do primeiro.
- **Um administrador institucional não pode ativar ou desativar a própria
  instituição.** `PATCH /api/v1/institutions/{id}` usa
  `InstitutionAdminUpdate`, que não possui `is_active` e define
  `extra="forbid"`; enviar o campo devolve 422. A única forma de alterar esse
  estado é `PATCH /api/v1/bootstrap/institutions/{id}/status`, protegido por
  `X-Bootstrap-Token` e limitado a `{"is_active": bool}`. Consulte o
  [fluxo no README](../README.md#reativação-de-uma-instituição).
- **O PostgreSQL aplica diretamente a consistência entre instituições, não
  apenas o código da aplicação.** A migração `3ed4bcad52c8` adiciona restrições
  únicas degeneradas em `(id, institution_id)` para `users` e `conversations`
  e substitui as chaves estrangeiras simples por compostas:
  `conversations.(user_id, institution_id)` → `users.(id, institution_id)`,
  `messages.(conversation_id, institution_id)` →
  `conversations.(id, institution_id)` e
  `messages.(user_id, institution_id)` → `users.(id, institution_id)`. A última
  é ignorada pelo PostgreSQL quando `user_id` é `NULL`, conforme `MATCH SIMPLE`.
  A base rejeita diretamente conversas e mensagens cujas referências pertençam
  a outra instituição.
- **O `status` de uma conversa controla novas atividades.** Apenas `active`
  aceita novas mensagens ou atualizações PATCH. `closed` e `archived` são
  estados **finais** neste protótipo: ambos rejeitam novas mensagens e qualquer
  PATCH com 409. Não há endpoint de reabertura nesta fase. O mesmo vale para o
  encaminhamento humano: `POST .../handoff` responde 409 numa conversa não
  ativa, sem criar mensagem.
- **O destino do encaminhamento humano vem sempre da instituição do utilizador
  autenticado.** `POST /api/v1/conversations/{id}/handoff` não aceita payload;
  `institution_id`, `user_id`, `destination`, `decision_outcome` e
  `handoff_trigger` nunca são lidos do cliente. Uma conversa de outro tenant
  responde 404 — o mesmo comportamento do restante módulo conversacional —, e
  a verificação de acesso precede a validação do destino, para que a resposta
  não varie consoante a instituição do requisitante ter atendimento
  configurado.
- **O `language` de conversas e mensagens é sempre sensível à instituição.** Em
  `POST /api/v1/conversations`, a omissão herda
  `institution.default_language`; um valor fornecido é normalizado e deve
  pertencer a `institution.supported_languages`, ou o pedido recebe 422. Em
  `POST .../messages`, a omissão herda o idioma da conversa e um valor
  fornecido é validado da mesma forma. A regra está centralizada em
  `app.core.language.resolve_language`, usado por `conversation_service` e
  `message_service`. Remover o idioma padrão da lista de suportados já era
  rejeitado por `institution_service.update_institution`; conversas históricas
  não são migradas quando a lista muda.

## Estado atual

O projeto inclui um fluxo experimental completo de respostas fundamentadas por
pesquisa lexical, com persistência transacional opcional nas conversas. A
abordagem definitiva permanece em aberto: não há embeddings, pesquisa semântica
ou híbrida, reranking por modelo, memória conversacional, agentes nem pontuação
de confiança, e o sistema não está livre de alucinações. O reranking existente é
lexical e determinístico (ver a etapa B acima). O pgvector permanece
apenas como infraestrutura. Consulte [`docs/answering.md`](answering.md) para o
pipeline neutro em relação ao fornecedor, a semântica atómica dos turnos, os
snapshots das fontes e as limitações atuais.
