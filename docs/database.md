# Database Notes

## Migration history

| Order | Revision | Description |
|---|---|---|
| 1 | `db13417f9dc4` | Enable the `pgvector` extension |
| 2 | `de4e133df3c9` | Create the `institutions` table |
| 3 | `9cf6ff5ac49c` | Create the `users` table with `institution_id` and the required multi-institution fields |
| 4 | `9ec09d09f22f` | Create the `conversations` and `messages` tables |
| 5 | `3ed4bcad52c8` | Add composite multi-institution foreign keys and their supporting unique constraints |
| 6 | `5f638cb2d2c3` | Add domain-value CHECK constraints for `users.role`, `conversations.status` and `messages.role` |
| 7 | `1482b165c943` | Create the `documents` and `document_versions` tables (document core) |
| 8 | `68cb34527411` | Create the `document_chunks` table and its supporting unique constraint on `document_versions` |
| 9 | `b7e2d8a9f4c1` | Add generated lexical `search_vector` and its GIN index |

Since the project is still in local-only development with no shared
environments, no production data, and disposable databases, the `users`
migration was rewritten in place to create the table already correctly
shaped for the multi-institution model, instead of adding a fourth
migration to alter it later. There is no separate "complete `users`"
migration — the historical migration itself is now correct.

The `users` table (as created by `9cf6ff5ac49c`) has:

- `id` — UUID, primary key, application-generated via the ORM default
- `institution_id` — UUID, `NOT NULL`, foreign key to `institutions.id`, indexed
- `full_name` — `String(255)`, `NOT NULL`
- `email` — `String(255)`, `NOT NULL`, globally unique
- `password_hash` — `String(255)`, `NOT NULL`
- `role` — `String(50)`, `NOT NULL`, server default `"user"`
- `is_active` — `Boolean`, `NOT NULL`, server default `true`
- `created_at` — timezone-aware timestamp, `NOT NULL`, server default `now()`
- `updated_at` — timezone-aware timestamp, `NOT NULL`, server default `now()`

`email` uniqueness remains global (not scoped per institution) — that is
unchanged from the original design and was not revisited in this pass.

The `institutions`, `users`, `conversations` and `messages` tables all
have a full API on top of them: institution management, a user
management API scoped to the authenticated admin's institution,
JWT + Argon2 based authentication (login and initial-admin
registration), and a conversations/messages API scoped to the
authenticated user's institution (and, for non-admins, to their own
conversations). See
[`app/api/routes/institutions.py`](../backend/app/api/routes/institutions.py),
[`app/api/routes/users.py`](../backend/app/api/routes/users.py),
[`app/api/routes/auth.py`](../backend/app/api/routes/auth.py) and
[`app/api/routes/conversations.py`](../backend/app/api/routes/conversations.py).

A conversation belongs to one institution and one user, and groups the
messages exchanged in an assistant session. This phase only covers
persistence and CRUD-style endpoints. The information-retrieval approach
(RAG or otherwise) is still an open question for the project's
literature review — nothing here should be read as a decision already
made; pgvector is enabled purely as infrastructure available for that
future work.

A message's `user_id` records who actually authored it: for `role="user"`
it's the sending user; for `role="system"` it's the admin who created it
manually (see `message_service.create_message`), which is what makes
system messages auditable. It is only ever `NULL` for future automatic
`"assistant"` messages, which aren't created through this API yet — role
`"system"` does **not** imply a null `user_id`.

## Document core (`documents` and `document_versions`)

Migration `1482b165c943` adds the document layer, split into two tables
on purpose: `documents` is the logical institutional document
(regulation, calendar, manual...) and its metadata; `document_versions`
is each concrete uploaded file/revision, so a document can be updated
without losing its history.

`documents` (all rows scoped by `institution_id`):

- `id` (UUID, app-generated), `institution_id` (FK to `institutions`),
  `created_by_user_id` — with a composite FK
  `(created_by_user_id, institution_id)` → `users(id, institution_id)`,
  so the creator must belong to the same institution;
- `title`, `description`, `language` (institution-aware, resolved with
  the same `resolve_language` rule as conversations), `source_url`,
  `official_source`, `is_active`, `valid_from`/`valid_until` (with a
  CHECK enforcing `valid_from <= valid_until`);
- a degenerate `UNIQUE (id, institution_id)` supporting the composite
  FKs from `document_versions`.

`document_versions`:

- composite FKs `(document_id, institution_id)` →
  `documents(id, institution_id)` and
  `(uploaded_by_user_id, institution_id)` → `users(id, institution_id)`:
  PostgreSQL itself rejects any cross-institution combination;
- `UNIQUE (document_id, version_number)` (second defense behind the
  `SELECT ... FOR UPDATE` lock used to assign version numbers) and
  `UNIQUE (institution_id, checksum_sha256)` (the same file content may
  exist in different institutions, never twice in the same one);
- CHECKs: `version_number > 0`, `size_bytes > 0`,
  `processing_status IN ('pending','processing','processed','failed')`,
  `page_count IS NULL OR page_count >= 0`;
- the binary file lives in local storage (`storage_path` is always
  relative to the storage root); PostgreSQL stores only metadata and
  the extracted text (`extracted_text`).

See [`docs/document-core.md`](document-core.md) for the full phase
documentation (endpoints, upload rules, processing states, storage
layout and limitations).

## Document chunks (`document_chunks`)

Migration `68cb34527411` adds `document_chunks`: the deterministic
segments of the extracted text of each document version. Chunks are an
**internal structure** — there is no public chunks endpoint, and
`normalized_content`, `content_sha256` and the offsets are never exposed
by the API. They exist to prepare the documents for a future
information-retrieval strategy; RAG is *not* a settled architectural
decision. Phase 3 adds only the experimental lexical baseline described
below; embeddings and vector retrieval remain absent.

Each row has:

- `id` (UUID, app-generated), `institution_id`, `document_id`,
  `document_version_id` — with a composite three-column FK
  `(document_version_id, document_id, institution_id)` →
  `document_versions(id, document_id, institution_id)`, backed by a
  degenerate `UNIQUE (id, document_id, institution_id)` on
  `document_versions` (id alone is already unique; it exists only to be
  referenced). PostgreSQL itself therefore rejects a chunk that points
  at the wrong version, the wrong document or another institution —
  the service checks are not the only defense;
- `chunk_index` (0-based, `UNIQUE (document_version_id, chunk_index)`),
  `content` (the original slice: `content ==
  extracted_text[start_char:end_char]`), `normalized_content` (see
  `app/core/text_normalization.py`: NFKD, no diacritics, casefolded,
  whitespace collapsed — prepared for future lexical search),
  `content_sha256`, `start_char`/`end_char` (end-exclusive offsets over
  the original text), `language` (inherited from the document at
  segmentation time), `created_at`;
- CHECKs: `chunk_index >= 0`, `start_char >= 0`,
  `end_char > start_char`, `btrim(content) <> ''`,
  `btrim(normalized_content) <> ''`;
- indexes on `institution_id`, `document_id`, `document_version_id` and
  `(institution_id, language)`; the pair
  `(document_version_id, chunk_index)` is already indexed by its UNIQUE
  constraint, so no duplicate index is created. There are deliberately
  **no** vector/embedding columns; the generated lexical vector below is
  unrelated to pgvector.

Chunking is integrated into the synchronous processing flow
(`document_processing_service.process_version`): extraction → chunking
(`document_chunking_service.chunk_text`, paragraph-preferring,
character-window fallback with configurable overlap; see
`DOCUMENT_CHUNK_SIZE_CHARS` / `DOCUMENT_CHUNK_OVERLAP_CHARS`) →
atomic replacement of the version's chunk set
(`document_chunk_service.replace_version_chunks`, no commit of its own)
→ version marked `processed`, all in one transaction. A version is
never `processed` without its chunks; a failure in chunking or
persistence rolls back, leaves no partial chunks and marks the version
`failed` with a short, safe error message. A `failed` version keeps no
chunks at all (having chunks is equivalent to being `processed`).
Reprocessing replaces only that version's chunks (protected by the same
`SELECT ... FOR UPDATE` lock as before); historical versions keep their
own chunk sets, and uploading a new version never touches the chunks of
previous versions.

### Experimental lexical search vector

Migration `b7e2d8a9f4c1` adds `search_vector TSVECTOR` as a generated,
stored column computed with `to_tsvector('simple', normalized_content)`.
The application never writes it manually. The explicit `simple`
configuration avoids choosing Portuguese- or English-specific stemming
before the baseline is evaluated. A GIN index named
`ix_document_chunks_search_vector` supports the `@@` match operator.

`PostgresLexicalRetriever` uses parameterized
`websearch_to_tsquery('simple', ...)` and `ts_rank_cd`. It selects only the
highest-numbered `processed` version per document and filters in SQL by
the authenticated institution, active status, language, current validity
and `official_only` (true by default). Historical chunks remain stored.

## Institutional security rules

These rules were added after a security review found the institutions
API was fully public and a few multi-institution invariants were
unenforced. They apply on top of the per-request `institution_id`
scoping already described above.

- **No `platform_admin` role yet.** Creating an institution
  (`POST /api/v1/institutions`) and registering its first admin
  (`POST /api/v1/auth/register-initial-admin`) are bootstrap-only
  operations, gated by the `BOOTSTRAP_TOKEN` setting sent as the
  `X-Bootstrap-Token` header — not by a JWT, since no admin exists yet
  at that point. A missing or wrong token, or an unset `BOOTSTRAP_TOKEN`,
  fails closed with 401. This is a temporary stand-in until a real
  platform-level admin role exists; see the
  [README bootstrap walkthrough](../README.md#bootstrapping-an-institution).
- **Reading and updating an institution require an authenticated admin,
  scoped to their own institution.** `GET /api/v1/institutions`,
  `GET /api/v1/institutions/{id}` and `PATCH /api/v1/institutions/{id}`
  all require a valid admin JWT. An admin's `institution_id` is never
  taken from the request payload or path for authorization purposes —
  only from the authenticated user. Any `id` other than the admin's own
  institution is reported as 404 (`resource_not_found`), the same as a
  non-existent institution, so these endpoints never confirm that
  another tenant exists.
- **An institution's `is_active` flag is enforced on every authenticated
  request, not only at login.** `get_current_user` re-checks both the
  user's and their institution's `is_active` on every call, so
  deactivating an institution immediately invalidates all outstanding
  tokens for its users (they get 401 on their next request, including
  `/auth/me`). Login also fails (401, generic message) if the user's
  institution is inactive, using the same wording as a wrong password so
  the response never reveals *why* it failed.
- **An institution must always keep at least one active admin.** In
  `PATCH /api/v1/users/{id}`: an admin can never deactivate their own
  account; and if a user is the institution's last active admin,
  neither deactivating them (`is_active: false`) nor changing their
  `role` away from `"admin"` is allowed (409 `resource_conflict`). With
  two or more active admins, one admin may deactivate or change the role
  of another.
- **`register_initial_admin` is race-safe, and refuses inactive
  institutions.** It takes a `SELECT ... FOR UPDATE` lock on the
  institution row before checking for an existing admin, so two
  concurrent registrations for the same institution are serialized —
  only one can succeed; the other gets 409. It also rejects (409) an
  attempt to register the first admin of an institution whose
  `is_active` is `false`: that admin could never log in anyway
  (`authenticate_user` also checks the institution's `is_active`), so
  it's better to refuse upfront than create an unusable account.
- **The last-admin invariant is enforced transactionally.** When
  `PATCH /api/v1/users/{id}` would deactivate or demote the institution's
  last active admin, `user_service.update_user` takes a
  `SELECT ... FOR UPDATE` lock on the institution row before counting
  active admins, so two concurrent requests targeting admins of the same
  institution are serialized — the second one re-counts active admins
  only after the first has committed, so the invariant (at least one
  active admin) can't be violated by a race.
- **An institutional admin can't (de)activate their own institution.**
  `PATCH /api/v1/institutions/{id}` uses the `InstitutionAdminUpdate`
  schema, which has no `is_active` field and uses `extra="forbid"` —
  sending `is_active` there is a 422, not a silent no-op. This closes
  off the obvious way an admin could lock themselves (and everyone else
  at that institution) out with no recovery path. The only way to
  (de)activate an institution now is the bootstrap-only
  `PATCH /api/v1/bootstrap/institutions/{id}/status` endpoint (gated by
  `X-Bootstrap-Token`, payload limited to `{"is_active": bool}`); see the
  [README walkthrough](../README.md#reactivating-an-institution).
- **PostgreSQL enforces cross-institution consistency directly, not just
  application code.** Migration `3ed4bcad52c8` adds "degenerate" unique
  constraints on `(id, institution_id)` for `users` and `conversations`
  (id alone is already unique; these exist only to be referenced) and
  replaces the plain foreign keys they superseded with composite ones:
  `conversations.(user_id, institution_id)` → `users.(id, institution_id)`,
  `messages.(conversation_id, institution_id)` →
  `conversations.(id, institution_id)`, and
  `messages.(user_id, institution_id)` → `users.(id, institution_id)`
  (skipped by PostgreSQL when `user_id` is `NULL`, its default `MATCH
  SIMPLE` behavior). A conversation whose `user_id` belongs to a
  different institution than its own `institution_id`, or a message
  whose `conversation_id`/`user_id` belongs to a different institution,
  is now rejected by the database itself — the previous simple foreign
  keys only checked that the referenced row existed, not that it
  belonged to the same institution.
- **A conversation's `status` gates further activity.** `active` is the
  only status that accepts new messages or `PATCH` updates; `closed` and
  `archived` are **final** states in this prototype — both reject new
  messages and any `PATCH` (including one attempting to move the status
  back to `active`) with 409. There is no reopen endpoint in this phase.
- **A conversation's/message's `language` is always institution-aware.**
  On `POST /api/v1/conversations`, an omitted `language` defaults to
  `institution.default_language`; a provided one is normalized and must
  be one of `institution.supported_languages`, or the request gets 422.
  On `POST .../messages`, an omitted `language` inherits the
  conversation's `language`; a provided one is validated the same way,
  against the *same* institution's `supported_languages` (different
  institutions can support different languages). This resolution lives
  in `app.core.language.resolve_language`, called from both
  `conversation_service` and `message_service`, so the rule is
  implemented once. Updating an institution's `supported_languages` to
  drop its current `default_language` was already rejected before this
  pass (`institution_service.update_institution` re-validates the
  resulting configuration on every `PATCH`); historical conversations
  are not migrated if an institution's supported languages change later.

## Current status

An experimental lexical evidence-retrieval baseline is implemented, but
the definitive approach remains an open question for the literature
review. There is no complete RAG workflow, embeddings, semantic/hybrid
search, answer generation, LLM or agent behavior; pgvector remains
infrastructure-only and is not used by retrieval. Current work covers
persistence, CRUD APIs, authentication, the core domain
invariants described above (institutional security rules,
conversation/message state and language rules, multi-institution data
integrity) and the document core (documents, versioned uploads, local
file storage, synchronous text extraction and deterministic chunking —
see [`docs/document-core.md`](document-core.md) and the
`document_chunks` section above), plus parameterized PostgreSQL lexical
search over the latest eligible processed version of each document.
