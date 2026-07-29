# Assistente Institucional Agêntico

Protótipo de backend para um assistente genérico e multi-institucional de ensino
superior. A abordagem de recuperação de informação (por exemplo, RAG) ainda será
escolhida por meio de uma revisão da literatura e não constitui, por enquanto,
uma decisão arquitetural.

A aplicação Python encontra-se integralmente em [`backend/`](backend/). O Docker
Compose na raiz do repositório executa apenas o PostgreSQL (com pgvector); a
aplicação FastAPI é executada localmente a partir de `backend/`, não num contentor.

Uma interface web mínima encontra-se em [`frontend/`](frontend/) (React +
TypeScript + Vite). Ela demonstra o fluxo completo — iniciar sessão, manter uma
conversa fundamentada com fontes e gerir documentos como administrador — sem
Swagger nem pedidos manuais. O servidor de desenvolvimento encaminha `/api` para
o backend (mesma origem, sem CORS permissivo); consulte
[`frontend/README.md`](frontend/README.md). Início rápido:

```bash
cd frontend
npm ci
npm run dev   # http://localhost:5173, backend em http://127.0.0.1:8000
```

## Pré-requisitos

- Python 3.12
- Docker (para PostgreSQL + pgvector)

## Configuração

### 1. Criar o arquivo de ambiente

A partir da raiz do repositório:

```powershell
Copy-Item .env.example .env
```

Edite `.env` com os seus valores locais. `DATABASE_URL` deve corresponder aos
valores `POSTGRES_*` abaixo e à porta exposta em `POSTGRES_HOST_PORT`. Defina
também `BOOTSTRAP_TOKEN` com um valor aleatório longo — consulte
[Inicialização de uma instituição](#inicialização-de-uma-instituição).

### 2. Iniciar o PostgreSQL (Docker Compose)

A partir da raiz do repositório:

```powershell
docker compose up -d
docker compose ps
```

Isso inicia um único serviço `database` (`pgvector/pgvector:pg17`). É o único
contentor deste projeto — não há contentor para a API.

### 3. Criar o ambiente virtual Python

A partir de `backend/`:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Aplicar as migrações

A partir de `backend/` (com o ambiente virtual ativo):

```powershell
alembic upgrade head
```

### 5. Criar a instituição de demonstração (opcional)

A partir de `backend/` (com o ambiente virtual ativo):

```powershell
python -m scripts.seed_demo_institution
```

### 6. Executar a API localmente

A partir de `backend/` (com o ambiente virtual ativo):

```powershell
uvicorn app.main:app --reload
```

A API fica disponível em `http://127.0.0.1:8000`, com documentação interativa
em `http://127.0.0.1:8000/docs`.

### 7. Executar os testes

A partir de `backend/` (com o ambiente virtual ativo):

```powershell
pytest -q
```

Os testes usam uma base de dados dedicada (consulte
`backend/tests/conftest.py`) e nunca alteram a base de desenvolvimento.

### 8. Validar antes de fazer commit

A partir de `backend/` (com o ambiente virtual ativo), execute as mesmas
verificações usadas pela integração contínua:

```powershell
pytest -q
ruff check .
mypy app tests
alembic upgrade head
alembic check
```

## Inicialização de uma instituição

Ainda não existe o papel `platform_admin`. Por isso, a criação de uma
instituição e o registo do seu primeiro administrador não são endpoints
abertos: são protegidos pelo segredo partilhado `BOOTSTRAP_TOKEN` (definido em
`.env`), enviado no cabeçalho `X-Bootstrap-Token`. Trata-se de um substituto
temporário e explícito para a administração ao nível da plataforma, destinado
apenas à inicialização local ou de desenvolvimento.

As operações regulares após o primeiro administrador usam autenticação JWT
normal. As exceções são as próprias operações de inicialização — criar outra
instituição, registar o primeiro administrador de outra instituição e
ativar/desativar uma instituição por meio de
`PATCH /api/v1/bootstrap/institutions/{id}/status` (consulte
[Reativação de uma instituição](#reativação-de-uma-instituição)) — que continuam
a usar `X-Bootstrap-Token`.

1. Crie a instituição (exige `X-Bootstrap-Token`):

   ```
   POST /api/v1/institutions
   X-Bootstrap-Token: <seu BOOTSTRAP_TOKEN>

   {
     "name": "Universidade Exemplo",
     "code": "UEX",
     "default_language": "pt",
     "supported_languages": ["pt", "en"]
   }
   ```

2. Registe o primeiro administrador da instituição (também exige
   `X-Bootstrap-Token`; uma segunda chamada para a mesma instituição falha com
   409, pois apenas um administrador pode ser registado por este endpoint —
   administradores adicionais são criados por um administrador autenticado
   através de `POST /api/v1/users`):

   ```
   POST /api/v1/auth/register-initial-admin
   X-Bootstrap-Token: <seu BOOTSTRAP_TOKEN>

   {
     "institution_id": "<id obtido no passo 1>",
     "full_name": "Utilizador Administrador",
     "email": "admin@example.com",
     "password": "..."
   }
   ```

3. Inicie sessão para obter um token Bearer:

   ```
   POST /api/v1/auth/login
   { "email": "admin@example.com", "password": "..." }
   ```

4. Use `Authorization: Bearer <token>` em todos os outros endpoints
   (`/api/v1/users`, `/api/v1/conversations` e `GET`/`PATCH`
   `/api/v1/institutions/{id}`). Um administrador só pode ler ou atualizar a
   própria instituição. Outro `institution_id` é informado como 404, não 403,
   para nunca revelar a existência de outros locatários. Um administrador
   institucional também não pode ativar ou desativar a própria instituição por
   este endpoint PATCH; o envio de `is_active` é rejeitado com 422 (consulte a
   secção seguinte).

### Reativação de uma instituição

Um administrador institucional não pode definir o campo `is_active` da própria
instituição por meio de `PATCH /api/v1/institutions/{id}`. Isso permitiria
bloquear o próprio acesso e o de todos os utilizadores da instituição, sem uma
forma de recuperação pela API regular. A ativação ou desativação de uma
instituição só é possível por um endpoint de inicialização, protegido pelo
mesmo `X-Bootstrap-Token`:

```
PATCH /api/v1/bootstrap/institutions/{institution_id}/status
X-Bootstrap-Token: <seu BOOTSTRAP_TOKEN>

{ "is_active": true }
```

Esse endpoint altera somente `is_active` e rejeita qualquer outro campo no
payload. Não há um papel `platform_admin` nem uma interface administrativa por
trás dele; é um mecanismo de recuperação deliberadamente mínimo e explícito
para este protótipo.

## Estado do projeto

Consulte [`docs/database.md`](docs/database.md) para conhecer o histórico de
migrações e as regras atuais de segurança institucional. `institutions`,
`users`, `auth`, `conversations`/`messages` e o núcleo documental possuem APIs
completas. O núcleo documental (`/api/v1/documents`, exclusivo para
administradores) cobre documentos lógicos com uploads de arquivos versionados
(PDF, TXT e Markdown), armazenamento local, deteção de duplicados e extração
síncrona de texto — consulte
[`docs/document-core.md`](docs/document-core.md).

PDFs digitalizados são suportados por OCR local e offline (Tesseract). Cada
página é analisada separadamente; o texto nativo é usado sempre que for
suficiente e o OCR é executado apenas nas páginas que dele necessitam. A
deteção abrange imagens diretas, imagens em Form XObjects, imagens inline e
desenhos vetoriais. Uma pré-visualização independente a 72 DPI, com limite de
pixels, distingue páginas visuais de páginas aproximadamente vazias quando o
texto nativo é insuficiente ou a inspeção estrutural é inconclusiva. A ordem
das páginas e o separador `\f` são preservados. A reconstrução de linhas do
OCR usa a geometria das palavras (sobreposição vertical, centros, alturas e
posição horizontal), em vez da ordem de blocos do Tesseract. Gaps horizontais
adaptativos preservam colunas observáveis com `" | "` e uma heurística
conservadora pode associar a continuação visual de uma célula multilinha. Não
há correção ortográfica, validação de datas ou interpretação semântica.

Os metadados de extração (`extraction_method` com native/ocr/mixed,
`extraction_quality` com high/medium/low, `extraction_warning` e
`extraction_details` por página) são persistidos e expostos apenas para
leitura; versões históricas mantêm esses campos como NULL. O Tesseract é
opcional: a aplicação inicia e processa documentos nativos sem ele. Apenas os
documentos que exigem OCR falham, com um erro curto e controlado, e podem ser
reprocessados posteriormente. A configuração de idiomas, DPI, timeout e
limites de páginas/pixels está em `.env.example`; os detalhes encontram-se em
[`docs/document-core.md`](docs/document-core.md).

Após uma extração bem-sucedida, o texto de cada versão é dividido em segmentos
internos e determinísticos (tabela `document_chunks`). `PAGE_SEPARATOR = "\f"`
é uma fronteira obrigatória: nenhum chunk atravessa páginas e os offsets
continuam globais sobre `extracted_text`. Títulos, parágrafos, linhas de tabela
e listas são unidades estruturais; uma `table_row` que caiba no limite permanece
inteira e separada das outras linhas. Apenas uma unidade individual demasiado
grande usa o fallback por caracteres, com overlap restrito a essa unidade.

Além dos offsets, normalização e SHA-256, chunks novos guardam `page_number`,
`section_title`, `structure_type` e `chunking_strategy` (`structured_v1` ou
`character_fallback_v1`). As colunas são anuláveis e não houve backfill:
chunks históricos continuam válidos com `NULL`. Uma versão só é marcada como
`processed` depois da substituição atómica dos chunks. A segmentação recebe
apenas texto/estruturas internas e não depende da rota, `UploadFile`, filename,
URL, instituição ou armazenamento local, mantendo compatibilidade com uma
futura fonte documental por API.

Os segmentos são uma estrutura interna sem endpoint público e preparam o
sistema para experiências de recuperação. Depois de um segmento ser citado
por uma resposta persistida, a respetiva linha não pode ser atualizada nem
eliminada. O reprocessamento e a reconstrução recusam a versão citada; o novo
conteúdo deve ser enviado como uma nova versão, enquanto os metadados
históricos da citação permanecem no respetivo snapshot.

A fase 3 adiciona uma baseline lexical experimental em
`POST /api/v1/retrieval/search`. Utilizadores autenticados recuperam evidências
classificadas da versão processada mais recente dos documentos elegíveis da
própria instituição. O PostgreSQL mantém um `TSVECTOR` gerado e um índice GIN;
`PostgresLexicalRetriever` usa `websearch_to_tsquery` parametrizado e
`ts_rank_cd` por trás de um contrato neutro `Retriever`.

O Momento 4 reforça a recuperação sem sair do lexical, determinístico e local.
A configuração Full-Text Search passa a ser **por idioma** (`portuguese`/
`english`/`simple`, por allowlist), melhorando a recuperação por stemming. O
retriever executa **todas** as variantes da consulta (exact, reduced_and,
reduced_or), agrega-as num *candidate pool* limitado e aplica um **reranking
lexical determinístico**: cobertura dos termos, frase exata, proximidade,
título/secção, estrutura (`table_row`) e comprimento, com o `ts_rank_cd` como
sinal apenas auxiliar. Ordinais padrão (`1.ª`/`primeira` ⇒ o mesmo) e
intervalos numéricos explícitos são canonizados; o OCR não é corrigido nem
adivinhado. Um limiar mínimo (`RETRIEVAL_MIN_RELEVANCE_SCORE`) e a dominância
entre candidatos excluem coincidências fracas. O `score` de `Evidence` passa a
ser a relevância lexical composta em `[0, 1]`. Operadores explícitos (aspas,
`OR`, `-termo`) preservam a intenção; todos os filtros institucionais aplicam-se
a todas as variantes. Sem embeddings, sem pesquisa semântica e sem LLM no
retrieval — consulte [`docs/database.md`](docs/database.md).

O endpoint de recuperação devolve apenas evidências. O texto processado
existente pode ser reconstruído de forma idempotente com
`python -m scripts.rebuild_document_chunks`, opcionalmente filtrado por
`--institution-id` ou `--document-id`; versões citadas são ignoradas e
informadas separadamente. O resumo inclui versões processadas/estruturadas,
chunks gerados, `table_row`, fragments de fallback, versões citadas ignoradas e
falhas. O rebuild usa somente `extracted_text` persistido: não reabre PDFs, não
executa OCR e não usa rede.

O passo 2 da fase 3 adiciona respostas fundamentadas experimentais em
`POST /api/v1/answering/ask` — consulte
[`docs/answering.md`](docs/answering.md). As evidências recuperadas são
convertidas num payload JSON limitado (IDs E1/E2 estáveis) sob um prompt de
sistema estático. Os dados institucionais continuam não confiáveis e não podem
alterar a estrutura JSON criada pela aplicação. Um adaptador de fornecedor
gera uma resposta curta limitada a esse contexto, e um validador determinístico
rejeita respostas vazias, extensas demais ou com IDs de evidência desconhecidos.

Sem evidências, o endpoint devolve `insufficient_evidence` com uma mensagem
fixa por idioma e nunca contacta o fornecedor. O SDK da OpenAI está isolado em
`app/answering/providers/openai.py` por trás do contrato neutro
`AnswerGenerator`. A aplicação inicia sem `OPENAI_API_KEY`; o endpoint devolve
503 apenas quando a geração é realmente necessária. Os logs de erro do
fornecedor contêm somente metadados controlados, o cliente do SDK desativa
explicitamente as novas tentativas e os testes são executados sem rede nem
credenciais.

O passo 3 da fase 3 adiciona
`POST /api/v1/conversations/{conversation_id}/ask`. Ele reutiliza o mesmo
pipeline neutro em relação ao fornecedor e, em seguida, revalida e bloqueia a
instituição ativa, o utilizador e papel atuais, a conversa e as linhas citadas
da base de dados. O checksum do segmento no momento da recuperação é comparado
com o conteúdo bloqueado antes de a mensagem do utilizador, a resposta do
assistente (`reply_to_message_id`) e os snapshots das fontes serem confirmados
atomicamente. `insufficient_evidence` persiste as duas mensagens de fallback
sem fontes. O histórico devolve fontes ordenadas sem consultas N+1, e alterações
posteriores nos metadados dos documentos não reescrevem citações antigas.

A etapa de usabilidade adiciona gestão do ciclo de vida dos documentos e
títulos de conversas. Administradores podem editar metadados dos documentos (o
idioma é bloqueado quando existem versões), criar documentos com Guardar,
Guardar e Novo ou Cancelar (fonte oficial ativa por omissão) e eliminar
permanentemente um documento **nunca citado** — incluindo segmentos, versões e
arquivos — mediante um diálogo de confirmação acessível.

Um documento citado por respostas persistidas devolve 409 e só pode ser
desativado, preservando o histórico auditável. Upload e eliminação partilham um
bloqueio consultivo por documento para que condições de corrida não deixem
arquivos órfãos. A limpeza de arquivos é enfileirada como linhas duráveis em
`storage_cleanup_tasks` na mesma transação da eliminação, depois processada e
reconciliada com `FOR UPDATE SKIP LOCKED` — armazenamento local síncrono, não
uma transação distribuída. As conversas são criadas sem solicitar um título: o
backend deriva-o localmente, sem LLM, a partir da primeira pergunta persistida
e na mesma transação do turno. Os utilizadores podem renomear conversas,
inclusive as fechadas ou arquivadas, que permanecem finais; as listagens são
ordenadas pela atividade mais recente (`updated_at`).

A abordagem de geração é experimental e substituível, não uma decisão
arquitetural definitiva, e o sistema **não** está livre de alucinações. Ainda
não há embeddings, pesquisa semântica ou híbrida, reranking, uma segunda LLM
de validação, pontuações de confiança, memória conversacional, idempotência,
encaminhamento para atendimento humano nem feedback. Perguntas concorrentes são
ordenadas pelo momento do commit, não pelo momento do envio.
