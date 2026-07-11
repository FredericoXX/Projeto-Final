# Agentic Institutional Assistant

Backend prototype for a generic, multi-institution higher-education assistant. The
information retrieval approach (e.g. RAG) is still to be chosen through a
literature review and is not yet an architectural decision.

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
`POSTGRES_*` values below and the `POSTGRES_HOST_PORT` you expose. Also set
`BOOTSTRAP_TOKEN` to a long random value — see
[Bootstrapping an institution](#bootstrapping-an-institution) below.

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

## Bootstrapping an institution

There is no `platform_admin` role yet, so creating an institution and
registering its first admin are not open endpoints — they are gated by a
shared secret, `BOOTSTRAP_TOKEN` (set in `.env`), sent as the
`X-Bootstrap-Token` header. This is a temporary, explicit stand-in for
platform-level administration, meant only for local/dev bootstrapping.
Everything after the first admin uses normal JWT authentication.

1. Create the institution (requires `X-Bootstrap-Token`):

   ```
   POST /api/v1/institutions
   X-Bootstrap-Token: <your BOOTSTRAP_TOKEN>

   {
     "name": "Example University",
     "code": "EXU",
     "default_language": "pt",
     "supported_languages": ["pt", "en"]
   }
   ```

2. Register that institution's first admin (also requires
   `X-Bootstrap-Token`; a second call for the same institution fails with
   409, since only one admin can be registered through this endpoint —
   additional admins are created by an authenticated admin via
   `POST /api/v1/users`):

   ```
   POST /api/v1/auth/register-initial-admin
   X-Bootstrap-Token: <your BOOTSTRAP_TOKEN>

   {
     "institution_id": "<id from step 1>",
     "full_name": "Admin User",
     "email": "admin@example.com",
     "password": "..."
   }
   ```

3. Log in to get a bearer token:

   ```
   POST /api/v1/auth/login
   { "email": "admin@example.com", "password": "..." }
   ```

4. Use `Authorization: Bearer <token>` for every other endpoint
   (`/api/v1/users`, `/api/v1/conversations`, and `GET`/`PATCH`
   `/api/v1/institutions/{id}`). An admin can only ever read or update
   their own institution — another `institution_id` is reported as 404,
   not 403, so the existence of other tenants is never revealed. An
   institutional admin also can't (de)activate their own institution
   through this PATCH endpoint; sending `is_active` there is rejected
   with 422 (see next section).

### Reactivating an institution

An institutional admin cannot set their own institution's `is_active`
through `PATCH /api/v1/institutions/{id}` — doing so would let them
lock themselves (and everyone else at that institution) out with no way
back in through the regular API. Activating or deactivating an
institution is only possible through a bootstrap-only endpoint, gated by
the same `X-Bootstrap-Token`:

```
PATCH /api/v1/bootstrap/institutions/{institution_id}/status
X-Bootstrap-Token: <your BOOTSTRAP_TOKEN>

{ "is_active": true }
```

This endpoint only ever touches `is_active` — it rejects any other field
in the payload. There is no `platform_admin` role or admin UI behind it;
it is a deliberately minimal, explicit recovery mechanism for this
prototype.

## Project status

See [`docs/database.md`](docs/database.md) for the migration history and
the current institutional security rules. `institutions`, `users`,
`auth` and `conversations`/`messages` all have a full API; no RAG,
embeddings, retrieval or agent behavior is implemented — the retrieval
approach is an open question for the literature review, not a decision
already made in this codebase.
