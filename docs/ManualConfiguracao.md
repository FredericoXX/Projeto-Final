# Manual de Configuração do Ambiente de Desenvolvimento

## 1. Finalidade do documento

Este manual descreve o procedimento necessário para configurar e executar localmente o ambiente de desenvolvimento do protótipo **Institutional Agentic RAG Assistant**.

O projeto é um protótipo de assistente institucional genérico, orientado a instituições de ensino superior. A aplicação é composta por um backend em Python/FastAPI e por uma base de dados PostgreSQL com a extensão pgvector. Nesta fase, apenas a base de dados é executada em contentor Docker; a API FastAPI é executada localmente através do ambiente virtual Python.

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
agentic-rag-assistant/
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
git clone https://github.com/FredericoXX/Projeto-Final.git agentic-rag-assistant
cd agentic-rag-assistant
```

Caso o repositório já esteja disponível no computador, basta aceder à respetiva pasta:

```powershell
cd C:\dev\agentic-rag-assistant
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
APP_NAME=Agentic RAG Assistant
ENVIRONMENT=development

POSTGRES_DB=agentic_rag
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=change_me
POSTGRES_HOST_PORT=5433

DATABASE_URL=postgresql+psycopg://rag_user:change_me@localhost:5433/agentic_rag

TEST_DATABASE_URL=postgresql+psycopg://rag_user:change_me@localhost:5433/agentic_rag_test

OPENAI_API_KEY=
```

Os valores definidos em `DATABASE_URL` devem corresponder aos valores de `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` e `POSTGRES_HOST_PORT`.

A variável `TEST_DATABASE_URL` identifica uma base de dados dedicada aos testes. Esta separação evita que os testes alterem ou eliminem dados utilizados no ambiente de desenvolvimento.

A variável `OPENAI_API_KEY` permanece vazia nesta fase, pois a integração com serviços de modelos de linguagem ainda não é necessária para executar a infraestrutura base.

O ficheiro `.env` contém configurações locais e não deve ser enviado para o repositório remoto.

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

O serviço `database` deve apresentar o estado `running` ou `healthy`. O contentor criado tem o nome `agentic-rag-assistant-db`.

Para confirmar a disponibilidade do PostgreSQL, execute:

```powershell
docker compose exec database psql -U rag_user -d agentic_rag -c "SELECT 1;"
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
docker compose exec database psql -U rag_user -d agentic_rag -c "\dx"
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
cd C:\dev\agentic-rag-assistant\backend
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

## 12. Execução dos testes e validação de qualidade

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

## 13. Encerramento do ambiente

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

## 14. Problemas frequentes e procedimentos de correção

### 14.1 O endereço `http://127.0.0.1:8000/docs` não abre

A causa mais provável é a API FastAPI não estar em execução. Na pasta `backend`, ative o ambiente virtual e execute:

```powershell
.\.venv\Scripts\Activate.ps1
fastapi dev app/main.py
```

Confirme no terminal que o servidor foi iniciado na porta `8000`.

### 14.2 O comando `fastapi` não é reconhecido

O ambiente virtual pode não estar ativo ou as dependências podem não estar instaladas. Execute:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Depois, tente novamente. Como alternativa, execute:

```powershell
uvicorn app.main:app --reload
```

### 14.3 O Docker não inicia a base de dados

Confirme que o Docker Desktop está aberto e em execução. Depois, na raiz do projeto, execute:

```powershell
docker compose up -d
docker compose ps
```

Para analisar mensagens de erro do serviço de base de dados, utilize:

```powershell
docker compose logs database
```

### 14.4 A porta da base de dados já está em utilização

Altere o valor de `POSTGRES_HOST_PORT` no ficheiro `.env` para uma porta disponível, por exemplo `5434`. Em seguida, atualize a porta na variável `DATABASE_URL` para que ambas permaneçam coerentes:

```env
POSTGRES_HOST_PORT=5434
DATABASE_URL=postgresql+psycopg://rag_user:change_me@localhost:5434/agentic_rag
```

Depois, reinicie o serviço:

```powershell
docker compose down
docker compose up -d
```

### 14.5 O Alembic não consegue ligar à base de dados

Confirme que a base de dados está em execução e que os valores em `.env` correspondem à configuração utilizada pelo Docker Compose. Execute:

```powershell
docker compose ps
alembic current
```

Verifique especialmente `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST_PORT` e `DATABASE_URL`.

### 14.6 A política de execução do PowerShell bloqueia a ativação do ambiente virtual

Quando o PowerShell impedir a execução de `Activate.ps1`, abra uma sessão de PowerShell com permissões adequadas e execute:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Em seguida, feche e abra novamente o terminal, navegue até à pasta `backend` e tente ativar o ambiente virtual outra vez.

---

## 15. Sequência resumida de arranque diário

Depois de a configuração inicial estar concluída, o procedimento normal para iniciar o ambiente é o seguinte:

```powershell
# Terminal 1 — raiz do projeto
cd C:\dev\agentic-rag-assistant
docker compose up -d

# Terminal 2 — backend
cd C:\dev\agentic-rag-assistant\backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
fastapi dev app/main.py
```

Por fim, aceda a:

```text
http://127.0.0.1:8000/docs
```

---

## 16. Estado da infraestrutura nesta fase

A configuração descrita neste manual cobre a infraestrutura base do backend: controlo de versões, variáveis de ambiente, PostgreSQL com pgvector, ambiente virtual Python, FastAPI, SQLAlchemy, Alembic, endpoint de saúde, testes automatizados e validação de qualidade.

A implementação de autenticação completa, gestão de utilizadores, conversas, mensagens, processamento de documentos, embeddings, recuperação de informação e lógica agêntica será desenvolvida progressivamente nas etapas seguintes do projeto.
