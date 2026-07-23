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

Os metadados do documento são copiados de linhas bloqueadas imediatamente
antes da inserção do turno. Edições posteriores não alteram citações históricas.
A FK do chunk sem cascata impede a eliminação ou reassociação de um chunk
citado. O trigger PostgreSQL
`trg_document_chunks_prevent_referenced_update` também rejeita qualquer
`UPDATE` numa linha citada. Reprocessamento e reconstrução consultam
`message_sources` com o mesmo bloqueio de `DocumentVersion` e rejeitam ou
ignoram versões citadas antes de alterar estado ou conteúdo.

### Vetor experimental de pesquisa lexical

A migração `b7e2d8a9f4c1` adiciona `search_vector TSVECTOR` como coluna gerada e
armazenada, calculada por `to_tsvector('simple', normalized_content)`. A
aplicação nunca a escreve manualmente. A configuração explícita `simple` evita
escolher stemming específico de português ou inglês antes de avaliar a
baseline. O índice GIN `ix_document_chunks_search_vector` suporta o operador
de correspondência `@@`.

`PostgresLexicalRetriever` usa `websearch_to_tsquery('simple', ...)`
parametrizado e `ts_rank_cd`. Seleciona apenas a versão `processed` de maior
número por documento e filtra em SQL pela instituição autenticada, estado
ativo, idioma, validade atual e `official_only` (verdadeiro por omissão). Os
chunks históricos permanecem armazenados.

#### Pesquisa lexical progressiva para perguntas naturais

Com `simple`, sem stopwords nem stemming, a baseline original exigia que
*todas* as palavras da pergunta correspondessem. Assim, “Quando começam as
aulas?” não encontrava um documento que contivesse apenas “aulas”. O
recuperador agora planeia variantes determinísticas
(`app/retrieval/query_planning.py`) e executa-as por prioridade estrita,
devolvendo o primeiro conjunto não vazio:

1. **exact** — consulta normalizada tal como foi escrita, sem alteração;
2. **reduced_and** — apenas os termos informativos, todos obrigatórios; palavras
   funcionais como artigos, preposições, interrogativos e auxiliares comuns são
   removidas por pequenas listas conservadoras para `pt` e `en`;
3. **reduced_or** — os mesmos termos informativos, sendo qualquer um suficiente.

Resultados e pontuações de estratégias diferentes nunca são misturados nem
comparados. Todas as variantes usam exatamente os mesmos filtros SQL:
instituição, estado ativo, idioma, validade, `official_only`, versão processada
mais recente, `top_k` e ordenação determinística. Nenhum fallback pesquisa num
âmbito mais amplo.

Consultas com sintaxe `websearch` explícita — frases entre aspas, `OR` ou
`-termos` negados — executam apenas a variante exata. Assim, uma intenção como
`matricula -propinas` nunca é relaxada para uma pesquisa que também encontre
“propinas”. Um idioma suportado sem lista própria de termos funcionais também
executa apenas a variante exata. Uma consulta simples formada somente por
termos funcionais, como “O que é?”, num idioma com lista conhecida não executa
**pesquisa alguma** e devolve zero evidências; uma correspondência seria uma
coincidência sem significado. Frases entre aspas mantêm a pesquisa exata mesmo
nesse caso. Tudo permanece determinístico e local: sem chamadas adicionais a
LLM, embeddings, stemming ou sinónimos. A abordagem continua uma baseline
experimental e **não** compreende semanticamente as perguntas.

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
  PATCH com 409. Não há endpoint de reabertura nesta fase.
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
ou híbrida, reranking, memória conversacional, agentes nem pontuação de
confiança, e o sistema não está livre de alucinações. O pgvector permanece
apenas como infraestrutura. Consulte [`docs/answering.md`](answering.md) para o
pipeline neutro em relação ao fornecedor, a semântica atómica dos turnos, os
snapshots das fontes e as limitações atuais.
