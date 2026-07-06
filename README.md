# Institutional Agentic RAG Assistant

Backend prototype for a generic, multi-institution higher-education assistant based on controlled Agentic RAG.

The Python application lives entirely in [`backend/`](backend/). Docker Compose at the
repository root runs only PostgreSQL (with pgvector); the FastAPI application itself
runs locally from `backend/`, not in a container.

## Prerequisites

- Python 3.12
- Docker (for PostgreSQL + pgvector)

## Setup

### 1. Create the environment file

From the repository root:

```powershell
Copy-Item .env.example .env
```

Edit `.env` with your local values. `DATABASE_URL` must match the
`POSTGRES_*` values below and the `POSTGRES_HOST_PORT` you expose.

### 2. Start PostgreSQL (Docker Compose)

From the repository root:

```powershell
docker compose up -d
docker compose ps
```

This starts a single `database` service (`pgvector/pgvector:pg17`). It is the
only container in this project — there is no API container.

### 3. Create the Python virtual environment

From `backend/`:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Apply migrations

From `backend/` (venv active):

```powershell
alembic upgrade head
```

### 5. Seed the demo institution (optional)

From `backend/` (venv active):

```powershell
python -m scripts.seed_demo_institution
```

### 6. Run the API locally

From `backend/` (venv active):

```powershell
uvicorn app.main:app --reload
```

The API is served at `http://127.0.0.1:8000`, with interactive docs at
`http://127.0.0.1:8000/docs`.

### 7. Run tests

From `backend/` (venv active):

```powershell
pytest -q
```

Tests run against a dedicated test database (see `backend/tests/conftest.py`)
and never touch the development database.

### 8. Lint

From `backend/` (venv active):

```powershell
ruff check .
```

## Project status

See [`docs/database.md`](docs/database.md) for the migration history and the
plan for the upcoming `users` migration (Block 2).
