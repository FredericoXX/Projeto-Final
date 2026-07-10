### Rodar o ambiente

1. Entrar na raiz do projeto:

```
cd C:\dev\agentic-rag-assistant
```

2. Subir a base de dados:


docker compose up -d


3. Entrar no backend:

```
cd backend
```

4. Ativar o ambiente virtual:

```
.\.venv\Scripts\Activate.ps1
```

5. Aplicar migrations:

```
alembic upgrade head
```

6. Criar a instituição demo:

```
python -m scripts.seed_demo_institution
```

7. Rodar a API:

```
uvicorn app.main:app --reload
```

8. Abrir no navegador:

```
http://127.0.0.1:8000/api/v1/health
http://127.0.0.1:8000/docs
```

### Parar o ambiente

1. Parar a API:

```
Ctrl + C
```

2. Voltar para a raiz do projeto:

```
cd ..
```

3. Parar a base de dados Docker sem apagar dados:

```
docker compose down
```

### Parar e apagar a base de dados

Usa isto só quando precisares recriar tudo do zero:

```
cd C:\dev\agentic-rag-assistant
docker compose down -v
```

Depois, para recriar:

```
docker compose up -d
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
python -m scripts.seed_demo_institution
uvicorn app.main:app --reload
```
