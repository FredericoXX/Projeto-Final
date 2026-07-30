# Manual de Configuração do Ambiente de Desenvolvimento

## 1. Finalidade do documento

Este manual descreve o procedimento necessário para configurar e executar localmente o ambiente de desenvolvimento do protótipo **Agentic Institutional Assistant**.

O projeto é um protótipo académico (trabalho final de mestrado) de assistente institucional genérico, orientado a instituições de ensino superior, e não deve ser tratado como um produto pronto para produção. A abordagem de recuperação de informação (RAG ou outra) ainda será escolhida através da revisão da literatura — nada neste manual deve ser lido como uma decisão já tomada nesse sentido. A aplicação é composta por um backend em Python/FastAPI e por uma base de dados PostgreSQL com a extensão pgvector, disponibilizada como infraestrutura para essa experimentação futura. Nesta fase, apenas a base de dados é executada em contentor Docker; a API FastAPI é executada localmente através do ambiente virtual Python.

Este procedimento permite preparar o ambiente, aplicar as migrações da base de dados, iniciar a API, validar a disponibilidade do serviço e executar os testes automatizados.

---

## 2. Pré-requisitos

Antes de iniciar a configuração, devem estar instalados os seguintes componentes:

| Componente | Versão ou requisito | Finalidade |
|---|---|---|
| Sistema operativo | Windows 10 ou Windows 11 | Ambiente de execução considerado neste manual |
| Git | Versão atual | Obtenção e controlo de versões do repositório |
| Python | 3.12 | Execução do backend FastAPI |
| Docker Desktop | Instalado e em execução | Execução do PostgreSQL com pgvector |
| PowerShell | Integrado no Windows | Execução dos comandos apresentados |
| Navegador web | Atualizado | Acesso à documentação Swagger da API |

A confirmação da instalação pode ser feita no PowerShell através dos comandos seguintes:

```powershell
git --version
py -3.12 --version
docker --version
docker compose version
```

O Docker Desktop deve estar aberto antes de iniciar a base de dados.

---

## 3. Estrutura relevante do projeto

A estrutura principal utilizada durante a configuração é a seguinte:

```text
institutional-assistant/
├── backend/
│   ├── alembic/                 # Configuração e versões das migrações
│   ├── app/                     # Código-fonte da aplicação FastAPI
│   ├── scripts/                 # Scripts auxiliares, incluindo dados de demonstração
│   ├── tests/                   # Testes automatizados
│   ├── requirements.txt         # Dependências Python
│   └── alembic.ini              # Configuração do Alembic
├── docs/                        # Documentação do projeto
├── .env                         # Configuração local, não versionada
├── .env.example                 # Modelo de configuração local
├── docker-compose.yml           # Serviço PostgreSQL com pgvector
└── README.md                    # Instruções resumidas do projeto
```

---

## 4. Obtenção do projeto

Abra o PowerShell e navegue até à pasta onde pretende guardar o projeto. Em seguida, execute:

```powershell
git clone https://github.com/FredericoXX/Projeto-Final.git institutional-assistant
cd institutional-assistant
```

Caso o repositório já esteja disponível no computador, basta aceder à respetiva pasta:

```powershell
cd <caminho-do-projeto>
```

Antes de continuar, confirme que se encontra na raiz do projeto:

```powershell
dir
```

Devem estar visíveis, entre outros, os ficheiros `docker-compose.yml`, `.env.example`, `README.md` e a pasta `backend`.

---

## 5. Configuração das variáveis de ambiente

Na raiz do projeto, crie o ficheiro `.env` a partir do modelo disponibilizado:

```powershell
Copy-Item .env.example .env
```

Abra o ficheiro `.env` num editor de texto ou no Visual Studio Code:

```powershell
code .env
```

A configuração base é a seguinte:

```env
APP_NAME=Agentic Institutional Assistant
ENVIRONMENT=development

POSTGRES_DB=institutional_assistant
POSTGRES_USER=assistant_user
POSTGRES_PASSWORD=change_me
POSTGRES_HOST_PORT=5433

DATABASE_URL=postgresql+psycopg://assistant_user:change_me@localhost:5433/institutional_assistant

TEST_DATABASE_URL=postgresql+psycopg://assistant_user:change_me@localhost:5433/institutional_assistant_test

ANSWER_GENERATOR_PROVIDER=openai
ANSWERING_DEFAULT_TOP_K=5
ANSWERING_MAX_TOP_K=10
ANSWERING_MAX_CONTEXT_CHARS=12000
ANSWERING_MAX_ANSWER_CHARS=4000

OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_TIMEOUT_SECONDS=30

JWT_SECRET_KEY=change_me_dev_secret_with_at_least_32_characters
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

BOOTSTRAP_TOKEN=change_me_dev_bootstrap_token

DOCUMENT_STORAGE_PATH=storage/documents
DOCUMENT_MAX_FILE_SIZE_MB=20

DOCUMENT_CHUNK_SIZE_CHARS=1200
DOCUMENT_CHUNK_OVERLAP_CHARS=150

RETRIEVAL_MIN_RELEVANCE_SCORE=0.05
```

Os valores definidos em `DATABASE_URL` devem corresponder aos valores de `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` e `POSTGRES_HOST_PORT`.

A variável `TEST_DATABASE_URL` identifica uma base de dados dedicada aos testes. Esta separação evita que os testes alterem ou eliminem dados utilizados no ambiente de desenvolvimento.

As variáveis `ANSWER_GENERATOR_PROVIDER`, `ANSWERING_DEFAULT_TOP_K`, `ANSWERING_MAX_TOP_K`, `ANSWERING_MAX_CONTEXT_CHARS` e `ANSWERING_MAX_ANSWER_CHARS` configuram a geração experimental de respostas fundamentadas nos endpoints `POST /api/v1/answering/ask` e `POST /api/v1/conversations/{conversation_id}/ask` — ver [`docs/answering.md`](answering.md): o provider ativo, o número de evidências recuperadas por omissão e no máximo, o limite do payload JSON de contexto enviado ao gerador e o limite da resposta gerada. O `default_top_k` não pode exceder o `max_top_k`; a aplicação recusa arrancar com valores inválidos.

As variáveis `OPENAI_API_KEY`, `OPENAI_MODEL` e `OPENAI_TIMEOUT_SECONDS` configuram o adapter OpenAI. **A aplicação inicia sem a chave**: a ausência de `OPENAI_API_KEY`/`OPENAI_MODEL` só produz efeito quando um dos endpoints de answering precisa de gerar (responde `503`); perguntas sem evidências continuam a devolver o fallback sem contactar o fornecedor. A chave real deve existir apenas no `.env` local, nunca no repositório, nos logs ou nas respostas. O adapter usa `max_retries=0` e regista somente metadados operacionais controlados, sem mensagens ou tracebacks do SDK. Os testes correm sem rede e sem credenciais.

A variável `JWT_SECRET_KEY` assina os tokens de autenticação emitidos em `POST /api/v1/auth/login`; deve ter pelo menos 32 caracteres e um valor diferente do exemplo em qualquer ambiente partilhado. `JWT_ALGORITHM` e `ACCESS_TOKEN_EXPIRE_MINUTES` controlam o algoritmo de assinatura e a validade do token (em minutos).

A variável `BOOTSTRAP_TOKEN` é um segredo temporário que substitui, nesta fase do protótipo, um papel de administração de plataforma que ainda não existe. É exigida no cabeçalho `X-Bootstrap-Token` para criar uma instituição, registar o seu primeiro administrador e reativar/desativar uma instituição — ver secção 12 abaixo. Se não estiver definida (ou não corresponder ao cabeçalho enviado), esses três endpoints recusam o pedido com `401`.

As variáveis `DOCUMENT_STORAGE_PATH` e `DOCUMENT_MAX_FILE_SIZE_MB` configuram o núcleo documental: a primeira define a pasta local onde os ficheiros carregados são guardados (um caminho relativo é resolvido a partir da raiz do projeto; a pasta `storage/` está no `.gitignore` e nunca é versionada), e a segunda o tamanho máximo aceite por ficheiro, em megabytes. Os ficheiros nunca são guardados no PostgreSQL — a base de dados guarda apenas metadados e o texto extraído (ver [`docs/document-core.md`](document-core.md)).

As variáveis `DOCUMENT_CHUNK_SIZE_CHARS` e `DOCUMENT_CHUNK_OVERLAP_CHARS` configuram a segmentação do texto extraído em *chunks* (tabela `document_chunks`): a primeira define o tamanho máximo de cada segmento, em caracteres, e a segunda a sobreposição entre segmentos consecutivos quando um corte é forçado por limite de caracteres. A sobreposição tem de ser inferior ao tamanho do segmento; a aplicação recusa arrancar com valores inválidos. Os chunks são uma estrutura interna, criada automaticamente quando uma versão é processada e reconstruída por inteiro no reprocessamento. A baseline lexical e a geração fundamentada pesquisam estes chunks; ainda não existem embeddings nem pesquisa semântica/híbrida (ver [`docs/database.md`](database.md)). Versões citadas por respostas persistidas não são reconstruídas ou reprocessadas: carregue uma nova versão.

A variável `RETRIEVAL_MIN_RELEVANCE_SCORE` (padrão `0.05`) define o limiar mínimo de relevância lexical composta do retrieval do Momento 4. Numa pergunta com vários termos, o limiar aplica-se a **todos** os candidatos (incluindo o melhor): se todos ficarem abaixo, o resultado é vazio e o answering devolve `insufficient_evidence` em vez de gerar sobre uma coincidência fraca. As correspondências de frase exata nunca são eliminadas pelo limiar. Em paralelo — e registada em separado no trace — a dominância remove candidatos redundantes (aqueles cujos termos correspondidos são um subconjunto próprio dos de um candidato mantido). Consultas de um único termo informativo têm política própria e mantêm os candidatos recuperados (para não perder recall quando o termo casou por stemming). O valor tem de ser finito e estar em `[0, 1]` (a aplicação recusa arrancar com valores inválidos); `0.0` desativa o piso, mantendo a dominância. **Apenas este limiar é configurável** — os pesos do ranking são constantes versionadas em `app/retrieval/reranking.py`, não variáveis de ambiente. Ver a secção de retrieval em [`docs/database.md`](database.md).

O ficheiro `.env` contém configurações locais, incluindo estes segredos, e não deve ser enviado para o repositório remoto.

---

## 6. Inicialização da base de dados

A base de dados utiliza PostgreSQL 17 com a extensão pgvector. O serviço é definido no ficheiro `docker-compose.yml` e é executado através do Docker Compose.

Na raiz do projeto, execute:

```powershell
docker compose up -d
```

Em seguida, verifique o estado do contentor:

```powershell
docker compose ps
```

O serviço `database` deve apresentar o estado `running` ou `healthy`. O contentor criado tem o nome `institutional-assistant-db`.

O volume PostgreSQL é gerado pelo Docker Compose a partir do nome do projeto
(`institutional-assistant`), resultando em `institutional-assistant_postgres_data`.
Nesta fase inicial do protótipo os dados locais são descartáveis: um ambiente
criado com identificadores antigos deve ser simplesmente recriado com os
identificadores atuais, executando na raiz do projeto:

```powershell
docker compose down -v
docker compose up -d
docker compose ps
```

**Atenção:** `docker compose down -v` elimina o volume e, com ele, todos os
dados locais da base de dados. Depois de recriar o ambiente, é necessário
voltar a aplicar as migrações (secção 8).

Para confirmar a disponibilidade do PostgreSQL, execute:

```powershell
docker compose exec database psql -U assistant_user -d institutional_assistant -c "SELECT 1;"
```

O resultado esperado é:

```text
 ?column?
----------
        1
(1 row)
```

Para verificar a extensão pgvector, execute:

```powershell
docker compose exec database psql -U assistant_user -d institutional_assistant -c "\dx"
```

A lista de extensões deve incluir `vector`.

---

## 7. Criação do ambiente virtual Python

A aplicação FastAPI é executada localmente na pasta `backend`. Entre nessa pasta:

```powershell
cd backend
```

Crie o ambiente virtual Python:

```powershell
py -3.12 -m venv .venv
```

Ative o ambiente virtual:

```powershell
.\.venv\Scripts\Activate.ps1
```

Quando a ativação for bem-sucedida, o terminal deverá apresentar `(.venv)` no início da linha de comandos.

Instale as dependências do backend:

```powershell
pip install -r requirements.txt
```

As dependências principais incluem FastAPI, SQLAlchemy, Alembic, psycopg, pgvector, Pydantic Settings, pytest, httpx, Ruff e pypdf.

Sempre que abrir um novo terminal para trabalhar no backend, é necessário voltar à pasta `backend` e ativar o ambiente virtual antes de executar comandos Python:

```powershell
cd <caminho-do-projeto>\backend
.\.venv\Scripts\Activate.ps1
```

---

## 8. Aplicação das migrações

O Alembic controla a evolução da estrutura da base de dados. Com o ambiente virtual ativo e a partir da pasta `backend`, aplique todas as migrações disponíveis:

```powershell
alembic upgrade head
```

Para confirmar a versão de migração aplicada, execute:

```powershell
alembic current
```

A execução deste procedimento deve ser repetida sempre que forem obtidas alterações do repositório que incluam novas migrações.

---

## 9. Dados institucionais de demonstração

O projeto disponibiliza um script opcional para criar dados institucionais de demonstração. Este passo só deve ser executado quando for necessário demonstrar ou testar o sistema com dados iniciais.

A partir da pasta `backend`, com o ambiente virtual ativo, execute:

```powershell
python -m scripts.seed_demo_institution
```

Este procedimento não é obrigatório para iniciar a API.

---

## 10. Arranque da API FastAPI

Com a base de dados em execução, as migrações aplicadas e o ambiente virtual ativo, inicie a API através do comando:

```powershell
fastapi dev app/main.py
```

Como alternativa, pode ser usado o Uvicorn:

```powershell
uvicorn app.main:app --reload
```

A opção `--reload` reinicia automaticamente a API quando são detetadas alterações no código durante o desenvolvimento.

Após o arranque, a API fica disponível no endereço:

```text
http://127.0.0.1:8000
```

A documentação interativa Swagger fica disponível em:

```text
http://127.0.0.1:8000/docs
```

O terminal onde a API está a ser executada deve permanecer aberto. Para interromper o servidor, utilize:

```text
Ctrl + C
```

---

## 11. Validação da instalação

A validação mais simples é realizada através do endpoint de saúde:

```text
GET /api/v1/health
```

Pode testar o endpoint diretamente no navegador através da documentação Swagger ou no PowerShell:

```powershell
curl http://127.0.0.1:8000/api/v1/health
```

A resposta esperada é:

```json
{
  "status": "ok",
  "database": "ok"
}
```

Esta resposta confirma que a API está ativa, que a ligação entre o backend e o PostgreSQL foi estabelecida e que a base de dados responde a consultas.

---

## 12. Autenticação e bootstrap institucional

Ainda não existe um papel de administração de plataforma (`platform_admin`) nem uma interface administrativa. Criar a primeira instituição, registar o seu primeiro administrador e reativar/desativar uma instituição são por isso operações de "bootstrap": protegidas pelo segredo partilhado `BOOTSTRAP_TOKEN` (definido em `.env`), enviado no cabeçalho `X-Bootstrap-Token`, em vez de um token de sessão. Esta secção descreve o fluxo completo, do zero até obter um token Bearer utilizável nos restantes endpoints.

Todos os exemplos abaixo podem ser executados na documentação Swagger (`http://127.0.0.1:8000/docs`) ou com `curl`/PowerShell.

### 12.1 Criar a instituição

```
POST /api/v1/institutions
X-Bootstrap-Token: <valor de BOOTSTRAP_TOKEN>
```

```json
{
  "name": "Universidade de Exemplo",
  "code": "UEX",
  "default_language": "pt",
  "supported_languages": ["pt", "en"]
}
```

Sem o cabeçalho `X-Bootstrap-Token`, ou com um valor incorreto, o pedido falha com `401`. Guarde o `id` devolvido na resposta — é necessário no passo seguinte.

### 12.2 Registar o administrador inicial

```
POST /api/v1/auth/register-initial-admin
X-Bootstrap-Token: <valor de BOOTSTRAP_TOKEN>
```

```json
{
  "institution_id": "<id do passo anterior>",
  "full_name": "Administrador de Exemplo",
  "email": "admin@example.com",
  "password": "uma-password-com-pelo-menos-8-caracteres"
}
```

Este endpoint só cria o **primeiro** administrador de cada instituição; uma segunda chamada para a mesma instituição devolve `409`. Administradores adicionais são criados por um administrador já autenticado através de `POST /api/v1/users`. O pedido também falha (`409`) se a instituição estiver inativa.

### 12.3 Iniciar sessão

```
POST /api/v1/auth/login
```

```json
{
  "email": "admin@example.com",
  "password": "uma-password-com-pelo-menos-8-caracteres"
}
```

A resposta inclui `access_token`. Este endpoint **não** usa o cabeçalho `X-Bootstrap-Token` — é autenticação normal por email/password.

### 12.4 Usar o token Bearer

Para todos os restantes endpoints protegidos (`/api/v1/auth/me`, `/api/v1/users`, `/api/v1/conversations`, `GET`/`PATCH /api/v1/institutions/{id}`), envie o token obtido no passo anterior:

```
Authorization: Bearer <access_token>
```

No Swagger, use o botão **Authorize** e cole apenas o token (sem o prefixo `Bearer`) — a API declara um esquema HTTP Bearer simples, não o fluxo OAuth2 por formulário.

Um administrador institucional só consegue consultar e atualizar a sua própria instituição através de `GET`/`PATCH /api/v1/institutions/{id}`; qualquer outro `id` é devolvido como `404`. Este `PATCH` também não permite alterar `is_active` — enviar esse campo devolve `422`.

### 12.5 Reativar (ou desativar) uma instituição

Como um administrador institucional já não pode alterar o estado (`is_active`) da própria instituição, existe um endpoint de bootstrap dedicado, protegido pelo mesmo `X-Bootstrap-Token`, que serve de mecanismo mínimo de recuperação para este protótipo:

```
PATCH /api/v1/bootstrap/institutions/{institution_id}/status
X-Bootstrap-Token: <valor de BOOTSTRAP_TOKEN>
```

```json
{ "is_active": true }
```

Este endpoint só aceita o campo `is_active`; qualquer outro campo no payload é rejeitado. Não existe (nem está planeado nesta fase) um papel `platform_admin` completo ou uma interface administrativa — este é um mecanismo temporário e explícito.

---

## 13. Execução dos testes e validação de qualidade

Os testes automatizados devem ser executados a partir da pasta `backend`, com o ambiente virtual ativo:

```powershell
pytest -q
```

A suite de testes utiliza uma base de dados dedicada e não deve alterar os dados da base de desenvolvimento.

Para verificar erros de estilo, imports não utilizados e outras regras de qualidade, execute:

```powershell
ruff check .
```

Para aplicar formatação automática aos ficheiros suportados, execute:

```powershell
ruff format .
```

Antes de registar alterações no repositório, devem ser executados os seguintes comandos:

```powershell
ruff check .
pytest -q
```

---

## 14. Encerramento do ambiente

Para interromper a API, pressione `Ctrl + C` no terminal onde o servidor FastAPI está ativo.

Para parar a base de dados sem eliminar os dados persistidos, volte à raiz do projeto e execute:

```powershell
docker compose stop
```

Para voltar a iniciar a base de dados posteriormente:

```powershell
docker compose up -d
```

O comando seguinte remove os contentores, mas preserva o volume de dados:

```powershell
docker compose down
```

O comando abaixo elimina também os volumes e, consequentemente, todos os dados locais da base de dados. Deve ser usado apenas quando for necessário reinicializar completamente o ambiente:

```powershell
docker compose down -v
```

---

## 15. Problemas frequentes e procedimentos de correção

### 15.1 O endereço `http://127.0.0.1:8000/docs` não abre

A causa mais provável é a API FastAPI não estar em execução. Na pasta `backend`, ative o ambiente virtual e execute:

```powershell
.\.venv\Scripts\Activate.ps1
fastapi dev app/main.py
```

Confirme no terminal que o servidor foi iniciado na porta `8000`.

### 15.2 O comando `fastapi` não é reconhecido

O ambiente virtual pode não estar ativo ou as dependências podem não estar instaladas. Execute:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Depois, tente novamente. Como alternativa, execute:

```powershell
uvicorn app.main:app --reload
```

### 15.3 O Docker não inicia a base de dados

Confirme que o Docker Desktop está aberto e em execução. Depois, na raiz do projeto, execute:

```powershell
docker compose up -d
docker compose ps
```

Para analisar mensagens de erro do serviço de base de dados, utilize:

```powershell
docker compose logs database
```

### 15.4 A porta da base de dados já está em utilização

Altere o valor de `POSTGRES_HOST_PORT` no ficheiro `.env` para uma porta disponível, por exemplo `5434`. Em seguida, atualize a porta na variável `DATABASE_URL` para que ambas permaneçam coerentes:

```env
POSTGRES_HOST_PORT=5434
DATABASE_URL=postgresql+psycopg://assistant_user:change_me@localhost:5434/institutional_assistant
```

Depois, reinicie o serviço:

```powershell
docker compose down
docker compose up -d
```

### 15.5 O Alembic não consegue ligar à base de dados

Confirme que a base de dados está em execução e que os valores em `.env` correspondem à configuração utilizada pelo Docker Compose. Execute:

```powershell
docker compose ps
alembic current
```

Verifique especialmente `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST_PORT` e `DATABASE_URL`.

### 15.6 A política de execução do PowerShell bloqueia a ativação do ambiente virtual

Quando o PowerShell impedir a execução de `Activate.ps1`, abra uma sessão de PowerShell com permissões adequadas e execute:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Em seguida, feche e abra novamente o terminal, navegue até à pasta `backend` e tente ativar o ambiente virtual outra vez.

---

## 16. Sequência resumida de arranque diário

Depois de a configuração inicial estar concluída, o procedimento normal para iniciar o ambiente é o seguinte:

```powershell
# Terminal 1 — raiz do projeto
cd <caminho-do-projeto>
docker compose up -d

# Terminal 2 — backend
cd <caminho-do-projeto>\backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
fastapi dev app/main.py
```

Por fim, aceda a:

```text
http://127.0.0.1:8000/docs
```

---

## 17. Estado da infraestrutura nesta fase

A configuração descrita neste manual cobre a infraestrutura base do backend (controlo de versões, variáveis de ambiente, PostgreSQL com pgvector, ambiente virtual Python, FastAPI, SQLAlchemy, Alembic, endpoint de saúde, testes automatizados e validação de qualidade) e o núcleo funcional do protótipo: gestão de instituições, autenticação JWT (com o fluxo de bootstrap descrito na secção 12), gestão de utilizadores, uma API de conversas/mensagens e o núcleo documental (documentos com versões, armazenamento local de ficheiros, extração de texto e segmentação em chunks internos), todas com isolamento multi-institucional reforçado a nível de aplicação e de base de dados (ver [`docs/database.md`](database.md) e [`docs/document-core.md`](document-core.md)).

O endpoint autenticado `POST /api/v1/retrieval/search` disponibiliza uma baseline lexical experimental sobre os chunks. Usa PostgreSQL Full-Text Search com configuração **por idioma** (`portuguese`/`english`/`simple`), coluna `TSVECTOR` gerada e índice GIN. A partir do Momento 4, agrega todas as variantes da consulta num *candidate pool* limitado e aplica um reranking lexical determinístico (cobertura, frase exata, proximidade, título/secção, estrutura e comprimento, com `ts_rank_cd` como sinal auxiliar), com ordinais/intervalos canonizados e um limiar mínimo (`RETRIEVAL_MIN_RELEVANCE_SCORE`); o `score` devolvido é a relevância lexical composta em `[0, 1]`. A pesquisa fica limitada à instituição e idioma do utilizador, considera documentos ativos e válidos, seleciona a versão `processed` mais recente e aplica `official_only=true` por omissão. Sem embeddings, sem pesquisa semântica e sem LLM no retrieval.

O comando `python -m scripts.rebuild_document_chunks` reconstrói idempotentemente os chunks de versões processadas sem reextrair ficheiros. Os filtros opcionais `--institution-id` e `--document-id` limitam o âmbito; o comando é destinado a dados anteriores à integração automática ou a reconstruções administrativas. Versões já citadas são ignoradas sob lock e contabilizadas como `skipped_referenced`, preservando o conteúdo usado por respostas anteriores.

O endpoint autenticado `POST /api/v1/answering/ask` acrescenta geração experimental de respostas fundamentadas sobre essas evidências (ver [`docs/answering.md`](answering.md)): um system prompt estático contém apenas regras, enquanto instituição, pergunta e evidências não confiáveis seguem num payload JSON limitado e estruturalmente separado. O gerador (adapter OpenAI substituível, isolado atrás do contrato `AnswerGenerator`) responde apenas com base nas evidências e uma validação determinística rejeita respostas com citações inválidas usando códigos estáveis, sem registar os valores recebidos. Sem evidências, devolve uma mensagem de fallback fixa por idioma sem contactar o fornecedor; sem `OPENAI_API_KEY`/`OPENAI_MODEL`, devolve `503` apenas quando a geração é necessária. A serialização reduz ambiguidades de fronteira, mas não torna o sistema imune a prompt injection ou alucinações.

O endpoint `POST /api/v1/conversations/{conversation_id}/ask` integra esse pipeline numa conversa ativa. Depois de gerar sem alterações pendentes, relê e bloqueia instituição, utilizador/papel atual, conversa e fontes; revalida o checksum do conteúdo recuperado e persiste mensagem user, resposta assistant e snapshots das fontes citadas num único commit, devolvendo 201. O histórico inclui `reply_to_message_id` e fontes ordenadas. Em `insufficient_evidence`, persiste as duas mensagens e zero fontes. Não há memória conversacional: mensagens anteriores não entram no prompt; também não há idempotência, e perguntas concorrentes ficam ordenadas pela confirmação na base.

A geração é experimental e substituível — a escolha definitiva continua dependente da revisão da literatura, e o sistema não é livre de alucinações. Embeddings, pesquisa semântica/híbrida, reranking, validação por segundo LLM, confidence score, memória, idempotência, feedback, escalonamento humano, agentes e frontend permanecem adiados.
