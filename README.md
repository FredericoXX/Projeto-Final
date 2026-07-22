# Agentic Institutional Assistant

Backend prototype for a generic, multi-institution higher-education assistant. The
information retrieval approach (e.g. RAG) is still to be chosen through a
literature review and is not yet an architectural decision.

The Python application lives entirely in [`backend/`](backend/). Docker Compose at the
repository root runs only PostgreSQL (with pgvector); the FastAPI application itself
runs locally from `backend/`, not in a container.

A minimal web interface lives in [`frontend/`](frontend/) (React + TypeScript +
Vite). It demonstrates the full flow — sign in, hold a grounded conversation
with sources, and manage documents as an admin — without Swagger or manual
requests. The dev server proxies `/api` to the backend (same-origin, no
permissive CORS); see [`frontend/README.md`](frontend/README.md). Quick start:

```bash
cd frontend
npm ci
npm run dev   # http://localhost:5173, backend at http://127.0.0.1:8000
```

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

### 8. Validate before committing

From `backend/` (venv active) — the same checks CI runs:

```powershell
pytest -q
ruff check .
mypy app tests
alembic upgrade head
alembic check
```

## Bootstrapping an institution

There is no `platform_admin` role yet, so creating an institution and
registering its first admin are not open endpoints — they are gated by a
shared secret, `BOOTSTRAP_TOKEN` (set in `.env`), sent as the
`X-Bootstrap-Token` header. This is a temporary, explicit stand-in for
platform-level administration, meant only for local/dev bootstrapping.
Regular operations after the first admin use normal JWT authentication;
the exceptions are the bootstrap-only operations themselves — creating
another institution, registering another institution's first admin, and
(de)activating an institution via
`PATCH /api/v1/bootstrap/institutions/{id}/status` (see
[Reactivating an institution](#reactivating-an-institution)) — which
keep using `X-Bootstrap-Token`.

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
`auth`, `conversations`/`messages` and the document core all have a full
API. The document core (`/api/v1/documents`, admin-only) covers logical
documents with versioned file uploads (PDF, TXT, Markdown), local file
storage, duplicate detection and synchronous text extraction — see
[`docs/document-core.md`](docs/document-core.md).

Scanned PDFs are supported through local, offline OCR (Tesseract):
each page is analysed separately, native text is used whenever it is
sufficient, and OCR runs only on pages that need it. Detection covers
direct, nested Form and inline images plus vector drawing; an independent,
pixel-limited 72-DPI preview distinguishes visual pages from approximately
blank pages when native text is insufficient or structural inspection is
inconclusive (page order and the `\f` page separator are preserved; OCR line
reconstruction keeps simple two-column tables — e.g. event | date — on one line). Extraction
metadata (`extraction_method` native/ocr/mixed, `extraction_quality`
high/medium/low, `extraction_warning`, per-page `extraction_details`)
is persisted and exposed read-only; historical versions keep these
fields NULL. The Tesseract runtime is optional: the application starts
and native documents process without it — only OCR-requiring documents
fail, with a short controlled error, and can be reprocessed later.
Configuration (languages, DPI, timeout, page/pixel limits) lives in
`.env.example`; details in
[`docs/document-core.md`](docs/document-core.md).

After a successful extraction, the text of each document version is also
split into internal, deterministic chunks (`document_chunks` table),
stored with character offsets, a normalized copy for lexical search and a
per-chunk SHA-256. Chunk size and overlap are configured via
`DOCUMENT_CHUNK_SIZE_CHARS` / `DOCUMENT_CHUNK_OVERLAP_CHARS`. A version
is only marked `processed` after its chunks are persisted, and
reprocessing atomically replaces that version's chunk set. Chunks are an
internal structure with no public endpoint: they prepare the system for
the retrieval experiments. Once a chunk has been cited by a persisted answer,
that chunk row cannot be updated or deleted. Reprocessing and rebuild refuse
the cited version, so new content must be uploaded as a new version;
historical citation metadata stays in its snapshot.

Phase 3 adds an experimental lexical baseline at
`POST /api/v1/retrieval/search`. Authenticated users retrieve ranked
evidence from the latest processed version of eligible documents in their
own institution. PostgreSQL maintains a generated `TSVECTOR` and GIN index;
`PostgresLexicalRetriever` uses parameterized `websearch_to_tsquery` and
`ts_rank_cd` behind a neutral `Retriever` contract.

Natural questions ("Quando começam as aulas?") are supported through
deterministic progressive search: the exact query is tried first, then
the informative terms (functional PT/EN words removed) with AND, then
with OR — the first non-empty strategy wins and results are never mixed.
All institutional filters apply to every strategy, explicit operators
(quotes, `OR`, `-term`) keep their semantics and skip relaxation, and no
extra LLM calls, embeddings, stemming or synonyms are involved. This
remains a lexical baseline, not semantic understanding — see
[`docs/database.md`](docs/database.md).

The retrieval endpoint returns evidence only. Existing processed text can be
rebuilt idempotently with `python -m scripts.rebuild_document_chunks`,
optionally filtered by `--institution-id` or `--document-id`; cited versions
are skipped and reported separately.

Phase 3 step 2 adds experimental grounded answering at
`POST /api/v1/answering/ask` — see [`docs/answering.md`](docs/answering.md).
Retrieved evidence is turned into a bounded JSON payload (stable E1/E2 ids)
under a static system prompt. Institutional data remains untrusted and cannot
change the JSON structure built by the application. A provider adapter
generates a short answer constrained to that context, and a deterministic
validator rejects any answer that cites unknown
evidence ids, is empty or exceeds the configured limit. With zero
evidence the endpoint returns `insufficient_evidence` with a fixed
per-language fallback message and never contacts the provider. The
OpenAI SDK is isolated in `app/answering/providers/openai.py` behind a
neutral `AnswerGenerator` contract; the app starts without
`OPENAI_API_KEY` (the endpoint returns 503 only when generation is
actually needed). Provider error logs contain only controlled metadata, the
SDK client explicitly disables retries, and tests run without network or
credentials.

Phase 3 step 3 adds `POST /api/v1/conversations/{conversation_id}/ask`.
It reuses the same provider-neutral pipeline, then revalidates and locks the
active institution, current user/role, conversation and cited database rows.
The retrieval-time chunk checksum is compared with the locked content before
the user message, assistant reply (`reply_to_message_id`) and source snapshots
are committed atomically.
`insufficient_evidence` persists the two-message fallback with no sources.
Message history now returns ordered sources without N+1 queries, and later
document metadata changes do not rewrite old citations.

The usability pass adds document lifecycle management and conversation
titles. Admins can edit document metadata (language locks once versions
exist), create documents with Save / Save and New / Cancel (official
source on by default), and permanently delete a **never-cited** document —
chunks, versions and files — behind an accessible confirmation dialog.
A document cited by persisted answers returns 409 and can only be
deactivated, preserving the auditable history; upload and deletion share
a per-document advisory lock so races leave no orphan files, and file
cleanup is enqueued as durable rows in `storage_cleanup_tasks` within the
same transaction as the deletion, then processed and reconciled with
`FOR UPDATE SKIP LOCKED` (local synchronous storage, not a distributed
transaction). Conversations are created without asking for a title: the
backend derives one locally (no LLM) from the first persisted question,
in the same transaction as the turn; users can rename conversations —
including closed/archived ones, which stay final — and listings order by
recent activity (`updated_at`).

The generation approach is experimental and replaceable, not a final
architectural decision, and the system is **not** hallucination-free.
There are still no embeddings, semantic or hybrid search, reranking, a
second validating LLM, confidence scores, conversational memory, idempotency,
human escalation, feedback or a frontend. Concurrent questions are ordered
by commit time, not submission time.
