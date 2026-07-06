# Configuração Inicial do Ambiente

## Objetivo

Este documento regista a configuração inicial realizada para preparar o ambiente de desenvolvimento do projeto **Agentic RAG Assistant**.

Nesta fase, foi configurada a infraestrutura base do backend, incluindo controlo de versões, ambiente Python isolado, base de dados PostgreSQL com pgvector, API FastAPI, migrações, endpoint de saúde e validações mínimas de qualidade.

O projeto ainda não possui RAG funcional, autenticação completa, processamento de documentos, interface de chat ou agente implementado. Esses componentes serão desenvolvidos em etapas posteriores, depois de a camada base do backend estar estável.

---

## Como arrancar o backend

Para colocar o backend funcional em ambiente local, devem ser executados os seguintes passos.

1. Abrir o terminal na raiz do projeto:

```powershell
cd C:\dev\agentic-rag-assistant
```

2. Arrancar a base de dados com Docker:

```powershell
docker compose up -d
docker compose ps
```

O serviço `database` deve apresentar o estado `running`.

3. Entrar na pasta do backend:

```powershell
cd backend
```

4. Ativar o ambiente virtual Python:

```powershell
.\.venv\Scripts\Activate.ps1
```

5. Instalar ou atualizar as dependências, quando necessário:

```powershell
pip install -r requirements.txt
```

6. Aplicar as migrações pendentes da base de dados:

```powershell
alembic upgrade head
```

7. Confirmar a versão atual das migrações:

```powershell
alembic current
```

8. Executar os testes automatizados:

```powershell
pytest
```

9. Verificar a qualidade do código:

```powershell
ruff check .
ruff format .
```

10. Arrancar a API FastAPI:

```powershell
fastapi dev app/main.py
```

Caso o comando anterior não esteja disponível, pode ser utilizado:

```powershell
uvicorn app.main:app --reload
```

O terminal onde a API foi iniciada deve permanecer aberto enquanto a aplicação estiver a ser utilizada.

11. Aceder à documentação automática da API:

```text
http://127.0.0.1:8000/docs
```

12. Testar o endpoint de saúde:

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

---

## Estrutura criada

Foi criada uma estrutura inicial modular para separar responsabilidades no backend:

```text
agentic-rag-assistant/
├── backend/
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   ├── app/
│   │   ├── agent/
│   │   ├── api/
│   │   │   └── routes/
│   │   ├── core/
│   │   ├── database/
│   │   ├── models/
│   │   ├── rag/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── requirements.txt
├── docker/
├── docs/
├── frontend/
├── .env
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

A organização foi preparada para permitir a evolução progressiva do sistema sem concentrar toda a lógica em poucos ficheiros.

---

## Ferramentas e tecnologias configuradas

Foram configuradas as seguintes tecnologias:

| Componente | Tecnologia | Finalidade |
|---|---|---|
| Controlo de versões | Git | Registo e gestão da evolução do código |
| Linguagem | Python 3.12 | Desenvolvimento do backend |
| API | FastAPI | Criação da API REST e documentação automática |
| Base de dados | PostgreSQL 17 | Persistência de dados estruturados |
| Pesquisa vetorial | pgvector | Preparação para armazenamento de embeddings |
| ORM | SQLAlchemy | Comunicação entre Python e PostgreSQL |
| Migrações | Alembic | Versionamento da estrutura da base de dados |
| Contentorização | Docker Compose | Execução reproduzível da base de dados |
| Testes | pytest | Validação automática mínima |
| Qualidade | Ruff | Verificação de estilo, imports e boas práticas |

---

## Configuração de variáveis de ambiente

Foram criados os ficheiros:

```text
.env
.env.example
```

O ficheiro `.env` contém as configurações locais da aplicação e credenciais técnicas da base de dados.

O ficheiro `.env` foi adicionado ao `.gitignore`, para impedir o envio de passwords, chaves de API ou outras configurações locais para o repositório Git.

O `.env.example` funciona como modelo de configuração para reproduzir o projeto noutro computador sem expor credenciais reais.

As variáveis configuradas incluem:

```env
APP_NAME
ENVIRONMENT
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_HOST_PORT
DATABASE_URL
OPENAI_API_KEY
```

Nesta fase, a chave `OPENAI_API_KEY` permanece vazia, porque a integração com modelo de linguagem ainda não foi iniciada.

---

## Base de dados com Docker

Foi configurado um contentor Docker para executar PostgreSQL com pgvector.

O ficheiro `docker-compose.yml` cria o serviço de base de dados e utiliza um volume persistente para manter os dados entre reinicializações do contentor.

O serviço foi iniciado com:

```powershell
docker compose up -d
```

O estado do contentor foi validado com:

```powershell
docker compose ps
```

A base de dados ficou disponível localmente na porta definida em `POSTGRES_HOST_PORT`.

Foi confirmada a disponibilidade da extensão pgvector com:

```powershell
docker compose exec database psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\dx"
```

O resultado confirmou que a extensão `vector` está ativa.

---

## Ambiente virtual Python

Foi criado um ambiente virtual isolado dentro da pasta `backend`:

```text
backend/.venv
```

O ambiente foi criado com:

```powershell
py -3.12 -m venv .venv
```

E ativado com:

```powershell
.\.venv\Scripts\Activate.ps1
```

As dependências foram instaladas a partir de `requirements.txt`:

```powershell
pip install -r requirements.txt
```

As bibliotecas principais instaladas incluem:

```text
fastapi
sqlalchemy
alembic
psycopg[binary]
pgvector
pydantic-settings
pytest
httpx
ruff
mypy
pypdf
```

---

## Configuração do backend FastAPI

Foi criado o ficheiro de configuração:

```text
backend/app/core/config.py
```

Este ficheiro usa `pydantic-settings` para carregar as variáveis definidas no ficheiro `.env`.

A ligação à base de dados foi configurada em:

```text
backend/app/database/session.py
```

A configuração inclui:

- criação do motor SQLAlchemy;
- verificação preventiva das ligações (`pool_pre_ping=True`);
- `SessionLocal` para criação de sessões;
- função `get_db()` para disponibilizar uma sessão por pedido e garantir o seu encerramento.

A ligação Python → PostgreSQL foi validada com uma consulta simples:

```sql
SELECT 1;
```

O resultado obtido foi:

```text
1
```

Isto confirma que o backend consegue comunicar com a base de dados em Docker.

---

## Endpoint de saúde

Foi criado o endpoint:

```text
GET /api/v1/health
```

Este endpoint verifica se:

1. a API FastAPI está ativa;
2. o backend consegue ligar-se à base de dados;
3. a consulta à base de dados é executada com sucesso.

A resposta esperada é:

```json
{
  "status": "ok",
  "database": "ok"
}
```

A API é iniciada com:

```powershell
fastapi dev app/main.py
```

A documentação automática fica disponível em:

```text
http://127.0.0.1:8000/docs
```

A documentação Swagger e o endpoint de saúde foram validados localmente, com resposta HTTP `200`.

---

## Migrações da base de dados

Foi configurado o Alembic para controlar alterações do esquema da base de dados.

Foram criadas e aplicadas duas migrações:

1. Ativação da extensão `pgvector`;
2. Criação da tabela `users`.

A extensão foi adicionada através de uma migração com:

```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

A tabela `users` foi criada com os campos:

| Campo | Tipo | Finalidade |
|---|---|---|
| `id` | UUID | Identificador único do utilizador |
| `email` | VARCHAR(255) | Email único do utilizador |
| `password_hash` | VARCHAR(255) | Hash da password, nunca password em texto simples |
| `created_at` | TIMESTAMP WITH TIME ZONE | Data de criação do registo |

A tabela foi confirmada diretamente no PostgreSQL com:

```powershell
docker compose exec database psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\d users"
```

A migração atual foi confirmada através de:

```powershell
alembic current
```

---

## Testes e qualidade de código

Foi criado um teste automatizado para o endpoint de saúde:

```text
backend/tests/test_health.py
```

O teste confirma que o endpoint retorna:

- código HTTP `200`;
- estado da API igual a `ok`;
- estado da base de dados igual a `ok`.

O teste foi executado com:

```powershell
pytest
```

Resultado obtido:

```text
1 passed
```

Também foi configurado o Ruff através do ficheiro:

```text
backend/pyproject.toml
```

Foram executados:

```powershell
ruff check .
ruff format .
pytest
```

Resultado final da validação:

```text
All checks passed!
1 passed
```

Os ficheiros gerados automaticamente pelo Alembic em `alembic/versions/` foram excluídos das verificações de estilo para evitar alterações desnecessárias no histórico de migrações.

---

## Estado atual

A infraestrutura base do backend encontra-se funcional e validada.

| Item | Estado |
|---|---|
| Repositório Git | Configurado |
| `.gitignore` | Configurado |
| Variáveis de ambiente | Configuradas |
| Docker Compose | Funcional |
| PostgreSQL | Funcional |
| pgvector | Ativo |
| Ambiente virtual Python | Criado |
| Dependências Python | Instaladas |
| FastAPI | Funcional |
| Documentação Swagger | Funcional |
| Ligação Python → PostgreSQL | Validada |
| Endpoint `/api/v1/health` | Funcional |
| Alembic | Configurado |
| Migrações | Aplicadas |
| Tabela `users` | Criada |
| pytest | Funcional |
| Ruff | Configurado e validado |

---

## Próxima etapa

A próxima etapa será desenvolver a camada funcional base da aplicação antes de avançar para RAG.

A ordem correta de implementação é:

1. schemas Pydantic;
2. serviços de utilizadores;
3. hash de passwords;
4. endpoints de criação e gestão de utilizadores;
5. autenticação com JWT;
6. modelos de conversas;
7. modelos de mensagens;
8. endpoints mínimos de conversas e mensagens;
9. testes automatizados dos novos endpoints;
10. integração posterior com documentos, embeddings, RAG e lógica agêntica.

A implementação de RAG, embeddings, indexação de documentos e lógica agêntica só deve começar depois de a camada de utilizadores, autenticação, conversas e mensagens estar estável.
